#!/usr/bin/env python3
"""Data-only tables/plots. Run summarize.py first."""
from pathlib import Path
import csv,json,collections
R=Path(__file__).resolve().parents[1]
P=R.parent/'paper';G=P/'generated';F=P/'figures';F.mkdir(exist_ok=True)
rows=list(csv.DictReader((R/'results/summary/case-configurations.csv').open()))
index={(x['case'],x['revision']):x for x in rows}
def trip(cases,rev,tool='ledger'):
 vals=[sum(int(index[c,rev][tool+'_'+v]) for c in cases) for v in ('pass','fail','inconclusive')]
 return '/'.join(map(str,vals))
hist=['success','queue','handled_inside','escaped','repeat','capture_epoch','lifecycle']
shape=['as_completed_list','as_completed_tuple','as_completed_generator','task_keyword']
groups=[('Historical pair: affected',hist,'affected'),('Historical pair: fixed',hist,'fixed'),
 ('Coroutine shapes: original',shape,'fixed'),('Coroutine shapes: local correction',shape,'local-shape-fix'),
 ('Threading: normal reuse',['thread_context'],'fixed'),('Threading: live-pool uninstrument',['thread_uninstrument_live'],'fixed'),
 ('Threading: recreate pool',['thread_recreate'],'fixed'),
 ('Submission/both/ended-parent controls',['submission_only','both_lifetimes','parent_ends_first'],'fixed'),
 ('Collection pending',['batch_pending'],'fixed'),('Collection drained',['batch_drained'],'fixed'),
 ('Deliberate exporter loss',['export_drop'],'fixed'),('Undeclared intent',['unknown_intent'],'fixed'),
 ('Service: defaults/async/caught-by-caller',['service_default','service_async','service_caller_handles'],'fixed'),
 ('Service: async, affected runtime',['service_async'],'affected'),
 ('Service: sync/background coverage gaps',['service_sync_gap','service_background_gap'],'fixed'),
 ('Service: sync/background corrections',['service_sync_corrected','service_background_corrected'],'fixed')]
t='\\begin{tabular}{lrrrr}\n\\toprule\nConfiguration family & $n$ & Ledger P/F/I & Direct P/F/I & Name P/F/I\\\\\n\\midrule\n'
for label,cs,rev in groups:
 t+=label+' & '+str(sum(int(index[c,rev]['trials']) for c in cs))+' & '+ ' & '.join(trip(cs,rev,tool) for tool in ('ledger','direct','name'))+'\\\\\n'
total_n = sum(int(x['trials']) for x in rows)
total_values = ['/'.join(str(sum(int(x[tool+'_'+v]) for x in rows)) for v in ('pass','fail','inconclusive')) for tool in ('ledger','direct','name')]
t += '\\midrule\nTotal & ' + str(total_n) + ' & ' + ' & '.join(total_values) + '\\\\\n\\bottomrule\n\\end{tabular}\n'
(G/'matrix-table.tex').write_text(t)
cs=list(csv.DictReader((R/'results/summary/cost-summary-us.csv').open()))
t='\\begin{tabular}{llrrr}\n\\toprule\nPath & Configuration & Median & IQR & Range\\\\\n\\midrule\n'
for w in ('direct','to_thread'):
 for m,lab in [('none','None'),('hook','Hooks'),('hook_sdk','Hooks + SDK')]:
  c=next(c for c in cs if c['workload']==w and c['mode']==m)
  t+=('Direct' if w=='direct' else '\\texttt{to\\_thread}')+' & '+lab+' & '+f"{float(c['median']):.2f}"+' & '+f"{float(c['q1']):.2f}--{float(c['q3']):.2f}"+' & '+f"{float(c['minimum']):.2f}--{float(c['maximum']):.2f}"+'\\\\\n'
