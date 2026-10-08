#!/usr/bin/env python3
"""Offline consistency check for the audited OpenTelemetry asyncio release boundary."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "provenance/release-lineage"
DATA = json.loads((BASE / "opentelemetry-asyncio-releases.json").read_text())

assert DATA["package"] == "opentelemetry-instrumentation-asyncio"
assert [r["version"] for r in DATA["releases"]] == ["0.44b0", "0.65b0", "0.66b0"]
assert [r["classification"] for r in DATA["releases"]] == ["affected", "affected", "fixed"]
for release in DATA["releases"]:
    assert re.fullmatch(r"[0-9a-f]{40}", release["tag_commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", release["source_blob"])
    assert re.fullmatch(r"[0-9a-f]{40}", release["version_blob"])
    assert re.fullmatch(r"[0-9a-f]{64}", release["wheel_sha256"])
    assert release["wheel"].endswith("-py3-none-any.whl")

affected_44 = (BASE / "v0.44b0-trace_to_thread.py.txt").read_text()
affected_65 = (BASE / "v0.65b0-trace_to_thread.py.txt").read_text()
fixed_66 = (BASE / "v0.66b0-wrap_to_thread_func.py.txt").read_text()
for text in (affected_44, affected_65):
    assert "return func" in text
    assert "func(*args" not in text
    assert "record_process(start" in text
assert "@functools.wraps(func)" in fixed_66
assert "result = func(*args, **kwargs)" in fixed_66
assert "record_process(start" in fixed_66

report = {
    "status": "pass",
    "versions": [r["version"] for r in DATA["releases"]],
    "classifications": [r["classification"] for r in DATA["releases"]],
    "metadata_sha256": hashlib.sha256((BASE / "opentelemetry-asyncio-releases.json").read_bytes()).hexdigest(),
    "scope": DATA["finding"]["scope"],
}
out = ROOT / 'results/release-lineage-verification.json'
out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, indent=2, sort_keys=True))
