"""Local-only regression correction for bounded scheduling shapes.

Iterable support is already proposed in upstream PR #5085; it is not claimed
as a new rule or invention here. Keyword create_task normalization is a local
extension tested on Python 3.13. No patch has been submitted upstream.
"""
from collections.abc import Iterable
import asyncio
from wrapt import wrap_function_wrapper


def install_shape_correction(cls):
    original = cls.instrument_method_with_coroutine

    def instrument_method(self, method_name):
        if method_name not in ("create_task", "as_completed"):
            return original(self, method_name)

        def wrapper(method, instance, args, kwargs):
            if method_name == "create_task":
                if args:
                    return method(self.trace_item(args[0]), *args[1:], **kwargs)
                if "coro" in kwargs:
                    kwargs = dict(kwargs)
                    kwargs["coro"] = self.trace_item(kwargs["coro"])
                return method(*args, **kwargs)
            if args and isinstance(args[0], Iterable) and not isinstance(args[0], (str, bytes)):
                args = ([self.trace_item(item) for item in args[0]],) + args[1:]
            return method(*args, **kwargs)
        wrap_function_wrapper(asyncio, method_name, wrapper)

    cls.instrument_method_with_coroutine = instrument_method