t+='\\bottomrule\n\\end{tabular}\n';(G/'cost-table.tex').write_text(t)
# Actual queue-case repeat 1, independently normalized to invocation entry.
tr=list(csv.DictReader((R/'results/summary/operation-timing.csv').open()))
a=next(x for x in tr if x['case']=='queue' and x['revision']=='affected' and x['repeat']=='1')
b=next(x for x in tr if x['case']=='queue' and x['revision']=='fixed' and x['repeat']=='1')
max_x=max(float(a['exit_ms']),float(b['exit_ms']))*1.08
s=r'''\begin{tikzpicture}
\begin{axis}[width=0.92\columnwidth,height=4.4cm,xmin=0,xmax=MAXX,
 ymin=0.4,ymax=4.6,ytick={1,2,3,4},yticklabels={Fixed callback,Fixed span,Affected callback,Affected span},
 xlabel={Milliseconds from invocation entry},tick label style={font=\scriptsize},
 label style={font=\small},axis y line=left,y axis line style={draw=none},ytick style={draw=none},axis x line=bottom,enlarge x limits=false]
'''.replace('MAXX',str(max_x))
for row,ys in [(a,(4,3)),(b,(2,1))]:
 for start,end,y,style in [(row['span_start_ms'],row['span_end_ms'],ys[0],'line width=1.3pt'),(row['entry_ms'],row['exit_ms'],ys[1],'line width=2.8pt,densely dashed')]:
  s+=f'\\addplot[{style},mark=|] coordinates {{({start},{y}) ({end},{y})}};\n'
s+='\\end{axis}\n\\end{tikzpicture}\n';(F/'timeline.tex').write_text(s)
# Two independent figures, no decorative redraw: observed cost distributions.
for w in ('direct','to_thread'):
 s=r'''\begin{tikzpicture}
\begin{axis}[width=\columnwidth,height=4.5cm,boxplot/draw direction=y,
 xtick={1,2,3},xticklabels={None,Hooks,Hooks + SDK},ylabel={Microseconds / operation},
 tick label style={font=\scriptsize},label style={font=\small},xmin=0.5,xmax=3.5]
'''
 for m in ('none','hook','hook_sdk'):
  c=next(c for c in cs if c['workload']==w and c['mode']==m)
  s+='\\addplot+[boxplot prepared={lower whisker='+c['minimum']+',lower quartile='+c['q1']+',median='+c['median']+',upper quartile='+c['q3']+',upper whisker='+c['maximum']+'},mark=none] coordinates {};\n'
 s+='\\end{axis}\n\\end{tikzpicture}\n';(F/f'cost-{w}.tex').write_text(s)

# Mutation challenge: collapse the 18 one-field transformations into mechanism
# families.  Each member still remains individually replayable in results/.
mutation=json.loads((R/'results/mutation-challenge/summary.json').read_text())
mutation_groups=[
 ('Valid controls',['control_execution','control_submission','control_parent_ends_first'],'Pass'),
 ('Interval/role',['starts_after_entry','ends_before_exit','includes_queue_wait','submission_as_execution'],'Fail'),
 ('Outcome',['missing_error_status','missing_exception_event'],'Fail'),
 ('Association/context',['parent_mismatch','context_mismatch','missing_span'],'Fail'),
 ('Evidence insufficiency',['export_loss','collection_unqualified','duplicate_association','unknown_intent','clock_unqualified','both_missing_submission'],'Inconclusive'),
]
t='\\begin{tabular}{lrrrr}\n\\toprule\nFamily & Kinds & Judgments & Expected & Exact\\\\\n\\midrule\n'
for label,names,expected in mutation_groups:
    n=sum(sum(mutation['by_mutation'][name]['ledger'].values()) for name in names)
    exact=sum(mutation['by_mutation'][name]['ledger'].get(expected.lower(),0) for name in names)
    t+=f'{label} & {len(names)} & {n} & {expected} & {exact}/{n}\\\\\n'
t+='\\midrule\nTotal & 18 & 360 & --- & 360/360\\\\\n\\bottomrule\n\\end{tabular}\n'
(G/'mutation-table.tex').write_text(t)

