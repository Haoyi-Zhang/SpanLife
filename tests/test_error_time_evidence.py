"""Error evidence is independent of interval qualification.

Only serialized, synthetic observations are used; no tracing SDK or service.
Each expectation is explicit, rather than derived from checker agreement.
"""
from copy import deepcopy
import unittest

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify
from spanlife.report import build_ci_report


LAYOUTS = ("legacy", "segments-id", "segments-attributes", "segments-name",
           "amended-flat", "mixed")
TIME_CASES = tuple((boundary, field, state)
                   for boundary in ("enter", "exit")
                   for field in ("wall_ns", "monotonic_ns")
                   for state in ("null", "omitted")) + (
    ("exit", "wall_ns", "reversed"), ("exit", "monotonic_ns", "reversed"),
    ("all", "both", "null"), ("all", "both", "omitted"),
)
ERROR_FAILURES = {"MISSING_ERROR_STATUS", "MISSING_EXCEPTION_EVENT"}
INTERVAL_FAILURES = {"STARTS_AFTER_ENTRY", "ENDS_BEFORE_EXIT"}
OBSERVATIONS = []


def record(layout="legacy"):
    policy = {"operation_id": "op", "role": "execution", "span_name": "work",
              "span_ids": ["s"], "error_on_escape": True,
              "exception_event": True, "non_error_types": ["CancelledError"],
              "ended_witness": 1}
    run = {
        "ledger": [
            {"operation_id": "op", "kind": "enter", "wall_ns": 10, "monotonic_ns": 10},
            {"operation_id": "op", "kind": "exit", "wall_ns": 20, "monotonic_ns": 20,
             "outcome": "raised", "exception_type": "ValueError"},
        ],
        "spans": [{"span_id": "s", "name": "work", "start_ns": 9, "end_ns": 21,
                   "status": "UNSET", "events": [], "trace_id": "t",
                   "parent_id": "root", "links": [], "attributes": {"operation": "op"}}],
        "policies": [policy], "contexts": {}, "drained": True, "always_on": True,
        "clock": {"epsilon_ns": 0, "timing_eligible": True},
    }
    if layout.startswith("segments"):
        segment = {k: deepcopy(v) for k, v in policy.items() if k != "operation_id"}
        segment["segment_id"] = "execute"
        if layout != "segments-id":
            segment.pop("span_ids")
        if layout == "segments-attributes":
            segment["association"] = {"kind": "attributes", "match": {"operation": "op"}}
        run["policies"] = [{"operation_id": "op", "segments": [segment]}]
    elif layout == "amended-flat":
        policy["exclude_submission"] = False  # Normalized, not the legacy path.
    elif layout == "mixed":
        run["ledger"].extend({**row, "operation_id": "context-op"}
                             for row in deepcopy(run["ledger"]))
        run["contexts"]["context-op"] = "A"
        run["policies"].append({"operation_id": "context-op", "segments": [
            {"segment_id": "context", "role": "context-only", "expected_context": "A"}]})
    return run


def segment(run):
    policy = run["policies"][0]
    return policy["segments"][0] if "segments" in policy else policy


def partial_time(run, case):
    boundary, field, state = case
    rows = [row for row in run["ledger"] if row["operation_id"] == "op"
            and (boundary == "all" or row["kind"] == boundary)]
    fields = ("wall_ns", "monotonic_ns") if field == "both" else (field,)
    for row in rows:
        for key in fields:
            if state == "omitted":
                row.pop(key)
            else:
                row[key] = None if state == "null" else 0


def known_violation(run, kind):
    span = run["spans"][0]
    if kind == "status-only":
        span["events"] = ["exception"]
    elif kind == "event-only":
        span["status"] = "ERROR"
    # Make the interval wrong if it were evaluated, without reversing the span.
    span.update(start_ns=12, end_ns=13)
    return ({"MISSING_ERROR_STATUS"} if kind == "status-only" else
            {"MISSING_EXCEPTION_EVENT"} if kind == "event-only" else ERROR_FAILURES)


