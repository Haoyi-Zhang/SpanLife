"""The data-only asset route must preserve the current non-TikZ consumer."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow_assets as assets


class WorkflowAssetsTests(unittest.TestCase):
    def test_success_restores_the_current_pdf_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'workflow.tex').write_text('obsolete drawing')
            def draw(command,check):
                self.assertTrue(check)
                self.assertEqual(command[1],str(assets.ROOT/'plots/draw_workflow.py'))
                self.assertEqual(command[2:],['--output-dir',str(out)])
                (out/'workflow.pdf').write_bytes(b'%PDF-owned-test-fixture')
            with patch.object(assets.subprocess,'run',side_effect=draw):
                assets.write_workflow_assets(out)
            self.assertEqual((out/'workflow.tex').read_text(),assets.WRAPPER)
            self.assertNotIn('tikzpicture',(out/'workflow.tex').read_text())

    def test_renderer_failure_does_not_replace_existing_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'workflow.tex').write_text('retained wrapper')
            with patch.object(assets.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['owned-renderer'])):
                with self.assertRaises(subprocess.CalledProcessError):assets.write_workflow_assets(out)
            self.assertEqual((out/'workflow.tex').read_text(),'retained wrapper')

    def test_missing_pdf_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(assets.subprocess,'run'):
                with self.assertRaises(RuntimeError):assets.write_workflow_assets(d)
            self.assertFalse((Path(d)/'workflow.tex').exists())


if __name__=='__main__':unittest.main()
