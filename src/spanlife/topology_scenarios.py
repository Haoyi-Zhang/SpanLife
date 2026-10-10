"""Executable multi-span topology and correlation scenarios.

These cases exercise two gaps left by single-span, unique-name tests:
(1) one logical operation may be represented by separate submission and
execution spans connected by a parent edge or a link; and (2) concurrent
same-name operations require explicit correlation rather than timing-based
matching.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Link, NonRecordingSpan

from .baselines import direct_assertions, existence_and_name
from .capture import Capture, current_parent
from .ledger import Ledger, clock_sample, tolerance
from .oracle import qualify
from .topology_records import EXPECTED, TOPOLOGY_CASES

TIMEOUT = 5.0


def _segment(segment_id: str, role: str, oid: str, *, strict_submission: bool = False) -> dict[str, Any]:
    segment = {
        "segment_id": segment_id,
        "role": role,
        "span_name": f"operation.{segment_id}",
        "association": {
            "kind": "attributes",
            "match": {
                "spanlife.operation_id": oid,
                "spanlife.segment": segment_id,
            },
        },
        "ended_witness": 0,
        "error_on_escape": True,
        "exception_event": True,
        "non_error_types": ["CancelledError", "GeneratorExit"],
    }
    if role == "execution":
        segment["exclude_queue"] = True
        segment["exclude_submission"] = True
    if strict_submission:
        segment["must_end_before_operation_entry"] = True
    return segment


def _build_run(case: str, repeat: int, before: dict, cap: Capture, ledger: Ledger,
               contexts: dict[str, Any], policies: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
    after = clock_sample()
    run: dict[str, Any] = {
        "schema": 3,
        "case": case,
        "revision": "topology-contract",
        "repeat": repeat,
        "ledger": ledger.snapshot(),
        "contexts": contexts,
        "policies": policies,
        "spans": cap.spans(),
        "metrics": [],
        "started": cap.witness.started,
        "ended": cap.witness.ended,
        "drained": bool(cap.flushes and cap.flushes[-1]),
        "always_on": True,
        "flushes": cap.flushes,
        "clock_before": before,
        "clock_after": after,
        "clock": tolerance(before, after),
        "extra": extra,
        "execution": {"status": "completed"},
    }
    run["ledger_check"] = qualify(run)
    run["direct_check"] = direct_assertions(run)
    run["name_check"] = existence_and_name(run)
    return run


def _split_case(case: str, repeat: int) -> dict[str, Any]:
    before = clock_sample()
    cap = Capture("simple")
    ledger = Ledger()
    contexts: dict[str, Any] = {}
    oid = "op-0"
    blocker_entered = threading.Event()
    release_blocker = threading.Event()
    operation_entered = threading.Event()
    release_operation = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spanlife-topology")

    def blocker() -> None:
        blocker_entered.set()
        if not release_blocker.wait(TIMEOUT):
            raise TimeoutError("queue blocker was not released")

    blocker_future = pool.submit(blocker)
    if not blocker_entered.wait(TIMEOUT):
        raise TimeoutError("queue blocker did not start")

    unrelated_context = None
    if case == "split_wrong_relation":
        unrelated = cap.tracer.start_span("unrelated")
        unrelated_context = unrelated.get_span_context()
        unrelated.end()

    submission_span = None
    submission_context = None
    submission_ended = False
    if case != "split_submission_missing":
        submission_span = cap.tracer.start_span(
            "operation.submit",
            attributes={"spanlife.operation_id": oid, "spanlife.segment": "submit"},
        )
        submission_context = submission_span.get_span_context()

    relation_kind = "parent" if case == "split_parent_valid" else "link"

    def worker() -> None:
        if case == "split_execution_missing":
            with ledger.operation(oid):
                contexts[oid] = {"execute": current_parent()}
                operation_entered.set()
                if not release_operation.wait(TIMEOUT):
                    raise TimeoutError("operation gate timeout")
            return

        kwargs: dict[str, Any] = {
            "name": "operation.execute",
            "attributes": {"spanlife.operation_id": oid, "spanlife.segment": "execute"},
        }
        if case == "split_parent_valid" and submission_context is not None:
            kwargs["context"] = trace.set_span_in_context(NonRecordingSpan(submission_context))
        elif case not in {"split_missing_relation", "split_submission_missing"}:
            linked_context = unrelated_context if case == "split_wrong_relation" else submission_context
            if linked_context is not None:
                kwargs["links"] = [Link(linked_context)]

        if case == "split_execution_early_end":
            span = cap.tracer.start_span(**kwargs)
            span.end()
            with ledger.operation(oid):
                contexts[oid] = {"execute": current_parent()}
                operation_entered.set()
                if not release_operation.wait(TIMEOUT):
                    raise TimeoutError("operation gate timeout")
            return

        with cap.tracer.start_as_current_span(**kwargs):
            with ledger.operation(oid):
                contexts[oid] = {"execute": current_parent()}
                operation_entered.set()
                if not release_operation.wait(TIMEOUT):
                    raise TimeoutError("operation gate timeout")

    try:
        ledger.record(oid, "submit_enter")
        future = pool.submit(worker)
        ledger.record(oid, "submit_exit")

        if submission_span is not None and case != "split_submission_overlap":
            submission_span.end()
            submission_ended = True

        # Retain an actual queue interval so execution spans can exclude it.
        time.sleep(0.002 + (repeat % 3) * 0.001)
        ledger.record(oid, "queue_release")
        release_blocker.set()
        if not operation_entered.wait(TIMEOUT):
            raise TimeoutError("operation did not enter")

        if submission_span is not None and case == "split_submission_overlap":
            # Deliberately overlap the declared submission-only segment with
            # operation execution before closing it.
            time.sleep(0.003)
            submission_span.end()
            submission_ended = True

        time.sleep(0.003 + (repeat % 2) * 0.001)
        release_operation.set()
        future.result(timeout=TIMEOUT)
        blocker_future.result(timeout=TIMEOUT)
        drained = cap.flush()
        assert drained

        segments = [
            _segment("submit", "submission", oid, strict_submission=True),
            _segment("execute", "execution", oid),
        ]
        relations = []
        if case not in {"split_execution_missing", "split_submission_missing"}:
            relations = [{"from": "execute", "to": "submit", "kind": relation_kind}]
        policy = {
            "operation_id": oid,
            "segments": segments,
            "relations": relations,
            "source": "explicit split-lifetime topology contract",
        }
        run = _build_run(
            case, repeat, before, cap, ledger, contexts, [policy],
            {
                "classification": "executable topology challenge",
                "relation": relation_kind if relations else "not-evaluable",
                "submission_span_present": submission_span is not None,
                "execution_span_present": case != "split_execution_missing",
            },
        )
        return run
    finally:
        release_blocker.set()
        release_operation.set()
        if submission_span is not None and not submission_ended:
            submission_span.end()
        pool.shutdown(wait=True, cancel_futures=False)
        cap.close()


def _correlated_case(case: str, repeat: int) -> dict[str, Any]:
    before = clock_sample()
    cap = Capture("simple")
    ledger = Ledger()
    contexts: dict[str, Any] = {}
    policies: list[dict[str, Any]] = []

    def add_policy(oid: str) -> None:
        policies.append({
            "operation_id": oid,
            "segments": [_segment("execute", "execution", oid)],
            "relations": [],
            "source": "explicit attribute correlation for same-name operations",
        })

    if case == "correlated_swapped_attribute":
        for actual_oid, labelled_oid in (("op-0", "op-1"), ("op-1", "op-0")):
            ledger.record(actual_oid, "submit_enter")
            ledger.record(actual_oid, "submit_exit")
            ledger.record(actual_oid, "queue_release")
            with cap.tracer.start_as_current_span(
                "operation.execute",
                attributes={"spanlife.operation_id": labelled_oid, "spanlife.segment": "execute"},
            ):
                with ledger.operation(actual_oid):
                    contexts[actual_oid] = {"execute": current_parent()}
                    time.sleep(0.004 + repeat % 2 * 0.001)
            add_policy(actual_oid)
            time.sleep(0.002)
    else:
        count = 2 if case == "correlated_duplicate_attribute" else 4
        barrier = threading.Barrier(count)
        release_workers = threading.Event()
        pool = ThreadPoolExecutor(max_workers=count, thread_name_prefix="spanlife-correlation")

        def worker(index: int) -> None:
            if not release_workers.wait(TIMEOUT):
                raise TimeoutError("correlation workers were not released")
            oid = f"op-{index}"
            attrs = {"spanlife.segment": "execute"}
            if case != "correlated_missing_attribute":
                attrs["spanlife.operation_id"] = oid
            if case == "correlated_duplicate_attribute" and index == 0:
                # Two spans intentionally carry the same correlation value for
                # one real operation.  Neither interval is chosen by timing.
                with cap.tracer.start_as_current_span("operation.execute", attributes=attrs):
                    with cap.tracer.start_as_current_span("operation.execute", attributes=attrs):
                        with ledger.operation(oid):
                            contexts[oid] = {"execute": current_parent()}
                            barrier.wait(timeout=TIMEOUT)
                            time.sleep(0.004)
                return
            with cap.tracer.start_as_current_span("operation.execute", attributes=attrs):
                with ledger.operation(oid):
                    contexts[oid] = {"execute": current_parent()}
                    barrier.wait(timeout=TIMEOUT)
                    time.sleep(0.004 + index * 0.0004)

        try:
            futures = []
            for index in range(count):
                oid = f"op-{index}"
                ledger.record(oid, "submit_enter")
                futures.append(pool.submit(worker, index))
                ledger.record(oid, "submit_exit")
                ledger.record(oid, "queue_release")
                add_policy(oid)
            release_workers.set()
            for future in futures:
                future.result(timeout=TIMEOUT)
        finally:
            pool.shutdown(wait=True)

    drained = cap.flush()
    assert drained
    run = _build_run(
        case, repeat, before, cap, ledger, contexts, policies,
        {
            "classification": "same-name correlation challenge",
            "operation_count": len(policies),
            "matching": "declared attributes; never time overlap",
        },
    )
    cap.close()
    return run


def run_topology_case(case: str, repeat: int = 0) -> dict[str, Any]:
    if case not in TOPOLOGY_CASES:
        raise ValueError(case)
    if case.startswith("split_"):
        return _split_case(case, repeat)
    return _correlated_case(case, repeat)
