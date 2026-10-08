"""Execute one unchanged public configuration function in a local test seam.

Full upstream module and git-blob checksum are retained. AST extraction avoids
importing unrelated Redis/database/logging and network-export dependencies.
The function body is not rewritten; only the OTLP exporter constructor is
bound to a local exporter. This is not an execution of the full application.
"""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_public_tracer(exporter):
    path = Path(__file__).resolve().parents[2] / "adapters/fastapi-best-architecture/otel.py"
    data = path.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == \
        "7ceda45739b011767c6c7e8e94512e2316c4f89d"
    tree = ast.parse(data, filename=str(path))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_tracer"]
    assert len(functions) == 1
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {"Resource": Resource, "TracerProvider": TracerProvider,
                 "BatchSpanProcessor": BatchSpanProcessor, "trace": trace,
                 "settings": SimpleNamespace(GRAFANA_OTLP_GRPC_ENDPOINT="local-exporter-seam"),
                 "OTLPSpanExporter": lambda **kwargs: exporter}
    exec(compile(module, str(path), "exec"), namespace)
    namespace["init_tracer"](Resource({"service.name": "spanlife.local-adapter"}))
    return trace.get_tracer_provider()
