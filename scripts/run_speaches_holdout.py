#!/usr/bin/env python3
"""Execute a second public-source holdout based on Speaches' tracing decorators.

The public source is imported unchanged from adapters/speaches/tracing.py.  The
complete Speaches application is intentionally not claimed or executed.  Each
trial runs in a fresh process so the global tracer provider is not reset.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.capture import Capture, current_parent
from spanlife.ledger import Ledger, clock_sample, tolerance
from spanlife.oracle import qualify

CASES = ("decorated_sync", "decorated_generator", "generator_misuse", "generator_exception")
EXPECTED = {
    "decorated_sync": ("pass", None),
    "decorated_generator": ("pass", None),
    "generator_misuse": ("fail", "ENDS_BEFORE_EXIT"),
    "generator_exception": ("pass", None),
}


def git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_public_module():
    path = ROOT / "adapters/speaches/tracing.py"
    assert git_blob(path) == "709e44eb95a292e0b8074cd2efd0fff34d39afa7"
    # Execute the two decorator definitions exactly as parsed from the pinned
    # source, while omitting unrelated OTLP/log/metric imports and setup.
    tree = ast.parse(path.read_text(), filename=str(path))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name in {"functools", "logging"} for a in node.names):
            selected.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module == "collections.abc":
            selected.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module == "opentelemetry":
            selected.append(ast.ImportFrom(module="opentelemetry", names=[ast.alias(name="trace")], level=0))
        elif isinstance(node, ast.FunctionDef) and node.name in {"traced", "traced_generator"}:
            selected.append(node)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("spanlife_speaches_tracing", loader=None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(path), "exec"), module.__dict__)
    return module


def single(case: str, repeat: int) -> dict:
    public = load_public_module()
    before = clock_sample()
    cap = Capture("simple")
    ledger = Ledger()
    contexts: dict[str, str] = {}
    oid = "op-0"
    name = {
        "decorated_sync": "speaches.sync",
        "decorated_generator": "speaches.generator",
        "generator_misuse": "speaches.generator-misuse",
        "generator_exception": "speaches.generator-exception",
    }[case]

    def body(*, fail: bool = False):
        with ledger.operation(oid):
            contexts[oid] = current_parent()
            value = sum(i * i for i in range(500 + repeat % 7))
            if fail:
                raise ValueError("public decorator holdout")
            return value

    if case == "decorated_sync":
        wrapped = public.traced(name)(body)
    elif case == "generator_misuse":
        @public.traced(name)
        def wrapped():
            with ledger.operation(oid):
                contexts[oid] = current_parent()
                yield sum(range(100 + repeat % 5))
    else:
        decorator = public.traced_generator(name)
        @decorator
        def wrapped():
            with ledger.operation(oid):
                contexts[oid] = current_parent()
                yield sum(range(100 + repeat % 5))
                if case == "generator_exception":
                    raise ValueError("public generator holdout")

    baseline_ids = {sid for _, sid in cap.witness.ended}
    with cap.tracer.start_as_current_span("holdout-parent") as parent:
        parent_id = str(parent.context.span_id)
        if case == "decorated_sync":
            wrapped()
        else:
            try:
                list(wrapped())
            except ValueError:
                if case != "generator_exception":
                    raise
    drained = cap.flush()
    spans = cap.spans()
    candidates = [s["span_id"] for s in spans if s["name"] == name and s["span_id"] not in baseline_ids]
    ended = [sid for n, sid in cap.witness.ended if n == name and sid not in baseline_ids]
    policy = {
        "operation_id": oid,
        "role": "execution",
        "span_name": name,
        "span_ids": candidates,
        "ended_witness": len(ended),
        "error_on_escape": True,
        "exception_event": True,
        "non_error_types": ["CancelledError", "GeneratorExit"],
        "source": "pinned public Speaches decorator source; local operation convention",
        "exclude_queue": False,
        "expected_parent": parent_id,
        "expected_context": candidates[0] if case == "decorated_sync" else parent_id,
    }
    after = clock_sample()
    run = {
        "schema": 2,
        "case": case,
        "revision": "speaches-993994f",
        "repeat": repeat,
        "ledger": ledger.snapshot(),
        "contexts": contexts,
        "policies": [policy],
        "spans": spans,
        "metrics": [],
        "started": cap.witness.started,
        "ended": cap.witness.ended,
        "drained": drained,
        "always_on": True,
        "flushes": cap.flushes,
        "clock_before": before,
        "clock_after": after,
        "clock": tolerance(before, after),
        "extra": {
            "public_source": "speaches-ai/speaches@993994f:src/speaches/tracing.py",
            "complete_application_executed": False,
            "mechanism": "manual decorator" if case == "decorated_sync" else "lazy generator decorator",
        },
        "execution": {"status": "completed"},
    }
    run["ledger_check"] = qualify(run)
    run["direct_check"] = direct_assertions(run)
    run["name_check"] = existence_and_name(run)
    cap.close()
    return run


def orchestrate(output: Path, repeats: int) -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise SystemExit(f"refusing to overwrite {output}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "vendor")])
    def run_one(job):
        case, repeat = job
        path = output / f"{case}__speaches-993994f__{repeat:03d}.json"
        cmd = [sys.executable, __file__, "--single", case, "--repeat", str(repeat), "--output-file", str(path)]
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        (path.with_suffix(".log")).write_text(p.stdout + p.stderr)
        return {"case": case, "repeat": repeat, "returncode": p.returncode}
    jobs = [(case, repeat) for case in CASES for repeat in range(repeats)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        processes = list(pool.map(run_one, jobs))
    failed = [p for p in processes if p["returncode"]]
    if failed:
        raise RuntimeError(f"holdout children failed: {failed[:3]}")
    rows = [json.loads(p.read_text()) for p in sorted(output.glob("*.json")) if p.name != "summary.json"]
    by_case = {}
    for case in CASES:
        selected = [r for r in rows if r["case"] == case]
        expected_verdict, expected_code = EXPECTED[case]
        counts = Counter(r["ledger_check"]["verdict"] for r in selected)
        codes = Counter(f["code"] for r in selected for f in r["ledger_check"]["findings"])
        # Clock qualification can legitimately abstain.  Controls must never
        # fail; the misuse must never pass and must emit the target code when
        # the clock is eligible.
        if expected_verdict == "pass":
            assert counts["fail"] == 0 and counts["pass"] + counts["inconclusive"] == repeats, (case, counts)
        else:
            assert counts["pass"] == 0 and counts["fail"] + counts["inconclusive"] == repeats, (case, counts)
        if expected_code:
            assert codes[expected_code] == counts["fail"], (case, codes, counts)
        assert all(r["direct_check"]["verdict"] == r["ledger_check"]["verdict"] for r in selected)
        by_case[case] = {"verdicts": dict(counts), "finding_codes": dict(codes)}
    summary = {
        "schema": 1,
        "source": "speaches-ai/speaches@993994f7984bf3fe9655b267448328cf66fccb42",
        "source_blob": "709e44eb95a292e0b8074cd2efd0fff34d39afa7",
        "cases": len(CASES),
        "trials": len(rows),
        "repeats": repeats,
        "by_case": by_case,
        "direct_disagreements": sum(r["direct_check"]["verdict"] != r["ledger_check"]["verdict"] for r in rows),
        "name_misses_with_ledger_fail": sum(r["ledger_check"]["verdict"] == "fail" and r["name_check"]["verdict"] == "pass" for r in rows),
        "scope_limit": "Pinned public decorators plus local operations; not the complete Speaches service or a deployment.",
        "processes": processes,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "processes"}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", choices=CASES)
    ap.add_argument("--repeat", type=int, default=0)
    ap.add_argument("--output-file", type=Path)
    ap.add_argument("--output", type=Path, default=ROOT / "results/speaches-holdout")
    ap.add_argument("--repeats", type=int, default=20)
    args = ap.parse_args()
    if args.single:
        if not args.output_file:
            ap.error("--output-file is required with --single")
        run = single(args.single, args.repeat)
        args.output_file.write_text(json.dumps(run, indent=2) + "\n")
        print(json.dumps({"case": args.single, "verdict": run["ledger_check"]["verdict"]}))
        return 0
    return orchestrate(args.output, args.repeats)


if __name__ == "__main__":
    raise SystemExit(main())
