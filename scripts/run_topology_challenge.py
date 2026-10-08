#!/usr/bin/env python3
"""Fresh-process challenge for multi-span lifetime topology and correlation."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.topology_scenarios import EXPECTED, TOPOLOGY_CASES, run_topology_case


def single(case: str, repeat: int, output_file: Path) -> int:
    run = run_topology_case(case, repeat)
    expected_verdict, expected_codes = EXPECTED[case]
    run["expected"] = {"verdict": expected_verdict, "codes": list(expected_codes)}
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(run, indent=2) + "\n")
    print(json.dumps({"case": case, "repeat": repeat,
                      "verdict": run["ledger_check"]["verdict"]}))
    return 0


def orchestrate(output: Path, repeats: int, workers: int) -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "execution-manifest.json").exists():
        raise SystemExit(f"refusing to overwrite {output}")
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "vendor")])
    jobs = [(case, repeat) for case in TOPOLOGY_CASES for repeat in range(repeats)]

    def run_one(job: tuple[str, int]) -> dict:
        case, repeat = job
        stem = f"{case}__{repeat:03d}"
        target = output / f"{stem}.json"
        cmd = [sys.executable, __file__, "--single", case, "--repeat", str(repeat),
               "--output-file", str(target)]
        started = time.perf_counter()
        try:
            proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                                  text=True, timeout=30)
            (output / f"{stem}.log").write_text(proc.stdout + proc.stderr)
            return {"case": case, "repeat": repeat, "returncode": proc.returncode,
                    "elapsed_s": time.perf_counter() - started}
        except subprocess.TimeoutExpired as exc:
            target.write_text(json.dumps({"case": case, "repeat": repeat,
                                          "execution": {"status": "timeout", "limit_s": 30}},
                                         indent=2) + "\n")
            (output / f"{stem}.log").write_text(str(exc))
            return {"case": case, "repeat": repeat, "returncode": 124,
                    "elapsed_s": time.perf_counter() - started}

    wall_start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processes = list(pool.map(run_one, jobs))
    failures = [row for row in processes if row["returncode"]]

    rows = []
    for case, repeat in jobs:
        path = output / f"{case}__{repeat:03d}.json"
        data = json.loads(path.read_text())
        if data.get("execution", {}).get("status") != "completed":
            continue
        expected_verdict, expected_codes = EXPECTED[case]
        codes = {finding["code"] for finding in data["ledger_check"]["findings"]}
        rows.append({
            "case": case,
            "repeat": repeat,
            "expected_verdict": expected_verdict,
            "expected_codes": list(expected_codes),
            "actual": data["ledger_check"]["verdict"],
            "codes": sorted(codes),
            "direct": data["direct_check"]["verdict"],
            "name": data["name_check"]["verdict"],
            "clock_eligible": data["clock"]["timing_eligible"],
            "raw": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "operation_contracts": len(data.get("policies", [])),
            "segment_contracts": sum(len(policy.get("segments", [policy])) for policy in data.get("policies", [])),
        })

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
            "expected_codes_present": sum(set(expected_codes).issubset(set(row["codes"])) for row in selected),
            "direct_disagreements": sum(row["actual"] != row["direct"] for row in selected),
            "name_disagreements": sum(row["actual"] != row["name"] for row in selected),
            "clock_ineligible": sum(not row["clock_eligible"] for row in selected),
        }

    summary = {
        "schema": 1,
        "cases": len(TOPOLOGY_CASES),
        "fresh_process_trials": len(rows),
        "runner_failures": len(failures),
        "exact_expected_verdicts": sum(row["actual"] == row["expected_verdict"] for row in rows),
        "expected_diagnostics_present": sum(set(row["expected_codes"]).issubset(set(row["codes"])) for row in rows),
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
            and row["actual"] == "fail" and row["name"] == "pass"
            for row in rows
        ),
        "wall_s": time.time() - wall_start,
        "by_case": by_case,
        "classification": (
            "Executable contract-topology and correlation challenge. Fault cases are controlled operators, "
            "not upstream defect or prevalence claims."
        ),
    }
    (output / "trials.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "execution-manifest.json").write_text(
        json.dumps({"schema": 1, "processes": processes, "failures": failures,
                    "trials": len(jobs), "wall_s": summary["wall_s"]}, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))
    return 1 if failures or summary["direct_disagreements"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", choices=TOPOLOGY_CASES)
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "results/topology-challenge")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 9))
    args = parser.parse_args()
    if args.single:
        if args.output_file is None:
            parser.error("--output-file is required with --single")
        return single(args.single, args.repeat, args.output_file)
    return orchestrate(args.output, args.repeats, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
