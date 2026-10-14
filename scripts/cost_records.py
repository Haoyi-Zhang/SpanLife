"""Validate a complete paired cost campaign before aggregation or plotting."""
import json
import math
from pathlib import Path


def load_cost_records(directory):
    data = json.loads((Path(directory) / "costs.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("blocks")) is not int or data["blocks"] != 15:
        raise ValueError("Expected a fifteen-block cost campaign")
    rows = data.get("samples")
    if not isinstance(rows, list) or len(rows) != 90:
        raise ValueError("Expected ninety cost samples")
    keys, ordinals = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Cost samples must be objects")
        for field in ("block", "ordinal", "operations", "warmup", "elapsed_ns",
                      "ledger_events", "automatic_spans"):
            if type(row.get(field)) is not int:
                raise ValueError(f"Cost {field} must be an integer, not a Boolean")
        workload, mode = row.get("workload"), row.get("mode")
        if workload not in ("direct", "to_thread") or mode not in ("none", "hook", "hook_sdk"):
            raise ValueError("Unknown cost workload or instrumentation mode")
        key = (row["block"], workload, mode)
        if not 0 <= row["block"] < 15 or key in keys:
            raise ValueError("Invalid or duplicate paired cost cell")
        ordinal = (row["block"], row["ordinal"])
        if not 0 <= row["ordinal"] < 6 or ordinal in ordinals:
            raise ValueError("Invalid or duplicate cost execution ordinal")
        keys.add(key)
        ordinals.add(ordinal)
        if row["operations"] != 1000 or row["warmup"] != 200 or row["elapsed_ns"] <= 0:
            raise ValueError("Incorrect operation denominator or elapsed time")
        if row["ledger_events"] != (0 if mode == "none" else 2400):
            raise ValueError("Operation ledger count differs from the executed workload")
        if row["automatic_spans"] != (1200 if mode == "hook_sdk" else 0):
            raise ValueError("SDK span count differs from the executed workload")
        value = row.get("ns_per_operation")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Cost per operation must be finite and positive")
        if not math.isclose(value, row["elapsed_ns"] / row["operations"], rel_tol=1e-12):
            raise ValueError("Cost per operation does not match its timed denominator")
    return rows
