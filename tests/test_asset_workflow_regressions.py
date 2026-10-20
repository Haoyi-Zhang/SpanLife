"""Bounded offline validation and publication regressions; no SDK or archive runs."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import asset_publication
import build_paper_assets as builder
import paper_topology
import run_native_mutation_matrix as native
import run_topology_challenge as runner
import verify
import workflow_assets


def long_path(path):
    path = Path(path).resolve()
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        return Path('\\\\?\\' + str(path))
    return path


class Scratch(unittest.TestCase):
    def scratch(self):
        parent = long_path(ROOT / '.repair-test-tmp')
        parent.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def native_fixture(self):
        root = self.scratch()
        target = root / 'results/native-mutation-matrix'
        target.mkdir(parents=True)
        for path in (ROOT / 'results/native-mutation-matrix').glob('*.json'):
            shutil.copy2(path, target / path.name)
        (root / 'tests/native').mkdir(parents=True)
        for suite in native.SUITES:
            shutil.copy2(ROOT / f'tests/native/test_to_thread_{suite}.py',
                         root / f'tests/native/test_to_thread_{suite}.py')
        return root, target

    def topology_fixture(self):
        target = self.scratch()
        for name in ('summary.json', 'trials.json'):
            shutil.copy2(ROOT / 'results/topology-challenge' / name, target / name)
        return target

    def paper_fixture(self):
        root = self.scratch()
        paper = root / 'paper'
        (paper / 'figures').mkdir(parents=True)
        (paper / 'generated').mkdir()
        for name in builder.FIGURES:
            (paper / 'figures' / (name + '.pdf')).write_bytes(b'%PDF-1.4\nowned retained ' + name.encode())
            (paper / 'figures' / (name + '.tex')).write_text('owned retained wrapper\n')
        (paper / 'generated/matrix-table.tex').write_text('owned retained table\n')
        (paper / 'unrelated.txt').write_text('keep me\n')
        return root, paper

    def snapshot(self, directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob('*') if path.is_file()}


class NativeRawTests(Scratch):
    def test_current_raw_records_reproduce_the_producer_summary(self):
        with patch.object(verify, 'ROOT', ROOT):
            result = verify.check_native_mutation_matrix()
        self.assertEqual(result['fresh_process_methods'], 90)
        self.assertEqual(result['legacy_detected_operators'], 2)
        self.assertEqual(result['updated_detected_operators'], 7)

    def test_invalid_missing_extra_and_misidentified_raw_records_are_rejected(self):
        for mode in ('json', 'missing', 'extra', 'identity', 'outcome', 'infrastructure', 'typed_count'):
            with self.subTest(mode=mode):
                root, target = self.native_fixture()
                path = target / 'legacy__early_end__test_to_thread.json'
                row = json.loads(path.read_text())
                if mode == 'json':
                    path.write_text('owned invalid JSON')
                elif mode == 'missing':
                    path.unlink()
                elif mode == 'extra':
                    (target / 'extra.json').write_text('{}')
                else:
                    if mode == 'identity': row['method'] = 'wrong-method'
                    if mode == 'outcome': row.update(passed=False, failures=['owned failure'])
                    if mode == 'infrastructure': row['infrastructure_error'] = 'owned import error'
                    if mode == 'typed_count': row['tests_run'] = True
                    path.write_text(json.dumps(row))
                with patch.object(verify, 'ROOT', root), self.assertRaises((AssertionError, ValueError)):
                    verify.check_native_mutation_matrix()

    def test_cached_rows_and_nested_summary_must_equal_recomputed_outputs(self):
        for filename in ('rows.json', 'summary.json'):
            with self.subTest(filename=filename):
                root, target = self.native_fixture()
                path = target / filename
                data = json.loads(path.read_text())
                if filename == 'rows.json':
                    data[0]['passed'] = False
                else:
                    data['by_suite']['legacy']['matrix']['early_end']['passed_methods'] = 0
                path.write_text(json.dumps(data))
                with patch.object(verify, 'ROOT', root), self.assertRaises(AssertionError):
                    verify.check_native_mutation_matrix()


class TopologyTableTests(Scratch):
    def test_retained_agreeing_table_is_unchanged(self):
        table = paper_topology.topology_table(ROOT / 'results/topology-challenge')
        self.assertIn('Valid split topology & 2/0/0 & agree & 2/0/0', table)
        self.assertEqual(table.count(' & agree & '), 7)

    def test_disagreement_is_rejected_even_with_consistently_recomputed_summary(self):
        target = self.topology_fixture()
        rows = json.loads((target / 'trials.json').read_text())
        rows[0]['direct'] = 'fail'
        summary = json.loads((target / 'summary.json').read_text())
        updated = paper_topology.summarize_rows(rows, 0)
        (target / 'trials.json').write_text(json.dumps(rows))
        (target / 'summary.json').write_text(json.dumps({**updated, 'wall_s': summary['wall_s']}))
        with self.assertRaisesRegex(ValueError, 'disagreement'):
            paper_topology.topology_table(target)

    def test_inconsistent_selected_summary_is_rejected(self):
        target = self.topology_fixture()
        path = target / 'summary.json'
        summary = json.loads(path.read_text())
        summary['by_case']['split_link_valid']['verdicts'] = {'fail': 1}
        path.write_text(json.dumps(summary))
        with self.assertRaisesRegex(ValueError, 'summary differs'):
            paper_topology.topology_table(target)


class RunnerFailureTests(Scratch):
    def campaign(self, mode):
        output = self.scratch() / 'campaign'
        case = 'split_link_valid'
        run = json.loads((ROOT / f'results/topology-challenge/{case}__000.json').read_text())

        def process(command, **kwargs):
            dest = Path(command[command.index('--output-file') + 1])
            if mode == 'timeout':
                raise subprocess.TimeoutExpired(command, 30)
            if mode == 'invalid_json':
                dest.write_text('{')
            elif mode not in ('missing', 'nonzero_missing'):
                if mode == 'identity': run['case'] = 'split_parent_valid'
                if mode == 'incomplete': run['execution']['status'] = 'missing'
                if mode == 'malformed': run.pop('ledger_check')
                dest.write_text(json.dumps(run))
            return SimpleNamespace(returncode=1 if mode.startswith('nonzero') else 0,
                                   stdout='', stderr='owned benign child fixture\n')

        with patch.object(runner, 'TOPOLOGY_CASES', (case,)), \
             patch.object(runner.subprocess, 'run', side_effect=process), redirect_stdout(StringIO()):
            result = runner.orchestrate(output, 1, 1)
        return output, result

    def test_agreeing_completed_child_is_scored(self):
        output, result = self.campaign('valid')
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads((output / 'trials.json').read_text())), 1)

    def test_failures_keep_receipts_guard_and_exclude_invalid_or_nonzero_records(self):
        for mode in ('missing', 'nonzero_missing', 'nonzero_valid', 'invalid_json',
                     'identity', 'incomplete', 'malformed', 'timeout'):
            with self.subTest(mode=mode):
                output, result = self.campaign(mode)
                self.assertEqual(result, 1)
                manifest = json.loads((output / 'execution-manifest.json').read_text())
                self.assertEqual(len(manifest['processes']), 1)
                self.assertEqual(len(manifest['failures']), 1)
                self.assertEqual(json.loads((output / 'trials.json').read_text()), [])
                self.assertEqual(json.loads((output / 'summary.json').read_text())['runner_failures'], 1)
                before = self.snapshot(output)
                with patch.object(runner.subprocess, 'run') as child, self.assertRaises(SystemExit):
                    runner.orchestrate(output, 1, 1)
                child.assert_not_called()
                self.assertEqual(self.snapshot(output), before)


class WorkflowPublicationTests(Scratch):
    @unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'requires requirements-figures.txt')
    def test_real_renderer_cli_uses_the_staged_pair_route(self):
        output = self.scratch() / 'figures'
        config = output.parent / 'matplotlib-config'
        with patch.dict(os.environ, {'MPLCONFIGDIR': str(config)}):
            subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/workflow_assets.py'),
                            '--output-dir', str(output)], check=True, timeout=60)
        self.assertTrue((output / 'workflow.pdf').read_bytes().startswith(b'%PDF-'))
        self.assertEqual((output / 'workflow.tex').read_text(), workflow_assets.WRAPPER)

    def test_direct_fixture_subprocess_installs_pair(self):
        output = self.scratch() / 'figures'
        with patch.object(workflow_assets, 'ROOT', ROOT / 'tests/fixtures/workflow_assets'):
            workflow_assets.write_workflow_assets(output)
        self.assertTrue((output / 'workflow.pdf').read_bytes().startswith(b'%PDF-'))
        self.assertEqual((output / 'workflow.tex').read_text(), workflow_assets.WRAPPER)

    def test_partial_failure_invalid_or_missing_pdf_preserves_both_old_files(self):
        for mode in ('failure', 'invalid', 'missing'):
            with self.subTest(mode=mode):
                _, paper = self.paper_fixture()
                output = paper / 'figures'
                before = self.snapshot(output)

                def renderer(command, check):
                    target = Path(command[command.index('--output-dir') + 1])
                    if mode != 'missing':
                        (target / 'workflow.pdf').write_bytes(b'%PDF-partial' if mode == 'failure' else b'not PDF')
                    if mode == 'failure':
                        raise subprocess.CalledProcessError(1, command)

                with patch.object(workflow_assets.subprocess, 'run', side_effect=renderer):
                    with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                        workflow_assets.write_workflow_assets(output)
                self.assertEqual(self.snapshot(output), before)

    def test_wrapper_publication_failure_rolls_back_pdf_too(self):
        _, paper = self.paper_fixture()
        output = paper / 'figures'
        before = self.snapshot(output)
        replace = asset_publication.os.replace
        failed = False

        def install(source, target):
            nonlocal failed
            if Path(target) == output / 'workflow.tex' and not failed:
                failed = True
                raise OSError('owned installation failure')
            return replace(source, target)

        with patch.object(workflow_assets, 'ROOT', ROOT / 'tests/fixtures/workflow_assets'), \
             patch.object(asset_publication.os, 'replace', side_effect=install):
            with self.assertRaises(OSError):
                workflow_assets.write_workflow_assets(output)
        self.assertEqual(self.snapshot(output), before)

    def test_double_io_failure_retains_backup_outside_renderer_temporary_tree(self):
        _, paper = self.paper_fixture()
        output = paper / 'figures'
        original = (output / 'workflow.pdf').read_bytes()
        replace = asset_publication.os.replace

        def install(source, target):
            if Path(target) == output / 'workflow.tex':
                raise OSError('owned publication failure')
            if '.asset-backup-' in str(source):
                raise OSError('owned restoration failure')
            return replace(source, target)

        with patch.object(workflow_assets, 'ROOT', ROOT / 'tests/fixtures/workflow_assets'), \
             patch.object(asset_publication.os, 'replace', side_effect=install):
            with self.assertRaises(asset_publication.PublicationRollbackError) as error:
                workflow_assets.write_workflow_assets(output)
        backup = error.exception.backup_directory
        self.assertIn(str(backup), str(error.exception))
        self.assertEqual((backup / 'workflow.pdf').read_bytes(), original)
        self.assertEqual(backup.parent, output.parent)


class BuilderTransactionTests(Scratch):
    def producer(self, fail=None, missing=False):
        def process(command, check):
            script = Path(command[1]).name
            if script == 'render_cost_table.py':
                target = Path(command[command.index('--output') + 1])
                self.assertNotEqual(target.parent.parent, getattr(self, 'current_paper', None))
                target.write_text('owned absolute cost table\n')
            else:
                flag = '--output-dir' if script == 'draw_workflow.py' else '--figure-dir'
                target = Path(command[command.index(flag) + 1])
                names = {'render_traces.py': ('timeline', 'uipath-early-close'),
                         'render_costs.py': ('cost-direct', 'cost-to_thread'),
                         'draw_workflow.py': ('workflow',)}[script]
                for name in names:
                    if not missing:
                        (target / (name + '.pdf')).write_bytes(b'%PDF-1.4\nowned new ' + name.encode())
                    if script == 'render_costs.py':
                        (target / (name + '.tex')).write_text('owned new wrapper\n')
            if script == fail:
                raise subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)
        return process

    def run_builder(self, paper, renderer):
        self.current_paper = paper
        with patch.object(builder, 'resolve_font_root', return_value=paper.parent / 'owned-fonts'), \
             patch.object(builder.subprocess, 'run', side_effect=renderer), redirect_stdout(StringIO()):
            builder.main(['--paper-dir', str(paper)])

    def test_missing_fonts_and_missing_data_leave_existing_paper_untouched(self):
        for missing in ('font', 'data'):
            with self.subTest(missing=missing):
                root, paper = self.paper_fixture()
                before = self.snapshot(paper)
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                    if missing == 'font':
                        builder.main(['--font-root', str(root / 'missing-fonts'), '--paper-dir', str(paper)])
                    else:
                        with patch.object(builder, 'resolve_font_root', return_value=root), patch.object(builder, 'R', root):
                            builder.main(['--paper-dir', str(paper)])
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(self.snapshot(paper), before)

    def test_each_native_font_or_workflow_producer_failure_preserves_all_outputs(self):
        for script in ('render_cost_table.py', 'render_traces.py', 'render_costs.py', 'draw_workflow.py'):
            with self.subTest(script=script):
                _, paper = self.paper_fixture()
                before = self.snapshot(paper)
                with self.assertRaises(subprocess.CalledProcessError):
                    self.run_builder(paper, self.producer(fail=script))
                self.assertEqual(self.snapshot(paper), before)

    def test_missing_renderer_output_is_not_published(self):
        _, paper = self.paper_fixture()
        before = self.snapshot(paper)
        with self.assertRaises(RuntimeError):
            self.run_builder(paper, self.producer(missing=True))
        self.assertEqual(self.snapshot(paper), before)

    def test_complete_output_set_publishes_and_keeps_unrelated_files(self):
        _, paper = self.paper_fixture()
        self.run_builder(paper, self.producer())
        builder.validate_outputs(paper)
        self.assertEqual((paper / 'unrelated.txt').read_text(), 'keep me\n')
        self.assertIn('agree', (paper / 'generated/topology-table.tex').read_text())

    def test_publication_failure_rolls_back_replaced_and_new_outputs(self):
        _, paper = self.paper_fixture()
        before = self.snapshot(paper)
        replace = asset_publication.os.replace
        count = 0

        def install(source, target):
            nonlocal count
            if Path(target).is_relative_to(paper):
                count += 1
                if count == 5:
                    raise OSError('owned publication failure')
            return replace(source, target)

        with patch.object(asset_publication.os, 'replace', side_effect=install):
            with self.assertRaises(OSError):
                self.run_builder(paper, self.producer())
        self.assertEqual(self.snapshot(paper), before)

    def test_double_io_failure_backup_survives_builder_staging_cleanup(self):
        _, paper = self.paper_fixture()
        original = (paper / 'figures/cost-direct.pdf').read_bytes()
        replace = asset_publication.os.replace
        count = 0

        def install(source, target):
            nonlocal count
            if '.asset-backup-' in str(source) and Path(target).is_relative_to(paper):
                raise OSError('owned restoration failure')
            if Path(target).is_relative_to(paper):
                count += 1
                if count == 5:
                    raise OSError('owned publication failure')
            return replace(source, target)

        with patch.object(asset_publication.os, 'replace', side_effect=install):
            with self.assertRaises(asset_publication.PublicationRollbackError) as error:
                self.run_builder(paper, self.producer())
        backup = error.exception.backup_directory
        self.assertEqual((backup / 'figures/cost-direct.pdf').read_bytes(), original)
        self.assertEqual(backup.parent, paper.parent)


@unittest.skipUnless((ROOT.parent / 'paper/build.py').is_file(), 'companion paper builder not present')
class PaperBuildConsumerTests(Scratch):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('companion_paper_build_under_test', ROOT.parent / 'paper/build.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        _, self.paper = self.paper_fixture()
        (self.paper / 'main.pdf').write_bytes(b'%PDF-1.4\nowned retained manuscript')
        (self.paper / 'main.tex').write_text('owned manuscript source\n')

    def process(self, failure=None):
        def run(command, **kwargs):
            if len(command) > 1 and Path(command[1]).name == 'draw_workflow.py':
                target = Path(command[command.index('--output-dir') + 1])
                (target / 'workflow.pdf').write_bytes(b'%PDF-1.4\nowned new workflow')
                if failure == 'renderer':
                    raise subprocess.CalledProcessError(1, command)
            else:
                if failure == 'compiler':
                    raise subprocess.CalledProcessError(1, command)
                work = Path(kwargs['cwd'])
                (work / 'main.pdf').write_bytes(b'%PDF-1.4\nowned new manuscript')
                (work / 'main.log').write_text('Overfull \\hbox' if failure == 'log' else 'owned clean log')
            return SimpleNamespace(returncode=0)
        return run

    def run_build(self, failure=None):
        with patch.object(self.module, 'HERE', self.paper), \
             patch.object(self.module.shutil, 'which', side_effect=lambda name: 'owned-' + name), \
             patch.object(self.module.subprocess, 'run', side_effect=self.process(failure)), redirect_stdout(StringIO()):
            self.module.main()

    def test_engine_preflight_does_not_run_renderer_or_touch_outputs(self):
        before = self.snapshot(self.paper)
        with patch.object(self.module, 'HERE', self.paper), \
             patch.object(self.module.shutil, 'which', return_value=None), \
             patch.object(self.module, 'write_workflow_assets') as draw, self.assertRaises(SystemExit):
            self.module.main()
        draw.assert_not_called()
        self.assertEqual(self.snapshot(self.paper), before)

    def test_renderer_compiler_and_log_failures_preserve_existing_pdfs(self):
        for mode in ('renderer', 'compiler', 'log'):
            with self.subTest(mode=mode):
                before = self.snapshot(self.paper)
                with self.assertRaises((subprocess.CalledProcessError, SystemExit)):
                    self.run_build(mode)
                self.assertEqual(self.snapshot(self.paper), before)

    def test_success_publishes_workflow_pair_and_manuscript_together(self):
        self.run_build()
        self.assertEqual((self.paper / 'main.pdf').read_bytes(), b'%PDF-1.4\nowned new manuscript')
        self.assertEqual((self.paper / 'figures/workflow.pdf').read_bytes(), b'%PDF-1.4\nowned new workflow')
        self.assertEqual((self.paper / 'figures/workflow.tex').read_text(), workflow_assets.WRAPPER)

    def test_late_publication_failure_restores_workflow_and_manuscript(self):
        before = self.snapshot(self.paper)
        replace = asset_publication.os.replace
        failed = False

        def install(source, target):
            nonlocal failed
            if Path(target) == self.paper / 'main.pdf' and not failed:
                failed = True
                raise OSError('owned manuscript publication failure')
            return replace(source, target)

        with patch.object(asset_publication.os, 'replace', side_effect=install), self.assertRaises(OSError):
            self.run_build()
        self.assertEqual(self.snapshot(self.paper), before)


if __name__ == '__main__':
    unittest.main()
