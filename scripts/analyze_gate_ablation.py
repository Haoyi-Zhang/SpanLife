#!/usr/bin/env python3
"""Ablate SpanLife's uncertainty gates on retained challenge observations.

The analysis asks a narrow CI question: how many previously undecidable cases
would be turned into an unsupported pass/fail action if a gate were removed?
It is a deterministic decision ablation, not an accuracy estimate and not a
set of additional executions.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.oracle import qualify

SOURCE = ROOT / "results/mutation-challenge"
DEFAULT_OUT = ROOT / "results/gate-ablation"

SPECS = {
    "collection_qualification": ("collection_unqualified", "fail"),
    "export_witness": ("export_loss", "fail"),
    "association_uniqueness": ("duplicate_association", "pass"),
    "declared_intent": ("unknown_intent", "pass"),
    "clock_eligibility": ("clock_unqualified", "pass"),
    "submission_completeness": ("both_missing_submission", "pass"),
}


def ablate(gate: str, run: dict) -> dict:
    changed = copy.deepcopy(run)
    policy = changed["policies"][0]
    if gate == "collection_qualification":
        changed["drained"] = True
        changed["always_on"] = True
        policy["ended_witness"] = 0
    elif gate == "export_witness":
        policy["ended_witness"] = 0
    elif gate == "association_uniqueness":
        policy["span_ids"] = policy["span_ids"][:1]
    elif gate == "declared_intent":
        policy["role"] = "execution"
    elif gate == "clock_eligibility":
        changed["clock"]["timing_eligible"] = True
    elif gate == "submission_completeness":
        # Preserve the execution obligation while omitting the missing
        # submission-boundary obligation from the declared combined role.
        policy["role"] = "execution"
    else:  # pragma: no cover
        raise ValueError(gate)
    return qualify(changed)


def main(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for gate, (mutation, expected_ablated) in SPECS.items():
        paths = sorted(SOURCE.glob(f"{mutation}__*.json"))
        if len(paths) != 20:
            raise RuntimeError((mutation, len(paths)))
        for path in paths:
            run = json.loads(path.read_text())
            reference = run["ledger_check"]["verdict"]
            if reference != "inconclusive":
                raise AssertionError((path, reference))
            result = ablate(gate, run)
            if result["verdict"] != expected_ablated:
                raise AssertionError((gate, path, result))
            rows.append(
                {
                    "gate": gate,
                    "mutation": mutation,
                    "source": str(path.relative_to(ROOT)),
                    "reference": reference,
                    "ablated": result["verdict"],
                    "ablated_codes": sorted(
                        finding["code"] for finding in result["findings"]
                    ),
                }
            )
    by_gate = {}
    for gate in SPECS:
        selected = [row for row in rows if row["gate"] == gate]
        by_gate[gate] = {
            "judgments": len(selected),
            "reference": dict(Counter(row["reference"] for row in selected)),
            "ablated": dict(Counter(row["ablated"] for row in selected)),
        }
    summary = {
        "schema": 1,
        "derived_judgments": len(rows),
        "gates": len(SPECS),
        "unsupported_definitive_actions": len(rows),
        "unsupported_passes": sum(row["ablated"] == "pass" for row in rows),
        "unsupported_failures": sum(row["ablated"] == "fail" for row in rows),
        "by_gate": by_gate,
        "interpretation": (
            "Removing any tested gate converts boundedly insufficient evidence "
            "into a definite CI action. Counts describe this retained challenge "
            "set only; they are not precision/recall estimates."
        ),
    }
    (output / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    raise SystemExit(main(args.output.resolve()))
