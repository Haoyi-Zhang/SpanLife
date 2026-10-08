from __future__ import annotations

import pytest

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.contracts import normalize_policy
from spanlife.oracle import qualify
from spanlife.topology_scenarios import EXPECTED, TOPOLOGY_CASES, run_topology_case


def qualified(run: dict) -> dict:
    run["clock"] = {**run["clock"], "epsilon_ns": 100_000, "timing_eligible": True}
    run["ledger_check"] = qualify(run)
    run["direct_check"] = direct_assertions(run)
    run["name_check"] = existence_and_name(run)
    return run


@pytest.mark.parametrize("case", TOPOLOGY_CASES)
def test_executable_topology_case_matches_predeclared_contract(case: str) -> None:
    run = qualified(run_topology_case(case, repeat=0))
    expected_verdict, expected_codes = EXPECTED[case]
    codes = {finding["code"] for finding in run["ledger_check"]["findings"]}
    assert run["ledger_check"]["verdict"] == expected_verdict
    assert set(expected_codes).issubset(codes)
    assert direct_assertions(run)["verdict"] == expected_verdict
    assert qualify(run) == run["ledger_check"]


def test_name_only_baseline_cannot_associate_concurrent_same_name_operations() -> None:
    run = qualified(run_topology_case("correlated_concurrent_valid", repeat=1))
    assert run["ledger_check"]["verdict"] == "pass"
    assert existence_and_name(run)["verdict"] == "fail"


@pytest.mark.parametrize("case", ["split_missing_relation", "split_wrong_relation"])
def test_name_only_baseline_misses_handoff_relation_faults(case: str) -> None:
    run = qualified(run_topology_case(case, repeat=2))
    assert run["ledger_check"]["verdict"] == "fail"
    assert existence_and_name(run)["verdict"] == "pass"


def test_parent_relation_allows_parent_to_end_before_child_execution() -> None:
    run = qualified(run_topology_case("split_parent_valid", repeat=2))
    policy = run["policies"][0]
    submit = next(span for span in run["spans"] if span["attributes"].get("spanlife.segment") == "submit")
    execute = next(span for span in run["spans"] if span["attributes"].get("spanlife.segment") == "execute")
    assert submit["end_ns"] < execute["start_ns"]
    assert execute["parent_id"] == submit["span_id"]
    assert policy["relations"] == [{"from": "execute", "to": "submit", "kind": "parent"}]
    assert run["ledger_check"]["verdict"] == "pass"


def test_link_relation_is_captured_as_primary_evidence() -> None:
    run = qualified(run_topology_case("split_link_valid", repeat=2))
    submit = next(span for span in run["spans"] if span["attributes"].get("spanlife.segment") == "submit")
    execute = next(span for span in run["spans"] if span["attributes"].get("spanlife.segment") == "execute")
    assert submit["span_id"] in {link["span_id"] for link in execute["links"]}
    assert run["ledger_check"]["verdict"] == "pass"


@pytest.mark.parametrize('case', ['split_link_valid', 'split_parent_valid'])
def test_full_handoff_identity_rejects_wrong_trace(case):
    run = qualified(run_topology_case(case, repeat=2))
    submit = next(span for span in run['spans'] if span['attributes'].get('spanlife.segment') == 'submit')
    submit['trace_id'] = 'different-trace'
    assert qualify(run)['verdict'] == 'fail'
    assert direct_assertions(run)['verdict'] == 'fail'


def test_cross_trace_link_with_full_identity_is_valid():
    run = qualified(run_topology_case('split_link_valid', repeat=2))
    submit = next(span for span in run['spans'] if span['attributes'].get('spanlife.segment') == 'submit')
    execute = next(span for span in run['spans'] if span['attributes'].get('spanlife.segment') == 'execute')
    submit['trace_id'] = 'other-trace'
    execute['links'][0]['trace_id'] = 'other-trace'
    assert qualify(run)['verdict'] == 'pass'
    assert direct_assertions(run)['verdict'] == 'pass'


def test_topology_pending_collection_and_colliding_ids():
    run = qualified(run_topology_case('split_parent_valid', repeat=2))
    run['drained'] = False
    assert qualify(run)['verdict'] == 'inconclusive'
    assert direct_assertions(run)['verdict'] == 'inconclusive'
    run['drained'] = True
    submit = next(span for span in run['spans'] if span['attributes'].get('spanlife.segment') == 'submit')
    execute = next(span for span in run['spans'] if span['attributes'].get('spanlife.segment') == 'execute')
    execute['span_id'] = submit['span_id']
    submit['trace_id'] = 'other-trace'
    execute['links'] = [{'trace_id': submit['trace_id'], 'span_id': submit['span_id']}]
    run['policies'][0]['relations'][0]['kind'] = 'link'
    assert qualify(run)['verdict'] == 'pass'
    assert direct_assertions(run)['verdict'] == 'pass'


def test_normalize_legacy_policy_preserves_single_segment_fields() -> None:
    policy = {
        "operation_id": "op-0",
        "role": "execution",
        "span_name": "work",
        "span_ids": ["1"],
        "exclude_queue": True,
    }
    normalized = normalize_policy(policy)
    assert normalized["segments"] == [{
        "segment_id": "primary",
        "role": "execution",
        "span_name": "work",
        "span_ids": ["1"],
        "exclude_queue": True,
    }]


@pytest.mark.parametrize(
    "policy, message",
    [
        ({"operation_id": "op", "segments": []}, "non-empty"),
        ({"operation_id": "op", "segments": [{"segment_id": "x", "role": "bad"}]}, "unsupported segment role"),
        ({"operation_id": "op", "segments": [{"segment_id": "x", "role": "execution"}],
          "relations": [{"from": "x", "to": "missing", "kind": "link"}]}, "endpoints"),
        ({"operation_id": "op", "segments": [{"segment_id": "x", "role": "execution",
                                                  "association": {"kind": "attributes", "match": {}}}]}, "non-empty match"),
    ],
)
def test_contract_shape_errors_are_rejected(policy: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_policy(policy)


def test_parent_or_link_accepts_parent_when_link_field_is_unavailable() -> None:
    run = qualified(run_topology_case("split_parent_valid", repeat=3))
    run["policies"][0]["relations"][0]["kind"] = "parent-or-link"
    for span in run["spans"]:
        span.pop("links", None)
    assert qualify(run)["verdict"] == "pass"
    assert direct_assertions(run)["verdict"] == "pass"


def test_same_trace_requires_trace_identifier_evidence() -> None:
    run = qualified(run_topology_case("split_parent_valid", repeat=4))
    run["policies"][0]["relations"][0]["kind"] = "same-trace"
    for span in run["spans"]:
        span.pop("trace_id", None)
    result = qualify(run)
    assert result["verdict"] == "inconclusive"
    assert {row["code"] for row in result["findings"]} == {"RELATION_EVIDENCE_MISSING"}
    assert direct_assertions(run)["verdict"] == "inconclusive"