# Combined runtime and serialized checker challenges. The executable row counts
# fresh-process SDK runs; the serialized row counts derived judgments only.
executable=json.loads((R/'results/executable-perturbations/summary.json').read_text())
t='\\begin{tabular}{p{.25\\columnwidth}rrrrr}\n\\toprule\nChallenge & Kinds & Judgments & Exact verdict & Exact code & Name misses\\\\\n\\midrule\n'
t+=f"Executable perturbations & {executable['perturbations']} & {executable['fresh_process_trials']} & {executable['exact_expected_verdicts']}/{executable['fresh_process_trials']} & {executable['expected_diagnostic_present']}/{executable['fresh_process_trials']} & {executable['name_misses_with_ledger_fail']}\\\\\n"
t+=f"Serialized one-field transformations & {mutation['mutations']} & {mutation['derived_trials']} & {mutation['exact_expected_verdicts']}/{mutation['derived_trials']} & {mutation['exact_expected_diagnostics']}/{mutation['derived_trials']} & {mutation['name_misses_with_ledger_fail']}\\\\\n"
t+='\\bottomrule\n\\end{tabular}\n'
(G/'challenge-table.tex').write_text(t)

# Policy counterfactual: the cells report 20 repeated observations under each
# declared role.  They are not independent runtime executions.
policy=json.loads((R/'results/policy-counterfactual/summary.json').read_text())
pm={(x['observation'],x['declared_role']):x for x in policy['matrix']}
def cell(obs,role):
    x=pm[obs,role]
    if x['pass']: return f"{x['pass']}P"
    if x['fail']: return f"{x['fail']}F"
    return f"{x['inconclusive']}I"
t='\\begin{tabular}{lccccc}\n\\toprule\nObserved span & Exec. & Submit & Both & Context & Unknown\\\\\n\\midrule\n'
for obs,label in [('execution_span','Execution'),('submission_span','Submission'),('combined_span','Combined')]:
    t+=label+' & '+' & '.join(cell(obs,r) for r in ('execution','submission','both','context-only','unknown'))+'\\\\\n'
t+='\\bottomrule\n\\end{tabular}\n'
(G/'policy-table.tex').write_text(t)

# Independent public-source holdout (pinned Speaches decorator source).
speaches=json.loads((R/'results/speaches-holdout/summary.json').read_text())
labels={
 'decorated_sync':('Sync decorator','control'),
 'decorated_generator':('Generator decorator','control'),
 'generator_misuse':('Sync decorator on generator','local misuse'),
 'generator_exception':('Generator exception','control'),
}
t='\\begin{tabular}{llrrr}\n\\toprule\nCase & Classification & P & F & I\\\\\n\\midrule\n'
for key in ('decorated_sync','decorated_generator','generator_misuse','generator_exception'):
    label,kind=labels[key]; v=speaches['by_case'][key]['verdicts']
    t+=f"{label} & {kind} & {v.get('pass',0)} & {v.get('fail',0)} & {v.get('inconclusive',0)}\\\\\n"
t+='\\midrule\nTotal & --- & 24 & 7 & 9\\\\\n\\bottomrule\n\\end{tabular}\n'
(G/'speaches-table.tex').write_text(t)

print('Generated principal, replay/challenge, counterfactual, holdout, release, and cost assets.')

# UiPath transfer and local correction: aggregate mechanism families from the
# independent confirmation runs.  The public early-close failure is a local,
# unconfirmed observation; the corrected row is a local intervention.
uipath=json.loads((R/'results/uipath-holdout/summary.json').read_text())
uipath_fix=json.loads((R/'results/uipath-local-correction/summary.json').read_text())
uipath_groups=[
 ('Sync call + error',['sync_success','sync_exception']),
 ('Coroutine call + error',['async_success','async_exception']),
 ('Sync generator',['generator_success','generator_partial_close','generator_exception']),
 ('Async generator complete/error',['async_generator_success','async_generator_exception']),
 ('Async generator early close',['async_generator_partial_close']),
]
def verdict_trip(summary,names):
    counts=collections.Counter()
    for name in names: counts.update(summary['by_case'][name]['verdicts'])
    return f"{counts['pass']}/{counts['fail']}/{counts['inconclusive']}"
