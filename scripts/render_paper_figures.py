# Copyright (c) 2026 SpanLife contributors
# SPDX-License-Identifier: MIT
"""Render the two included timing illustrations without running asset builders.

Reuses scripts/render_traces.py, the artifact copy of paper/figures/draw_traces.py.
The timeline illustrates one retained affected/fixed queue pair, not a population
estimate. The UiPath illustration uses separate public/corrected observations.
"""
import argparse
import csv
import math
from pathlib import Path

from render_traces import COLUMN_PT, PT_PER_CM, draw, register_font


def load_data(source):
    with source.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["figure", "row", "label", "start", "end"]:
            raise ValueError("Expected figure,row,label,start,end header")
        rows = list(reader)
    expected = {
        "timeline": {4: "Affected span", 3: "Affected callback", 2: "Fixed span", 1: "Fixed callback"},
        "uipath": {4: "Public span", 3: "Public operation", 2: "Corrected span", 1: "Corrected operation"},
    }
    if len(rows) != 8:
        raise ValueError("Expected eight retained intervals")
    groups = {}
    for name, labels in expected.items():
        selected = [row for row in rows if row["figure"] == name]
        if len(selected) != 4 or sorted(int(row["row"]) for row in selected) != [1, 2, 3, 4]:
            raise ValueError(f"Expected four unique rows for {name}")
        for row in selected:
            if row["label"] != labels[int(row["row"])]:
                raise ValueError(f"Unexpected interval label in {name}")
            start, end = float(row["start"]), float(row["end"])
            if not math.isfinite(start) or not math.isfinite(end) or end < start:
                raise ValueError("Intervals must be finite and ordered; signed starts are retained")
        groups[name] = selected
    if max(float(row["end"]) for row in groups["timeline"] if row["label"].endswith("callback")) <= 0:
        raise ValueError("Timeline callback end must be positive")
    return groups["timeline"], groups["uipath"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--font-root", type=Path, required=True)
    args = parser.parse_args(argv)
    timeline, uipath = load_data(args.source)
    for relative in ("afm/urw/times/utmr8a.afm", "type1/urw/times/utmr8a.pfb"):
        if not (args.font_root / relative).is_file():
            raise FileNotFoundError(f"Required installed font: {args.font_root / relative}")
    register_font(args.font_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timeline_max = max(float(row["end"]) for row in timeline if not row["label"].endswith("span")) * 1.08
    uipath_min = min(float(row["start"]) for row in uipath) - 8
    uipath_max = max(float(row["end"]) for row in uipath) + 8
    draw(args.output_dir, "timeline", timeline, .92 * COLUMN_PT,
         4.4 * PT_PER_CM, (0, timeline_max), "Milliseconds from invocation entry")
    draw(args.output_dir, "uipath-early-close", uipath, .98 * COLUMN_PT,
         4.3 * PT_PER_CM, (uipath_min, uipath_max), "Microseconds from operation entry")


if __name__ == "__main__":
    main()
