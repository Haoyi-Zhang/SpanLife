"""Intent-conditioned qualification over serialized observations.

No SDK objects or global tree-nesting requirements appear here. Matching must
be supplied by the test adapter (unique names or an explicit serialized span
window); time overlap is never used to choose a span.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any


def qualify(run: dict[str, Any]) -> dict[str, Any]:
    events = defaultdict(lambda: defaultdict(list))
    for event in run["ledger"]:
        events[event["operation_id"]][event["kind"]].append(event)
    spans = {str(s["span_id"]): s for s in run["spans"]}
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
            if exit["monotonic_ns"] < enter["monotonic_ns"]:
                finding(oid, "INVALID_LEDGER", "inconclusive")
            if "expected_context" in policy:
                observed = observed_contexts.get(oid)
                if observed is None:
                    finding(oid, "MISSING_CONTEXT_OBSERVATION", "inconclusive")
                elif observed != policy["expected_context"]:
                    finding(oid, "CONTEXT_MISMATCH", "fail",
                            observed=observed, expected=policy["expected_context"])
            if role != "context-only":
                candidate_ids = policy.get("span_ids", [])
                selected = [spans[str(i)] for i in candidate_ids if str(i) in spans]
                if len(candidate_ids) > 1 or len(selected) > 1:
                    finding(oid, "AMBIGUOUS_ASSOCIATION", "inconclusive")
                elif not selected:
                    if not run.get("drained") or not run.get("always_on"):
                        finding(oid, "COLLECTION_NOT_QUALIFIED", "inconclusive")
                    elif policy.get("ended_witness", 0):
                        finding(oid, "EXPORT_LOSS", "inconclusive")
                    else:
                        finding(oid, "MISSING_SPAN", "fail")
                else:
                    span = selected[0]
                    if timing:
                        if role in ("execution", "both"):
                            if span["start_ns"] > enter["wall_ns"] + eps:
                                finding(oid, "STARTS_AFTER_ENTRY", "fail",
                                        gap_ns=span["start_ns"] - enter["wall_ns"])
                            if span["end_ns"] < exit["wall_ns"] - eps:
                                finding(oid, "ENDS_BEFORE_EXIT", "fail",
                                        gap_ns=exit["wall_ns"] - span["end_ns"])
                        if role in ("submission", "both"):
                            if len(ev["submit_enter"]) != 1 or len(ev["submit_exit"]) != 1:
                                finding(oid, "MISSING_SUBMISSION_BOUNDARY", "inconclusive")
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
                    if (role in ("execution", "both") and policy.get("error_on_escape")
                            and exit["outcome"] == "raised"
                            and exit["exception_type"] not in policy.get("non_error_types", [])):
                        if span["status"] != "ERROR":
                            finding(oid, "MISSING_ERROR_STATUS", "fail")
                        if policy.get("exception_event") and "exception" not in span["events"]:
                            finding(oid, "MISSING_EXCEPTION_EVENT", "fail")
                    if "expected_parent" in policy and span["parent_id"] != policy["expected_parent"]:
                        finding(oid, "PARENT_MISMATCH", "fail",
                                observed=span["parent_id"], expected=policy["expected_parent"])
        local = findings[initial:]
        verdict = ("fail" if any(f["verdict"] == "fail" for f in local) else
                   "inconclusive" if local else "pass")
        operations.append({"operation_id": oid, "verdict": verdict})
    verdict = ("fail" if any(o["verdict"] == "fail" for o in operations) else
               "inconclusive" if any(o["verdict"] == "inconclusive" for o in operations) else "pass")
    return {"verdict": verdict, "operations": operations, "findings": findings}
