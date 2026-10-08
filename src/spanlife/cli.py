from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import traceback
from .scenarios import run_case, CASES
from .runtime_perturbations import PERTURBATIONS


def main():
    parser = argparse.ArgumentParser(description="One fresh-process SpanLife case")
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--revision", choices=["affected", "fixed", "local-shape-fix"] +
                        [f"perturbation-{name}" for name in PERTURBATIONS], default="fixed")
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = run_case(args.case, args.revision, args.repeat)
        data["execution"] = {"status": "completed", "python": platform.python_version(),
                             "pid": os.getpid()}
        code = 0  # An observed discrepancy is data, not a runner crash.
    except BaseException as exc:
        data = {"case": args.case, "revision": args.revision, "repeat": args.repeat,
                "execution": {"status": "failed", "error": str(exc), "type": type(exc).__name__,
                              "traceback": traceback.format_exc()}}
        code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"case": args.case, "revision": args.revision,
                      "execution": data["execution"]["status"],
                      "verdict": data.get("ledger_check", {}).get("verdict")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
