"""SDK capture plumbing, kept separate from the operation ledger."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
import threading
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

ROOT = Path(__file__).resolve().parents[2]


def select_revision(revision: str):
    perturbation = revision.removeprefix("perturbation-") if revision.startswith("perturbation-") else None
    if revision not in ("affected", "fixed", "local-shape-fix") and perturbation is None:
        raise ValueError(f"unsupported revision: {revision}")
    if revision == "affected":
        name = "opentelemetry.instrumentation.asyncio"
        directory = ROOT / "vendor/opentelemetry/instrumentation/asyncio"
        spec = importlib.util.spec_from_file_location(name, directory / "affected.py",
                                                      submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
    if revision == "local-shape-fix":
        from .local_correction import install_shape_correction
        install_shape_correction(AsyncioInstrumentor)
    if perturbation is not None:
        from .runtime_perturbations import install_runtime_perturbation
        install_runtime_perturbation(AsyncioInstrumentor, perturbation)
    return AsyncioInstrumentor


class EndWitness(SpanProcessor):
    """Diagnostic witness for exporter loss; NOT the boundary oracle."""
    def __init__(self):
        self.ended = []
        self.started = []
        self.lock = threading.Lock()
    def on_start(self, span, parent_context=None):
        with self.lock:
            self.started.append((span.name, str(span.context.span_id)))
    def on_end(self, span):
        with self.lock:
            self.ended.append((span.name, str(span.context.span_id)))
    def shutdown(self):
        pass
    def force_flush(self, timeout_millis=30000):
        return True


class DroppingExporter(InMemorySpanExporter):
    """Deliberate local fault injection, not a historical SDK defect."""
    def export(self, spans):
        return SpanExportResult.SUCCESS


class Capture:
    def __init__(self, mode="simple"):
        self.exporter = DroppingExporter() if mode == "drop" else InMemorySpanExporter()
        self.witness = EndWitness()
        if mode == "public":
            from .public_adapter import configure_public_tracer
            self.provider = configure_public_tracer(self.exporter)
            # The source uses the SDK default ParentBased(AlwaysOn). Every
            # local request root is sampled, so all tested descendants are on.
        else:
            self.provider = TracerProvider(sampler=ALWAYS_ON, shutdown_on_exit=False)
            processor = (BatchSpanProcessor(self.exporter, schedule_delay_millis=600000,
                                           max_queue_size=2048, max_export_batch_size=512)
                         if mode == "batch" else SimpleSpanProcessor(self.exporter))
            self.provider.add_span_processor(processor)
            trace.set_tracer_provider(self.provider)
        self.provider.add_span_processor(self.witness)
        self.reader = InMemoryMetricReader()
        self.meter_provider = MeterProvider(metric_readers=[self.reader], shutdown_on_exit=False)
        self.tracer = self.provider.get_tracer("spanlife.application")
        self.flushes = []

    def flush(self):
        ok = self.provider.force_flush(timeout_millis=5000)
        self.flushes.append(bool(ok))
        return bool(ok)

    def spans(self):
        return [{"name": s.name, "span_id": str(s.context.span_id),
                 "trace_id": str(s.context.trace_id),
                 "parent_id": str(s.parent.span_id) if s.parent else "0",
                 "start_ns": s.start_time, "end_ns": s.end_time,
                 "status": s.status.status_code.name,
                 "events": [e.name for e in s.events],
                 "links": [{"span_id": str(link.context.span_id),
                            "trace_id": str(link.context.trace_id),
                            "attributes": dict(link.attributes or {})}
                           for link in (s.links or ())],
                 "scope": s.instrumentation_scope.name,
                 "attributes": dict(s.attributes or {})}
                for s in self.exporter.get_finished_spans()]

    def metrics(self):
        data = self.reader.get_metrics_data()
        result = []
        if data:
            for resource in data.resource_metrics:
                for scope in resource.scope_metrics:
                    for m in scope.metrics:
                        for point in m.data.data_points:
                            result.append({"name": m.name, "attributes": dict(point.attributes),
                                           "count": getattr(point, "count", None),
                                           "sum": getattr(point, "sum", None),
                                           "value": getattr(point, "value", None)})
        return result

    def close(self):
        self.provider.shutdown()
        self.meter_provider.shutdown()


def current_parent() -> str:
    return str(trace.get_current_span().get_span_context().span_id)
