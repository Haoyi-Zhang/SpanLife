"""Ordinary comparison baselines.

The direct baseline is deliberately implemented separately from the SpanLife
checker.  It receives the same observations and declared contract, so agreement
is expected.  The name baseline intentionally ignores correlation attributes,
segment relations, timing, status, parentage, and context.
"""
from __future__ import annotations

from .contracts import is_legacy_policy, normalize_policy, validate_run


def _ordered(first: dict, last: dict) -> bool:
    # Independent boundary implementation; no oracle predicate imports.
    for field in ("wall_ns", "monotonic_ns"):
        if type(first.get(field)) is not int or type(last.get(field)) is not int:
            return False
        if first[field] > last[field]:
            return False
    return True


def _error_checks(policy: dict, exit_event: dict, span: dict) -> tuple[list[bool], bool]:
    if policy["role"] not in ("execution", "both") or not policy.get("error_on_escape"):
        return [], False
    outcome = exit_event.get("outcome")
    if outcome == "returned":
        return [], False
    if outcome != "raised" or exit_event.get("exception_type") in (None, "unknown"):
        return [], True
    if exit_event["exception_type"] in policy.get("non_error_types", []):
        return [], False
    checks, unknown = [], False
    if span.get("status") in (None, "unknown"):
        unknown = True
    else:
        checks.append(span["status"] == "ERROR")
    if policy.get("exception_event"):
        if span.get("events") is None:
            unknown = True
        else:
            checks.append("exception" in span["events"])
    return checks, unknown


def _legacy_existence_and_name(run: dict) -> dict:
    if not run.get("drained"):
        return {"verdict": "inconclusive", "reason": "collection pending"}
    spans = {str(s["span_id"]): s for s in run["spans"]}
    failures = []
    for p in run["policies"]:
        if p["role"] == "unknown":
            return {"verdict": "inconclusive", "reason": "undeclared intent"}
        if p["role"] == "context-only":
            continue
        selected = [spans[str(i)] for i in p.get("span_ids", []) if str(i) in spans]
        if len(selected) != 1 or selected[0]["name"] != p["span_name"]:
            failures.append(p["operation_id"])
    return {"verdict": "fail" if failures else "pass", "failures": failures}


def existence_and_name(run: dict) -> dict:
    validate_run(run)
    if all(is_legacy_policy(policy) for policy in run["policies"]):
        return _legacy_existence_and_name(run)
    if not run.get("drained"):
        return {"verdict": "inconclusive", "reason": "collection pending"}
    failures: list[str] = []
    for raw in run["policies"]:
        if is_legacy_policy(raw):
            result = _legacy_existence_and_name({**run, "policies": [raw]})
            if result["verdict"] == "inconclusive":
                return result
            failures.extend(result["failures"])
            continue
        policy = normalize_policy(raw)
        for segment in policy["segments"]:
            if segment["role"] == "unknown":
                return {"verdict": "inconclusive", "reason": "undeclared intent"}
            if segment["role"] == "context-only":
                continue
            # This baseline knows only a global span name.  It cannot use
            # operation IDs, correlation attributes, or relation topology.
            selected = [span for span in run["spans"] if span.get("name") == segment["span_name"]]
            if len(selected) != 1:
                failures.append(f"{policy['operation_id']}:{segment['segment_id']}")
    return {"verdict": "fail" if failures else "pass", "failures": failures}


