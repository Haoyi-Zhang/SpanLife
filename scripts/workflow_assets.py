"""Regenerate the current workflow PDF and its matching TeX inclusion wrapper."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = r'\includegraphics[width=\columnwidth]{figures/workflow.pdf}' + '\n'


def write_workflow_assets(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'plots/draw_workflow.py'),
                    '--output-dir', str(directory)], check=True)
    pdf = directory / 'workflow.pdf'
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
        raise RuntimeError('Workflow renderer did not produce a PDF.')
    # Install the wrapper only after the renderer has completed successfully.
    (directory / 'workflow.tex').write_text(WRAPPER, encoding='utf-8')
