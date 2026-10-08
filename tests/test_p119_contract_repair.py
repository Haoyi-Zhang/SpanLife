"""Offline synthetic regressions for contract admission and lifetime checks.

These tests use only the standard library and owned JSON fixtures.  They do not
load tracing SDKs, retained results, adapters, native scenarios, or services.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.contracts import normalize_policy
from spanlife.oracle import qualify
from spanlife.report import build_ci_report


ROOT = Path(__file__).resolve().parents[1]


def example(role: str = "execution") -> dict:
    events = [
        {"operation_id": "x", "kind": kind, "wall_ns": value,
         "monotonic_ns": value, "outcome": "returned" if kind == "exit" else None,
         "exception_type": None}
        for kind, value in [("submit_enter", 1), ("submit_exit", 2),
                            ("queue_release", 7), ("enter", 10), ("exit", 20)]
    ]
    return {
        "ledger": events,
        "spans": [{"span_id": "s", "name": "worker", "start_ns": 9, "end_ns": 21,
                   "parent_id": "root", "status": "UNSET", "events": [],
                   "attributes": {"operation": "x"}}],
        "policies": [{"operation_id": "x", "role": role, "span_ids": ["s"],
                      "span_name": "worker", "error_on_escape": True,
                      "exception_event": True, "expected_parent": "root"}],
        "contexts": {}, "drained": True, "always_on": True,
        "clock": {"epsilon_ns": 0, "timing_eligible": True},
    }


def segmented(run: dict) -> dict:
    result = deepcopy(run)
    flat = result["policies"][0]
    segment = {key: value for key, value in flat.items() if key != "operation_id"}
    result["policies"] = [{"operation_id": flat["operation_id"],
                           "segments": [{"segment_id": "primary", **segment}]}]
    return result


class ContractRepairTests(unittest.TestCase):
    def assert_verdict(self, run: dict, expected: str) -> dict:
        result = qualify(run)
        self.assertEqual(result["verdict"], expected)
        self.assertEqual(direct_assertions(run)["verdict"], expected)
        self.assertEqual(build_ci_report(run)["verdict"], expected)
        return result

    def cli(self, run: object, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="spanlife-owned-test-") as directory:
            record = Path(directory) / "record.json"
            record.write_text(json.dumps(run), encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-B", "-m", "spanlife.check_record",
                 str(record), "--format", "json", *args],
                cwd=ROOT, env=env, capture_output=True, text=True,
                timeout=10, check=False,
            )

    def test_true_legacy_output_is_unchanged(self) -> None:
        run = example()
        self.assertEqual(qualify(run), {
            "verdict": "pass", "operations": [{"operation_id": "x", "verdict": "pass"}],
            "findings": [],
        })
        run["spans"][0]["end_ns"] = 12
        expected = {
            "verdict": "fail", "operations": [{"operation_id": "x", "verdict": "fail"}],
            "findings": [{"operation_id": "x", "code": "ENDS_BEFORE_EXIT",
                          "verdict": "fail", "gap_ns": 8}],
        }
        self.assertEqual(qualify(run), expected)
        run["ledger_check"] = deepcopy(expected)
        self.assertTrue(build_ci_report(run)["record_consistent"])

    def test_strict_submission_flat_segment_equivalence(self) -> None:
        for end, expected in [(3, "pass"), (21, "fail")]:
            run = example("submission")
            run["spans"][0].update(start_ns=0, end_ns=end)
            run["policies"][0]["must_end_before_operation_entry"] = True
            for candidate in (run, segmented(run)):
                with self.subTest(end=end, segmented="segments" in candidate["policies"][0]):
                    result = self.assert_verdict(candidate, expected)
                    self.assertEqual(result["operations"][0]["segments"][0]["verdict"], expected)
                    if expected == "fail":
                        self.assertIn("SUBMISSION_OVERLAPS_EXECUTION",
                                      {row["code"] for row in result["findings"]})

    def test_exclude_submission_flat_segment_equivalence(self) -> None:
        for start, expected in [(9, "pass"), (0, "fail")]:
            run = example()
            run["spans"][0]["start_ns"] = start
            run["policies"][0]["exclude_submission"] = True
            for candidate in (run, segmented(run)):
                with self.subTest(start=start, segmented="segments" in candidate["policies"][0]):
                    result = self.assert_verdict(candidate, expected)
                    if expected == "fail":
                        self.assertIn("INCLUDES_SUBMISSION",
                                      {row["code"] for row in result["findings"]})

    def test_attribute_association_flat_segment_equivalence(self) -> None:
        for observed, expected in [("x", "pass"), ("other", "fail")]:
            run = example()
            run["policies"][0].pop("span_ids")
            run["policies"][0]["association"] = {
                "kind": "attributes", "match": {"operation": "x"}}
            run["spans"][0]["attributes"]["operation"] = observed
            for candidate in (run, segmented(run)):
                with self.subTest(observed=observed, segmented="segments" in candidate["policies"][0]):
                    result = self.assert_verdict(candidate, expected)
                    if expected == "fail":
                        self.assertIn("MISSING_SPAN", {row["code"] for row in result["findings"]})
                    # The name-only baseline still intentionally ignores correlation.
                    self.assertEqual(existence_and_name(candidate)["verdict"], "pass")

    def test_name_association_flat_segment_equivalence(self) -> None:
        for name, expected in [("worker", "pass"), ("other", "fail")]:
            run = example()
            run["policies"][0].pop("span_ids")
            run["policies"][0]["association"] = {"kind": "name"}
            run["spans"][0]["name"] = name
            for candidate in (run, segmented(run)):
                with self.subTest(name=name, segmented="segments" in candidate["policies"][0]):
                    self.assert_verdict(candidate, expected)

    def test_explicit_ids_keep_precedence_over_attribute_association(self) -> None:
        run = example()
        run["policies"][0]["association"] = {
            "kind": "attributes", "match": {"operation": "not-observed"}}
        for candidate in (run, segmented(run)):
            self.assert_verdict(candidate, "pass")

    def test_empty_policies_are_rejected_at_public_entrypoints(self) -> None:
        run = example()
        run.update(ledger=[], spans=[], policies=[])
        for entrypoint in (qualify, direct_assertions, existence_and_name, build_ci_report):
            with self.subTest(entrypoint=entrypoint.__name__):
                with self.assertRaisesRegex(ValueError, "non-empty"):
                    entrypoint(run)

    def test_invalid_roles_are_rejected_at_public_entrypoints(self) -> None:
        for role in ("executon", None, [], {}, 1):
            run = example()
            run["policies"][0]["role"] = role
            for candidate in (run, segmented(run)):
                for entrypoint in (qualify, direct_assertions, existence_and_name, build_ci_report):
                    with self.subTest(role=role, segmented="segments" in candidate["policies"][0],
                                      entrypoint=entrypoint.__name__):
                        with self.assertRaisesRegex(ValueError, "unsupported segment role"):
                            entrypoint(candidate)

    def test_basic_record_shape_is_rejected(self) -> None:
        cases = [[], {}, {**example(), "policies": None},
                 {**example(), "ledger": {}}, {**example(), "spans": {}},
                 {**example(), "contexts": []}, {**example(), "clock": {}},
                 {**example(), "clock": {"epsilon_ns": -1, "timing_eligible": True}},
                 {**example(), "clock": {"epsilon_ns": True, "timing_eligible": True}},
                 {**example(), "clock": {"epsilon_ns": 0, "timing_eligible": "true"}},
                 {**example(), "drained": "true"}]
        missing_id = example()
        missing_id["policies"][0].pop("operation_id")
        cases.append(missing_id)
        for index, run in enumerate(cases):
            for entrypoint in (qualify, direct_assertions, existence_and_name, build_ci_report):
                with self.subTest(case=index, entrypoint=entrypoint.__name__):
                    with self.assertRaises(ValueError):
                        entrypoint(run)

    def test_unknown_or_omitted_role_abstains(self) -> None:
        for omit in (False, True):
            run = example("unknown")
            if omit:
                run["policies"][0].pop("role")
            for candidate in (run, segmented(run)):
                with self.subTest(omit=omit, segmented="segments" in candidate["policies"][0]):
                    result = self.assert_verdict(candidate, "inconclusive")
                    self.assertIn("UNDECLARED_INTENT", {row["code"] for row in result["findings"]})
                    self.assertEqual(existence_and_name(candidate)["verdict"], "inconclusive")

    def test_missing_entry_or_exit_never_passes_segments(self) -> None:
        for missing in ("enter", "exit"):
            for role in ("execution", "submission", "context-only"):
                run = example(role)
                run["policies"][0]["exclude_submission"] = False
                run["ledger"] = [row for row in run["ledger"] if row["kind"] != missing]
                for candidate in (run, segmented(run)):
                    with self.subTest(missing=missing, role=role,
                                      segmented="segments" in candidate["policies"][0]):
                        result = self.assert_verdict(candidate, "inconclusive")
                        self.assertEqual(result["operations"][0]["segments"],
                                         [{"segment_id": "primary", "verdict": "inconclusive"}])
                        self.assertIn("INCOMPLETE_OPERATION",
                                      {row["code"] for row in result["findings"]})

    def test_duplicate_boundaries_never_pass_segments(self) -> None:
        for kind in ("enter", "exit"):
            run = segmented(example())
            run["ledger"].append(deepcopy(next(row for row in run["ledger"] if row["kind"] == kind)))
            result = self.assert_verdict(run, "inconclusive")
            self.assertEqual(result["operations"][0]["segments"][0]["verdict"], "inconclusive")

    def test_invalid_order_keeps_independent_parent_failure(self) -> None:
        run = example()
        run["policies"][0]["exclude_submission"] = False
        run["ledger"][-1]["monotonic_ns"] = 0
        run["spans"][0].update(start_ns=12, end_ns=13)
        for candidate in (run, segmented(run)):
            result = self.assert_verdict(candidate, "inconclusive")
            self.assertEqual(result["operations"][0]["segments"][0]["verdict"], "inconclusive")
            self.assertNotIn("ENDS_BEFORE_EXIT", {row["code"] for row in result["findings"]})
            candidate["spans"][0]["parent_id"] = "wrong"
            result = self.assert_verdict(candidate, "fail")
            self.assertEqual(result["operations"][0]["segments"][0]["verdict"], "fail")
            self.assertIn("PARENT_MISMATCH", {row["code"] for row in result["findings"]})

    def test_collection_clock_and_submission_prerequisites_still_abstain(self) -> None:
        for gate in ("drained", "always_on", "clock", "missing_submission", "reversed_submission"):
            run = example("submission")
            run["spans"][0].update(start_ns=0, end_ns=3)
            run["policies"][0]["must_end_before_operation_entry"] = True
            if gate in ("drained", "always_on"):
                run[gate] = False
            elif gate == "clock":
                run["clock"]["timing_eligible"] = False
            elif gate == "missing_submission":
                run["ledger"] = [row for row in run["ledger"] if row["kind"] != "submit_exit"]
            else:
                run["ledger"][1]["monotonic_ns"] = 0
            for candidate in (run, segmented(run)):
                with self.subTest(gate=gate, segmented="segments" in candidate["policies"][0]):
                    self.assert_verdict(candidate, "inconclusive")

    def test_duplicate_association_is_not_a_semantic_failure(self) -> None:
        run = example()
        run["policies"][0].pop("span_ids")
        run["policies"][0]["association"] = {"kind": "attributes", "match": {"operation": "x"}}
        run["spans"].append({**deepcopy(run["spans"][0]), "span_id": "other"})
        for candidate in (run, segmented(run)):
            self.assert_verdict(candidate, "inconclusive")

    def test_missing_span_and_export_witness_stay_distinct(self) -> None:
        for witness, expected in [(0, "fail"), (1, "inconclusive")]:
            run = example()
            run["spans"] = []
            run["policies"][0].update(span_ids=[], ended_witness=witness, exclude_submission=False)
            for candidate in (run, segmented(run)):
                self.assert_verdict(candidate, expected)

    def test_context_only_has_no_collection_or_timing_obligation(self) -> None:
        run = example("context-only")
        run["spans"] = []
        run["drained"] = run["always_on"] = False
        run["clock"]["timing_eligible"] = False
        run["policies"][0].update(expected_context="A", exclude_submission=False)
        for candidate in (run, segmented(run)):
            self.assert_verdict(candidate, "inconclusive")
            candidate["contexts"]["x"] = "A"
            self.assert_verdict(candidate, "pass")
            candidate["contexts"]["x"] = "B"
            self.assert_verdict(candidate, "fail")

    def test_ineligible_clock_keeps_independent_error_failure(self) -> None:
        run = example()
        run["policies"][0]["exclude_submission"] = False
        run["clock"]["timing_eligible"] = False
        run["ledger"][-1].update(outcome="raised", exception_type="ValueError")
        for candidate in (run, segmented(run)):
            result = self.assert_verdict(candidate, "fail")
            self.assertIn("MISSING_ERROR_STATUS", {row["code"] for row in result["findings"]})

    def test_inputs_and_provenance_are_not_mutated(self) -> None:
        run = example()
        run["policies"][0].update(exclude_submission=True, source="owned synthetic fixture")
        run["source_blob"] = "synthetic-provenance"
        before = deepcopy(run)
        self.assert_verdict(run, "pass")
        existence_and_name(run)
        normalize_policy(run["policies"][0])
        self.assertEqual(run, before)

    def test_cli_valid_failure_and_inconclusive_exit_classes(self) -> None:
        for topology in (False, True):
            for expected, gated, exit_code in [
                ("pass", False, 0), ("fail", False, 1),
                ("inconclusive", False, 0), ("inconclusive", True, 2),
            ]:
                run = example("unknown" if expected == "inconclusive" else "submission")
                run["policies"][0]["must_end_before_operation_entry"] = True
                run["spans"][0].update(start_ns=0, end_ns=21 if expected == "fail" else 3)
                if topology:
                    run = segmented(run)
                with self.subTest(topology=topology, expected=expected, gated=gated):
                    proc = self.cli(run, *(["--fail-on-inconclusive"] if gated else []))
                    self.assertEqual(proc.returncode, exit_code, proc.stderr)
                    self.assertEqual(json.loads(proc.stdout)["verdict"], expected)

    def test_cli_rejects_invalid_records_even_without_inconclusive_gate(self) -> None:
        empty = example()
        empty.update(ledger=[], spans=[], policies=[])
        bad_role = example("executon")
        for run in (empty, bad_role, segmented(bad_role), []):
            for gated in (False, True):
                with self.subTest(run=run, gated=gated):
                    proc = self.cli(run, *(["--fail-on-inconclusive"] if gated else []))
                    self.assertEqual(proc.returncode, 2, proc.stderr)
                    self.assertEqual(proc.stdout, "")
                    self.assertIn("INVALID_RECORD", proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)

    def test_stored_mismatch_keeps_exit_three(self) -> None:
        run = example()
        run["ledger_check"] = {"verdict": "fail"}
        report = build_ci_report(run)
        self.assertFalse(report["record_consistent"])
        self.assertEqual(report["ci_exit_code"], 3)
        proc = self.cli(run)
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_small_interval_truth_table_preserves_legacy_and_segment_semantics(self) -> None:
        for start in range(0, 25, 2):
            for end in range(start, 26, 2):
                for epsilon in (0, 1, 2):
                    run = example()
                    run["spans"][0].update(start_ns=start, end_ns=end)
                    run["clock"]["epsilon_ns"] = epsilon
                    expected = "pass" if start <= 10 + epsilon and end >= 20 - epsilon else "fail"
                    with self.subTest(start=start, end=end, epsilon=epsilon):
                        self.assert_verdict(run, expected)
                        run["policies"][0]["exclude_submission"] = False
                        self.assert_verdict(run, expected)
                        self.assert_verdict(segmented(run), expected)


if __name__ == "__main__":
    unittest.main()

