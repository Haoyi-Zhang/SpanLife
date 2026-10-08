"""Executable instrumentation perturbations used only for bounded challenge runs.

Each perturbation changes the fixed OpenTelemetry asyncio wrapper at runtime in
one fresh process.  They are synthetic challenge operators, not reported as
upstream defects.  The application operation ledger, SDK provider/exporter,
and SpanLife/direct baselines remain unchanged.
"""
from __future__ import annotations
import asyncio
from contextvars import Context as VarsContext
from opentelemetry.context import Context as OtelContext
import functools
from timeit import default_timer
from opentelemetry.trace.status import Status, StatusCode

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


def _name(func):
    n = getattr(func, "__name__", None)
    if n is None and isinstance(func, functools.partial):
        n = getattr(func.func, "__name__", None)
    return n


def _start(self, func, *, context=None):
    name = _name(func)
    start = default_timer()
    span = (self._tracer.start_span(f"asyncio to_thread-{name}", context=context)
            if name in self._to_thread_name_to_trace else None)
    return start, span, {"type": "to_thread", "name": name}


def _normal_state(exc):
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    return "exception" if exc else "finished"


def install_runtime_perturbation(cls, name: str) -> None:
    if name not in PERTURBATIONS:
        raise ValueError(f"unsupported perturbation: {name}")
    original = cls.wrap_to_thread_func

    if name == "early_end":
        def method(self, func):
            start, span, attr = _start(self, func)
            attr["state"] = "finished"
            self.record_process(start, attr, span, None)
            return func

    elif name == "late_start":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                caught = None
                traceback = None
                try:
                    result = func(*args, **kwargs)
                except BaseException as exc:  # preserve non-timing semantics
                    caught = exc
                    traceback = exc.__traceback__
                    result = None
                start, span, attr = _start(self, func)
                attr["state"] = _normal_state(caught)
                self.record_process(
                    start,
                    attr,
                    span,
                    None if isinstance(caught, asyncio.CancelledError) else caught,
                )
                if caught is not None:
                    raise caught.with_traceback(traceback)
                return result
            return wrapper

    elif name == "queue_inclusive":
        def method(self, func):
            start, span, attr = _start(self, func)
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                exc = None
                try:
                    result = func(*args, **kwargs)
                    attr["state"] = "finished"
                    return result
                except asyncio.CancelledError:
                    attr["state"] = "cancelled"
                    raise
                except BaseException as caught:
                    exc = caught
                    attr["state"] = _normal_state(caught)
                    raise
                finally:
                    self.record_process(start, attr, span, exc)
            return wrapper

    elif name == "no_span":
        def method(self, func):
            return func

    elif name == "duplicate_span":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                starts=[]
                for _ in range(2):
                    starts.append(_start(self, func))
                exc=None
                try:
                    result=func(*args, **kwargs)
                    for _,_,attr in starts: attr["state"]="finished"
                    return result
                except asyncio.CancelledError:
                    for _,_,attr in starts: attr["state"]="cancelled"
                    raise
                except BaseException as caught:
                    exc=caught
                    for _,_,attr in starts: attr["state"]=_normal_state(caught)
                    raise
                finally:
                    for start,span,attr in starts:
                        self.record_process(start,attr,span,exc)
            return wrapper

    elif name == "wrong_parent":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                start, span, attr = _start(self, func, context=OtelContext())
                exc=None
                try:
                    result=func(*args, **kwargs);attr["state"]="finished";return result
                except asyncio.CancelledError:
                    attr["state"]="cancelled";raise
                except BaseException as caught:
                    exc=caught;attr["state"]=_normal_state(caught);raise
                finally:
                    self.record_process(start,attr,span,exc)
            return wrapper

    elif name == "missing_error_status":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                start, span, attr = _start(self, func)
                try:
                    result=func(*args, **kwargs);attr["state"]="finished";return result
                except asyncio.CancelledError:
                    attr["state"]="cancelled"
                    raise
                except BaseException as caught:
                    attr["state"]=_normal_state(caught)
                    if span and span.is_recording():
                        span.record_exception(caught)
                    raise
                finally:
                    self.record_process(start,attr,span,None)
            return wrapper

    elif name == "missing_exception_event":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                start, span, attr = _start(self, func)
                try:
                    result=func(*args, **kwargs);attr["state"]="finished";return result
                except BaseException as caught:
                    attr["state"]=_normal_state(caught)
                    if span and span.is_recording() and not isinstance(caught, asyncio.CancelledError):
                        span.set_status(Status(StatusCode.ERROR))
                    raise
                finally:
                    self.record_process(start,attr,span,None)
            return wrapper

    elif name == "first_call_only":
        seen=set()
        def method(self, func):
            key=id(func)
            if key in seen:
                return func
            seen.add(key)
            return original(self, func)

    elif name == "empty_context_execution":
        def method(self, func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                def invoke():
                    start, span, attr = _start(self, func, context=OtelContext())
                    exc=None
                    try:
                        result=func(*args, **kwargs);attr["state"]="finished";return result
                    except asyncio.CancelledError:
                        attr["state"]="cancelled";raise
                    except BaseException as caught:
                        exc=caught;attr["state"]=_normal_state(caught);raise
                    finally:
                        self.record_process(start,attr,span,exc)
                return VarsContext().run(invoke)
            return wrapper
    else:  # pragma: no cover
        raise AssertionError(name)

    method.__name__ = f"spanlife_{name}"
    cls.wrap_to_thread_func = method
    cls.trace_to_thread = method
