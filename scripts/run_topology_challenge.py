#!/usr/bin/env python3
"""Fresh-process challenge for multi-span lifetime topology and correlation."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.topology_records import EXPECTED, TOPOLOGY_CASES, summarize_rows, trial_row


def single(case: str, repeat: int, output_file: Path) -> int:
    from spanlife.topology_scenarios import run_topology_case
    run = run_topology_case(case, repeat)
    expected_verdict, expected_codes = EXPECTED[case]
    run["expected"] = {"verdict": expected_verdict, "codes": list(expected_codes)}
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(run, indent=2) + "\n")
    print(json.dumps({"case": case, "repeat": repeat,
                      "verdict": run["ledger_check"]["verdict"]}))
    return 0


def orchestrate(output: Path, repeats: int, workers: int) -> int:
    if repeats < 1:
        raise ValueError('repeats must be positive')
    if workers < 1:
        raise ValueError('workers must be positive')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "execution-manifest.json").exists():
        raise SystemExit(f"refusing to overwrite {output}")
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "vendor")])
    jobs = [(case, repeat) for case in TOPOLOGY_CASES for repeat in range(repeats)]
    # Reserve the campaign before launch, including interrupted/failed campaigns.
    manifest_path = output / 'execution-manifest.json'
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump({'schema': 1, 'processes': [], 'failures': [],
                   'trials': len(jobs), 'wall_s': 0, 'status': 'running'}, stream)

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
            (output / f"{stem}.log").write_text(str(exc))
            return {"case": case, "repeat": repeat, "returncode": 124,
                    "elapsed_s": time.perf_counter() - started}
        except OSError as exc:
            return {"case": case, "repeat": repeat, "returncode": 1,
                    "process_error": str(exc), "elapsed_s": time.perf_counter() - started}

    wall_start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processes = list(pool.map(run_one, jobs))
    rows = []
    for (case, repeat), process in zip(jobs, processes):
        if process['returncode']:
            continue
        path = output / f"{case}__{repeat:03d}.json"
        try:
            data = json.loads(path.read_text())
            if type(data['repeat']) is not int or (data['case'], data['repeat']) != (case, repeat):
                raise ValueError('child record identity differs from planned job')
            if data['execution']['status'] != 'completed':
                raise ValueError('child record did not complete')
            raw = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            row = trial_row(data, raw)
            for field in ('actual', 'direct', 'name'):
                if row[field] not in {'pass', 'fail', 'inconclusive'}:
                    raise ValueError(f'invalid {field} verdict')
            if not isinstance(row['codes'], list) or not all(isinstance(code, str) for code in row['codes']):
                raise ValueError('invalid diagnostic codes')
            if type(row['clock_eligible']) is not bool:
                raise ValueError('invalid clock eligibility')
            for field in ('operation_contracts', 'segment_contracts'):
                if type(row[field]) is not int or row[field] < 1:
                    raise ValueError(f'invalid {field} count')
            rows.append(row)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            process['record_error'] = f'{type(exc).__name__}: {exc}'
    failures = [row for row in processes if row['returncode'] or row.get('record_error')]

    summary = {
        **summarize_rows(rows, len(failures)),
        "wall_s": time.time() - wall_start,
    }
    # Save receipts before derived outputs, so a later write failure retains the guard.
    manifest_path.write_text(
        json.dumps({"schema": 1, "processes": processes, "failures": failures,
                    "trials": len(jobs), "wall_s": summary["wall_s"]}, indent=2) + "\n"
    )
    (output / "trials.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    # Agreement between implementations does not establish the expected verdict.
    # Require one completed observation and the declared diagnostics for every job.
    accepted = (not failures and len(rows) == len(jobs)
                and summary["direct_disagreements"] == 0
                and summary["exact_expected_verdicts"] == len(jobs)
                and summary["expected_diagnostics_present"] == len(jobs))
    return 0 if accepted else 1


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