def _legacy_direct_assertions(run: dict) -> dict:
    spans = list(run['spans'])
    failed, uncertain = [], []
    eps = run["clock"]["epsilon_ns"]
    for p in run["policies"]:
        oid = p["operation_id"]
        ev = [e for e in run["ledger"] if e["operation_id"] == oid]
        lookup = {k: [e for e in ev if e["kind"] == k]
                  for k in ("enter", "exit", "submit_enter", "submit_exit", "queue_release")}
        if p["role"] == "unknown" or len(lookup["enter"]) != 1 or len(lookup["exit"]) != 1:
            uncertain.append(oid); continue
        a, b = lookup["enter"][0], lookup["exit"][0]
        execution_valid = _ordered(a, b)
        if not execution_valid:
            uncertain.append(oid)
        if (p["role"] == "context-only" or "expected_context" in p) and p.get("expected_context") is None:
            uncertain.append(oid)
        if p.get("expected_context") is not None:
            if run.get("contexts", {}).get(oid) is None:
                uncertain.append(oid)
            elif run["contexts"][oid] != p["expected_context"]:
                failed.append(oid)
        if p["role"] == "context-only":
            continue
        ids = p.get("span_ids", [])
        chosen = [span for span in spans if str(span['span_id']) in {str(i) for i in ids}]
        if not run.get('drained') or not run.get('always_on'):
            uncertain.append(oid)
            continue
        if len(ids) > 1 or len(chosen) > 1:
            uncertain.append(oid); continue
        if not chosen:
            witness = p.get("ended_witness")
            if (not run.get("drained") or not run.get("always_on")
                    or type(witness) is not int or witness != 0):
                uncertain.append(oid)
            else:
                failed.append(oid)
            continue
        s = chosen[0]
        checks = []
        if (s.get("start_ns") is None or s.get("end_ns") is None
                or s["start_ns"] > s["end_ns"]):
            uncertain.append(oid)
        elif run["clock"]["timing_eligible"] and eps <= run["clock"].get("cap_ns", 100_000):
            if p["role"] in ("execution", "both") and execution_valid:
                checks.extend([s["start_ns"] <= a["wall_ns"] + eps,
                               s["end_ns"] >= b["wall_ns"] - eps])
            if p["role"] in ("submission", "both"):
                if len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1:
                    uncertain.append(oid)
                elif not _ordered(lookup["submit_enter"][0], lookup["submit_exit"][0]):
                    uncertain.append(oid)
                else:
                    checks.extend([s["start_ns"] <= lookup["submit_enter"][0]["wall_ns"] + eps,
                                   s["end_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps])
            if p["role"] == "execution" and p.get("exclude_queue"):
                if len(lookup["queue_release"]) != 1 or not _ordered(lookup["queue_release"][0], a):
                    uncertain.append(oid)
                else:
                    checks.append(s["start_ns"] >= lookup["queue_release"][0]["wall_ns"] - eps)
        else:
            uncertain.append(oid)
        if execution_valid:
            error_checks, unknown_error = _error_checks(p, b, s)
            checks.extend(error_checks)
            if unknown_error:
                uncertain.append(oid)
        if "expected_parent" in p:
            if p["expected_parent"] is None or s.get("parent_id") is None:
                uncertain.append(oid)
            else:
                checks.append(s["parent_id"] == p["expected_parent"])
        if not all(checks):
            failed.append(oid)
    return {"verdict": "fail" if failed else "inconclusive" if uncertain else "pass",
            "failures": sorted(set(failed)), "inconclusive": sorted(set(uncertain))}


def _select(segment: dict, spans: list[dict]) -> list[dict]:
    name = segment.get("span_name", "")
    if "span_ids" in segment:
        ids = {str(value) for value in segment.get("span_ids", [])}
        return [span for span in spans if str(span["span_id"]) in ids]
    association = segment.get("association") or {"kind": "name"}
    if association["kind"] == "attributes":
        match = association["match"]
        return [span for span in spans
                if (not name or span.get("name") == name)
                and all(span.get("attributes", {}).get(key) == value for key, value in match.items())]
    return [span for span in spans if span.get("name") == name]


def _context(run: dict, oid: str, segment_id: str):
    value = run.get("contexts", {}).get(oid)
    return value.get(segment_id) if isinstance(value, dict) else value


def _topology_direct_assertions(run: dict) -> dict:
    failed: list[str] = []
    uncertain: list[str] = []
    eps = run["clock"]["epsilon_ns"]
    timing = run["clock"]["timing_eligible"] and eps <= run["clock"].get("cap_ns", 100_000)

    for raw in run["policies"]:
        if is_legacy_policy(raw):
            result = _legacy_direct_assertions({**run, "policies": [raw]})
            failed.extend(result["failures"])
            uncertain.extend(result["inconclusive"])
            continue
        policy = normalize_policy(raw)
        oid = policy["operation_id"]
        ev = [row for row in run["ledger"] if row["operation_id"] == oid]
        lookup = {kind: [row for row in ev if row["kind"] == kind]
                  for kind in ("enter", "exit", "submit_enter", "submit_exit", "queue_release")}
        if len(lookup["enter"]) != 1 or len(lookup["exit"]) != 1:
            uncertain.append(oid)
            continue
        enter, exit_event = lookup["enter"][0], lookup["exit"][0]
        execution_valid = _ordered(enter, exit_event)
        if not execution_valid:
            uncertain.append(oid)
        selected: dict[str, dict] = {}
        for segment in policy["segments"]:
            sid = segment["segment_id"]
            key = f"{oid}:{sid}"
            role = segment["role"]
            if role == "unknown":
                uncertain.append(key)
                continue
            if (role == "context-only" or "expected_context" in segment) and segment.get("expected_context") is None:
                uncertain.append(key)
            if segment.get("expected_context") is not None:
                observed = _context(run, oid, sid)
                if observed is None:
                    uncertain.append(key)
                elif observed != segment["expected_context"]:
                    failed.append(key)
            if role == "context-only":
                continue
            candidates = _select(segment, run["spans"])
            if not run.get('drained') or not run.get('always_on'):
                uncertain.append(key)
                continue
            if len(candidates) > 1 or len(segment.get("span_ids", [])) > 1:
                uncertain.append(key)
                continue
            if not candidates:
                witness = segment.get("ended_witness")
                if (not run.get("drained") or not run.get("always_on")
                        or type(witness) is not int or witness != 0):
                    uncertain.append(key)
                else:
                    failed.append(key)
                continue
            span = candidates[0]
            selected[sid] = span
            checks: list[bool] = []
            if (span.get("start_ns") is None or span.get("end_ns") is None
                    or span["start_ns"] > span["end_ns"]):
                uncertain.append(key)
            elif timing:
                if role in ("execution", "both") and execution_valid:
                    checks.extend([span["start_ns"] <= enter["wall_ns"] + eps,
                                   span["end_ns"] >= exit_event["wall_ns"] - eps])
                if role in ("submission", "both"):
                    if len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1:
                        uncertain.append(key)
                    elif not _ordered(lookup["submit_enter"][0], lookup["submit_exit"][0]):
                        uncertain.append(key)
                    else:
                        checks.extend([span["start_ns"] <= lookup["submit_enter"][0]["wall_ns"] + eps,
                                       span["end_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps])
                if role == "execution" and segment.get("exclude_queue"):
                    if len(lookup["queue_release"]) != 1 or not _ordered(lookup["queue_release"][0], enter):
                        uncertain.append(key)
                    else:
                        checks.append(span["start_ns"] >= lookup["queue_release"][0]["wall_ns"] - eps)
                if role == "execution" and segment.get("exclude_submission"):
                    if (len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1
                            or not _ordered(lookup["submit_enter"][0], lookup["submit_exit"][0])):
                        uncertain.append(key)
                    else:
                        checks.append(span["start_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps)
                if execution_valid and segment.get("must_end_before_operation_entry"):
                    checks.append(span["end_ns"] <= enter["wall_ns"] + eps)
            else:
                uncertain.append(key)
            if execution_valid:
                error_checks, unknown_error = _error_checks(segment, exit_event, span)
                checks.extend(error_checks)
                if unknown_error:
                    uncertain.append(key)
            if "expected_parent" in segment:
                if segment["expected_parent"] is None or span.get("parent_id") is None:
                    uncertain.append(key)
                else:
                    checks.append(span["parent_id"] == segment["expected_parent"])
            if checks and not all(checks):
                failed.append(key)

        for relation in policy.get("relations", []):
            source = selected.get(relation["from"])
            target = selected.get(relation["to"])
            key = f"{oid}:{relation['from']}->{relation['to']}"
            if source is None or target is None:
                uncertain.append(key)
                continue
            links = source.get("links")
            linked = any(target.get('trace_id') is not None
                         and link.get('trace_id') == target['trace_id']
                         and str(link.get('span_id')) == str(target['span_id']) for link in (links or []))
            parented = (source.get('trace_id') is not None
                        and source.get('trace_id') == target.get('trace_id')
                        and str(source.get('parent_id')) == str(target['span_id']))
            trace_missing = source.get('trace_id') is None or target.get('trace_id') is None
            parent_missing = source.get('parent_id') is None
            link_trace_missing = any(link.get('span_id') is None
                                     or (str(link['span_id']) == str(target['span_id'])
                                         and link.get('trace_id') is None) for link in (links or []))
            if ((relation['kind'] == 'parent' and (trace_missing or parent_missing))
                    or (relation['kind'] == 'link' and not linked
                        and (target.get('trace_id') is None or link_trace_missing))
                    or (relation['kind'] == 'parent-or-link' and not (parented or linked)
                        and (trace_missing or parent_missing or link_trace_missing))):
                uncertain.append(key)
                continue
            if relation["kind"] == "link" and links is None:
                uncertain.append(key)
                continue
            if relation["kind"] == "parent-or-link" and not parented and links is None:
                uncertain.append(key)
                continue
            if relation["kind"] == "same-trace" and (source.get("trace_id") is None or target.get("trace_id") is None):
                uncertain.append(key)
                continue
            satisfied = ((relation["kind"] == "link" and linked) or
                         (relation["kind"] == "parent" and parented) or
                         (relation["kind"] == "parent-or-link" and (linked or parented)) or
                         (relation["kind"] == "same-trace" and source["trace_id"] == target["trace_id"]))
            if not satisfied:
                failed.append(key)

    return {"verdict": "fail" if failed else "inconclusive" if uncertain else "pass",
            "failures": sorted(set(failed)), "inconclusive": sorted(set(uncertain))}


def direct_assertions(run: dict) -> dict:
    validate_run(run)
    if all(is_legacy_policy(policy) for policy in run["policies"]):
        return _legacy_direct_assertions(run)
    return _topology_direct_assertions(run)
