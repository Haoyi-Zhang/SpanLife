#!/usr/bin/env python3
"""Measure which executable lifetime perturbations native upstream tests detect.

Every test method runs in a fresh interpreter against the fixed OpenTelemetry
source plus one bounded runtime perturbation.  A mutation is considered caught
by a suite when at least one unchanged upstream method fails or errors.  This
is a test-sensitivity experiment, not a mutation score for the repository.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PERTURBATIONS = (
    "early_end",
    "late_start",
    "queue_inclusive",
    "no_span",
    "duplicate_span",
    "wrong_parent",
    "missing_error_status",
    "missing_exception_event",
    "first_call_only",
    "empty_context_execution",
)
SUITES = ("legacy", "updated")


def suite_methods(suite: str) -> list[str]:
    path = ROOT / "tests/native" / f"test_to_thread_{suite}.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node.name
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def child(suite: str, perturbation: str, method: str) -> dict:
    from spanlife.capture import select_revision

    select_revision(f"perturbation-{perturbation}")
    sys.path.insert(0, str(ROOT / "tests"))
    from native_fixture import TestBase

    sys.modules["opentelemetry.test"] = types.ModuleType("opentelemetry.test")
    compat = types.ModuleType("opentelemetry.test.test_base")
    compat.TestBase = TestBase
    sys.modules["opentelemetry.test.test_base"] = compat

    path = ROOT / "tests/native" / f"test_to_thread_{suite}.py"
    spec = importlib.util.spec_from_file_location("upstream_mutation_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = unittest.TestResult()
    module.TestAsyncioToThread(method).run(result)
    return {
        "suite": suite,
        "perturbation": perturbation,
        "method": method,
        "passed": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": [text for _, text in result.failures],
        "errors": [text for _, text in result.errors],
        "skipped": [reason for _, reason in result.skipped],
    }


def orchestrate(output: Path, workers: int) -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise SystemExit(f"refusing to overwrite {output}")
    methods = {suite: suite_methods(suite) for suite in SUITES}
    jobs = [
        (suite, perturbation, method)
        for suite in SUITES
        for perturbation in PERTURBATIONS
        for method in methods[suite]
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "vendor")]
    )

    def run_one(job: tuple[str, str, str]) -> dict:
        suite, perturbation, method = job
        stem = f"{suite}__{perturbation}__{method}"
        command = [
            sys.executable,
            __file__,
            "--child",
            suite,
            perturbation,
            method,
        ]
        try:
            process = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            row = {
                "suite": suite,
                "perturbation": perturbation,
                "method": method,
                "infrastructure_error": f"timeout: {exc}",
                "passed": False,
            }
            (output / f"{stem}.json").write_text(json.dumps(row, indent=2) + "\n")
            (output / f"{stem}.log").write_text(str(exc))
            return row
        log = process.stdout + process.stderr
        (output / f"{stem}.log").write_text(log)
        if process.returncode:
            row = {
                "suite": suite,
                "perturbation": perturbation,
                "method": method,
                "infrastructure_error": f"child return code {process.returncode}",
                "stdout": process.stdout,
                "stderr": process.stderr,
                "passed": False,
            }
        else:
            try:
                row = json.loads(process.stdout)
            except json.JSONDecodeError as exc:
                row = {
                    "suite": suite,
                    "perturbation": perturbation,
                    "method": method,
                    "infrastructure_error": f"invalid child JSON: {exc}",
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "passed": False,
                }
        (output / f"{stem}.json").write_text(json.dumps(row, indent=2) + "\n")
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run_one, jobs))

    infrastructure = [row for row in rows if row.get("infrastructure_error")]
    by_suite: dict[str, dict] = {}
    for suite in SUITES:
        matrix: dict[str, dict] = {}
        for perturbation in PERTURBATIONS:
            selected = [
                row
                for row in rows
                if row["suite"] == suite and row["perturbation"] == perturbation
            ]
            failing_methods = [row["method"] for row in selected if not row["passed"]]
            matrix[perturbation] = {
                "methods": len(selected),
                "passed_methods": sum(row["passed"] for row in selected),
                "failing_methods": failing_methods,
                "detected": bool(failing_methods),
                "failures": sum(bool(row.get("failures")) for row in selected),
                "errors": sum(bool(row.get("errors")) for row in selected),
            }
        by_suite[suite] = {
            "methods": methods[suite],
            "detected_perturbations": sum(
                item["detected"] for item in matrix.values()
            ),
            "matrix": matrix,
        }

    summary = {
        "schema": 1,
        "base_revision": "fixed OpenTelemetry source e008b0e315b7d0a219c43e7ded1dc02e5abbeb69",
        "test_sources": {
            "legacy": "unchanged upstream pre-fix methods (2)",
            "updated": "unchanged upstream post-fix methods (7)",
        },
        "perturbations": list(PERTURBATIONS),
        "fresh_process_methods": len(rows),
        "infrastructure_errors": len(infrastructure),
        "by_suite": by_suite,
        "classification": (
            "Bounded test-sensitivity matrix over synthetic executable operators; "
            "not repository-wide mutation testing or defect prevalence."
        ),
    }
    (output / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return int(bool(infrastructure))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=3, metavar=("SUITE", "PERTURBATION", "METHOD"))
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results/native-mutation-matrix"
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(*args.child)))
        return 0
    return orchestrate(args.output, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
