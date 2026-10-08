#!/usr/bin/env python3
"""Execute a fresh-process holdout over UiPath's pinned tracing decorator.

The public source file is copied byte-for-byte from a fixed public commit.  To
keep the experiment CPU-local and independent of the rest of the UiPath
package, this runner parses the exact ``_opentelemetry_traced`` function and
supplies small dependency seams for helpers that only attach payload metadata.
The executed lifetime-control logic is therefore the public function itself;
this is not a claim that the complete UiPath package or a deployed service was
executed.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import hashlib
import importlib.util
import inspect
import types
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opentelemetry import context as context_api
from opentelemetry import trace
from opentelemetry.context import _SUPPRESS_INSTRUMENTATION_KEY
from opentelemetry.trace import SpanContext, TraceFlags
from opentelemetry.trace.status import StatusCode

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.capture import Capture, current_parent
from spanlife.ledger import Ledger, clock_sample, tolerance
from spanlife.oracle import qualify

COMMIT = "7181c279993fbca453b948cf767781282e1e6017"
BLOB = "b7204271a784b7fccce420c11c8c6a9db1d48837"
CASES = (
    "sync_success",
    "sync_exception",
    "async_success",
    "async_exception",
    "generator_success",
    "generator_partial_close",
    "generator_exception",
    "async_generator_success",
    "async_generator_partial_close",
    "async_generator_exception",
)

EXPECTED = {
    case: (
        ("fail", "ENDS_BEFORE_EXIT")
        if case == "async_generator_partial_close"
        else ("pass", None)
    )
    for case in CASES
}


def git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class _UiPathSpanUtils:
    """Dependency seam for the one public helper used on the recording path."""

    @staticmethod
    def get_parent_context():
        return context_api.get_current()


class _UnusedRegistry:
    def register_span(self, _span: Any) -> None:
        raise AssertionError("non-recording path is outside this holdout")


def _unused_non_recording_span(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("recording=False is outside this holdout")


def _set_span_input_attributes(*_args: Any, **_kwargs: Any) -> None:
    """Metadata-only seam; lifetime and error handling remain public code."""


def _set_span_output_attributes(*_args: Any, **_kwargs: Any) -> None:
    """Metadata-only seam; lifetime and error handling remain public code."""


def load_public_decorator(variant: str = "public"):
    """Load the complete pinned source file with transparent local seams.

    The file itself is executed byte-for-byte.  Only the package helpers used
    for payload attributes and parent-context lookup are supplied locally;
    they do not choose span start/end points or exception handling.
    """
    path = ROOT / "adapters/uipath/decorators.py"
    observed = git_blob(path)
    if observed != BLOB:
        raise RuntimeError(f"UiPath source drift: expected {BLOB}, observed {observed}")

    package_names = ["uipath", "uipath.core", "uipath.core.tracing"]
    for name in package_names:
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module

    utils = types.ModuleType("uipath.core.tracing._utils")
    utils.get_supported_params = lambda _impl, params: params
    utils.set_span_input_attributes = _set_span_input_attributes
    utils.set_span_output_attributes = _set_span_output_attributes
    sys.modules[utils.__name__] = utils

    span_utils = types.ModuleType("uipath.core.tracing.span_utils")
    span_utils.ParentedNonRecordingSpan = _unused_non_recording_span
    span_utils.UiPathSpanUtils = _UiPathSpanUtils
    span_utils._span_registry = _UnusedRegistry()
    sys.modules[span_utils.__name__] = span_utils

    module_name = f"spanlife_uipath_decorator_{variant.replace('-', '_')}"
    if variant == "public":
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not create UiPath source loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    elif variant == "local-correction":
        source = path.read_text()
        old = """                outputs = []
                async for item in func(*args, **kwargs):
                    outputs.append(item)
                    span.add_event(f"Yielded: {item}")
                    yield item

                # Set output attributes AFTER execution
                set_span_output_attributes(
                    span,
                    result=outputs,
                    output_processor=output_processor,
                )
"""
        new = """                outputs = []
                inner_generator = func(*args, **kwargs)
                try:
                    async for item in inner_generator:
                        outputs.append(item)
                        span.add_event(f"Yielded: {item}")
                        yield item

                    # Set output attributes AFTER execution
                    set_span_output_attributes(
                        span,
                        result=outputs,
                        output_processor=output_processor,
                    )
                finally:
                    await inner_generator.aclose()
