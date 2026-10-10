"""Intent-conditioned qualification over serialized observations.

The checker accepts the original single-span record and a backwards-compatible
multi-segment contract.  Matching is explicit (span IDs or declared attribute
correlation); timing overlap is never used to select a candidate.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import is_legacy_policy, normalize_policy, validate_run


def _qualify_legacy(run: dict[str, Any]) -> dict[str, Any]:
    """Single-span evaluator with the original schema-1 output shape."""
    events = defaultdict(lambda: defaultdict(list))
    for event in run["ledger"]:
        events[event["operation_id"]][event["kind"]].append(event)
    spans = list(run["spans"])
    findings: list[dict[str, Any]] = []
    operations = []
    eps = run["clock"]["epsilon_ns"]
    timing = run["clock"]["timing_eligible"]
    observed_contexts = run.get("contexts", {})

    def finding(op: str, code: str, verdict: str, **detail: Any) -> None:
        findings.append({"operation_id": op, "code": code,
                         "verdict": verdict, **detail})

    for policy in run["policies"]:
        oid, role = policy["operation_id"], policy["role"]
        ev = events[oid]
        initial = len(findings)
        if role == "unknown":
            finding(oid, "UNDECLARED_INTENT", "inconclusive")
        elif len(ev["enter"]) != 1 or len(ev["exit"]) != 1:
            finding(oid, "INCOMPLETE_OPERATION", "inconclusive")
        else:
            enter, exit = ev["enter"][0], ev["exit"][0]
            execution_valid = exit["monotonic_ns"] >= enter["monotonic_ns"]
            if not execution_valid:
                finding(oid, "INVALID_LEDGER", "inconclusive")
            if role == "context-only" and policy.get("expected_context") is None:
                finding(oid, "MISSING_CONTEXT_EXPECTATION", "inconclusive")
            if "expected_context" in policy and (role != "context-only" or policy["expected_context"] is not None):
                observed = observed_contexts.get(oid)
                if observed is None:
                    finding(oid, "MISSING_CONTEXT_OBSERVATION", "inconclusive")
                elif observed != policy["expected_context"]:
                    finding(oid, "CONTEXT_MISMATCH", "fail",
                            observed=observed, expected=policy["expected_context"])
            if role != "context-only":
                candidate_ids = policy.get("span_ids", [])
                selected = [span for span in spans if str(span['span_id']) in {str(i) for i in candidate_ids}]
                if not run.get('drained') or not run.get('always_on'):
                    finding(oid, 'COLLECTION_NOT_QUALIFIED', 'inconclusive')
                elif len(candidate_ids) > 1 or len(selected) > 1:
                    finding(oid, "AMBIGUOUS_ASSOCIATION", "inconclusive")
                elif not selected:
                    if not run.get("drained") or not run.get("always_on"):
                        finding(oid, "COLLECTION_NOT_QUALIFIED", "inconclusive")
                    elif (type(policy.get("ended_witness")) is not int
                          or policy["ended_witness"] < 0):
                        finding(oid, "END_WITNESS_UNQUALIFIED", "inconclusive")
                    elif policy["ended_witness"] > 0:
                        finding(oid, "EXPORT_LOSS", "inconclusive")
                    else:
                        finding(oid, "MISSING_SPAN", "fail")
                else:
                    span = selected[0]
                    if timing:
                        if role in ("execution", "both") and execution_valid:
                            if span["start_ns"] > enter["wall_ns"] + eps:
                                finding(oid, "STARTS_AFTER_ENTRY", "fail",
                                        gap_ns=span["start_ns"] - enter["wall_ns"])
                            if span["end_ns"] < exit["wall_ns"] - eps:
                                finding(oid, "ENDS_BEFORE_EXIT", "fail",
                                        gap_ns=exit["wall_ns"] - span["end_ns"])
                        if role in ("submission", "both"):
                            if len(ev["submit_enter"]) != 1 or len(ev["submit_exit"]) != 1:
                                finding(oid, "MISSING_SUBMISSION_BOUNDARY", "inconclusive")
                            elif ev["submit_exit"][0]["monotonic_ns"] < ev["submit_enter"][0]["monotonic_ns"]:
                                finding(oid, "INVALID_SUBMISSION_BOUNDARY", "inconclusive")
                            else:
                                if span["start_ns"] > ev["submit_enter"][0]["wall_ns"] + eps:
                                    finding(oid, "MISSES_SUBMISSION_START", "fail")
                                if span["end_ns"] < ev["submit_exit"][0]["wall_ns"] - eps:
                                    finding(oid, "MISSES_SUBMISSION_END", "fail")
                        if role == "execution" and policy.get("exclude_queue"):
                            if len(ev["queue_release"]) != 1:
                                finding(oid, "MISSING_QUEUE_BOUNDARY", "inconclusive")
                            elif span["start_ns"] < ev["queue_release"][0]["wall_ns"] - eps:
                                finding(oid, "INCLUDES_QUEUE_WAIT", "fail")
                    else:
                        finding(oid, "CLOCK_UNQUALIFIED", "inconclusive")
                    if (execution_valid and role in ("execution", "both") and policy.get("error_on_escape")
                            and exit["outcome"] == "raised"
                            and exit["exception_type"] not in policy.get("non_error_types", [])):
                        if span["status"] != "ERROR":
                            finding(oid, "MISSING_ERROR_STATUS", "fail")
                        if policy.get("exception_event") and "exception" not in span["events"]:
                            finding(oid, "MISSING_EXCEPTION_EVENT", "fail")
                    if "expected_parent" in policy:
                        if span.get("parent_id") is None:
                            finding(oid, "RELATION_EVIDENCE_MISSING", "inconclusive")
                        elif span["parent_id"] != policy["expected_parent"]:
                            finding(oid, "PARENT_MISMATCH", "fail",
                                    observed=span["parent_id"], expected=policy["expected_parent"])
        local = findings[initial:]
        verdict = ("fail" if any(f["verdict"] == "fail" for f in local) else
                   "inconclusive" if local else "pass")
        operations.append({"operation_id": oid, "verdict": verdict})
    verdict = ("fail" if any(o["verdict"] == "fail" for o in operations) else
               "inconclusive" if any(o["verdict"] == "inconclusive" for o in operations) else "pass")
    return {"verdict": verdict, "operations": operations, "findings": findings}


def _matches_attributes(span: dict[str, Any], match: dict[str, Any]) -> bool:
    attributes = span.get("attributes", {})
    return all(attributes.get(key) == value for key, value in match.items())


def _resolve_segment(segment: dict[str, Any], spans: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    if "span_ids" in segment:
        ids = [str(value) for value in segment.get("span_ids", [])]
        return ids, [span for span in spans if str(span['span_id']) in ids]
    association = segment.get("association") or {"kind": "name"}
    name = segment.get("span_name", "")
    if association["kind"] == "attributes":
        match = association["match"]
        selected = [span for span in spans
                    if (not name or span.get("name") == name) and _matches_attributes(span, match)]
    else:
        selected = [span for span in spans if span.get("name") == name]
    return [str(span["span_id"]) for span in selected], selected


def _context_for(observed: dict[str, Any], oid: str, segment_id: str) -> Any:
    value = observed.get(oid)
    if isinstance(value, dict):
        return value.get(segment_id)
    return value


def _qualify_topology(run: dict[str, Any]) -> dict[str, Any]:
    events = defaultdict(lambda: defaultdict(list))
    for event in run["ledger"]:
        events[event["operation_id"]][event["kind"]].append(event)
    spans = list(run["spans"])
    findings: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    eps = run["clock"]["epsilon_ns"]
    timing = run["clock"]["timing_eligible"]
    observed_contexts = run.get("contexts", {})

    def finding(op: str, segment_id: str | None, code: str, verdict: str, **detail: Any) -> None:
        row: dict[str, Any] = {"operation_id": op, "code": code, "verdict": verdict}
        if segment_id is not None:
            row["segment_id"] = segment_id
        row.update(detail)
        findings.append(row)

    for raw_policy in run["policies"]:
        # Flat policies keep their original explicit-ID association semantics,
        # irrespective of other policies in this record.
        if is_legacy_policy(raw_policy):
            result = _qualify_legacy({**run, "policies": [raw_policy]})
            findings.extend(result["findings"])
            operations.extend(result["operations"])
            continue
        policy = normalize_policy(raw_policy)
        oid = policy["operation_id"]
        ev = events[oid]
        initial = len(findings)
        selected_by_segment: dict[str, dict[str, Any]] = {}
        segment_rows: list[dict[str, Any]] = []

        operation_complete = len(ev["enter"]) == 1 and len(ev["exit"]) == 1
        enter = ev["enter"][0] if operation_complete else None
        exit_event = ev["exit"][0] if operation_complete else None
        execution_valid = operation_complete and exit_event["monotonic_ns"] >= enter["monotonic_ns"]
        if not operation_complete:
            finding(oid, None, "INCOMPLETE_OPERATION", "inconclusive")
        elif exit_event["monotonic_ns"] < enter["monotonic_ns"]:
            finding(oid, None, "INVALID_LEDGER", "inconclusive")

        for segment in policy["segments"]:
            segment_id = segment["segment_id"]
            role = segment["role"]
            if role == "unknown":
                finding(oid, segment_id, "UNDECLARED_INTENT", "inconclusive")
            elif operation_complete:
                if role == "context-only" and segment.get("expected_context") is None:
                    finding(oid, segment_id, "MISSING_CONTEXT_EXPECTATION", "inconclusive")
                if "expected_context" in segment and (role != "context-only" or segment["expected_context"] is not None):
                    observed = _context_for(observed_contexts, oid, segment_id)
                    if observed is None:
                        finding(oid, segment_id, "MISSING_CONTEXT_OBSERVATION", "inconclusive")
                    elif observed != segment["expected_context"]:
                        finding(oid, segment_id, "CONTEXT_MISMATCH", "fail",
                                observed=observed, expected=segment["expected_context"])
                if role != "context-only":
                    candidate_ids, selected = _resolve_segment(segment, spans)
                    if not run.get('drained') or not run.get('always_on'):
                        finding(oid, segment_id, 'COLLECTION_NOT_QUALIFIED', 'inconclusive')
                    elif len(candidate_ids) > 1 or len(selected) > 1:
                        finding(oid, segment_id, "AMBIGUOUS_ASSOCIATION", "inconclusive",
                                candidate_count=max(len(candidate_ids), len(selected)))
                    elif not selected:
                        if not run.get("drained") or not run.get("always_on"):
                            finding(oid, segment_id, "COLLECTION_NOT_QUALIFIED", "inconclusive")
                        elif (type(segment.get("ended_witness")) is not int
                              or segment["ended_witness"] < 0):
                            finding(oid, segment_id, "END_WITNESS_UNQUALIFIED", "inconclusive")
                        elif segment["ended_witness"] > 0:
                            finding(oid, segment_id, "EXPORT_LOSS", "inconclusive")
                        else:
                            finding(oid, segment_id, "MISSING_SPAN", "fail")
                    else:
                        span = selected[0]
                        selected_by_segment[segment_id] = span
                        if timing:
                            if role in ("execution", "both") and execution_valid:
                                if span["start_ns"] > enter["wall_ns"] + eps:
                                    finding(oid, segment_id, "STARTS_AFTER_ENTRY", "fail",
                                            gap_ns=span["start_ns"] - enter["wall_ns"])
                                if span["end_ns"] < exit_event["wall_ns"] - eps:
                                    finding(oid, segment_id, "ENDS_BEFORE_EXIT", "fail",
                                            gap_ns=exit_event["wall_ns"] - span["end_ns"])
                            if role in ("submission", "both"):
                                if len(ev["submit_enter"]) != 1 or len(ev["submit_exit"]) != 1:
                                    finding(oid, segment_id, "MISSING_SUBMISSION_BOUNDARY", "inconclusive")
                                elif ev["submit_exit"][0]["monotonic_ns"] < ev["submit_enter"][0]["monotonic_ns"]:
                                    finding(oid, segment_id, "INVALID_SUBMISSION_BOUNDARY", "inconclusive")
                                else:
                                    if span["start_ns"] > ev["submit_enter"][0]["wall_ns"] + eps:
                                        finding(oid, segment_id, "MISSES_SUBMISSION_START", "fail")
                                    if span["end_ns"] < ev["submit_exit"][0]["wall_ns"] - eps:
                                        finding(oid, segment_id, "MISSES_SUBMISSION_END", "fail")
                            if role == "execution" and segment.get("exclude_queue"):
                                if len(ev["queue_release"]) != 1:
                                    finding(oid, segment_id, "MISSING_QUEUE_BOUNDARY", "inconclusive")
                                elif span["start_ns"] < ev["queue_release"][0]["wall_ns"] - eps:
                                    finding(oid, segment_id, "INCLUDES_QUEUE_WAIT", "fail")
                            if role == "execution" and segment.get("exclude_submission"):
                                if len(ev["submit_exit"]) != 1:
                                    finding(oid, segment_id, "MISSING_SUBMISSION_BOUNDARY", "inconclusive")
                                elif span["start_ns"] < ev["submit_exit"][0]["wall_ns"] - eps:
                                    finding(oid, segment_id, "INCLUDES_SUBMISSION", "fail")
                            if execution_valid and segment.get("must_end_before_operation_entry"):
                                if span["end_ns"] > enter["wall_ns"] + eps:
                                    finding(oid, segment_id, "SUBMISSION_OVERLAPS_EXECUTION", "fail",
                                            overlap_ns=span["end_ns"] - enter["wall_ns"])
                        else:
                            finding(oid, segment_id, "CLOCK_UNQUALIFIED", "inconclusive")
                        if (execution_valid and role in ("execution", "both") and segment.get("error_on_escape")
                                and exit_event["outcome"] == "raised"
                                and exit_event["exception_type"] not in segment.get("non_error_types", [])):
                            if span["status"] != "ERROR":
                                finding(oid, segment_id, "MISSING_ERROR_STATUS", "fail")
                            if segment.get("exception_event") and "exception" not in span["events"]:
                                finding(oid, segment_id, "MISSING_EXCEPTION_EVENT", "fail")
                        if "expected_parent" in segment:
                            if span.get("parent_id") is None:
                                finding(oid, segment_id, "RELATION_EVIDENCE_MISSING", "inconclusive")
                            elif span["parent_id"] != segment["expected_parent"]:
                                finding(oid, segment_id, "PARENT_MISMATCH", "fail",
                                        observed=span["parent_id"], expected=segment["expected_parent"])
        # Unresolved declared relations abstain; context identity is not span evidence.
        for relation in policy.get("relations", []):
            source_id, target_id = relation["from"], relation["to"]
            source, target = selected_by_segment.get(source_id), selected_by_segment.get(target_id)
            kind = relation["kind"]
            if source is None or target is None:
                finding(oid, source_id, "RELATION_EVIDENCE_MISSING", "inconclusive",
                        relation_kind=kind, target_segment=target_id)
                continue
            links = source.get("links")
            linked = False
            if links is not None:
                linked = any(target.get('trace_id') is not None
                             and link.get('trace_id') == target['trace_id']
                             and str(link.get('span_id')) == str(target['span_id']) for link in links)
            parented = (source.get('trace_id') is not None
                        and source.get('trace_id') == target.get('trace_id')
                        and str(source.get('parent_id')) == str(target['span_id']))
            trace_missing = source.get('trace_id') is None or target.get('trace_id') is None
            parent_missing = source.get('parent_id') is None
            link_trace_missing = any(str(link.get('span_id')) == str(target['span_id'])
                                     and link.get('trace_id') is None for link in (links or []))
            if ((kind == 'parent' and (trace_missing or parent_missing))
                    or (kind == 'link' and not linked and (target.get('trace_id') is None or link_trace_missing))
                    or (kind == 'parent-or-link' and not (parented or linked)
                        and (trace_missing or parent_missing or link_trace_missing))):
                finding(oid, source_id, 'RELATION_EVIDENCE_MISSING', 'inconclusive',
                        relation_kind=kind, target_segment=target_id)
                continue
            if kind == "link" and links is None:
                finding(oid, source_id, "RELATION_EVIDENCE_MISSING", "inconclusive",
                        relation_kind=kind, target_segment=target_id)
                continue
            if kind == "parent-or-link" and not parented and links is None:
                finding(oid, source_id, "RELATION_EVIDENCE_MISSING", "inconclusive",
                        relation_kind=kind, target_segment=target_id)
                continue
            if kind == "same-trace" and (source.get("trace_id") is None or target.get("trace_id") is None):
                finding(oid, source_id, "RELATION_EVIDENCE_MISSING", "inconclusive",
                        relation_kind=kind, target_segment=target_id)
                continue
            satisfied = ((kind == "link" and linked) or
                         (kind == "parent" and parented) or
                         (kind == "parent-or-link" and (parented or linked)) or
                         (kind == "same-trace" and source["trace_id"] == target["trace_id"]))
            if not satisfied:
                finding(oid, source_id, "MISSING_HANDOFF_RELATION", "fail",
                        relation_kind=kind, target_segment=target_id,
                        observed_parent=source.get("parent_id"),
                        observed_links=[str(link.get("span_id")) for link in (links or [])])

        local = findings[initial:]
        # Relation diagnostics belong to their source segment, so summarize
        # only after all interval, context, and relation checks are complete.
        for segment in policy["segments"]:
            segment_id = segment["segment_id"]
            local_segment = [row for row in local if row.get("segment_id") == segment_id]
            segment_verdict = ("fail" if any(row["verdict"] == "fail" for row in local_segment) else
                               "inconclusive" if local_segment or not execution_valid else "pass")
            segment_rows.append({"segment_id": segment_id, "verdict": segment_verdict})
        verdict = ("fail" if any(row["verdict"] == "fail" for row in local) else
                   "inconclusive" if local else "pass")
        operations.append({"operation_id": oid, "verdict": verdict, "segments": segment_rows})

    verdict = ("fail" if any(row["verdict"] == "fail" for row in operations) else
               "inconclusive" if any(row["verdict"] == "inconclusive" for row in operations) else "pass")
    return {"verdict": verdict, "operations": operations, "findings": findings}


def qualify(run: dict[str, Any]) -> dict[str, Any]:
    validate_run(run)
    if all(is_legacy_policy(policy) for policy in run["policies"]):
        return _qualify_legacy(run)
    return _qualify_topology(run)
