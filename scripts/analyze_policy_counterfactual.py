#!/usr/bin/env python3
"""Re-evaluate the same captured observation under alternative declared roles.

This is a policy counterfactual, not a new execution and not evidence that one
role is universally preferable.  It demonstrates why the intended lifetime
must be an input rather than inferred from span shape.
"""
from __future__ import annotations
from collections import Counter
import argparse
import copy
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.oracle import qualify

BASE = ROOT / "results/evaluation"
OUT = ROOT / "results/policy-counterfactual"
SOURCES = {
    "execution_span": "success",
    "submission_span": "submission_only",
    "combined_span": "both_lifetimes",
}
ROLES = ("execution", "submission", "both", "context-only", "unknown")


def main(output: Path = OUT):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, case in SOURCES.items():
        paths = sorted(BASE.glob(f"{case}__fixed__*.json"))
        assert len(paths) == 20
        for repeat, path in enumerate(paths):
            source = json.loads(path.read_text())
            assert source["ledger_check"]["verdict"] == "pass"
            for role in ROLES:
                run = copy.deepcopy(source)
                p = run["policies"][0]
                p["role"] = role
                if role == "context-only":
                    # Context observation remains a separately declared obligation.
                    observed = run.get("contexts", {}).get(p["operation_id"])
                    if observed is None:
                        p.pop("expected_context", None)
                    else:
                        p["expected_context"] = observed
                result = qualify(run)
                codes = sorted(f["code"] for f in result["findings"])
                rows.append({
                    "observation": label,
                    "source_case": case,
                    "repeat": repeat,
                    "declared_role": role,
                    "verdict": result["verdict"],
                    "codes": ";".join(codes),
                    "source": str(path.relative_to(ROOT)),
                })
    aggregate = []
    for label in SOURCES:
        for role in ROLES:
            selected = [x for x in rows if x["observation"] == label and x["declared_role"] == role]
            counts = Counter(x["verdict"] for x in selected)
            codes = Counter(c for x in selected for c in x["codes"].split(";") if c)
            aggregate.append({
                "observation": label,
                "declared_role": role,
                "pass": counts["pass"],
                "fail": counts["fail"],
                "inconclusive": counts["inconclusive"],
                "dominant_codes": ";".join(f"{k}:{v}" for k, v in codes.most_common()),
            })
    with (output / "evaluations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with (output / "matrix.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(aggregate[0])); w.writeheader(); w.writerows(aggregate)
    summary = {
        "schema": 1,
        "source_observations": len(SOURCES) * 20,
        "policy_evaluations": len(rows),
        "roles": list(ROLES),
        "matrix": aggregate,
        "interpretation": "The same trace evidence can be valid for one declared role and invalid or undecidable for another; this does not rank the roles.",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    main(args.output)
