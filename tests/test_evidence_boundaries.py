from copy import deepcopy
import json
import pytest
from test_oracle import example
from test_report import qualified, cli_env
from spanlife.oracle import qualify
from spanlife.baselines import direct_assertions
from spanlife.report import build_ci_report, format_text
import subprocess
import sys


@pytest.mark.parametrize('topology', [False, True])
def test_reversed_submission_is_inconclusive(topology):
    run = example('submission')
    run['spans'][0].update(start_ns=0, end_ns=3)
    run['ledger'][1]['monotonic_ns'] = 0
    if topology:
        original = run['policies'][0]
        run['policies'] = [{'operation_id': 'x', 'segments': [{**original, 'segment_id': 'submit'}]}]
    assert qualify(run)['verdict'] == direct_assertions(run)['verdict'] == 'inconclusive'


@pytest.mark.parametrize('topology', [False, True])
def test_invalid_execution_keeps_independent_parent_violation(topology):
    run = example()
    run['ledger'][-1]['monotonic_ns'] = 0
    run['spans'][0].update(start_ns=12, end_ns=13)
    if topology:
        original = run['policies'][0]
        run['policies'] = [{'operation_id': 'x', 'segments': [{**original, 'segment_id': 'execute'}]}]
    assert qualify(run)['verdict'] == direct_assertions(run)['verdict'] == 'inconclusive'
    run['spans'][0]['parent_id'] = 'wrong'
    assert qualify(run)['verdict'] == direct_assertions(run)['verdict'] == 'fail'


@pytest.mark.parametrize('parent', [None, '0'])
def test_parent_absence_differs_from_observed_root(parent):
    run = qualified('split_parent_valid')
    execute = next(s for s in run['spans'] if s['attributes'].get('spanlife.segment') == 'execute')
    execute['parent_id'] = parent
    expected = 'inconclusive' if parent is None else 'fail'
    assert qualify(run)['verdict'] == direct_assertions(run)['verdict'] == expected


@pytest.mark.parametrize('declared', [0, 1, 2])
@pytest.mark.parametrize('collected', [0, 1, 2])
def test_explicit_association_cardinality_agrees(declared, collected):
    run = example()
    spans = [{**run['spans'][0], 'span_id': str(i)} for i in range(collected)]
    segment = {**run['policies'][0], 'segment_id': 'execute', 'span_ids': [str(i) for i in range(declared)]}
    run['policies'] = [{'operation_id': 'x', 'segments': [segment]}]
    run['spans'] = spans
    assert qualify(run)['verdict'] == direct_assertions(run)['verdict']


def test_stored_mismatch_is_visible_and_fails_cli(tmp_path):
    run = qualified('split_link_valid')
    run['ledger_check'] = {'verdict': 'fail'}
    report = build_ci_report(run)
    assert not report['record_consistent'] and report['ci_exit_code'] == 3
    assert 'RECORD_MISMATCH' in format_text(report)
    path = tmp_path/'run.json'; path.write_text(json.dumps(run))
    result = subprocess.run([sys.executable, '-m', 'spanlife.check_record', str(path)],
                            env=cli_env(), capture_output=True, text=True)
    assert result.returncode == 3
