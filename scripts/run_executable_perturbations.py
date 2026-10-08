#!/usr/bin/env python3
"""Fresh-process executable perturbation challenge over the real SDK capture path."""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPECS={
 'early_end':('success','fail','ENDS_BEFORE_EXIT'),
 'late_start':('success','fail','STARTS_AFTER_ENTRY'),
 'queue_inclusive':('queue','fail','INCLUDES_QUEUE_WAIT'),
 'no_span':('success','fail','MISSING_SPAN'),
 'duplicate_span':('success','inconclusive','AMBIGUOUS_ASSOCIATION'),
 'wrong_parent':('success','fail','PARENT_MISMATCH'),
 'missing_error_status':('escaped','fail','MISSING_ERROR_STATUS'),
 'missing_exception_event':('escaped','fail','MISSING_EXCEPTION_EVENT'),
 'first_call_only':('repeat','fail','MISSING_SPAN'),
 'empty_context_execution':('success','fail','CONTEXT_MISMATCH'),
}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'results/executable-perturbations');ap.add_argument('--repeats',type=int,default=10);ap.add_argument('--workers',type=int,default=4,choices=range(1,9))
 args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 if (out/'execution-manifest.json').exists():ap.error('choose a new output directory')
 env={k:v for k,v in os.environ.items() if not k.startswith('OTEL_')}
 env['PYTHONPATH']=os.pathsep.join([str(ROOT/'src'),str(ROOT/'vendor')])
 jobs=[(name,rep) for name in SPECS for rep in range(args.repeats)]
 def run(job):
  name,rep=job;case,expected,code=SPECS[name];base=f'{name}__{rep:03d}';target=out/(base+'.json')
  cmd=[sys.executable,'-m','spanlife.cli','--case',case,'--revision',f'perturbation-{name}','--repeat',str(rep),'--output',str(target)]
  t=time.perf_counter()
  try:
   p=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True,timeout=30)
   (out/(base+'.log')).write_text(p.stdout+p.stderr);rc=p.returncode
  except subprocess.TimeoutExpired as e:
   rc=124;target.write_text(json.dumps({'case':case,'revision':f'perturbation-{name}','repeat':rep,'execution':{'status':'timeout','limit_s':30}},indent=2));(out/(base+'.log')).write_text(str(e))
  return {'perturbation':name,'repeat':rep,'returncode':rc,'elapsed_s':time.perf_counter()-t}
 start=time.time()
 with ThreadPoolExecutor(max_workers=args.workers) as ex:procs=list(ex.map(run,jobs))
 failures=[p for p in procs if p['returncode']]
 rows=[]
 for name,rep in jobs:
  case,expected,code=SPECS[name];path=out/f'{name}__{rep:03d}.json';d=json.loads(path.read_text())
  if d.get('execution',{}).get('status')!='completed':continue
  codes={f['code'] for f in d['ledger_check']['findings']}
  rows.append({'perturbation':name,'repeat':rep,'case':case,'expected_verdict':expected,'expected_code':code,'actual':d['ledger_check']['verdict'],'codes':sorted(codes),'direct':d['direct_check']['verdict'],'name':d['name_check']['verdict'],'clock_eligible':d['clock']['timing_eligible'],'raw':str(path.relative_to(ROOT))})
 by={}
 for name in SPECS:
  x=[r for r in rows if r['perturbation']==name];expected=SPECS[name][1];code=SPECS[name][2]
  by[name]={'case':SPECS[name][0],'expected_verdict':expected,'expected_code':code,'trials':len(x),'verdicts':dict(Counter(r['actual'] for r in x)),'exact_verdicts':sum(r['actual']==expected for r in x),'expected_code_present':sum(code in r['codes'] for r in x),'direct_disagreements':sum(r['actual']!=r['direct'] for r in x),'clock_ineligible':sum(not r['clock_eligible'] for r in x)}
 summary={'schema':1,'perturbations':len(SPECS),'fresh_process_trials':len(rows),'runner_failures':len(failures),'exact_expected_verdicts':sum(r['actual']==r['expected_verdict'] for r in rows),'expected_diagnostic_present':sum(r['expected_code'] in r['codes'] for r in rows),'direct_disagreements':sum(r['actual']!=r['direct'] for r in rows),'name_misses_with_ledger_fail':sum(r['actual']=='fail' and r['name']=='pass' for r in rows),'wall_s':time.time()-start,'by_perturbation':by,'classification':'Synthetic executable challenge operators; not upstream defects or application bug prevalence.'}
 (out/'trials.json').write_text(json.dumps(rows,indent=2)+'\n');(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(out/'execution-manifest.json').write_text(json.dumps({'schema':1,'processes':procs,'failures':failures,'trials':len(jobs),'wall_s':summary['wall_s']},indent=2)+'\n')
 print(json.dumps(summary,indent=2));return 1 if failures or summary['direct_disagreements'] else 0
if __name__=='__main__':sys.exit(main())
