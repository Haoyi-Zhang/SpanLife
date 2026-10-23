"""Exercise the four CLI exit contracts without an SDK or service execution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ('results/ci-examples/current-raw/pass.json', 0, 'pass', True),
    ('results/ci-examples/current-raw/fail.json', 1, 'fail', True),
    ('results/ci-examples/current-raw/inconclusive.json', 2, 'inconclusive', True),
    ('results/topology-challenge/split_missing_relation__000.json', 3, 'fail', False),
)
SOURCES = ('scripts/ci_contract_smoke.py', 'src/spanlife/check_record.py',
           'src/spanlife/report.py', 'src/spanlife/oracle.py',
           'src/spanlife/contracts.py', 'src/spanlife/topology_records.py',
           'src/spanlife/__init__.py')


def admit(case, completed):
    """Expected failures test the adapter contract; they do not pass a service."""
    relative, expected_exit, expected_verdict, consistent = case
    if completed.returncode != expected_exit:
        raise ValueError(f'{relative}: expected exit {expected_exit}, got {completed.returncode}')
    report = json.loads(completed.stdout)
    if (report.get('verdict') != expected_verdict or
            report.get('record_consistent') is not consistent or
            report.get('ci_exit_code') != expected_exit):
        raise ValueError(f'{relative}: exit and semantic report disagree')
    if completed.stderr.strip():
        raise ValueError(f'{relative}: unexpected diagnostic on stderr')
    return {'record': relative, 'exit_code': completed.returncode, 'report': report}


def bindings():
    paths = sorted(set(SOURCES) | {case[0] for case in CASES})
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def run():
    before = bindings()
    start = datetime.now(timezone.utc).isoformat()
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'}
    results = []
    for case in CASES:
        proc = subprocess.run(
            [sys.executable, '-B', '-S', '-m', 'spanlife.check_record',
             case[0], '--format', 'json', '--fail-on-inconclusive'],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding='utf-8', timeout=15, check=False)
        results.append(admit(case, proc))
    if bindings() != before:
        raise ValueError('CLI inputs or checker sources changed during execution')
    return {'kind': 'SDK-free CLI integration contract',
            'started_utc': start, 'finished_utc': datetime.now(timezone.utc).isoformat(),
            'python': sys.version, 'new_sdk_or_service_trials': 0,
            'source_and_input_bindings': before, 'cases': results,
            'all_exit_contracts_satisfied': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='write a new file; never overwrite')
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error('output already exists')
    try:
        result = run()
        text = json.dumps(result, indent=2) + '\n'
        if args.output is not None:
            with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
        else:
            print(text, end='')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
