"""SDK-independent, bounded test-side operation ledger.

This module deliberately imports no tracing package. Recorded boundaries are
inside the operation under test, not around the instrumentation wrapper.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, asdict
import threading
import time
from typing import Iterator


@dataclass(frozen=True)
class Event:
    operation_id: str
    kind: str
    wall_ns: int
    monotonic_ns: int
    thread_id: int
    outcome: str | None = None
    exception_type: str | None = None
    related_operation_id: str | None = None


class Ledger:
    def __init__(self, max_events: int = 10000) -> None:
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self.max_events = max_events

    def record(self, operation_id: str, kind: str, *, outcome: str | None = None,
               exception_type: str | None = None,
               related_operation_id: str | None = None) -> Event:
        # Capture before taking the list lock: event timestamps describe the
        # boundary, not the order in which threads acquired the collector lock.
        wall = time.time_ns()
        mono = time.perf_counter_ns()
        event = Event(operation_id, kind, wall, mono, threading.get_ident(),
                      outcome, exception_type, related_operation_id)
        with self._lock:
            if len(self._events) >= self.max_events:
                raise RuntimeError("ledger capacity exceeded; trial is incomplete")
            self._events.append(event)
        return event

    @contextmanager
    def operation(self, operation_id: str) -> Iterator[None]:
        self.record(operation_id, "enter")
        outcome, exception_type = "returned", None
        try:
            yield
        except BaseException as exc:
            outcome, exception_type = "raised", type(exc).__name__
            raise
        finally:
            self.record(operation_id, "exit", outcome=outcome,
                        exception_type=exception_type)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(e) for e in self._events]


def clock_sample(n: int = 200) -> dict:
    """Bound wall-read placement by bracketing it with monotonic reads.

    These are empirical diagnostics, not a guarantee against a clock jump
    between samples. The runner also obtains a post-run sample.
    """
    triples = []
    for _ in range(n):
        a = time.perf_counter_ns()
        w = time.time_ns()
        b = time.perf_counter_ns()
        triples.append((a, w, b))
    widths = [b-a for a, _, b in triples]
    offsets = sorted(w-(a+b)//2 for a, w, b in triples)
    return {"samples": n, "max_bracket_ns": max(widths),
            "median_offset_ns": offsets[len(offsets)//2],
            "min_offset_ns": min(offsets), "max_offset_ns": max(offsets)}


def tolerance(before: dict, after: dict) -> dict:
    drift = abs(after["median_offset_ns"] - before["median_offset_ns"])
    epsilon = max(1000, 2 * before["max_bracket_ns"],
                  2 * after["max_bracket_ns"], 2 * drift)
    # A 100 us cap avoids legitimizing a visibly wrong 5 ms interval with a
    # tolerance that expanded to absorb a descheduling/clock anomaly.
    return {"epsilon_ns": epsilon, "offset_drift_ns": drift,
            "timing_eligible": epsilon <= 100000, "cap_ns": 100000}
