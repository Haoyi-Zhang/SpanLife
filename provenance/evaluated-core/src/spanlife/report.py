"""Practitioner-facing CI report and responsibility routing.

The mapping is deliberately conservative: it routes evidence to the layer that
can usually act first, without claiming a unique root cause.  The raw finding
and contract remain in the report for review.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .oracle import qualify

ROUTES: dict[str, dict[str, str]] = {
    "UNDECLARED_INTENT": {"owner": "application", "action": "declare the span role before judging it"},
    "INCOMPLETE_OPERATION": {"owner": "test-harness", "action": "complete or repair independent operation boundaries"},
    "INVALID_LEDGER": {"owner": "test-harness", "action": "repair boundary ordering or the local clock source"},
    "MISSING_CONTEXT_OBSERVATION": {"owner": "test-harness", "action": "capture active context inside the operation"},
    "CONTEXT_MISMATCH": {"owner": "propagation", "action": "inspect context capture, attach, and detach at the execution boundary"},
    "AMBIGUOUS_ASSOCIATION": {"owner": "instrumentation", "action": "add a stable operation correlation attribute or explicit span id"},
    "COLLECTION_NOT_QUALIFIED": {"owner": "telemetry-pipeline", "action": "verify sampling and drain or flush the local processor"},
    "EXPORT_LOSS": {"owner": "telemetry-pipeline", "action": "inspect exporter delivery after processor-end was observed"},
    "MISSING_SPAN": {"owner": "instrumentation", "action": "instrument the dispatcher or execution path that actually ran"},
    "STARTS_AFTER_ENTRY": {"owner": "instrumentation", "action": "move span start before the declared operation entry"},
    "ENDS_BEFORE_EXIT": {"owner": "instrumentation", "action": "keep the span open through operation completion and cleanup"},
    "MISSES_SUBMISSION_START": {"owner": "instrumentation", "action": "start the submission segment before enqueue or scheduling"},
    "MISSES_SUBMISSION_END": {"owner": "instrumentation", "action": "end the submission segment after scheduling returns"},
    "MISSING_SUBMISSION_BOUNDARY": {"owner": "test-harness", "action": "record both submission boundaries before evaluating this role"},
    "MISSING_QUEUE_BOUNDARY": {"owner": "test-harness", "action": "record a synchronized queue-release witness"},
    "INCLUDES_QUEUE_WAIT": {"owner": "instrumentation", "action": "start an execution-only segment after queue release"},
    "INCLUDES_SUBMISSION": {"owner": "instrumentation", "action": "separate submission and execution lifetimes"},
    "SUBMISSION_OVERLAPS_EXECUTION": {"owner": "instrumentation", "action": "close the strict submission segment before execution begins"},
    "MISSING_ERROR_STATUS": {"owner": "instrumentation", "action": "set ERROR when an in-scope exception escapes the operation"},
    "MISSING_EXCEPTION_EVENT": {"owner": "instrumentation", "action": "record the escaping exception event before ending the span"},
    "PARENT_MISMATCH": {"owner": "propagation", "action": "repair the declared parent edge or change the contract to a link"},
    "RELATION_EVIDENCE_MISSING": {"owner": "capture", "action": "retain span links or parent evidence in the captured record"},
    "MISSING_HANDOFF_RELATION": {"owner": "propagation", "action": "preserve the declared parent or link across the asynchronous handoff"},
    "CLOCK_UNQUALIFIED": {"owner": "test-environment", "action": "reduce clock-conversion uncertainty or keep the result inconclusive"},
}


def build_ci_report(run: dict[str, Any]) -> dict[str, Any]:
    result = qualify(run)
    routed = []
    for finding in result["findings"]:
        route = ROUTES.get(finding["code"], {"owner": "review", "action": "inspect the raw evidence and contract"})
        routed.append({**finding, **route})
    owners = Counter(row["owner"] for row in routed)
    stored = run.get("ledger_check")
    return {
        "schema": 1,
        "case": run.get("case"),
        "revision": run.get("revision"),
        "verdict": result["verdict"],
        "finding_count": len(routed),
        "owners": dict(sorted(owners.items())),
        "findings": routed,
        "record_consistent": stored is None or stored == result,
        "ci_exit_code": 1 if result["verdict"] == "fail" else 2 if result["verdict"] == "inconclusive" else 0,
    }


def format_text(report: dict[str, Any]) -> str:
    lines = [f"SpanLife {report['verdict'].upper()}: {report.get('case')} @ {report.get('revision')}"]
    if not report["findings"]:
        lines.append("No unsatisfied or unqualified obligations.")
        return "\n".join(lines)
    for row in report["findings"]:
        location = row["operation_id"]
        if "segment_id" in row:
            location += f"/{row['segment_id']}"
        lines.append(f"- {row['verdict'].upper()} {row['code']} [{location}] -> {row['owner']}: {row['action']}")
    return "\n".join(lines)
