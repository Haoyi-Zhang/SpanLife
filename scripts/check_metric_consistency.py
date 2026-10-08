#!/usr/bin/env python3
"""Post-evaluation consistency diagnostic; not another independent defect set."""
from pathlib import Path
import json,csv,statistics
ROOT=Path(__file__).resolve().parents[1]
rows=[]
for case in ('success','handled_inside','escaped','repeat','lifecycle'):
 for rev in ('affected','fixed'):
  for p in sorted((ROOT/'results/evaluation').glob(f'{case}__{rev}__*.json')):
   r=json.loads(p.read_text())
   durations=[m for m in r['metrics'] if m['name']=='asyncio.process.duration' and m['attributes'].get('type')=='to_thread' and m['attributes'].get('name')=='work']
   entered={e['operation_id']:e['monotonic_ns'] for e in r['ledger'] if e['kind']=='enter'}
   selected={p['operation_id'] for p in r['policies'] if p['role']=='execution'}
   measured=sum(e['monotonic_ns']-entered[e['operation_id']] for e in r['ledger'] if e['kind']=='exit' and e['operation_id'] in selected)/1e9
   total=sum(m['sum'] for m in durations)
   rows.append(dict(case=case,revision=rev,repeat=r['repeat'],histogram_count=sum(m['count'] for m in durations),states=';'.join(sorted(m['attributes']['state'] for m in durations)),histogram_seconds=total,ledger_seconds=measured,metric_to_ledger_ratio=total/measured))
out=ROOT/'results/summary/metric-consistency.csv'
with out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
for case in ('success','handled_inside','escaped','repeat','lifecycle'):
 for rev in ('affected','fixed'):
  subset=[r for r in rows if r['case']==case and r['revision']==rev]
  print(case,rev,'counts',sorted(set(r['histogram_count'] for r in subset)),'states',sorted(set(r['states'] for r in subset)),'median ratio',statistics.median(r['metric_to_ledger_ratio'] for r in subset))
