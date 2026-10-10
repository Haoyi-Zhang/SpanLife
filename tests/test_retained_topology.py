"""Offline retained-record regressions; no SDK, application, or subprocess."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.check_record import main as check_record_main
from spanlife.oracle import qualify
from spanlife.report import build_ci_report
from spanlife.topology_records import EXPECTED, TOPOLOGY_CASES, summarize_rows, trial_row

CHECKS = runpy.run_path(str(ROOT / "scripts/verify.py"))
CHECK_TOPOLOGY = CHECKS["check_topology_challenge"]
GLOBALS = CHECK_TOPOLOGY.__globals__


def record(case: str) -> dict:
    return json.loads((ROOT / f"results/topology-challenge/{case}__000.json").read_text())


class RetainedTopologyTests(unittest.TestCase):
    def assert_rejects_edited_json(self, relative: str, edit) -> None:
        original_load = GLOBALS["load_json"]

        def load(path: Path):
            value = original_load(path)
            if path == ROOT / relative:
                edit(value)
            return value

        with patch.dict(GLOBALS, {"load_json": load}):
            with self.assertRaises(AssertionError):
                CHECK_TOPOLOGY()

    def test_archive_and_current_are_reported_separately(self):
        result = CHECK_TOPOLOGY()
        self.assertEqual(result["archival_replay"]["exact_record_checks"], 12)
        current = result["current_reanalysis"]
        self.assertEqual(current["retained_observations"], 12)
        self.assertEqual(current["new_runtime_trials"], 0)
        self.assertEqual(current["exact_expected_verdicts"], 12)
        self.assertEqual(current["expected_diagnostics_present"], 12)
        self.assertEqual([row["case"] for row in current["changed_record_checks"]],
                         ["split_missing_relation", "split_wrong_relation"])

    def test_every_archival_output_replays_exactly(self):
        archive, direct, name = CHECKS["_topology_archive_checkers"]()
        for case in TOPOLOGY_CASES:
            with self.subTest(case=case):
                run = record(case)
                before = deepcopy(run)
                self.assertEqual(archive(run), run["ledger_check"])
                self.assertEqual(direct(run), run["direct_check"])
                self.assertEqual(name(run), run["name_check"])
                self.assertEqual(run, before)

    def test_relation_source_segment_fails_under_current_semantics(self):
        for case in ("split_missing_relation", "split_wrong_relation"):
            with self.subTest(case=case):
                run = record(case)
                before = deepcopy(run)
                current = qualify(run)
                self.assertEqual(run["ledger_check"]["operations"][0]["segments"][1]["verdict"], "pass")
                self.assertEqual(current["operations"][0]["segments"][1],
                                 {"segment_id": "execute", "verdict": "fail"})
                self.assertEqual(current["findings"], run["ledger_check"]["findings"])
                CHECKS["_check_current_topology_acceptance"](run, current, direct_assertions(run))
                self.assertEqual(run, before)

    def test_old_checker_cannot_supply_current_acceptance(self):
        archive, _, _ = CHECKS["_topology_archive_checkers"]()
        with patch.dict(GLOBALS, {"qualify": archive}):
            with self.assertRaises(AssertionError):
                CHECK_TOPOLOGY()

    def test_arbitrary_current_output_changes_are_not_ignored(self):
        def altered(run):
            current = qualify(run)
            if run["case"] == "split_missing_relation":
                current["findings"][0]["observed_parent"] = "different-observation"
            return current

        with patch.dict(GLOBALS, {"qualify": altered}):
            with self.assertRaisesRegex(AssertionError, "unexpected current ledger change"):
                CHECK_TOPOLOGY()

    def test_stored_segment_judgment_tampering_is_rejected(self):
        def edit(run):
            run["ledger_check"]["operations"][0]["segments"][1]["verdict"] = "fail"

        self.assert_rejects_edited_json(
            "results/topology-challenge/split_missing_relation__000.json", edit)

    def test_stored_direct_and_name_tampering_is_rejected(self):
        for field in ("direct_check", "name_check"):
            with self.subTest(field=field):
                self.assert_rejects_edited_json(
                    "results/topology-challenge/split_link_valid__000.json",
                    lambda run: run[field].update(verdict="fail"))

    def test_trial_row_tampering_is_rejected(self):
        for field, value in (("actual", "fail"), ("codes", ["invented"]),
                             ("operation_contracts", 99), ("raw", "wrong.json")):
            with self.subTest(field=field):
                self.assert_rejects_edited_json("results/topology-challenge/trials.json",
                                               lambda rows: rows[0].update({field: value}))

    def test_nested_summary_and_wall_time_tampering_are_rejected(self):
        self.assert_rejects_edited_json(
            "results/topology-challenge/summary.json",
            lambda summary: summary["by_case"]["split_link_valid"].update(exact_verdicts=0))
        self.assert_rejects_edited_json("results/topology-challenge/summary.json",
                                       lambda summary: summary.update(wall_s=0.0))

    def test_manifest_duplicate_case_is_rejected(self):
        self.assert_rejects_edited_json(
            "results/topology-challenge/execution-manifest.json",
            lambda manifest: manifest["processes"][1].update(case="split_link_valid"))

    def test_changed_expected_contract_is_rejected(self):
        self.assert_rejects_edited_json(
            "results/topology-challenge/split_missing_relation__000.json",
            lambda run: run["expected"].update(verdict="pass", codes=[]))

    def test_archival_hash_is_verified_before_module_execution(self):
        target = ROOT / "provenance/evaluated-core/src/spanlife/oracle.py"
        original_read = Path.read_bytes

        def read(path):
            return b"raise RuntimeError('must not execute')" if path == target else original_read(path)

        with patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(AssertionError, "archival topology source changed"):
                CHECKS["_topology_archive_checkers"]()

    def test_archival_contract_import_is_not_the_live_contract(self):
        with patch("spanlife.contracts.normalize_policy", side_effect=RuntimeError("live contract used")):
            archive, direct, name = CHECKS["_topology_archive_checkers"]()
            run = record("split_link_valid")
            self.assertEqual(archive(run), run["ledger_check"])
            self.assertEqual(direct(run), run["direct_check"])
            self.assertEqual(name(run), run["name_check"])

    def test_current_collection_and_clock_gates_do_not_false_pass(self):
        for case in ("split_link_valid", "split_parent_valid"):
            for field in ("drained", "always_on", "timing_eligible"):
                with self.subTest(case=case, field=field):
                    run = record(case)
                    if field == "timing_eligible":
                        run["clock"][field] = False
                    else:
                        run[field] = False
                    self.assertEqual(qualify(run)["verdict"], "inconclusive")
                    self.assertEqual(direct_assertions(run)["verdict"], "inconclusive")
                    with self.assertRaises(AssertionError):
                        CHECKS["_check_current_topology_acceptance"](
                            run, qualify(run), direct_assertions(run))

    def test_relation_missing_identity_abstains_wrong_identity_fails(self):
        for case in ("split_link_valid", "split_parent_valid"):
            with self.subTest(case=case):
                run = record(case)
                target = next(s for s in run["spans"] if s["name"] == "operation.submit")
                target.pop("trace_id")
                self.assertEqual(qualify(run)["verdict"], "inconclusive")
                self.assertEqual(direct_assertions(run)["verdict"], "inconclusive")
                run = record(case)
                target = next(s for s in run["spans"] if s["name"] == "operation.submit")
                target["trace_id"] = "wrong-trace"
                self.assertEqual(qualify(run)["verdict"], "fail")
                self.assertEqual(direct_assertions(run)["verdict"], "fail")
        run = record("split_link_valid")
        source = next(s for s in run["spans"] if s["name"] == "operation.execute")
        target = next(s for s in run["spans"] if s["name"] == "operation.submit")
        source["links"] = None
        self.assertEqual(qualify(run)["verdict"], "inconclusive")
        self.assertEqual(qualify(run)["operations"][0]["segments"][1]["verdict"], "inconclusive")
        source["links"] = [{"span_id": target["span_id"], "trace_id": "cross-trace"}]
        target["trace_id"] = "cross-trace"
        self.assertEqual(qualify(run)["verdict"], "pass")
        self.assertEqual(direct_assertions(run)["verdict"], "pass")

    def test_current_cli_report_keeps_exact_stored_mismatch(self):
        for case in ("split_missing_relation", "split_wrong_relation"):
            with self.subTest(case=case):
                run = record(case)
                self.assertFalse(build_ci_report(run)["record_consistent"])
                self.assertEqual(build_ci_report(run)["ci_exit_code"], 3)
                current = {**run, "ledger_check": qualify(run)}
                self.assertTrue(build_ci_report(current)["record_consistent"])
                self.assertEqual(build_ci_report(current)["ci_exit_code"], 1)

    def test_single_record_cli_preserves_all_exit_classes(self):
        cases = (("split_link_valid", [], 0), ("split_execution_early_end", [], 1),
                 ("correlated_duplicate_attribute", ["--fail-on-inconclusive"], 2),
                 ("split_missing_relation", [], 3), ("split_wrong_relation", [], 3))
        for case, options, expected_exit in cases:
            with self.subTest(case=case):
                args = ["spanlife.check_record", str(ROOT / f"results/topology-challenge/{case}__000.json"),
                        "--format", "json", *options]
                with patch.object(sys, "argv", args), redirect_stdout(StringIO()) as output:
                    exit_code = check_record_main()
                self.assertEqual(exit_code, expected_exit)
                self.assertEqual(json.loads(output.getvalue())["ci_exit_code"], expected_exit)

    def test_generator_uses_shared_pure_expectations_and_rollups(self):
        runner = ast.parse((ROOT / "scripts/run_topology_challenge.py").read_text())
        calls = {node.func.id for node in ast.walk(runner)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue({"trial_row", "summarize_rows"}.issubset(calls))
        scenario = ast.parse((ROOT / "src/spanlife/topology_scenarios.py").read_text())
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.module == "topology_records"
                            and {alias.name for alias in node.names} == {"EXPECTED", "TOPOLOGY_CASES"}
                            for node in scenario.body))
        rows = [trial_row(record(case), f"results/topology-challenge/{case}__000.json")
                for case in TOPOLOGY_CASES]
        summary = summarize_rows(rows, 0)
        self.assertNotIn("wall_s", summary)
        self.assertEqual((summary["fresh_process_trials"], summary["operation_contracts"],
                          summary["segment_contracts"]), (12, 20, 28))
        self.assertEqual(set(EXPECTED), set(TOPOLOGY_CASES))


if __name__ == "__main__":
    unittest.main()
