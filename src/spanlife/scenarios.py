"""Bounded, in-process runtime scenarios; all network transports remain local."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import os
import threading
from typing import Callable

from opentelemetry import trace
from .capture import Capture, current_parent, select_revision
from .ledger import Ledger, clock_sample, tolerance
from .oracle import qualify
from .baselines import direct_assertions, existence_and_name

TIMEOUT = 5.0


async def wait_thread_event(event: threading.Event) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT
    while not event.is_set():
        if loop.time() > deadline:
            raise TimeoutError("synchronization event not reached")
        await asyncio.sleep(0.0002)


class QueueProbeExecutor(ThreadPoolExecutor):
    """One-worker executor with a post-submit handshake, not a fake executor."""
    def __init__(self):
        super().__init__(max_workers=1, thread_name_prefix="spanlife")
        self.submissions = 0
        self.second_submission = threading.Event()

    def submit(self, fn, /, *args, **kwargs):
        result = super().submit(fn, *args, **kwargs)
        self.submissions += 1
        if self.submissions == 2:
            self.second_submission.set()
        return result


class Trial:
    def __init__(self, case: str, revision: str, repeat: int = 0):
        self.case, self.revision, self.repeat = case, revision, repeat
        self.before = clock_sample()
        self.ledger, self.contexts, self.policies = Ledger(), {}, []
        self.context_lock = threading.Lock()
        self.extra = {}
        mode = ("batch" if case in ("batch_pending", "batch_drained") else
                "drop" if case == "export_drop" else
                "public" if case.startswith("service_") else "simple")
        self.capture = Capture(mode)
        self.cls = select_revision(revision)
        self.instrumentor = None
        self.drained = False

    def instrument(self, *, functions="work", coroutines="", future=False):
        os.environ["OTEL_PYTHON_ASYNCIO_TO_THREAD_FUNCTION_NAMES_TO_TRACE"] = functions
        os.environ["OTEL_PYTHON_ASYNCIO_COROUTINE_NAMES_TO_TRACE"] = coroutines
        os.environ["OTEL_PYTHON_ASYNCIO_FUTURE_TRACE_ENABLED"] = str(future)
        self.instrumentor = self.cls()
        self.instrumentor.instrument(tracer_provider=self.capture.provider,
                                     meter_provider=self.capture.meter_provider)
        assert self.instrumentor.is_instrumented_by_opentelemetry

    def observe(self, oid):
        with self.context_lock:
            self.contexts[oid] = current_parent()

    def policy(self, oid, name, baseline_ids, *, role="execution", parent=None,
               context=None, exclude_queue=False, source="documented execution semantics"):
        # Matching uses a serialized invocation window plus a declared name,
        # never a fitted overlap/duration. Baseline IDs include ended-but-not-
        # exported spans so export failures cannot masquerade as no creation.
        all_spans = self.capture.spans()
        candidates = [s["span_id"] for s in all_spans
                      if s["name"] == name and s["span_id"] not in baseline_ids]
        ended = [sid for n, sid in self.capture.witness.ended
                 if n == name and sid not in baseline_ids]
        p = {"operation_id": oid, "role": role, "span_name": name,
             "span_ids": candidates, "ended_witness": len(ended),
             "error_on_escape": True, "exception_event": True,
             "non_error_types": ["CancelledError"], "source": source,
             "exclude_queue": exclude_queue}
        if parent is not None:
            p["expected_parent"] = parent
        if context is not None:
            p["expected_context"] = context
        self.policies.append(p)

    def before_ids(self):
        return {sid for _, sid in self.capture.witness.ended}

    def finish(self):
        after = clock_sample()
        run = {"schema": 1, "case": self.case, "revision": self.revision,
               "repeat": self.repeat, "ledger": self.ledger.snapshot(),
               "contexts": self.contexts, "policies": self.policies,
               "spans": self.capture.spans(), "metrics": self.capture.metrics(),
               "started": self.capture.witness.started,
               "ended": self.capture.witness.ended, "drained": self.drained,
               "always_on": True, "flushes": self.capture.flushes,
               "clock_before": self.before, "clock_after": after,
               "clock": tolerance(self.before, after), "extra": self.extra}
        run["ledger_check"] = qualify(run)
        run["direct_check"] = direct_assertions(run)
        run["name_check"] = existence_and_name(run)
        if self.instrumentor and self.instrumentor.is_instrumented_by_opentelemetry:
            self.instrumentor.uninstrument()
        self.capture.close()
        return run


async def thread_execution(t: Trial):
    t.instrument()
    case, ledger, cap = t.case, t.ledger, t.capture
    n = 3 if case in ("repeat", "lifecycle") else 1
    delay = [0.002, 0.005, 0.009][t.repeat % 3]
    t.extra["requested_gate_hold_s"] = delay
    pool = QueueProbeExecutor()
    asyncio.get_running_loop().set_default_executor(pool)

    def work(oid, entered, release, behavior):
        with ledger.operation(oid):
            t.observe(oid)
            entered.set()
            if not release.wait(TIMEOUT):
                raise TimeoutError("worker gate was not released")
            if behavior == "inside":
                try:
                    raise ValueError("caught within operation")
                except ValueError:
                    return 7
            if behavior == "escaped":
                raise ValueError("escaped operation")
            return 7

    blocked, release_blocker = threading.Event(), threading.Event()
    blocker = None
    if case == "queue":
        def block_worker():
            blocked.set()
            if not release_blocker.wait(TIMEOUT):
                raise TimeoutError("queue blocker timeout")
        blocker = pool.submit(block_worker)
        await wait_thread_event(blocked)
    try:
        for i in range(n):
            oid = f"op-{i}"
            entered, release = threading.Event(), threading.Event()
            ids = t.before_ids()
            role = "execution"
            if case == "lifecycle" and i == 1:
                t.instrumentor.uninstrument()
                role = "context-only"
            if case == "lifecycle" and i == 2:
                t.instrument()
            behavior = "inside" if case == "handled_inside" else "escaped" if case == "escaped" else "success"
            try:
                if case == "capture_epoch":
                    with cap.tracer.start_as_current_span("creation-parent"):
                        ledger.record(oid, "submit_enter")
                        pending = asyncio.to_thread(work, oid, entered, release, behavior)
                        ledger.record(oid, "submit_exit")
                    parent_cm = cap.tracer.start_as_current_span("execution-parent")
                else:
                    pending = None
                    parent_cm = cap.tracer.start_as_current_span(f"request-{i}")
                with parent_cm as root:
                    parent = str(root.context.span_id)
                    if pending is None:
                        ledger.record(oid, "submit_enter")
                        pending = asyncio.to_thread(work, oid, entered, release, behavior)
                        ledger.record(oid, "submit_exit")
                    task = asyncio.create_task(pending)
                    if case == "queue":
                        await wait_thread_event(pool.second_submission)
                        await asyncio.sleep(delay)
                        ledger.record(oid, "queue_release")
                        release_blocker.set()
                    await wait_thread_event(entered)
                    await asyncio.sleep(delay)
                    release.set()
                    try:
                        value = await asyncio.wait_for(task, TIMEOUT)
                        assert value == 7
                    except ValueError:
                        assert behavior == "escaped"
                    if case != "batch_pending":
                        t.drained = cap.flush()
                t.policy(oid, "asyncio to_thread-work", ids, role=role,
                         parent=parent, context=parent, exclude_queue=case == "queue")
            finally:
                release.set()
        if case != "batch_pending":
            t.drained = cap.flush()
    finally:
        release_blocker.set()
        if blocker is not None:
            await asyncio.wrap_future(blocker)
        # asyncio.run drains the default executor as a second defense.
        pool.shutdown(wait=True)


async def coroutine_shapes(t: Trial):
    case = t.case
    size = 1 if case == "task_keyword" else 3
    t.instrument(functions="", coroutines=",".join(f"job{i}" for i in range(size)))
    entered = [asyncio.Event() for _ in range(size)]
    release = asyncio.Event()
    def make(i):
        async def job():
            oid = f"op-{i}"
            with t.ledger.operation(oid):
                t.observe(oid)
                entered[i].set()
                await asyncio.wait_for(release.wait(), TIMEOUT)
                return i
        job.__name__ = f"job{i}"
        return job
    with t.capture.tracer.start_as_current_span("request") as root:
        parent = str(root.context.span_id)
        ids = t.before_ids()
        coros = [make(i)() for i in range(size)]
        for i in range(size):
            t.ledger.record(f"op-{i}", "submit_enter")
        if case == "task_keyword":
            completion = asyncio.create_task(coro=coros[0])
        else:
            if case == "as_completed_tuple":
                values = tuple(coros)
            elif case == "as_completed_generator":
                values = (c for c in coros)
            else:
                values = coros
            async def consume():
                return [await future for future in asyncio.as_completed(values)]
            completion = asyncio.create_task(consume())
        for i in range(size):
            t.ledger.record(f"op-{i}", "submit_exit")
        try:
            for event in entered:
                await asyncio.wait_for(event.wait(), TIMEOUT)
            await asyncio.sleep([.002, .005, .009][t.repeat % 3])
        finally:
            release.set()
        await asyncio.wait_for(completion, TIMEOUT)
    t.drained = t.capture.flush()
    for i in range(size):
        t.policy(f"op-{i}", f"asyncio coro-job{i}", ids,
                 parent=parent, context=parent, source="explicit named coroutine coverage convention")


def threading_context(t: Trial):
    from opentelemetry.instrumentation.threading import ThreadingInstrumentor
    instrumentor = ThreadingInstrumentor()
    instrumentor.instrument()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="context-reuse")
    identities = []
    def work(oid):
        with t.ledger.operation(oid):
            t.observe(oid)
            identities.append(threading.get_ident())
    try:
        for i in range(2):
            oid = f"op-{i}"
            with t.capture.tracer.start_as_current_span(f"root-{i}") as parent:
                expected = str(parent.context.span_id)
                t.ledger.record(oid, "submit_enter")
                f = pool.submit(work, oid)
                t.ledger.record(oid, "submit_exit")
                f.result(timeout=TIMEOUT)
            t.policy(oid, "", set(), role="context-only", context=expected,
                     source="documented ThreadingInstrumentor context propagation")
        if t.case in ("thread_uninstrument_live", "thread_recreate"):
            if t.case == "thread_recreate":
                pool.shutdown(wait=True)
            instrumentor.uninstrument()
            if t.case == "thread_recreate":
                pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recreated")
        oid = "op-2"
        t.ledger.record(oid, "submit_enter")
        f = pool.submit(work, oid)
        t.ledger.record(oid, "submit_exit")
        f.result(timeout=TIMEOUT)
        t.policy(oid, "", set(), role="context-only", context="0",
                 source="application convention: clean context for next unparented work item")
        t.extra["worker_ids"] = identities
        t.extra["same_reported_thread_id"] = len(set(identities)) == 1
    finally:
        pool.shutdown(wait=True)
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
    t.drained = t.capture.flush()
    t.extra["auto_span_count"] = sum(s["scope"].startswith("opentelemetry.instrumentation.threading")
                                      for s in t.capture.spans())


async def intent_controls(t: Trial):
    oid, cap, ledger = "op-0", t.capture, t.ledger
    pool = ThreadPoolExecutor(max_workers=1)
    entered, release = threading.Event(), threading.Event()
    block_enter, block_release = threading.Event(), threading.Event()
    def blocker():
        block_enter.set()
        assert block_release.wait(TIMEOUT)
    pool.submit(blocker)
    await wait_thread_event(block_enter)
    def callback():
        with ledger.operation(oid):
            entered.set()
            assert release.wait(TIMEOUT)
    try:
        if t.case == "parent_ends_first":
            root = cap.tracer.start_span("already-finished-parent")
            root.end()
            ctx = trace.set_span_in_context(root)
            span_cm = cap.tracer.start_as_current_span("operation", context=ctx)
            role = "both"
        else:
            span_cm = cap.tracer.start_as_current_span("operation")
            role = "submission" if t.case == "submission_only" else "both"
        span = span_cm.__enter__()
        ids = t.before_ids()
        ledger.record(oid, "submit_enter")
        future = pool.submit(callback)
        ledger.record(oid, "submit_exit")
        if role == "submission":
            span_cm.__exit__(None, None, None)
        await asyncio.sleep(.003)
        ledger.record(oid, "queue_release")
        block_release.set()
        await wait_thread_event(entered)
        await asyncio.sleep(.003)
        release.set()
        await asyncio.wait_for(asyncio.wrap_future(future), TIMEOUT)
        if role != "submission":
            span_cm.__exit__(None, None, None)
        t.drained = cap.flush()
        t.policy(oid, "operation", ids, role=role, source="explicit application lifetime convention")
        if t.case == "unknown_intent":
            t.policies[-1]["role"] = "unknown"
    finally:
        release.set(); block_release.set(); pool.shutdown(wait=True)


async def service_adapter(t: Trial):
    """Public tracer setup slice plus real local FastAPI/Starlette dispatch.

    Not the complete upstream application; databases, logs, remote OTLP and
    unrelated instrumentors are excluded. The exporter constructor is the
    only replacement in the pinned public init_tracer function.
    """
    import httpx
    from fastapi import FastAPI, BackgroundTasks
    case = t.case
    t.instrument(functions="" if case == "service_default" else "work")
    app = FastAPI()
    call_index = 0
    active = {}
    def work(oid, behavior="success"):
        with t.ledger.operation(oid):
            t.observe(oid)
            # Barrier-based pilot already covers duration; these are real
            # local route-dispatch and exception-boundary checks, no delay
            # threshold is inferred from this small deterministic workload.
            total = sum(i*i for i in range(300))
            if behavior == "escaped":
                raise ValueError("service callback failed")
            return total
    def manually_traced(oid):
        with t.capture.tracer.start_as_current_span("manual-work"):
            return work(oid)

    @app.get("/async")
    async def async_route():
        oid = active["oid"]
        try:
            value = await asyncio.to_thread(work, oid,
                                           "escaped" if case == "service_caller_handles" else "success")
            return {"value": value}
        except ValueError:
            return {"handled": True}

    @app.get("/sync")
    def sync_route():
        oid = active["oid"]
        value = manually_traced(oid) if case == "service_sync_corrected" else work(oid)
        return {"value": value}

    @app.get("/background", status_code=202)
    async def background_route(background_tasks: BackgroundTasks):
        callback = manually_traced if case == "service_background_corrected" else work
        background_tasks.add_task(callback, active["oid"])
        return {"accepted": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://spanlife.local") as client:
        for i in range(3):
            oid = f"op-{i}"; active["oid"] = oid
            ids = t.before_ids()
            with t.capture.tracer.start_as_current_span(f"local-client-{i}") as root:
                parent = str(root.context.span_id)
                t.ledger.record(oid, "submit_enter")
                route = "/background" if case.startswith("service_background") else "/sync" if case.startswith("service_sync") else "/async"
                response = await client.get(route)
                t.ledger.record(oid, "submit_exit")
            assert response.status_code == (202 if case.startswith("service_background") else 200)
            preflush = len(t.capture.spans())
            t.drained = t.capture.flush()
            target = "manual-work" if case in ("service_sync_corrected", "service_background_corrected") else "asyncio to_thread-work"
            role = "context-only" if case == "service_default" else "execution"
            # Manual execution span is current in the corrected sync callback;
            # otherwise AsyncioInstrumentor preserves the caller context.
            t.policy(oid, target, ids, role=role, parent=parent,
                     context=parent if case not in ("service_sync_corrected", "service_background_corrected") else None,
                     source="application-selected worker execution coverage")
            t.extra.setdefault("requests", []).append({"status": response.status_code,
                "json": response.json(), "exported_before_flush": preflush,
                "exported_after_flush": len(t.capture.spans())})
    t.extra["framework"] = {"fastapi": "0.128.2", "starlette": "0.50.0", "httpx": "0.28.1"}
    t.extra["public_adapter"] = "fastapi-best-architecture:init_tracer (exporter constructor seam)"


CASES = ("success", "queue", "handled_inside", "escaped", "repeat", "capture_epoch", "lifecycle",
         "batch_pending", "batch_drained", "export_drop", "as_completed_list", "as_completed_tuple",
         "as_completed_generator", "task_keyword", "thread_context", "thread_uninstrument_live",
         "thread_recreate", "submission_only", "both_lifetimes", "parent_ends_first", "unknown_intent",
         "service_default", "service_async", "service_caller_handles", "service_sync_gap", "service_sync_corrected",
         "service_background_gap", "service_background_corrected")


def run_case(case, revision="fixed", repeat=0):
    if case not in CASES:
        raise ValueError(case)
    t = Trial(case, revision, repeat)
    if case.startswith("thread_"):
        threading_context(t)
    elif case.startswith("as_completed") or case == "task_keyword":
        asyncio.run(coroutine_shapes(t))
    elif case in ("submission_only", "both_lifetimes", "parent_ends_first", "unknown_intent"):
        asyncio.run(intent_controls(t))
    elif case.startswith("service_"):
        asyncio.run(service_adapter(t))
    else:
        asyncio.run(thread_execution(t))
    return t.finish()
