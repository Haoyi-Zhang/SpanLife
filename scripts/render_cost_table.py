#!/usr/bin/env python3
"""Render absolute costs from the selected raw campaign and its checked summary."""
import argparse
import csv
import math
import statistics
from pathlib import Path

from cost_records import load_cost_records


GROUPS = tuple((workload, mode) for workload in ("direct", "to_thread")
               for mode in ("none", "hook", "hook_sdk"))
FIELDS = ("minimum", "q1", "median", "q3", "maximum")


def quantile(values, probability):
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (position - lower) * (values[upper] - values[lower])


def checked_distributions(raw_directory, summary_path):
    records = load_cost_records(raw_directory)
    with Path(summary_path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(GROUPS):
        raise ValueError("Expected six absolute-cost summary groups")
    summary = {}
    for row in rows:
        key = (row.get("workload"), row.get("mode"))
        if key not in GROUPS or key in summary or row.get("n") != "15":
            raise ValueError("Invalid, repeated, or incomplete absolute-cost group")
        summary[key] = row
    distributions = {}
    for key in GROUPS:
        values = [row["ns_per_operation"] / 1000 for row in records
                  if (row["workload"], row["mode"]) == key]
        expected = dict(zip(FIELDS, (min(values), quantile(values, .25),
                                   statistics.median(values), quantile(values, .75),
                                   max(values))))
        for field in FIELDS:
            value = float(summary[key][field])
            if not math.isfinite(value) or not math.isclose(
                    value, expected[field], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f"Absolute-cost summary differs from raw records: {key} {field}")
        distributions[key] = expected
    return distributions


def render(distributions):
    lines = [r"\begin{tabular}{lrrr}", r"\toprule",
             r"Instrumentation & Median & IQR & Range \\", r"\midrule"]
    for workload, label in (("direct", "Direct callback"),
                            ("to_thread", "Thread transfer")):
        lines.append(r"\multicolumn{4}{l}{" + label + r"} \\")
        for mode, name in (("none", "None"), ("hook", "Hooks"),
                           ("hook_sdk", "Hooks + SDK")):
            row = distributions[workload, mode]
            lines.append(f"{name} & {row['median']:.2f} & "
                         f"{row['q1']:.2f}--{row['q3']:.2f} & "
                         f"{row['minimum']:.2f}--{row['maximum']:.2f} " + r"\\")
        if workload == "direct":
            lines.append(r"\midrule")
    lines.extend((r"\bottomrule", r"\end{tabular}"))
    return "\n".join(lines) + "\n"


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=root.parent / "paper/generated/cost-distribution-table.tex")
    args = parser.parse_args()
    text = render(checked_distributions(root / "results/costs-local",
                                      root / "results/summary/cost-summary-us.csv"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
