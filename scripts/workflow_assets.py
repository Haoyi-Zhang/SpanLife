"""Regenerate the current workflow PDF and its matching TeX inclusion wrapper."""
from pathlib import Path
import subprocess
import sys
import tempfile

from asset_publication import publish_tree

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = r'\includegraphics[width=\columnwidth]{figures/workflow.pdf}' + '\n'


def write_workflow_assets(directory):
    directory = Path(directory).resolve()
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.workflow-', dir=directory.parent) as temp:
        staged = Path(temp)
        subprocess.run([sys.executable, str(ROOT / 'plots/draw_workflow.py'),
                        '--output-dir', str(staged)], check=True)
        pdf = staged / 'workflow.pdf'
        if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
            raise RuntimeError('Workflow renderer did not produce a PDF.')
        (staged / 'workflow.tex').write_text(WRAPPER, encoding='utf-8')
        publish_tree(staged, directory)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    write_workflow_assets(parser.parse_args().output_dir)
