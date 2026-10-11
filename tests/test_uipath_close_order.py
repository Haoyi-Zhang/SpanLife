"""Exact pinned function, CPython close order, and a recording-only tracer seam.

This is not an SDK/package/deployment run or a timing experiment.  It checks
that the executed public lifecycle statements and retained local patch put
inner asynchronous cleanup on opposite sides of outer span finalization.
"""
import ast
import asyncio
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest


ROOT = Path(__file__).resolve().parents[1]
BLOB = "b7204271a784b7fccce420c11c8c6a9db1d48837"


def decorator(variant, events):
    path = ROOT / "adapters/uipath/decorators.py"
    raw = path.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == BLOB
    source = raw.decode("utf-8")
    if variant == "local-correction":
        # Read only constant replacement strings from the reviewed runner;
        # do not import it or execute its orchestration/SDK paths.
        runner = ast.parse((ROOT / "scripts/run_uipath_holdout.py").read_text())
        loader = next(node for node in runner.body
                      if isinstance(node, ast.FunctionDef) and node.name == "load_public_decorator")
        replacements = {node.targets[0].id: node.value.value for node in ast.walk(loader)
                        if isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id in {"old", "new"}
                        and isinstance(node.value, ast.Constant)}
        assert source.count(replacements["old"]) == 1
        source = source.replace(replacements["old"], replacements["new"])
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_opentelemetry_traced")

    class Span:
        def add_event(self, _name):
            pass

        def record_exception(self, _exc):
            events.append("exception-recorded")

        def set_status(self, *_args):
            events.append("error-status")

    class SpanContext:
        def __enter__(self):
            events.append("span-start")
            return Span()

        def __exit__(self, *_args):
            events.append("span-end")

    namespace = {
        "Any": Any, "Callable": Callable, "Optional": Optional,
        "inspect": inspect, "wraps": wraps,
        "context_api": SimpleNamespace(get_value=lambda _key: False),
        "_SUPPRESS_INSTRUMENTATION_KEY": "unused",
        "UiPathSpanUtils": SimpleNamespace(get_parent_context=lambda: None),
        "trace": SimpleNamespace(get_tracer=lambda _name: SimpleNamespace(
            start_as_current_span=lambda *_args, **_kwargs: SpanContext())),
        "set_span_input_attributes": lambda *_args, **_kwargs: None,
        "set_span_output_attributes": lambda *_args, **_kwargs: None,
        "StatusCode": SimpleNamespace(ERROR="ERROR"), "__name__": __name__,
    }
    module = ast.Module(body=[deepcopy(function)], type_ignores=[])
    exec(compile(module, str(path) + "#recording-tracer-seam", "exec"), namespace)
    return namespace["_opentelemetry_traced"]


@pytest.mark.parametrize("variant", ["public", "local-correction"])
@pytest.mark.parametrize("repeat", range(10))
def test_explicit_early_close_orders_real_async_cleanup(variant, repeat):
    events = []
    decorate = decorator(variant, events)

    async def consume():
        cleanup_done = asyncio.Event()

        async def body():
            try:
                events.append("operation-enter")
                yield repeat
                yield repeat + 1
            finally:
                events.append("cleanup-start")
                await asyncio.sleep(0)
                events.append("cleanup-end")
                cleanup_done.set()

        outer = decorate(name="bounded-close-order")(body)()
        assert await outer.__anext__() == repeat
        await outer.aclose()
        events.append("outer-close-returned")
        await asyncio.wait_for(cleanup_done.wait(), timeout=1)

    asyncio.run(consume())
    assert events.count("span-end") == events.count("cleanup-end") == 1
    if variant == "public":
        assert events.index("span-end") < events.index("outer-close-returned") < events.index("cleanup-end")
    else:
        assert events.index("cleanup-end") < events.index("span-end") < events.index("outer-close-returned")
