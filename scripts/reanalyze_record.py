#!/usr/bin/env python3
"""Derive a current raw CI input from recorded observations, without the SDK."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.oracle import qualify


def reanalyze_record(source: Path) -> dict:
    source = source.resolve()
    run = json.loads(source.read_text(encoding="utf-8"))
    result = qualify(run)
    if "reanalysis" in run:
        raise ValueError("use the original recorded observations, not a derived input")
    run["ledger_check"] = result
    run["reanalysis"] = {
        "kind": "current reanalysis of recorded observations",
        "source_record": (source.relative_to(ROOT).as_posix()
                          if source.is_relative_to(ROOT) else source.as_posix()),
        "updated_fields": ["ledger_check"],
        "new_runtime_trials": 0,
    }
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--output", type=Path, required=True,
                        help="new raw JSON file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        run = reanalyze_record(args.record)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(run, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(args.output), "verdict": run["ledger_check"]["verdict"],
                      "new_runtime_trials": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