"""
        if source.count(old) != 1:
            raise RuntimeError("local correction target drift")
        source = source.replace(old, new)
        module = types.ModuleType(module_name)
        module.__file__ = str(path)
        exec(compile(source, str(path) + "#local-correction", "exec"), module.__dict__)
    else:
        raise ValueError(f"unsupported UiPath holdout variant: {variant}")
    return module._opentelemetry_traced


def single(case: str, repeat: int, variant: str = "public") -> dict:
    decorate = load_public_decorator(variant)
    before = clock_sample()
    cap = Capture("simple")
    ledger = Ledger()
    contexts: dict[str, str] = {}
    oid = "op-0"
    span_name = f"uipath.{case.replace('_', '-')}"
    escaped = case.endswith("exception")
    partial = case.endswith("partial_close")

    def sync_body() -> int:
        with ledger.operation(oid):
            contexts[oid] = current_parent()
            value = sum(i * i for i in range(700 + repeat % 11))
            if escaped:
                raise ValueError("uipath holdout")
            return value

    async def async_body() -> int:
        with ledger.operation(oid):
            contexts[oid] = current_parent()
            await asyncio.sleep(0)
            value = sum(i * i for i in range(700 + repeat % 11))
            if escaped:
                raise ValueError("uipath holdout")
            return value

    def generator_body():
        with ledger.operation(oid):
            contexts[oid] = current_parent()
            yield sum(range(130 + repeat % 7))
            if escaped:
                raise ValueError("uipath generator holdout")
            yield sum(range(90 + repeat % 5))

    async def async_generator_body():
        with ledger.operation(oid):
            contexts[oid] = current_parent()
            await asyncio.sleep(0)
            yield sum(range(130 + repeat % 7))
            if escaped:
                raise ValueError("uipath async-generator holdout")
            await asyncio.sleep(0)
            yield sum(range(90 + repeat % 5))

    if case.startswith("sync_"):
        wrapped = decorate(name=span_name)(sync_body)
    elif case.startswith("async_generator_"):
        wrapped = decorate(name=span_name)(async_generator_body)
    elif case.startswith("async_"):
        wrapped = decorate(name=span_name)(async_body)
    else:
        wrapped = decorate(name=span_name)(generator_body)

    baseline_ids = {sid for _, sid in cap.witness.ended}
    with cap.tracer.start_as_current_span("uipath-holdout-parent") as parent:
        parent_id = str(parent.context.span_id)
        try:
            if case.startswith("sync_"):
                wrapped()
            elif case.startswith("async_generator_"):
                async def consume_async_generator() -> None:
                    agen = wrapped()
                    if partial:
                        await agen.__anext__()
                        await agen.aclose()
                    else:
                        async for _ in agen:
                            pass
                asyncio.run(consume_async_generator())
            elif case.startswith("async_"):
                asyncio.run(wrapped())
            else:
                gen = wrapped()
                if partial:
                    next(gen)
                    gen.close()
                else:
                    list(gen)
        except ValueError:
            if not escaped:
                raise

    drained = cap.flush()
    spans = cap.spans()
    candidates = [
        s["span_id"]
        for s in spans
        if s["name"] == span_name and s["span_id"] not in baseline_ids
    ]
    ended = [
        sid
        for name, sid in cap.witness.ended
        if name == span_name and sid not in baseline_ids
    ]
    policy = {
        "operation_id": oid,
        "role": "execution",
        "span_name": span_name,
        "span_ids": candidates,
        "ended_witness": len(ended),
        "error_on_escape": True,
        "exception_event": True,
        "non_error_types": ["CancelledError", "GeneratorExit"],
        "source": "pinned public UiPath decorator; local execution convention",
        "exclude_queue": False,
        "expected_parent": parent_id,
        "expected_context": candidates[0] if len(candidates) == 1 else "unresolved",
    }
    after = clock_sample()
    run = {
        "schema": 2,
        "case": case,
        "revision": (
            f"uipath-{COMMIT[:9]}" if variant == "public"
            else f"uipath-{COMMIT[:9]}-local-correction"
        ),
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
            "public_source": (
                "UiPath/uipath-python@"
                f"{COMMIT}:packages/uipath-core/src/uipath/core/tracing/decorators.py"
            ),
            "source_blob": BLOB,
            "variant": variant,
            "complete_package_executed": False,
            "dependency_seams": [
                "UiPathSpanUtils.get_parent_context",
                "input/output attribute helpers",
            ],
            "mechanism": case.rsplit("_", 1)[0],
        },
        "execution": {"status": "completed"},
    }
    run["ledger_check"] = qualify(run)
    run["direct_check"] = direct_assertions(run)
    run["name_check"] = existence_and_name(run)
    cap.close()
    return run


def orchestrate(output: Path, repeats: int, workers: int, variant: str = "public") -> int:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise SystemExit(f"refusing to overwrite {output}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "vendor")])

    def run_one(job: tuple[str, int]) -> dict:
        case, repeat = job
        suffix = f"uipath-{COMMIT[:9]}" + (
            "" if variant == "public" else "-local-correction"
        )
        path = output / f"{case}__{suffix}__{repeat:03d}.json"
        cmd = [
            sys.executable,
            __file__,
            "--single",
            case,
            "--repeat",
            str(repeat),
            "--output-file",
            str(path),
            "--variant",
            variant,
        ]
        process = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        path.with_suffix(".log").write_text(process.stdout + process.stderr)
        return {"case": case, "repeat": repeat, "returncode": process.returncode}

    jobs = [(case, repeat) for case in CASES for repeat in range(repeats)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processes = list(pool.map(run_one, jobs))
    failed = [p for p in processes if p["returncode"]]
    if failed:
        raise RuntimeError(f"UiPath holdout children failed: {failed[:5]}")

    rows = [
        json.loads(path.read_text())
        for path in sorted(output.glob("*.json"))
        if path.name != "summary.json"
    ]
    by_case: dict[str, Any] = {}
    for case in CASES:
        selected = [row for row in rows if row["case"] == case]
        counts = Counter(row["ledger_check"]["verdict"] for row in selected)
        codes = Counter(
            finding["code"]
            for row in selected
            for finding in row["ledger_check"]["findings"]
        )
        expected_verdict, expected_code = (
            ("pass", None) if variant == "local-correction" else EXPECTED[case]
        )
        if expected_verdict == "pass":
            if counts["fail"] or counts["pass"] + counts["inconclusive"] != repeats:
                raise AssertionError((case, counts, codes))
        else:
            if counts["pass"] or counts["fail"] + counts["inconclusive"] != repeats:
                raise AssertionError((case, counts, codes))
            if codes[expected_code] != counts["fail"]:
                raise AssertionError((case, counts, codes))
        if not all(
            row["direct_check"]["verdict"] == row["ledger_check"]["verdict"]
            for row in selected
        ):
            raise AssertionError(f"direct disagreement in {case}")
        by_case[case] = {
            "expected_verdict": expected_verdict,
            "expected_code": expected_code,
            "verdicts": dict(counts),
            "finding_codes": dict(codes),
            "clock_ineligible": sum(
                not row["clock"]["timing_eligible"] for row in selected
            ),
        }

    summary = {
        "schema": 1,
        "source": f"UiPath/uipath-python@{COMMIT}",
        "source_blob": BLOB,
        "variant": variant,
        "cases": len(CASES),
        "trials": len(rows),
        "repeats": repeats,
        "by_case": by_case,
        "verdicts": dict(Counter(row["ledger_check"]["verdict"] for row in rows)),
        "direct_disagreements": sum(
            row["direct_check"]["verdict"] != row["ledger_check"]["verdict"]
            for row in rows
        ),
        "name_misses_with_ledger_fail": sum(
            row["ledger_check"]["verdict"] == "fail"
            and row["name_check"]["verdict"] == "pass"
            for row in rows
        ),
        "scope_limit": (
            "Complete pinned public source file with local metadata/context dependency "
            "seams; not the complete UiPath package, product, or deployment."
        ),
        "processes": processes,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "processes"}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", choices=CASES)
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results/uipath-holdout"
    )
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--variant", choices=("public", "local-correction"), default="public")
    args = parser.parse_args()
    if args.single:
        if not args.output_file:
            parser.error("--output-file is required with --single")
        run = single(args.single, args.repeat, args.variant)
        args.output_file.write_text(json.dumps(run, indent=2) + "\n")
        print(
            json.dumps(
                {"case": args.single, "verdict": run["ledger_check"]["verdict"]}
            )
        )
        return 0
    return orchestrate(args.output, args.repeats, args.workers, args.variant)


if __name__ == "__main__":
    raise SystemExit(main())