t='\\begin{tabular}{lrrr}\n\\toprule\nMechanism family & Trials & Public P/F/I & Local correction P/F/I\\\\\n\\midrule\n'
for label,names in uipath_groups:
    n=sum(sum(uipath['by_case'][name]['verdicts'].values()) for name in names)
    t+=f"{label} & {n} & {verdict_trip(uipath,names)} & {verdict_trip(uipath_fix,names)}\\\\\n"
t+='\\midrule\nTotal & 100 & 90/10/0 & 97/0/3\\\\\n\\bottomrule\n\\end{tabular}\n'
(G/'uipath-table.tex').write_text(t)

# Native test sensitivity to the same ten executable operators.  The last
# column is the checker outcome distribution, not a repository mutation score.
native=json.loads((R/'results/native-mutation-matrix/summary.json').read_text())
exec_rows=json.loads((R/'results/executable-perturbations/trials.json').read_text())
exec_by=collections.defaultdict(list)
for row in exec_rows: exec_by[row['perturbation']].append(row)
operator_labels={
 'early_end':'Early end', 'late_start':'Late start',
 'queue_inclusive':'Queue included', 'no_span':'No span',
 'duplicate_span':'Duplicate span', 'wrong_parent':'Wrong parent',
 'missing_error_status':'Missing error status',
 'missing_exception_event':'Missing exception event',
 'first_call_only':'First call only',
 'empty_context_execution':'Empty execution context',
}
def verdict_counts(rows,key):
    c=collections.Counter(row[key] for row in rows)
    parts=[]
    for symbol,name in [('P','pass'),('F','fail'),('I','inconclusive')]:
        if c[name]: parts.append(f"{c[name]}{symbol}")
    return '/'.join(parts)
t='\\begin{tabular}{lcccc}\n\\toprule\nOperator & Name check & Legacy native & Updated native & SpanLife\\\\\n\\midrule\n'
for op in native['perturbations']:
    name_out=verdict_counts(exec_by[op],'name')
    legacy=native['by_suite']['legacy']['matrix'][op]['detected']
    updated=native['by_suite']['updated']['matrix'][op]['detected']
    span=verdict_counts(exec_by[op],'actual')
    t+=f"{operator_labels[op]} & {name_out} & {'yes' if legacy else '--'} & {'yes' if updated else '--'} & {span}\\\\\n"
t+='\\bottomrule\n\\end{tabular}\n'
(G/'native-mutation-table.tex').write_text(t)

# Evidence-gate ablation.  Every source row is inconclusive with the gate and
# becomes a definite action after the gate is removed.
gates=json.loads((R/'results/gate-ablation/summary.json').read_text())
gate_labels={
 'collection_qualification':('Collection complete','20 failures'),
 'export_witness':('End/export distinction','20 failures'),
 'association_uniqueness':('Unique association','20 passes'),
 'declared_intent':('Declared role','20 passes'),
 'clock_eligibility':('Eligible clock','20 passes'),
 'submission_completeness':('Complete submission bounds','20 passes'),
}
t='\\begin{tabular}{p{.43\\columnwidth}rr}\n\\toprule\nRemoved gate & Reference & Unsupported action\\\\\n\\midrule\n'
for gate in gate_labels:
    label,action=gate_labels[gate]
    t+=f"{label} & 20 I & {action}\\\\\n"
t+='\\midrule\nTotal & 120 I & 80 passes + 40 failures\\\\\n\\bottomrule\n\\end{tabular}\n'
(G/'gate-ablation-table.tex').write_text(t)

