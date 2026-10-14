"""Owned malformed-record controls for paired cost aggregation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/cost_records.py"
SPEC = importlib.util.spec_from_file_location("spanlife_cost_records", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def campaign():
    rows = []
    for block in range(15):
        for workload in ("direct", "to_thread"):
            for mode in ("none", "hook", "hook_sdk"):
                rows.append(dict(block=block, ordinal=len(rows) % 6, workload=workload, mode=mode,
                                 operations=1000, warmup=200, elapsed_ns=100000,
                                 ns_per_operation=100.0,
                                 ledger_events=0 if mode == "none" else 2400,
                                 automatic_spans=1200 if mode == "hook_sdk" else 0))
    return dict(blocks=15, samples=rows)


class CostRecordChecks(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "costs.json").write_text(json.dumps(data), encoding="utf-8")
            return MODULE.load_cost_records(directory)

    def test_complete_campaign(self):
        self.assertEqual(len(self.read(campaign())), 90)

    def test_boolean_denominators(self):
        for field in ("blocks", "block", "ordinal", "operations", "warmup", "elapsed_ns",
                      "ledger_events", "automatic_spans", "ns_per_operation"):
            data = campaign()
            (data if field == "blocks" else data["samples"][0])[field] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.read(data)

    def test_missing_duplicate_and_unknown_cells(self):
        for mutation in ("missing", "duplicate", "unknown", "ordinal"):
            data = campaign()
            if mutation == "missing":
                data["samples"].pop()
            elif mutation == "duplicate":
                data["samples"][-1] = copy.deepcopy(data["samples"][0])
            elif mutation == "unknown":
                data["samples"][0]["mode"] = "other"
            else:
                data["samples"][1]["ordinal"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.read(data)

    def test_work_and_elapsed_mismatches(self):
        for field, value in (("operations", 999), ("ledger_events", 2400),
                             ("automatic_spans", 1200), ("elapsed_ns", 0),
                             ("ns_per_operation", 101.0), ("ns_per_operation", float("inf"))):
            data = campaign()
            data["samples"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.read(data)


if __name__ == "__main__":
    unittest.main()
