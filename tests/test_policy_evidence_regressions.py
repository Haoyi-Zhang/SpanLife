"""Small in-memory contract regressions; no SDKs, services, or retained replay."""
from copy import deepcopy
import unittest

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify
from spanlife.report import build_ci_report


def record():
    return {
        "ledger": [{"operation_id": "op", "kind": kind, "wall_ns": t,
                    "monotonic_ns": t, "outcome": "returned", "exception_type": None}
                   for kind, t in [("enter", 10), ("exit", 20)]],
        "spans": [{"span_id": "s", "name": "work", "start_ns": 9, "end_ns": 21,
                   "trace_id": "t", "parent_id": "root", "links": [],
                   "status": "UNSET", "events": []}],
        "policies": [{"operation_id": "op", "role": "execution",
                      "span_name": "work", "span_ids": ["s"]}],
        "contexts": {}, "drained": True, "always_on": True,
        "clock": {"epsilon_ns": 0, "timing_eligible": True},
    }


def segmented(run):
    run = deepcopy(run)
    policy = run["policies"][0]
    run["policies"] = [{"operation_id": policy["operation_id"], "segments": [
        {"segment_id": "primary", **{k: v for k, v in policy.items() if k != "operation_id"}}]}]
    return run


class PolicyEvidenceRegressions(unittest.TestCase):
    def check(self, run, verdict, code=None):
        before = deepcopy(run)
        result = qualify(run)
        self.assertEqual(result["verdict"], verdict)
        self.assertEqual(direct_assertions(run)["verdict"], verdict)
        self.assertEqual(build_ci_report(run)["verdict"], verdict)
        if code:
            self.assertIn(code, {row["code"] for row in result["findings"]})
        self.assertEqual(run, before)
        return result

    def test_context_expectation_cannot_be_omitted(self):
        for observed in ({}, {"op": "A"}):
            run = record()
            run["policies"][0]["role"] = "context-only"
            run["contexts"] = observed
            for null_expectation in (False, True):
                if null_expectation:
                    run["policies"][0]["expected_context"] = None
                for candidate in (run, segmented(run)):
                    self.check(candidate, "inconclusive", "MISSING_CONTEXT_EXPECTATION")

    def test_context_identity_and_missing_observation(self):
        for observed, verdict in [(None, "inconclusive"), ("A", "pass"), ("B", "fail")]:
            run = record()
            run["spans"] = []
            run["drained"] = run["always_on"] = False
            run["clock"]["timing_eligible"] = False
            run["policies"][0].update(role="context-only", expected_context="A")
            if observed is not None:
                run["contexts"]["op"] = observed
            for candidate in (run, segmented(run)):
                self.check(candidate, verdict)

    def test_unknown_end_count_is_not_zero(self):
        for witness, verdict, code in [(None, "inconclusive", "END_WITNESS_UNQUALIFIED"),
                                       (0, "fail", "MISSING_SPAN"),
                                       (1, "inconclusive", "EXPORT_LOSS"),
                                       (-1, "inconclusive", "END_WITNESS_UNQUALIFIED")]:
            run = record()
            run["spans"] = []
            if witness is not None:
                run["policies"][0]["ended_witness"] = witness
            for candidate in (run, segmented(run)):
                self.check(candidate, verdict, code)

    def test_absence_still_requires_completion_and_collection(self):
        for gate in ("drained", "always_on", "completion"):
            run = record()
            run["spans"] = []
            run["policies"][0]["ended_witness"] = 0
            if gate == "completion":
                run["ledger"] = run["ledger"][:1]
            else:
                run[gate] = False
            for candidate in (run, segmented(run)):
                self.check(candidate, "inconclusive")

    def test_flat_association_is_stable_in_mixed_records(self):
        for ids in (None, [], ["s"]):
            run = record()
            run["policies"][0]["ended_witness"] = 0
            if ids is None:
                run["policies"][0].pop("span_ids")
            else:
                run["policies"][0]["span_ids"] = ids
            original = qualify(run)
            original_direct = direct_assertions(run)
            original_name = existence_and_name(run)
            run["ledger"].extend([{**row, "operation_id": "other"} for row in run["ledger"]])
            run["contexts"]["other"] = "A"
            run["policies"].append({"operation_id": "other", "segments": [
                {"segment_id": "context", "role": "context-only", "expected_context": "A"}]})
            mixed = qualify(run)
            self.assertEqual(mixed["operations"][0], original["operations"][0])
            self.assertEqual(mixed["findings"], original["findings"])
            self.assertEqual(direct_assertions(run), original_direct)
            self.assertEqual(existence_and_name(run), original_name)

    def relation_record(self):
        run = segmented(record())
        run["spans"].append({**deepcopy(run["spans"][0]), "span_id": "root"})
        run["policies"][0]["segments"].append({"segment_id": "parent", "role": "execution",
                                               "span_ids": ["root"]})
        run["policies"][0]["relations"] = [{"from": "primary", "to": "parent", "kind": "parent"}]
        return run

    def test_relation_failure_and_abstention_reach_segment_summary(self):
        for parent, verdict in [("wrong", "fail"), (None, "inconclusive"), ("root", "pass")]:
            run = self.relation_record()
            run["spans"][0]["parent_id"] = parent
            result = self.check(run, verdict)
            self.assertEqual(result["operations"][0]["segments"], [
                {"segment_id": "primary", "verdict": verdict},
                {"segment_id": "parent", "verdict": "pass"}])

    def test_relation_failure_retains_priority_over_clock_abstention(self):
        run = self.relation_record()
        run["spans"][0]["parent_id"] = "wrong"
        run["clock"]["timing_eligible"] = False
        result = self.check(run, "fail")
        self.assertEqual(result["operations"][0]["segments"][0]["verdict"], "fail")

    def test_context_only_relation_endpoints_abstain(self):
        for kind in ("parent", "link", "parent-or-link", "same-trace"):
            for source, target in (("primary", "context"), ("context", "primary"),
                                   ("context", "context")):
                with self.subTest(kind=kind, source=source, target=target):
                    run = segmented(record())
                    run["policies"][0]["segments"].append(
                        {"segment_id": "context", "role": "context-only", "expected_context": "A"})
                    run["contexts"]["op"] = {"context": "A"}
                    self.check(run, "pass")  # Context identity alone needs no new span.
                    run["policies"][0]["relations"] = [
                        {"from": source, "to": target, "kind": kind}]
                    result = self.check(run, "inconclusive", "RELATION_EVIDENCE_MISSING")
                    self.assertEqual(result["findings"], [{
                        "operation_id": "op", "segment_id": source,
                        "code": "RELATION_EVIDENCE_MISSING", "verdict": "inconclusive",
                        "relation_kind": kind, "target_segment": target}])
                    self.assertEqual(result["operations"][0]["segments"], [
                        {"segment_id": sid, "verdict": "inconclusive" if sid == source else "pass"}
                        for sid in ("primary", "context")])
                    self.assertEqual(build_ci_report(run)["ci_exit_code"], 2)

    def test_context_only_relation_preserves_qualified_failure(self):
        for source, target in (("primary", "context"), ("context", "primary")):
            with self.subTest(source=source):
                run = segmented(record())
                run["spans"][0]["end_ns"] = 15
                run["policies"][0]["segments"].append(
                    {"segment_id": "context", "role": "context-only", "expected_context": "A"})
                run["contexts"]["op"] = {"context": "A"}
                run["policies"][0]["relations"] = [
                    {"from": source, "to": target, "kind": "parent"}]
                result = self.check(run, "fail", "RELATION_EVIDENCE_MISSING")
                self.assertIn("ENDS_BEFORE_EXIT", {row["code"] for row in result["findings"]})
                self.assertEqual(result["operations"][0]["segments"][0]["verdict"], "fail")
                self.assertEqual(build_ci_report(run)["ci_exit_code"], 1)

    def test_unresolved_span_relation_marks_source_inconclusive(self):
        for witness, verdict in ((None, "inconclusive"), (0, "fail"), (1, "inconclusive")):
            with self.subTest(witness=witness):
                run = self.relation_record()
                run["spans"] = run["spans"][:1]
                if witness is not None:
                    run["policies"][0]["segments"][1]["ended_witness"] = witness
                result = self.check(run, verdict, "RELATION_EVIDENCE_MISSING")
                self.assertEqual(result["operations"][0]["segments"], [
                    {"segment_id": "primary", "verdict": "inconclusive"},
                    {"segment_id": "parent", "verdict": verdict}])


if __name__ == "__main__":
    unittest.main()
