#!/usr/bin/env python3
"""Challenge the frozen checker with independent mutations of real captured traces.

Mutations are test-oracle validation inputs, not upstream defects.  The script
starts from retained, successful SDK observations and changes one evidence field
at a time.  It checks exact diagnostic codes and preserves every derived input.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import argparse
import copy
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify

OUT = ROOT / "results/mutation-challenge"
BASE = ROOT / "results/evaluation"


def event(run, kind):
    return next(e for e in run["ledger"] if e["operation_id"] == "op-0" and e["kind"] == kind)


def selected_span(run):
    sid = str(run["policies"][0]["span_ids"][0])
    return next(s for s in run["spans"] if str(s["span_id"]) == sid)


def mutate(name, run):
    r = copy.deepcopy(run)
    p = r["policies"][0]
    s = selected_span(r) if p.get("span_ids") else None
    eps = r["clock"]["epsilon_ns"]
    if name == "control_execution":
        pass
    elif name == "starts_after_entry":
        enter = event(r, "enter")["wall_ns"]
        s["start_ns"] = min(s["end_ns"] - 1, enter + eps + 200_000)
    elif name == "ends_before_exit":
        exit_ns = event(r, "exit")["wall_ns"]
        s["end_ns"] = max(s["start_ns"] + 1, exit_ns - eps - 200_000)
    elif name == "missing_error_status":
        s["status"] = "UNSET"
    elif name == "missing_exception_event":
        s["events"] = [x for x in s["events"] if x != "exception"]
    elif name == "parent_mismatch":
        s["parent_id"] = "0" if p.get("expected_parent") != "0" else "1"
    elif name == "context_mismatch":
        r["contexts"]["op-0"] = "0" if p.get("expected_context") != "0" else "1"
    elif name == "missing_span":
        sid = str(p["span_ids"][0])
        r["spans"] = [x for x in r["spans"] if str(x["span_id"]) != sid]
        p["ended_witness"] = 0
    elif name == "export_loss":
        sid = str(p["span_ids"][0])
        r["spans"] = [x for x in r["spans"] if str(x["span_id"]) != sid]
        p["ended_witness"] = 1
    elif name == "collection_unqualified":
        sid = str(p["span_ids"][0])
        r["spans"] = [x for x in r["spans"] if str(x["span_id"]) != sid]
        p["ended_witness"] = 0
        r["drained"] = False
    elif name == "duplicate_association":
        clone = copy.deepcopy(s)
        clone["span_id"] = str(int(s["span_id"]) + 1)
        r["spans"].append(clone)
        p["span_ids"].append(clone["span_id"])
    elif name == "includes_queue_wait":
        s["start_ns"] = event(r, "submit_enter")["wall_ns"]
    elif name == "unknown_intent":
        p["role"] = "unknown"
    elif name == "clock_unqualified":
        r["clock"]["timing_eligible"] = False
    elif name == "control_submission":
        pass
    elif name == "submission_as_execution":
        p["role"] = "execution"
    elif name == "both_missing_submission":
        r["ledger"] = [e for e in r["ledger"] if not (e["operation_id"] == "op-0" and e["kind"] == "submit_exit")]
    elif name == "control_parent_ends_first":
        pass
    else:
        raise ValueError(name)
    r["case"] = f"mutation:{name}"
    return r


SPECS = {
    "control_execution": ("success", "pass", None),
    "starts_after_entry": ("success", "fail", "STARTS_AFTER_ENTRY"),
    "ends_before_exit": ("success", "fail", "ENDS_BEFORE_EXIT"),
    "missing_error_status": ("escaped", "fail", "MISSING_ERROR_STATUS"),
    "missing_exception_event": ("escaped", "fail", "MISSING_EXCEPTION_EVENT"),
    "parent_mismatch": ("success", "fail", "PARENT_MISMATCH"),
    "context_mismatch": ("success", "fail", "CONTEXT_MISMATCH"),
    "missing_span": ("success", "fail", "MISSING_SPAN"),
    "export_loss": ("success", "inconclusive", "EXPORT_LOSS"),
    "collection_unqualified": ("success", "inconclusive", "COLLECTION_NOT_QUALIFIED"),
    "duplicate_association": ("success", "inconclusive", "AMBIGUOUS_ASSOCIATION"),
    "includes_queue_wait": ("queue", "fail", "INCLUDES_QUEUE_WAIT"),
    "unknown_intent": ("success", "inconclusive", "UNDECLARED_INTENT"),
    "clock_unqualified": ("success", "inconclusive", "CLOCK_UNQUALIFIED"),
    "control_submission": ("submission_only", "pass", None),
    "submission_as_execution": ("submission_only", "fail", "ENDS_BEFORE_EXIT"),
    "both_missing_submission": ("both_lifetimes", "inconclusive", "MISSING_SUBMISSION_BOUNDARY"),
    "control_parent_ends_first": ("parent_ends_first", "pass", None),
}


def main(output: Path = OUT):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for p in output.glob("*.json"):
        p.unlink()
    for p in output.glob("*.csv"):
        p.unlink()
    rows = []
    for mutation, (base_case, expected, expected_code) in SPECS.items():
        bases = sorted(BASE.glob(f"{base_case}__fixed__*.json"))
        assert len(bases) == 20, (base_case, len(bases))
        for i, path in enumerate(bases):
            source = json.loads(path.read_text())
            assert source["ledger_check"]["verdict"] == "pass", path
            run = mutate(mutation, source)
            run["mutation"] = {
                "name": mutation,
                "source": str(path.relative_to(ROOT)),
                "expected_verdict": expected,
                "expected_code": expected_code,
                "classification": "deliberate checker challenge; not an upstream defect",
            }
            run["ledger_check"] = qualify(run)
            run["direct_check"] = direct_assertions(run)
            run["name_check"] = existence_and_name(run)
            assert run["ledger_check"]["verdict"] == expected, (mutation, i, run["ledger_check"])
            codes = {f["code"] for f in run["ledger_check"]["findings"]}
            if expected_code:
                assert expected_code in codes, (mutation, codes)
            assert run["direct_check"]["verdict"] == expected, (mutation, run["direct_check"], expected)
            out = output / f"{mutation}__{i:03d}.json"
            out.write_text(json.dumps(run, indent=2) + "\n")
            rows.append({
                "mutation": mutation,
                "repeat": i,
                "base_case": base_case,
                "expected": expected,
                "expected_code": expected_code or "",
                "ledger": run["ledger_check"]["verdict"],
                "direct": run["direct_check"]["verdict"],
                "name": run["name_check"]["verdict"],
                "codes": ";".join(sorted(codes)),
                "raw": str(out.relative_to(ROOT)),
            })
    by_mutation = {}
    for mutation in SPECS:
        selected = [x for x in rows if x["mutation"] == mutation]
        by_mutation[mutation] = {
            "base_case": selected[0]["base_case"],
            "expected": selected[0]["expected"],
            "expected_code": selected[0]["expected_code"] or None,
            "ledger": dict(Counter(x["ledger"] for x in selected)),
            "direct": dict(Counter(x["direct"] for x in selected)),
            "name": dict(Counter(x["name"] for x in selected)),
        }
    summary = {
        "schema": 1,
        "mutations": len(SPECS),
        "derived_trials": len(rows),
        "source_trials": 20 * len({v[0] for v in SPECS.values()}),
        "exact_expected_verdicts": sum(x["ledger"] == x["expected"] for x in rows),
        "exact_expected_diagnostics": sum((not x["expected_code"]) or x["expected_code"] in x["codes"].split(";") for x in rows),
        "direct_disagreements": sum(x["ledger"] != x["direct"] for x in rows),
        "name_misses_with_ledger_fail": sum(x["ledger"] == "fail" and x["name"] == "pass" for x in rows),
        "by_mutation": by_mutation,
        "interpretation": "Oracle mutation analysis over retained real SDK traces; not additional software defects or independent application runs.",
    }
    with (output / "trials.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    main(args.output)