class ErrorTimeEvidenceRegressions(unittest.TestCase):
    def check(self, run, expected, required=(), absent=()):
        before = deepcopy(run)
        result = qualify(run)
        direct = direct_assertions(run)
        report = build_ci_report(run)
        codes = {row["code"] for row in result["findings"]}
        OBSERVATIONS.append({"test": self.id(), "expected": expected,
                             "required_codes": sorted(required), "absent_codes": sorted(absent),
                             "oracle": result, "direct": direct,
                             "report_verdict": report["verdict"]})
        self.assertEqual(result["verdict"], expected)
        self.assertEqual(direct["verdict"], expected)
        self.assertEqual(report["verdict"], expected)
        self.assertTrue(set(required) <= codes, (required, codes))
        self.assertFalse(set(absent) & codes, (absent, codes))
        self.assertEqual(run, before, "evaluation must not change supplied evidence")
        self.assertEqual(result["operations"][0]["verdict"], expected)
        if "segments" in result["operations"][0]:
            self.assertEqual(result["operations"][0]["segments"][0]["verdict"], expected)
        if len(run["policies"]) > 1:
            self.assertEqual(result["operations"][1]["verdict"], "pass")
        return result, direct

    def test_partial_operation_times_keep_independent_known_violations(self):
        for layout in LAYOUTS:
            for case in TIME_CASES:
                for kind in ("both", "status-only", "event-only"):
                    with self.subTest(layout=layout, time=case, violation=kind):
                        run = record(layout)
                        partial_time(run, case)
                        errors = known_violation(run, kind)
                        _, direct = self.check(run, "fail", {"INVALID_LEDGER"} | errors,
                                               INTERVAL_FAILURES | (ERROR_FAILURES - errors))
                        self.assertTrue(direct["inconclusive"])
                        self.assertTrue(direct["failures"])
                        self.assertEqual(existence_and_name(run)["verdict"], "pass")

    def test_nonviolating_error_evidence_cannot_pass_partial_time(self):
        for layout in LAYOUTS:
            for case in TIME_CASES:
                with self.subTest(layout=layout, time=case):
                    run = record(layout)
                    partial_time(run, case)
                    run["spans"][0].update(status="ERROR", events=["exception"],
                                           start_ns=12, end_ns=13)
                    self.check(run, "inconclusive", {"INVALID_LEDGER"},
                               ERROR_FAILURES | INTERVAL_FAILURES)

    def test_unknown_outcome_or_exception_type_never_invents_error_scope(self):
        for layout in LAYOUTS:
            for case in TIME_CASES:
                for field, code in (("outcome", "EXIT_OUTCOME_UNQUALIFIED"),
                                    ("exception_type", "EXCEPTION_TYPE_UNQUALIFIED")):
                    for state in (None, "unknown", "omitted"):
                        with self.subTest(layout=layout, time=case, field=field, state=state):
                            run = record(layout)
                            partial_time(run, case)
                            exit_row = run["ledger"][1]
                            if state == "omitted":
                                exit_row.pop(field)
                            else:
                                exit_row[field] = state
                            self.check(run, "inconclusive", {"INVALID_LEDGER", code}, ERROR_FAILURES)

    def test_unknown_status_and_event_capture_are_not_observed_violations(self):
        captures = ((None, None, (), {"ERROR_STATUS_UNQUALIFIED", "EXCEPTION_EVENT_UNQUALIFIED"}),
                    ("unknown", None, (), {"ERROR_STATUS_UNQUALIFIED", "EXCEPTION_EVENT_UNQUALIFIED"}),
                    ("omitted", "omitted", (), {"ERROR_STATUS_UNQUALIFIED", "EXCEPTION_EVENT_UNQUALIFIED"}),
                    (None, [], {"MISSING_EXCEPTION_EVENT"}, {"ERROR_STATUS_UNQUALIFIED"}),
                    ("UNSET", None, {"MISSING_ERROR_STATUS"}, {"EXCEPTION_EVENT_UNQUALIFIED"}))
        for layout in LAYOUTS:
            for case in TIME_CASES:
                for status, events, failures, unknowns in captures:
                    with self.subTest(layout=layout, time=case, status=status, events=events):
                        run = record(layout)
                        partial_time(run, case)
                        for field, value in (("status", status), ("events", events)):
                            if value == "omitted":
                                run["spans"][0].pop(field)
                            else:
                                run["spans"][0][field] = value
                        self.check(run, "fail" if failures else "inconclusive",
                                   {"INVALID_LEDGER"} | set(failures) | unknowns,
                                   ERROR_FAILURES - set(failures))

    def test_collection_and_unique_boundary_requirements_still_gate_errors(self):
        blockers = ("missing-enter", "missing-exit", "duplicate-enter", "duplicate-exit",
                    "drained-false", "always_on-false", "drained-omitted", "always_on-omitted")
        for layout in LAYOUTS:
            for case in TIME_CASES:
                for blocker in blockers:
                    with self.subTest(layout=layout, time=case, blocker=blocker):
                        run = record(layout)
                        partial_time(run, case)
                        if blocker.startswith(("missing-", "duplicate-")):
                            action, kind = blocker.split("-")
                            row = next(row for row in run["ledger"]
                                       if row["operation_id"] == "op" and row["kind"] == kind)
                            if action == "missing":
                                run["ledger"].remove(row)
                            else:
                                run["ledger"].append(deepcopy(row))
                            required = {"INCOMPLETE_OPERATION"}
                        else:
                            field, state = blocker.split("-")
                            if state == "omitted":
                                run.pop(field)
                            else:
                                run[field] = False
                            required = {"COLLECTION_NOT_QUALIFIED", "INVALID_LEDGER"}
                        self.check(run, "inconclusive", required, ERROR_FAILURES)

    def test_ambiguity_and_unassociated_bad_telemetry_do_not_supply_error_evidence(self):
        for layout in LAYOUTS:
            for mode in ("duplicate-row", "two-matches", "missing-association"):
                with self.subTest(layout=layout, mode=mode):
                    run = record(layout)
                    partial_time(run, TIME_CASES[0])
                    p = segment(run)
                    if mode == "missing-association":
                        # Keep bad telemetry, but no matching candidate. A positive
                        # end witness preserves the existing export-loss abstention.
                        if "span_ids" in p:
                            p["span_ids"] = ["not-collected"]
                        elif "association" in p:
                            p["association"]["match"]["operation"] = "different"
                        else:
                            p["span_name"] = "different"
                        code = "EXPORT_LOSS"
                    else:
                        clone = deepcopy(run["spans"][0])
                        if mode == "two-matches":
                            clone["span_id"] = "second"
                            if "span_ids" in p:
                                p["span_ids"].append("second")
                        run["spans"].append(clone)
                        code = "AMBIGUOUS_ASSOCIATION"
                    self.check(run, "inconclusive", {code, "INVALID_LEDGER"}, ERROR_FAILURES)
        for layout in LAYOUTS:
            with self.subTest(layout=layout, mode="unrelated-bad-span"):
                run = record(layout)
                partial_time(run, TIME_CASES[0])
                unrelated = deepcopy(run["spans"][0])
                unrelated.update(span_id="unrelated", name="other", attributes={"operation": "other"})
                run["spans"][0].update(status="ERROR", events=["exception"])
                run["spans"].append(unrelated)
                self.check(run, "inconclusive", {"INVALID_LEDGER"}, ERROR_FAILURES)

    def test_span_time_and_clock_abstention_are_independent_of_errors(self):
        for layout in LAYOUTS:
            for mode, code in (("start-null", "SPAN_TIME_UNQUALIFIED"),
                               ("end-omitted", "SPAN_TIME_UNQUALIFIED"),
                               ("reversed-span", "INVALID_SPAN_INTERVAL"),
                               ("clock-off", "CLOCK_UNQUALIFIED"),
                               ("clock-over-cap", "CLOCK_UNQUALIFIED")):
                for violation in (False, True):
                    with self.subTest(layout=layout, mode=mode, violation=violation):
                        run = record(layout)
                        if not violation:
                            run["spans"][0].update(status="ERROR", events=["exception"])
                        if mode == "start-null":
                            run["spans"][0]["start_ns"] = None
                        elif mode == "end-omitted":
                            run["spans"][0].pop("end_ns")
                        elif mode == "reversed-span":
                            run["spans"][0].update(start_ns=21, end_ns=9)
                        elif mode == "clock-off":
                            run["clock"]["timing_eligible"] = False
                        else:
                            run["clock"]["epsilon_ns"] = 100_001
                        self.check(run, "fail" if violation else "inconclusive",
                                   {code} | (ERROR_FAILURES if violation else set()), INTERVAL_FAILURES)

    def test_absent_candidate_end_witness_rules_survive_partial_time(self):
        for layout in LAYOUTS:
            for witness, expected, code in ((None, "inconclusive", "END_WITNESS_UNQUALIFIED"),
                                            ("omitted", "inconclusive", "END_WITNESS_UNQUALIFIED"),
                                            (-1, "inconclusive", "END_WITNESS_UNQUALIFIED"),
                                            (0, "fail", "MISSING_SPAN"),
                                            (1, "inconclusive", "EXPORT_LOSS")):
                with self.subTest(layout=layout, witness=witness):
                    run = record(layout)
                    partial_time(run, TIME_CASES[0])
                    run["spans"] = []
                    if witness == "omitted":
                        segment(run).pop("ended_witness")
                    else:
                        segment(run)["ended_witness"] = witness
                    self.check(run, expected, {"INVALID_LEDGER", code}, ERROR_FAILURES)
        for layout in ("legacy", "segments-id", "amended-flat", "mixed"):
            with self.subTest(layout=layout, ambiguous="one-of-two-declared-ids"):
                run = record(layout)
                partial_time(run, TIME_CASES[0])
                segment(run)["span_ids"].append("not-collected")
                self.check(run, "inconclusive", {"INVALID_LEDGER", "AMBIGUOUS_ASSOCIATION"}, ERROR_FAILURES)

    def test_other_non_timing_violations_keep_priority_with_unknown_error_scope(self):
        for layout in LAYOUTS:
            for field, code in (("parent", "PARENT_MISMATCH"), ("context", "CONTEXT_MISMATCH")):
                with self.subTest(layout=layout, field=field):
                    run = record(layout)
                    partial_time(run, TIME_CASES[0])
                    run["ledger"][1]["outcome"] = None
                    p = segment(run)
                    if field == "parent":
                        p["expected_parent"] = "expected"
                    else:
                        p["expected_context"] = "expected"
                        run["contexts"]["op"] = "observed"
                    self.check(run, "fail", {"INVALID_LEDGER", "EXIT_OUTCOME_UNQUALIFIED", code}, ERROR_FAILURES)

    def test_role_return_exclusion_and_disabled_obligations_are_unchanged(self):
        for layout in LAYOUTS:
            for mode in ("returned", "excluded", "error-disabled", "event-disabled",
                         "unknown-role", "submission-role", "both-role"):
                with self.subTest(layout=layout, mode=mode):
                    run = record(layout)
                    partial_time(run, TIME_CASES[0])
                    p = segment(run)
                    if mode == "returned":
                        run["ledger"][1].update(outcome="returned", exception_type=None)
                    elif mode == "excluded":
                        run["ledger"][1]["exception_type"] = "CancelledError"
                    elif mode == "error-disabled":
                        p["error_on_escape"] = False
                    elif mode == "event-disabled":
                        p["exception_event"] = False
                        run["spans"][0]["status"] = "ERROR"
                    elif mode == "unknown-role":
                        p["role"] = "unknown"
                    elif mode == "submission-role":
                        p["role"] = "submission"
                    else:
                        p["role"] = "both"
                    self.check(run, "fail" if mode == "both-role" else "inconclusive",
                               ERROR_FAILURES if mode == "both-role" else (),
                               () if mode == "both-role" else ERROR_FAILURES)

    def test_complete_time_controls_and_name_presence_semantics(self):
        for layout in LAYOUTS:
            for kind in ("both", "status-only", "event-only", "good"):
                with self.subTest(layout=layout, kind=kind):
                    run = record(layout)
                    if kind == "good":
                        run["spans"][0].update(status="ERROR", events=["exception"])
                        failures = set()
                    else:
                        failures = known_violation(run, kind)
                        run["spans"][0].update(start_ns=9, end_ns=21)
                    self.check(run, "fail" if failures else "pass", failures,
                               ERROR_FAILURES - failures)
                    self.assertEqual(existence_and_name(run)["verdict"], "pass")

    def test_malformed_timestamps_and_evidence_remain_rejected(self):
        entrypoints = (qualify, direct_assertions, existence_and_name, build_ci_report)
        for layout in LAYOUTS:
            for container, key in (("enter", "wall_ns"), ("exit", "monotonic_ns"),
                                   ("span", "start_ns"), ("span", "end_ns"),
                                   ("clock", "epsilon_ns"), ("clock", "cap_ns")):
                for bad in (float("nan"), float("inf"), -float("inf"), 1.5, True, "10", []):
                    with self.subTest(layout=layout, container=container, key=key, bad=bad):
                        run = record(layout)
                        target = (run["ledger"][0] if container == "enter" else
                                  run["ledger"][1] if container == "exit" else
                                  run["spans"][0] if container == "span" else run["clock"])
                        target[key] = bad
                        for entrypoint in entrypoints:
                            with self.assertRaises(ValueError):
                                entrypoint(run)
        for layout in LAYOUTS:
            for field, bad in (("status", []), ("events", "exception")):
                run = record(layout)
                run["spans"][0][field] = bad
                for entrypoint in entrypoints:
                    with self.assertRaises(ValueError):
                        entrypoint(run)


if __name__ == "__main__":
    unittest.main()
