"""Local fixture compatibility for unmodified upstream test methods.

This replaces the unavailable opentelemetry-test-utils TestBase only. Each
method is launched in a fresh process, so no private provider-reset API is
used. Do not describe this as the full upstream CI environment or suite.
"""
import unittest
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


class TestBase(unittest.TestCase):
    def setUp(self):
        self.memory_exporter = InMemorySpanExporter()
        self.provider = TracerProvider(sampler=ALWAYS_ON, shutdown_on_exit=False)
        self.provider.add_span_processor(SimpleSpanProcessor(self.memory_exporter))
        trace.set_tracer_provider(self.provider)
        self.memory_metrics_reader = InMemoryMetricReader()
        self.meter_provider = MeterProvider(metric_readers=[self.memory_metrics_reader], shutdown_on_exit=False)
        metrics.set_meter_provider(self.meter_provider)

    def get_sorted_metrics(self, scope):
        data = self.memory_metrics_reader.get_metrics_data()
        return sorted([m for r in data.resource_metrics for s in r.scope_metrics
                       if s.scope.name == scope for m in s.metrics], key=lambda m: m.name)

    def tearDown(self):
        self.provider.force_flush()
        self.provider.shutdown()
        self.meter_provider.shutdown()