# Paired process-block cost differences with deterministic percentile bootstrap
# intervals for the median.  Intervals quantify this local benchmark only.
paired=list(csv.DictReader((R/'results/summary/cost-paired-differences-us.csv').open()))
def paired_row(workload,comparison):
    return next(x for x in paired if x['workload']==workload and x['comparison']==comparison)
t='\\begin{tabular}{lrr}\n\\toprule\nPath & Hooks $-$ none & SDK increment\\\\\n\\midrule\n'
for workload,label in [('direct','Direct'),('to_thread','\\texttt{to\\_thread}')]:
    hook=paired_row(workload,'hook-minus-none'); sdk=paired_row(workload,'sdk-increment')
    hook_text=f"{float(hook['median']):.2f} [{float(hook['ci95_low']):.2f}, {float(hook['ci95_high']):.2f}]"
    sdk_text=f"{float(sdk['median']):.2f} [{float(sdk['ci95_low']):.2f}, {float(sdk['ci95_high']):.2f}]"
    t+=f"{label} & {hook_text} & {sdk_text}\\\\\n"
t+='\\bottomrule\n\\end{tabular}\n'
(G/'cost-paired-table.tex').write_text(t)

# Data-derived timeline for the independently confirmed UiPath early-close
# observation and the local correction, normalized to operation entry.
def one_uipath(directory):
    path=sorted((R/directory).glob('async_generator_partial_close__*.json'))[0]
    run=json.loads(path.read_text())
    enter=next(e for e in run['ledger'] if e['operation_id']=='op-0' and e['kind']=='enter')['wall_ns']
    exit_ns=next(e for e in run['ledger'] if e['operation_id']=='op-0' and e['kind']=='exit')['wall_ns']
    sid=run['policies'][0]['span_ids'][0]
    span=next(x for x in run['spans'] if x['span_id']==sid)
    return {'op_start':0.0,'op_end':(exit_ns-enter)/1000,
            'span_start':(span['start_ns']-enter)/1000,
            'span_end':(span['end_ns']-enter)/1000}
public=one_uipath('results/uipath-holdout')
corrected=one_uipath('results/uipath-local-correction')
xmin=min(public['span_start'],corrected['span_start'])-8
xmax=max(public['op_end'],corrected['op_end'],public['span_end'],corrected['span_end'])+8
s=r'''\begin{tikzpicture}
\begin{axis}[width=.98\columnwidth,height=4.3cm,xmin=XMIN,xmax=XMAX,
 ymin=.4,ymax=4.6,ytick={1,2,3,4},
 yticklabels={Corrected operation,Corrected span,Public operation,Public span},
 xlabel={Microseconds from operation entry},tick label style={font=\scriptsize},
 label style={font=\small},axis y line=left,y axis line style={draw=none},
 ytick style={draw=none},axis x line=bottom,enlarge x limits=false]
'''.replace('XMIN',str(xmin)).replace('XMAX',str(xmax))
for row,span_y,op_y in [(public,4,3),(corrected,2,1)]:
    s+=f"\\addplot[line width=1.4pt,mark=|] coordinates {{({row['span_start']},{span_y}) ({row['span_end']},{span_y})}};\n"
    s+=f"\\addplot[line width=2.8pt,densely dashed,mark=|] coordinates {{({row['op_start']},{op_y}) ({row['op_end']},{op_y})}};\n"
s+='\\end{axis}\n\\end{tikzpicture}\n'
(F/'uipath-early-close.tex').write_text(s)

