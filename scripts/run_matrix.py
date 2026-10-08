#!/usr/bin/env python3
"""Run bounded fresh-process trials; retain stdout/stderr and all failures."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Historical pair first, then separate discovery mechanisms and controls.
MATRIX = [(case, rev) for case in
          ("success", "queue", "handled_inside", "escaped", "repeat", "capture_epoch", "lifecycle")
          for rev in ("affected", "fixed")]
MATRIX += [(case, "fixed") for case in
           ("batch_pending", "batch_drained", "export_drop", "as_completed_list", "as_completed_tuple",
            "as_completed_generator", "task_keyword", "thread_context", "thread_uninstrument_live",
            "thread_recreate", "submission_only", "both_lifetimes", "parent_ends_first", "unknown_intent")]
MATRIX += [(case, "local-shape-fix") for case in
           ("as_completed_list", "as_completed_tuple", "as_completed_generator", "task_keyword")]
MATRIX += [(case, "fixed") for case in
           ("service_default", "service_async", "service_caller_handles", "service_sync_gap", "service_sync_corrected")]
MATRIX += [("service_async", "affected")]
# Held-out paths, not an independent-project holdout.
MATRIX += [("service_background_gap", "fixed"), ("service_background_corrected", "fixed")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=ROOT / "results/reproduced")
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--workers", type=int, default=2, choices=[1, 2])
    args = ap.parse_args()
    if not 1 <= args.repeats <= 100:
        ap.error("repeats must be between 1 and 100")
    args.output = args.output.resolve()
    if (args.output / "execution-manifest.json").exists():
        ap.error("output already contains a run; choose a new --output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT/"src"), str(ROOT/"vendor")]))
    # Do not let ambient auto-instrumentation/sampling configuration determine
    # a supposedly controlled local trial. Retain non-OTel environment normally.
    env = {k: v for k, v in env.items() if not k.startswith("OTEL_")}
    jobs = [(c, v, r) for r in range(args.repeats) for c, v in MATRIX]
    start = time.time()
    def run(job):
        case, revision, rep = job
        base = f"{case}__{revision}__{rep:03d}"
        target = args.output / (base + ".json")
        command = [sys.executable, "-m", "spanlife.cli", "--case", case,
                   "--revision", revision, "--repeat", str(rep), "--output", str(target)]
        t0 = time.perf_counter()
        try:
            process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                     text=True, timeout=30)
            (args.output/(base+".log")).write_text(process.stdout + process.stderr)
            status = process.returncode
        except subprocess.TimeoutExpired as exc:
            status = 124
            target.write_text(json.dumps({"case": case, "revision": revision, "repeat": rep,
                                          "execution": {"status": "timeout", "limit_s": 30}}, indent=2))
            (args.output/(base+".log")).write_text(str(exc))
        return {"case": case, "revision": revision, "repeat": rep,
                "returncode": status, "elapsed_s": time.perf_counter()-t0}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(run, jobs))
    meta = {"schema": 1, "repeats": args.repeats, "workers": args.workers,
            "case_configurations": len(MATRIX), "trials": len(jobs),
            "wall_s": time.time()-start, "failures": [r for r in results if r["returncode"]],
            "processes": results}
    (args.output/"execution-manifest.json").write_text(json.dumps(meta, indent=2)+"\n")
    print(json.dumps({k:v for k,v in meta.items() if k != "processes"}, indent=2))
    return 1 if meta["failures"] else 0

if __name__ == "__main__":
    sys.exit(main())
