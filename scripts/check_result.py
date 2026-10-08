#!/usr/bin/env python3
"""Recheck one complete serialized trial without importing the tracing SDK."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from spanlife.oracle import qualify

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);a=ap.parse_args()
    try:
        r=json.loads(a.input.read_text())
        for key in ('ledger','policies','spans','clock'):assert key in r,f'missing {key}'
        assert r['policies'],'no operation policies supplied'
        for p in r['policies']:
            assert p['role'] in {'execution','submission','both','context-only','unknown'},'unsupported role'
        result=qualify(r)
    except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
        ap.error(f'input not qualified: {exc}')
    print(json.dumps(result,indent=2))
    return {'pass':0,'fail':1,'inconclusive':2}[result['verdict']]
if __name__=='__main__':sys.exit(main())
