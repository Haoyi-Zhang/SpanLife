"""Command-line checker for a retained or freshly produced SpanLife record."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .report import build_ci_report, format_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify one SpanLife JSON record")
    parser.add_argument("record", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on-inconclusive", action="store_true")
    args = parser.parse_args()
    run = json.loads(args.record.read_text())
    report = build_ci_report(run)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    if report["verdict"] == "fail":
        return 1
    if report["verdict"] == "inconclusive" and args.fail_on_inconclusive:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