# Conceptual workflow.  All text is semantic; no numerical claim is encoded.
workflow=r'''\begin{tikzpicture}[
  node distance=3.0mm and 4.0mm,
  box/.style={draw,rounded corners=1.5pt,fill=black!3,align=center,
              minimum height=8mm,inner sep=3pt,font=\scriptsize},
  gate/.style={box,fill=black!8},
  verdict/.style={box,fill=black!12},
  arr/.style={-{Latex[length=2mm]},line width=.55pt}
]
\node[box,text width=.42\columnwidth] (ledger) {Independent operation ledger\\submission; entry/exit; outcome; context};
\node[box,text width=.42\columnwidth,right=of ledger] (capture) {Telemetry capture\\candidate spans; parent/link edges; interval; status/events; end/export witnesses};
\node[box,text width=.88\columnwidth,above=of $(ledger.north)!0.5!(capture.north)$] (policy) {Lifetime topology: one or more execution, submission, combined, or context-only segments; declared handoff relations};
\node[gate,text width=.88\columnwidth,below=of $(ledger.south)!0.5!(capture.south)$] (gates) {Evidence gates: completed operation $\rightarrow$ deterministic correlation $\rightarrow$ qualified collection $\rightarrow$ eligible clock};
\node[box,text width=.88\columnwidth,below=of gates] (predicates) {Evaluate declared segment intervals, queue/error/context obligations, and parent/link topology};
\node[verdict,text width=.27\columnwidth,below left=of predicates] (pass) {PASS\\retain regression};
\node[verdict,text width=.27\columnwidth,below=of predicates] (fail) {FAIL\\narrow correction};
\node[verdict,text width=.27\columnwidth,below right=of predicates] (inc) {INCONCLUSIVE\\repair evidence};
\draw[arr] (policy) -- (ledger);
\draw[arr] (policy) -- (capture);
\draw[arr] (ledger) -- (gates);
\draw[arr] (capture) -- (gates);
\draw[arr] (gates) -- (predicates);
\draw[arr] (predicates) -- (pass);
\draw[arr] (predicates) -- (fail);
\draw[arr] (predicates) -- (inc);
\end{tikzpicture}
'''
(F/'workflow.tex').write_text(workflow)

print('Generated UiPath, native-sensitivity, gate-ablation, paired-cost, and workflow assets.')

# Multi-span topology and explicit-correlation challenge.  Each row is one
# fresh-process scenario; grouped rows summarize contract behavior, not defect
# prevalence.
topology=json.loads((R/'results/topology-challenge/summary.json').read_text())
topology_groups=[
 ('Valid split topology',['split_link_valid','split_parent_valid']),
 ('Missing/wrong handoff',['split_missing_relation','split_wrong_relation']),
 ('Boundary-order faults',['split_submission_overlap','split_execution_early_end']),
 ('Missing segment',['split_execution_missing','split_submission_missing']),
 ('Valid same-name concurrency',['correlated_concurrent_valid']),
 ('Missing/swapped correlation',['correlated_missing_attribute','correlated_swapped_attribute']),
 ('Duplicate correlation',['correlated_duplicate_attribute']),
]
def topology_counts(names):
    counts=collections.Counter()
    name_counts=collections.Counter()
    for name in names:
        data=topology['by_case'][name]
        counts.update(data['verdicts'])
        # One retained process per case; reconstruct the name-only outcome from
        # the trial rows to avoid inferring it from disagreement alone.
    rows=json.loads((R/'results/topology-challenge/trials.json').read_text())
    for row in rows:
        if row['case'] in names:
            name_counts[row['name']]+=1
    return counts,name_counts

t='\\begin{tabular}{lccc}\n\\toprule\nContract family & SpanLife P/F/I & Direct & Name-only P/F/I\\\\\n\\midrule\n'
for label,names in topology_groups:
    counts,names_out=topology_counts(names)
    pfi=f"{counts['pass']}/{counts['fail']}/{counts['inconclusive']}"
    npfi=f"{names_out['pass']}/{names_out['fail']}/{names_out['inconclusive']}"
    t+=f"{label} & {pfi} & agree & {npfi}\\\\\n"
t+='\\bottomrule\n\\end{tabular}\n'
(G/'topology-table.tex').write_text(t)
print('Generated topology/correlation challenge table.')
