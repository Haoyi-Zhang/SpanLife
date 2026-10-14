"""SDK-free owned arithmetic controls for the actual benchmark operation.

The same subprocess checks run with and without -O. They do not import any
public tracing source, collect new cost measurements or replace old records.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'benchmark.py'
COUNT_WORK = '''
import builtins, importlib.util, json, sys
spec = importlib.util.spec_from_file_location('owned_benchmark', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
calls = []
def counted_sum(values):
    calls.append(1)
    return builtins.sum(values) if sys.argv[4] == 'good' else -1
module.sum = counted_sum
result = module.sample(sys.argv[2], sys.argv[3], 3, 2)
print(json.dumps({'calls': len(calls), 'sample': result}))
'''


class BenchmarkOperationExecutionTests(unittest.TestCase):
    def run_child(self, optimized, arguments):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(ROOT / 'src'))
        env.pop('PYTHONOPTIMIZE', None)
        command = [sys.executable, '-B'] + (['-O'] if optimized else []) + arguments
        with tempfile.TemporaryDirectory(prefix='spanlife-owned-benchmark-') as cwd:
            return subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                  text=True, encoding='utf-8', timeout=10)

    def test_hook_sample_executes_every_warmup_and_measurement_under_optimization(self):
        for optimized in (False, True):
            for workload in ('direct', 'to_thread'):
                with self.subTest(optimized=optimized, workload=workload):
                    run = self.run_child(optimized, [str(SCRIPT), '--sample', '--mode', 'hook',
                        '--workload', workload, '--n', '3', '--warmup', '2'])
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    result = json.loads(run.stdout)
                    self.assertEqual(result['operations'], 3)
                    self.assertEqual(result['warmup'], 2)
                    self.assertEqual(result['ledger_events'], 10)

    def test_owned_work_is_called_even_without_hooks(self):
        for optimized in (False, True):
            for mode in ('none', 'hook'):
                for workload in ('direct', 'to_thread'):
                    with self.subTest(optimized=optimized, mode=mode, workload=workload):
                        run = self.run_child(optimized, ['-c', COUNT_WORK, str(SCRIPT),
                                                       mode, workload, 'good'])
                        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                        result = json.loads(run.stdout)
                        self.assertEqual(result['calls'], 5)
                        self.assertEqual(result['sample']['ledger_events'], 0 if mode == 'none' else 10)

    def test_wrong_owned_arithmetic_result_cannot_be_reported_as_a_sample(self):
        for optimized in (False, True):
            for workload in ('direct', 'to_thread'):
                with self.subTest(optimized=optimized, workload=workload):
                    run = self.run_child(optimized, ['-c', COUNT_WORK, str(SCRIPT),
                                                   'hook', workload, 'bad'])
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(run.stdout, '')


if __name__ == '__main__':
    unittest.main()
