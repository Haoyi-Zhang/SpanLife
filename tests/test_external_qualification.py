"""Benign external-record admission and evidence qualification regressions."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify
from spanlife.report import build_ci_report
from test_p119_contract_repair import example, segmented


ENTRYPOINTS = (qualify, direct_assertions, existence_and_name, build_ci_report)


def candidate(topology):
    return segmented(example()) if topology else example()


def agree(run, verdict, code=None):
    before = deepcopy(run)
    result = qualify(run)
    assert result["verdict"] == direct_assertions(run)["verdict"] == verdict
    assert build_ci_report(run)["verdict"] == verdict
    if code:
        assert code in {row["code"] for row in result["findings"]}
    assert run == before
    return result


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("outcome", [None, "unknown", "omitted"])
def test_unknown_exit_outcome_cannot_satisfy_error_policy(topology, outcome):
    run = candidate(topology)
    run["ledger"][-1]["outcome"] = outcome
    run["ledger"][-1]["exception_type"] = "ValueError"
    if outcome == "omitted":
        run["ledger"][-1].pop("outcome")
    agree(run, "inconclusive", "EXIT_OUTCOME_UNQUALIFIED")
    assert existence_and_name(run)["verdict"] == "pass"
    run["spans"][0]["parent_id"] = "wrong"
    agree(run, "fail", "PARENT_MISMATCH")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("exception", [None, "unknown", "omitted"])
def test_raised_exit_needs_known_exception_scope(topology, exception):
    run = candidate(topology)
    run["ledger"][-1].update(outcome="raised", exception_type=exception)
    if exception == "omitted":
        run["ledger"][-1].pop("exception_type")
    agree(run, "inconclusive", "EXCEPTION_TYPE_UNQUALIFIED")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("field,unknown,code", [
    ("status", None, "ERROR_STATUS_UNQUALIFIED"),
    ("status", "unknown", "ERROR_STATUS_UNQUALIFIED"),
    ("events", None, "EXCEPTION_EVENT_UNQUALIFIED"),
])
def test_unknown_error_capture_is_not_an_observed_absence(topology, field, unknown, code):
    run = candidate(topology)
    run["ledger"][-1].update(outcome="raised", exception_type="ValueError")
    run["spans"][0].update(status="ERROR", events=["exception"])
    run["spans"][0][field] = unknown
    agree(run, "inconclusive", code)
    run["spans"][0].pop(field)
    agree(run, "inconclusive", code)
    # A separate known violation keeps fail priority over unresolved capture.
    run["spans"][0]["end_ns"] = 12
    agree(run, "fail", "ENDS_BEFORE_EXIT")


@pytest.mark.parametrize("topology", [False, True])
def test_known_errors_and_exclusions_retain_semantics(topology):
    run = candidate(topology)
    run["ledger"][-1].update(outcome="raised", exception_type="ValueError")
    agree(run, "fail", "MISSING_ERROR_STATUS")
    run["spans"][0]["status"] = "ERROR"
    agree(run, "fail", "MISSING_EXCEPTION_EVENT")
    run["spans"][0]["events"] = ["exception"]
    agree(run, "pass")
    policy = run["policies"][0]["segments"][0] if topology else run["policies"][0]
    policy["non_error_types"] = ["ValueError"]
    run["spans"][0].update(status=None, events=None)
    agree(run, "pass")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("location,field", [
    ("ledger", "wall_ns"), ("ledger", "monotonic_ns"),
    ("spans", "start_ns"), ("spans", "end_ns"),
    ("clock", "epsilon_ns"), ("clock", "cap_ns"),
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.5, True, "10", []])
def test_malformed_time_is_rejected(topology, location, field, value):
    run = candidate(topology)
    target = run[location][0] if location != "clock" else run["clock"]
    target[field] = value
    for entrypoint in ENTRYPOINTS:
        with pytest.raises(ValueError):
            entrypoint(run)


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("field", ["wall_ns", "monotonic_ns"])
def test_unknown_or_reversed_operation_time_abstains(topology, field):
    run = candidate(topology)
    run["ledger"][-1][field] = None
    agree(run, "inconclusive", "INVALID_LEDGER")
    run["ledger"][-1].pop(field)
    agree(run, "inconclusive", "INVALID_LEDGER")
    run["ledger"][-1][field] = 0
    agree(run, "inconclusive", "INVALID_LEDGER")
    run["spans"][0]["parent_id"] = "wrong"
    agree(run, "fail", "PARENT_MISMATCH")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("field", ["start_ns", "end_ns"])
def test_unknown_span_time_abstains(topology, field):
    run = candidate(topology)
    run["spans"][0][field] = None
    agree(run, "inconclusive", "SPAN_TIME_UNQUALIFIED")
    run["spans"][0].pop(field)
    agree(run, "inconclusive", "SPAN_TIME_UNQUALIFIED")
    run["spans"][0]["parent_id"] = "wrong"
    agree(run, "fail", "PARENT_MISMATCH")


@pytest.mark.parametrize("topology", [False, True])
def test_reversed_span_and_inconsistent_clock_eligibility_abstain(topology):
    run = candidate(topology)
    run["spans"][0].update(start_ns=21, end_ns=9)
    run["clock"]["epsilon_ns"] = 100
    agree(run, "inconclusive", "INVALID_SPAN_INTERVAL")
    run = candidate(topology)
    run["clock"].update(epsilon_ns=100_001, cap_ns=100_000, timing_eligible=True)
    agree(run, "inconclusive", "CLOCK_UNQUALIFIED")
    run["clock"].pop("cap_ns")  # Legacy records retain the protocol's 100 us cap.
    agree(run, "inconclusive", "CLOCK_UNQUALIFIED")
    run["ledger"][-1].update(outcome="raised", exception_type="ValueError")
    agree(run, "fail", "MISSING_ERROR_STATUS")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("field", ["wall_ns", "monotonic_ns"])
def test_submission_and_queue_boundaries_must_be_complete_and_ordered(topology, field):
    run = example("submission")
    run["spans"][0].update(start_ns=0, end_ns=3)
    run["ledger"][1][field] = None
    if topology:
        run = segmented(run)
    agree(run, "inconclusive", "INVALID_SUBMISSION_BOUNDARY")
    run = candidate(topology)
    policy = run["policies"][0]["segments"][0] if topology else run["policies"][0]
    policy["exclude_queue"] = True
    run["ledger"][2][field] = 30
    agree(run, "inconclusive", "INVALID_QUEUE_BOUNDARY")


@pytest.mark.parametrize("topology", [False, True])
@pytest.mark.parametrize("edit", [
    lambda r: r["ledger"][0].pop("operation_id"),
    lambda r: r["ledger"][0].update(operation_id=[]),
    lambda r: r["ledger"][0].update(kind=[]),
    lambda r: r["ledger"][-1].update(outcome=[]),
    lambda r: r["ledger"][-1].update(exception_type=[]),
    lambda r: r["ledger"][-1].update(outcome="returned", exception_type="ValueError"),
    lambda r: r["spans"][0].pop("span_id"),
    lambda r: r["spans"][0].update(span_id=[]),
    lambda r: r["spans"][0].update(status=[]),
    lambda r: r["spans"][0].update(events="exception"),
    lambda r: r["spans"][0].update(attributes=[]),
    lambda r: r["spans"][0].update(links=[[]]),
    lambda r: r["contexts"].update(x=[]),
    lambda r: r["policies"].append(deepcopy(r["policies"][0])),
])
def test_malformed_evidence_has_normal_public_rejection(topology, edit):
    run = candidate(topology)
    edit(run)
    for entrypoint in ENTRYPOINTS:
        with pytest.raises(ValueError):
            entrypoint(run)


@pytest.mark.parametrize("edit", [
    lambda p: p.update(error_on_escape="false"),
    lambda p: p.update(non_error_types="ValueError"),
    lambda p: p.update(span_ids=[[]]),
    lambda p: p.update(span_name=[]),
    lambda p: p.update(association={"kind": []}),
    lambda p: p.update(association={"kind": "attributes", "match": {"operation": None}}),
    lambda p: p.update(association={"kind": "attributes", "match": {"operation": float("nan")}}),
    lambda p: p.update(segments=[{"segment_id": [], "role": "execution"}]),
    lambda p: p.update(segments=[{"segment_id": "s", "role": "execution"}],
                       relations=[{"kind": [], "from": "s", "to": "s"}]),
    lambda p: p.update(segments=[{"segment_id": "s", "role": "execution"}],
                       relations=[{"kind": "link", "from": [], "to": "s"}]),
])
def test_malformed_contract_has_normal_public_rejection(edit):
    run = example()
    edit(run["policies"][0])
    for entrypoint in ENTRYPOINTS:
        with pytest.raises(ValueError):
            entrypoint(run)


@pytest.mark.parametrize("topology", [False, True])
def test_null_expected_parent_is_unknown_not_a_mismatch(topology):
    run = candidate(topology)
    policy = run["policies"][0]["segments"][0] if topology else run["policies"][0]
    policy["expected_parent"] = None
    agree(run, "inconclusive", "MISSING_PARENT_EXPECTATION")


@pytest.mark.parametrize("topology", [False, True])
def test_null_context_expectation_is_unknown_for_execution_too(topology):
    run = candidate(topology)
    policy = run["policies"][0]["segments"][0] if topology else run["policies"][0]
    policy["expected_context"] = None
    run["contexts"]["x"] = "observed"
    agree(run, "inconclusive", "MISSING_CONTEXT_EXPECTATION")


def test_incomplete_link_identity_is_not_proof_of_missing_handoff():
    run = segmented(example())
    run["spans"][0].update(trace_id="t", links=[{"span_id": None, "trace_id": "t"}])
    run["spans"].append({**deepcopy(run["spans"][0]), "span_id": "root", "links": []})
    run["policies"][0]["segments"].append(
        {"segment_id": "parent", "role": "execution", "span_ids": ["root"]})
    run["policies"][0]["relations"] = [{"from": "primary", "to": "parent", "kind": "link"}]
    agree(run, "inconclusive", "RELATION_EVIDENCE_MISSING")
    run["spans"][0]["links"] = []
    agree(run, "fail", "MISSING_HANDOFF_RELATION")


@pytest.mark.parametrize("record_kind", ["missing-id", "bad-association", "nan", "unknown-outcome"])
@pytest.mark.parametrize("gated", [False, True])
def test_external_cli_rejection_vs_abstention(tmp_path, record_kind, gated):
    run = example()
    if record_kind == "missing-id":
        run["ledger"][0].pop("operation_id")
    elif record_kind == "bad-association":
        run["policies"][0]["association"] = {"kind": []}
    elif record_kind == "nan":
        run["spans"][0]["start_ns"] = float("nan")
    else:
        run["ledger"][-1]["outcome"] = None
    record = tmp_path / "record.json"
    record.write_text(json.dumps(run), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "spanlife.check_record", str(record),
         "--format", "json", *(["--fail-on-inconclusive"] if gated else [])],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert "Traceback" not in proc.stderr
    if record_kind == "unknown-outcome":
        assert proc.returncode == (2 if gated else 0)
        assert json.loads(proc.stdout)["verdict"] == "inconclusive"
    else:
        assert proc.returncode == 2 and not proc.stdout
        assert "INVALID_RECORD" in proc.stderr
