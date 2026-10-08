"""Ordinary comparison baselines.

The direct baseline is deliberately implemented separately from the SpanLife
checker.  It receives the same observations and declared contract, so agreement
is expected.  The name baseline intentionally ignores correlation attributes,
segment relations, timing, status, parentage, and context.
"""
from __future__ import annotations

from .contracts import normalize_policy


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
    if all("segments" not in policy and not policy.get("relations") for policy in run["policies"]):
        return _legacy_existence_and_name(run)
    if not run.get("drained"):
        return {"verdict": "inconclusive", "reason": "collection pending"}
    failures: list[str] = []
    for raw in run["policies"]:
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
        execution_valid = b["monotonic_ns"] >= a["monotonic_ns"]
        if not execution_valid:
            uncertain.append(oid)
        if "expected_context" in p:
            if oid not in run.get("contexts", {}):
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
            if not run.get("drained") or not run.get("always_on") or p.get("ended_witness"):
                uncertain.append(oid)
            else:
                failed.append(oid)
            continue
        s = chosen[0]
        checks = []
        if run["clock"]["timing_eligible"]:
            if p["role"] in ("execution", "both") and execution_valid:
                checks.extend([s["start_ns"] <= a["wall_ns"] + eps,
                               s["end_ns"] >= b["wall_ns"] - eps])
            if p["role"] in ("submission", "both"):
                if len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1:
                    uncertain.append(oid)
                elif lookup["submit_exit"][0]["monotonic_ns"] < lookup["submit_enter"][0]["monotonic_ns"]:
                    uncertain.append(oid)
                else:
                    checks.extend([s["start_ns"] <= lookup["submit_enter"][0]["wall_ns"] + eps,
                                   s["end_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps])
            if p["role"] == "execution" and p.get("exclude_queue"):
                if len(lookup["queue_release"]) != 1:
                    uncertain.append(oid)
                else:
                    checks.append(s["start_ns"] >= lookup["queue_release"][0]["wall_ns"] - eps)
        else:
            uncertain.append(oid)
        if (execution_valid and p["role"] in ("execution", "both") and p.get("error_on_escape")
                and b["outcome"] == "raised" and b["exception_type"] not in p.get("non_error_types", [])):
            checks.append(s["status"] == "ERROR")
            if p.get("exception_event"):
                checks.append("exception" in s["events"])
        if "expected_parent" in p:
            if s.get("parent_id") is None:
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
    timing = run["clock"]["timing_eligible"]

    for raw in run["policies"]:
        policy = normalize_policy(raw)
        oid = policy["operation_id"]
        ev = [row for row in run["ledger"] if row["operation_id"] == oid]
        lookup = {kind: [row for row in ev if row["kind"] == kind]
                  for kind in ("enter", "exit", "submit_enter", "submit_exit", "queue_release")}
        if len(lookup["enter"]) != 1 or len(lookup["exit"]) != 1:
            uncertain.append(oid)
            continue
        enter, exit_event = lookup["enter"][0], lookup["exit"][0]
        execution_valid = exit_event["monotonic_ns"] >= enter["monotonic_ns"]
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
            if "expected_context" in segment:
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
                if not run.get("drained") or not run.get("always_on") or segment.get("ended_witness"):
                    uncertain.append(key)
                else:
                    failed.append(key)
                continue
            span = candidates[0]
            selected[sid] = span
            checks: list[bool] = []
            if timing:
                if role in ("execution", "both") and execution_valid:
                    checks.extend([span["start_ns"] <= enter["wall_ns"] + eps,
                                   span["end_ns"] >= exit_event["wall_ns"] - eps])
                if role in ("submission", "both"):
                    if len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1:
                        uncertain.append(key)
                    elif lookup["submit_exit"][0]["monotonic_ns"] < lookup["submit_enter"][0]["monotonic_ns"]:
                        uncertain.append(key)
                    else:
                        checks.extend([span["start_ns"] <= lookup["submit_enter"][0]["wall_ns"] + eps,
                                       span["end_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps])
                if role == "execution" and segment.get("exclude_queue"):
                    if len(lookup["queue_release"]) != 1:
                        uncertain.append(key)
                    else:
                        checks.append(span["start_ns"] >= lookup["queue_release"][0]["wall_ns"] - eps)
                if role == "execution" and segment.get("exclude_submission"):
                    if len(lookup["submit_exit"]) != 1:
                        uncertain.append(key)
                    else:
                        checks.append(span["start_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps)
                if execution_valid and segment.get("must_end_before_operation_entry"):
                    checks.append(span["end_ns"] <= enter["wall_ns"] + eps)
            else:
                uncertain.append(key)
            if (execution_valid and role in ("execution", "both") and segment.get("error_on_escape")
                    and exit_event["outcome"] == "raised"
                    and exit_event["exception_type"] not in segment.get("non_error_types", [])):
                checks.append(span["status"] == "ERROR")
                if segment.get("exception_event"):
                    checks.append("exception" in span["events"])
            if "expected_parent" in segment:
                if span.get("parent_id") is None:
                    uncertain.append(key)
                else:
                    checks.append(span["parent_id"] == segment["expected_parent"])
            if checks and not all(checks):
                failed.append(key)

        for relation in policy.get("relations", []):
            source = selected.get(relation["from"])
            target = selected.get(relation["to"])
            if source is None or target is None:
                continue
            key = f"{oid}:{relation['from']}->{relation['to']}"
            links = source.get("links")
            linked = any(target.get('trace_id') is not None
                         and link.get('trace_id') == target['trace_id']
                         and str(link.get('span_id')) == str(target['span_id']) for link in (links or []))
            parented = (source.get('trace_id') is not None
                        and source.get('trace_id') == target.get('trace_id')
                        and str(source.get('parent_id')) == str(target['span_id']))
            trace_missing = source.get('trace_id') is None or target.get('trace_id') is None
            parent_missing = source.get('parent_id') is None
            link_trace_missing = any(str(link.get('span_id')) == str(target['span_id'])
                                     and link.get('trace_id') is None for link in (links or []))
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
    if all("segments" not in policy and not policy.get("relations") for policy in run["policies"]):
        return _legacy_direct_assertions(run)
    return _topology_direct_assertions(run)
