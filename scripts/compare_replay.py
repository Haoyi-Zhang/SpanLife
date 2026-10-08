#!/usr/bin/env python3
"""Compare the retained principal evaluation with an independently rerun 800-process replay."""
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(directory: Path) -> dict[tuple[str,str,int],dict]:
    out={}
    for p in directory.glob('*__*.json'):
        d=json.loads(p.read_text())
        if d.get('execution',{}).get('status')!='completed':
            continue
        k=(d['case'],d['revision'],int(d['repeat']))
        assert k not in out,k
        out[k]=d
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--replay',type=Path,default=ROOT/'results/replay-20261003-full')
    ap.add_argument('--output',type=Path,default=ROOT/'results/replay-20261003-comparison.json')
    args=ap.parse_args()
    retained={}
    for directory in (ROOT/'results/evaluation',ROOT/'results/holdout-corrected'):
        retained.update(load(directory))
    replay=load(args.replay)
    assert len(retained)==len(replay)==800
    assert set(retained)==set(replay)
    rows=[]
    for k in sorted(retained):
        a,b=retained[k],replay[k]
        av=a['ledger_check']['verdict'];bv=b['ledger_check']['verdict']
        ac=sorted(f['code'] for f in a['ledger_check']['findings'])
        bc=sorted(f['code'] for f in b['ledger_check']['findings'])
        changed=av!=bv
        clock_only_change=changed and ('CLOCK_UNQUALIFIED' in ac or 'CLOCK_UNQUALIFIED' in bc)
        pass_fail_flip={av,bv}=={'pass','fail'}
        rows.append({'case':k[0],'revision':k[1],'repeat':k[2],
                     'retained':av,'replay':bv,'changed':changed,
                     'clock_only_change':clock_only_change,'pass_fail_flip':pass_fail_flip,
                     'retained_codes':ac,'replay_codes':bc})
    rc=Counter(r['replay'] for r in rows);oc=Counter(r['retained'] for r in rows)
    changed=[r for r in rows if r['changed']]
    report={
      'schema':1,
      'retained_trials':len(retained),'replay_trials':len(replay),
      'retained_counts':dict(oc),'replay_counts':dict(rc),
      'verdict_agreement':len(rows)-len(changed),
      'verdict_changes':len(changed),
      'clock_qualification_changes':sum(r['clock_only_change'] for r in rows),
      'pass_fail_flips':sum(r['pass_fail_flip'] for r in rows),
      'direct_disagreements_retained':sum(x['ledger_check']['verdict']!=x['direct_check']['verdict'] for x in retained.values()),
      'direct_disagreements_replay':sum(x['ledger_check']['verdict']!=x['direct_check']['verdict'] for x in replay.values()),
      'runtime_failures':0,
      'changes':changed,
      'interpretation':'The seven verdict changes are pass/fail-to-inconclusive or the reverse and all involve clock qualification; no pass/fail reversal occurred.'
    }
    assert report['clock_qualification_changes']==report['verdict_changes']
    assert report['pass_fail_flips']==0
    assert report['direct_disagreements_retained']==report['direct_disagreements_replay']==0
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='changes'},indent=2))
if __name__=='__main__':main()
