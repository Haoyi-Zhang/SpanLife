"""The reusable CLI gate preserves semantic failures and historical mismatches."""
from pathlib import Path
import json
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/ci_contract_smoke.py'
MODULE = runpy.run_path(str(SCRIPT))


def test_four_actual_cli_contracts_and_no_sdk_trials():
    result = MODULE['run']()
    assert result['all_exit_contracts_satisfied'] is True
    assert result['new_sdk_or_service_trials'] == 0
    assert [case['exit_code'] for case in result['cases']] == [0, 1, 2, 3]
    assert [case['report']['record_consistent'] for case in result['cases']] == [True, True, True, False]
    assert result['cases'][1]['report']['findings'][0]['owner'] == 'propagation'
    assert result['cases'][3]['report']['verdict'] == 'fail'


@pytest.mark.parametrize('change', ['exit', 'verdict', 'consistency', 'report_exit', 'stderr', 'json'])
def test_adapter_rejects_exit_or_semantic_disagreement(change):
    case = MODULE['CASES'][1]
    report = {'verdict': 'fail', 'record_consistent': True, 'ci_exit_code': 1}
    exit_code, stderr = 1, ''
    if change == 'exit':
        exit_code = 0
    elif change == 'verdict':
        report['verdict'] = 'pass'
    elif change == 'consistency':
        report['record_consistent'] = False
    elif change == 'report_exit':
        report['ci_exit_code'] = 0
    elif change == 'stderr':
        stderr = 'unexpected diagnostic'
    stdout = '{' if change == 'json' else json.dumps(report)
    proc = subprocess.CompletedProcess([], exit_code, stdout, stderr)
    with pytest.raises(ValueError):
        MODULE['admit'](case, proc)


def test_output_is_new_only_and_current_input_is_never_overwritten(tmp_path):
    target = tmp_path / 'report.json'
    command = [sys.executable, '-B', '-S', str(SCRIPT), '--output', str(target)]
    first = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert first.returncode == 0, first.stderr
    before = target.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True, timeout=5)
    assert second.returncode == 2
    assert target.read_bytes() == before
    source = ROOT / MODULE['CASES'][0][0]
    before_source = source.read_bytes()
    rejected = subprocess.run([sys.executable, '-B', '-S', str(SCRIPT), '--output', str(source)],
                              capture_output=True, text=True, timeout=5)
    assert rejected.returncode == 2
    assert source.read_bytes() == before_source
