"""Owned subprocess fixture for the workflow output-directory contract."""
import argparse
from pathlib import Path

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    out = parser.parse_args().output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / 'workflow.pdf').write_bytes(b'%PDF-1.4\nowned workflow renderer fixture\n%%EOF\n')
