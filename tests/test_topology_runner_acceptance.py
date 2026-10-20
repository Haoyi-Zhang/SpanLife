"""Runner acceptance must enforce declared expectations, not just mutual agreement."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('topology_runner_under_test', ROOT/'scripts/run_topology_challenge.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class TopologyRunnerAcceptanceTests(unittest.TestCase):
    def run_with_edit(self, edit=None, omit=None):
        def process(command, **kwargs):
            case = command[command.index('--single') + 1]
            dest = Path(command[command.index('--output-file') + 1])
            dest.write_text(json.dumps({'case': case, 'repeat': 0,
                                       'execution': {'status': 'missing' if case == omit else 'completed'}}))
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        def row(data, raw):
            case = data['case']
            verdict, codes = runner.EXPECTED[case]
            value = dict(case=case, repeat=0, expected_verdict=verdict,
                         expected_codes=list(codes), actual=verdict, direct=verdict,
                         name=verdict, codes=list(codes), clock_eligible=True,
                         raw=raw, operation_contracts=1, segment_contracts=1)
            if edit:
                edit(value)
            return value

        with tempfile.TemporaryDirectory() as temp, \
             patch.object(runner.subprocess, 'run', side_effect=process), \
             patch.object(runner, 'trial_row', side_effect=row), redirect_stdout(StringIO()):
            return runner.orchestrate(Path(temp), 1, 2)

    def test_complete_expected_matrix_passes(self):
        self.assertEqual(self.run_with_edit(), 0)

    def test_two_implementations_rejecting_valid_case_is_failure(self):
        def edit(row):
            if row['case'] == 'split_link_valid':
                row['actual'] = row['direct'] = 'fail'
        self.assertEqual(self.run_with_edit(edit), 1)

    def test_two_implementations_missing_handoff_is_failure(self):
        def edit(row):
            if row['case'] == 'split_missing_relation':
                row['actual'] = row['direct'] = 'pass'
                row['codes'] = []
        self.assertEqual(self.run_with_edit(edit), 1)

    def test_correct_verdict_without_required_diagnostic_is_failure(self):
        def edit(row):
            if row['case'] == 'split_wrong_relation':
                row['codes'] = []
        self.assertEqual(self.run_with_edit(edit), 1)

    def test_missing_completed_record_is_failure(self):
        self.assertEqual(self.run_with_edit(omit='split_link_valid'), 1)

    def test_empty_campaign_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            runner.orchestrate(Path(temp), 0, 1)
