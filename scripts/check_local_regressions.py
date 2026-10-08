#!/usr/bin/env python3
"""Local correction regression integration. Fresh processes; no network."""
import argparse,json,sys
from pathlib import Path
import run_matrix
ROOT=Path(__file__).resolve().parents[1]
CASES=[('service_sync_gap','fixed','fail'),('service_sync_corrected','fixed','pass'),
       ('service_background_gap','fixed','fail'),('service_background_corrected','fixed','pass'),
       ('as_completed_tuple','fixed','fail'),('as_completed_tuple','local-shape-fix','pass'),
       ('thread_uninstrument_live','fixed','fail'),('thread_recreate','fixed','pass')]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'results/local-regressions')
    args=ap.parse_args();out=args.output.resolve()
    run_matrix.MATRIX=[(c,r) for c,r,_ in CASES]
    sys.argv=[sys.argv[0],'--output',str(out),'--repeats','1','--workers','1']
    rc=run_matrix.main()
    if rc:return rc
    results=[]
    for case,revision,expected in CASES:
        r=json.loads((out/f'{case}__{revision}__000.json').read_text())
        actual=r['ledger_check']['verdict'];agrees=actual==r['direct_check']['verdict']
        findings=r['ledger_check']['findings']
        clock_only=(actual=='inconclusive' and findings and
                    all(f['code']=='CLOCK_UNQUALIFIED' for f in findings))
        status='pass' if actual==expected and agrees else 'inconclusive' if clock_only and agrees else 'fail'
        results.append(dict(case=case,revision=revision,expected=expected,actual=actual,
                            baseline_agrees=agrees,regression_status=status))
    report={'results':results,'regression_pass':sum(r['regression_status']=='pass' for r in results),
            'regression_fail':sum(r['regression_status']=='fail' for r in results),
            'regression_inconclusive':sum(r['regression_status']=='inconclusive' for r in results)}
    (out/'regression-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 1 if report['regression_fail'] else 2 if report['regression_inconclusive'] else 0
if __name__=='__main__':sys.exit(main())
