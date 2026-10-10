"""Pure expectations and rollups shared by topology generation and record checks.

No SDK capture or process execution belongs here. A rollup describes the
supplied judgments; it does not establish their correctness or run a new trial.
"""
from __future__ import annotations

from collections import Counter

TOPOLOGY_CASES = (
    "split_link_valid",
    "split_parent_valid",
    "split_missing_relation",
    "split_wrong_relation",
    "split_submission_overlap",
    "split_execution_early_end",
    "split_execution_missing",
    "split_submission_missing",
    "correlated_concurrent_valid",
    "correlated_missing_attribute",
    "correlated_duplicate_attribute",
    "correlated_swapped_attribute",
)

EXPECTED: dict[str, tuple[str, tuple[str, ...]]] = {
    "split_link_valid": ("pass", ()),
    "split_parent_valid": ("pass", ()),
    "split_missing_relation": ("fail", ("MISSING_HANDOFF_RELATION",)),
    "split_wrong_relation": ("fail", ("MISSING_HANDOFF_RELATION",)),
    "split_submission_overlap": ("fail", ("SUBMISSION_OVERLAPS_EXECUTION",)),
    "split_execution_early_end": ("fail", ("ENDS_BEFORE_EXIT",)),
    "split_execution_missing": ("fail", ("MISSING_SPAN",)),
    "split_submission_missing": ("fail", ("MISSING_SPAN",)),
    "correlated_concurrent_valid": ("pass", ()),
    "correlated_missing_attribute": ("fail", ("MISSING_SPAN",)),
    "correlated_duplicate_attribute": ("inconclusive", ("AMBIGUOUS_ASSOCIATION",)),
    "correlated_swapped_attribute": ("fail", ("STARTS_AFTER_ENTRY", "ENDS_BEFORE_EXIT")),
}


def trial_row(run: dict, raw: str) -> dict:
    expected_verdict, expected_codes = EXPECTED[run["case"]]
    return {
        "case": run["case"],
        "repeat": run["repeat"],
        "expected_verdict": expected_verdict,
        "expected_codes": list(expected_codes),
        "actual": run["ledger_check"]["verdict"],
        "codes": sorted({finding["code"] for finding in run["ledger_check"]["findings"]}),
        "direct": run["direct_check"]["verdict"],
        "name": run["name_check"]["verdict"],
        "clock_eligible": run["clock"]["timing_eligible"],
        "raw": raw,
        "operation_contracts": len(run.get("policies", [])),
        "segment_contracts": sum(len(policy.get("segments", [policy]))
                                 for policy in run.get("policies", [])),
    }


def summarize_rows(rows: list[dict], runner_failures: int) -> dict:
    """Use the runner's retained schema, without inventing a wall-time sample."""
    by_case = {}
    for case in TOPOLOGY_CASES:
        selected = [row for row in rows if row["case"] == case]
        expected_verdict, expected_codes = EXPECTED[case]
        by_case[case] = {
            "trials": len(selected),
            "expected_verdict": expected_verdict,
            "expected_codes": list(expected_codes),
            "verdicts": dict(Counter(row["actual"] for row in selected)),
            "exact_verdicts": sum(row["actual"] == expected_verdict for row in selected),
            "expected_codes_present": sum(set(expected_codes).issubset(row["codes"]) for row in selected),
            "direct_disagreements": sum(row["actual"] != row["direct"] for row in selected),
            "name_disagreements": sum(row["actual"] != row["name"] for row in selected),
            "clock_ineligible": sum(not row["clock_eligible"] for row in selected),
        }
    return {
        "schema": 1,
        "cases": len(TOPOLOGY_CASES),
        "fresh_process_trials": len(rows),
        "runner_failures": runner_failures,
        "exact_expected_verdicts": sum(row["actual"] == row["expected_verdict"] for row in rows),
        "expected_diagnostics_present": sum(set(row["expected_codes"]).issubset(row["codes"]) for row in rows),
        "direct_disagreements": sum(row["actual"] != row["direct"] for row in rows),
        "name_disagreements": sum(row["actual"] != row["name"] for row in rows),
        "operation_contracts": sum(row["operation_contracts"] for row in rows),
        "segment_contracts": sum(row["segment_contracts"] for row in rows),
        "name_false_alarms_on_valid_correlation": sum(
            row["case"] == "correlated_concurrent_valid" and row["actual"] == "pass" and row["name"] == "fail"
            for row in rows
        ),
        "relation_faults_missed_by_name": sum(
            row["case"] in {"split_missing_relation", "split_wrong_relation"}
            and row["actual"] == "fail" and row["name"] == "pass" for row in rows
        ),
        "by_case": by_case,
        "classification": (
            "Executable contract-topology and correlation challenge. Fault cases are controlled operators, "
            "not upstream defect or prevalence claims."
        ),
    }
