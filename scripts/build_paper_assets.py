#!/usr/bin/env python3
"""Regenerate presentation assets from retained data, publishing only a complete set."""
from pathlib import Path
import argparse
import csv
import json
import collections
import shutil
import subprocess
import sys
import tempfile

from asset_publication import publish_tree
from paper_topology import topology_table
from render_cost_table import checked_distributions

R = Path(__file__).resolve().parents[1]
JSON_INPUTS = (
    'mutation-challenge/summary.json', 'executable-perturbations/summary.json',
    'executable-perturbations/trials.json', 'policy-counterfactual/summary.json',
    'speaches-holdout/summary.json', 'uipath-holdout/summary.json',
    'uipath-local-correction/summary.json', 'native-mutation-matrix/summary.json',
    'gate-ablation/summary.json', 'topology-challenge/summary.json',
    'topology-challenge/trials.json',
)
CSV_INPUTS = ('case-configurations.csv', 'cost-summary-us.csv',
              'operation-timing.csv', 'cost-paired-differences-us.csv')
GENERATED_TABLES = ('matrix', 'cost', 'mutation', 'challenge', 'policy', 'speaches',
                    'uipath', 'native-mutation', 'gate-ablation', 'cost-paired',
                    'cost-distribution', 'topology')
FIGURES = ('timeline', 'uipath-early-close', 'cost-direct', 'cost-to_thread', 'workflow')


def csv_rows(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def resolve_font_root(font_root):
    if font_root is None:
        kpsewhich = shutil.which('kpsewhich')
        if kpsewhich is None:
            raise ValueError('TeX fonts are required: pass --font-root /path/to/texmf-dist/fonts.')
        afm = subprocess.check_output([kpsewhich, 'utmr8a.afm'], text=True).strip()
        if not afm:
            raise ValueError('Times font metrics are not installed in the selected TeX environment.')
        font_root = Path(afm).parents[3]
    font_root = Path(font_root).resolve()
    for relative in ('afm/urw/times/utmr8a.afm', 'type1/urw/times/utmr8a.pfb'):
        if not (font_root / relative).is_file():
            raise FileNotFoundError(font_root / relative)
    return font_root


def preflight_inputs(root):
    checked_distributions(root / 'results/costs-local', root / 'results/summary/cost-summary-us.csv')
    for relative in JSON_INPUTS:
        json.loads((root / 'results' / relative).read_text())
    for relative in CSV_INPUTS:
        with (root / 'results/summary' / relative).open(newline='', encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError(f'Invalid CSV header: {relative}')
            rows = list(reader)
            if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
                raise ValueError(f'Incomplete CSV data: {relative}')
    for directory in ('uipath-holdout', 'uipath-local-correction'):
        paths = sorted((root / 'results' / directory).glob('async_generator_partial_close__*.json'))
        if not paths:
            raise ValueError(f'Missing early-close input: {directory}')
        json.loads(paths[0].read_text())
    topology_table(root / 'results/topology-challenge')


def validate_outputs(paper):
    expected = [paper / 'generated' / (name + '-table.tex') for name in GENERATED_TABLES]
    expected += [paper / 'figures' / (name + suffix) for name in FIGURES for suffix in ('.pdf', '.tex')]
    expected.append(paper / 'figures/trace_intervals.csv')
    for path in expected:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'Missing generated asset: {path}')
        if path.suffix == '.pdf' and not path.read_bytes().startswith(b'%PDF-'):
            raise RuntimeError(f'Invalid generated PDF: {path}')


def generate_assets(root, paper, font_root):
    R, P = Path(root), Path(paper)
    G, F = P/'generated', P/'figures'
    G.mkdir(parents=True, exist_ok=True)
    F.mkdir(parents=True, exist_ok=True)
    rows=csv_rows(R/'results/summary/case-configurations.csv')
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
    cs=csv_rows(R/'results/summary/cost-summary-us.csv')
    t='\\begin{tabular}{llrrr}\n\\toprule\nPath & Configuration & Median & IQR & Range\\\\\n\\midrule\n'
    for w in ('direct','to_thread'):
     for m,lab in [('none','None'),('hook','Hooks'),('hook_sdk','Hooks + SDK')]:
      c=next(c for c in cs if c['workload']==w and c['mode']==m)
      t+=('Direct' if w=='direct' else 'Thread transfer')+' & '+lab+' & '+f"{float(c['median']):.2f}"+' & '+f"{float(c['q1']):.2f}--{float(c['q3']):.2f}"+' & '+f"{float(c['minimum']):.2f}--{float(c['maximum']):.2f}"+'\\\\\n'
    t+='\\bottomrule\n\\end{tabular}\n';(G/'cost-table.tex').write_text(t)
    # Actual queue-case repeat 1, independently normalized to invocation entry.
    tr=csv_rows(R/'results/summary/operation-timing.csv')
    a=next(x for x in tr if x['case']=='queue' and x['revision']=='affected' and x['repeat']=='1')
    b=next(x for x in tr if x['case']=='queue' and x['revision']=='fixed' and x['repeat']=='1')
    trace_intervals=[]
    for row,span_y,op_y,label in [(a,4,3,'Affected'),(b,2,1,'Fixed')]:
     trace_intervals.append(dict(figure='timeline',row=span_y,label=label+' span',start=row['span_start_ms'],end=row['span_end_ms']))
     trace_intervals.append(dict(figure='timeline',row=op_y,label=label+' callback',start=row['entry_ms'],end=row['exit_ms']))
    # Cost distributions are rendered below after resolving the same Times fonts
    # used by the timing figures.  Their five-number summaries remain unchanged.

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
    paired=csv_rows(R/'results/summary/cost-paired-differences-us.csv')
    def paired_row(workload,comparison):
        return next(x for x in paired if x['workload']==workload and x['comparison']==comparison)
    t='\\begin{tabular}{lrr}\n\\toprule\nPath & Hooks $-$ none & SDK increment\\\\\n\\midrule\n'
    for workload,label in [('direct','Direct'),('to_thread','Thread transfer')]:
        hook=paired_row(workload,'hook-minus-none'); sdk=paired_row(workload,'sdk-increment')
        hook_text=f"{float(hook['median']):.2f} [{float(hook['ci95_low']):.2f}, {float(hook['ci95_high']):.2f}]"
        sdk_text=f"{float(sdk['median']):.2f} [{float(sdk['ci95_low']):.2f}, {float(sdk['ci95_high']):.2f}]"
        t+=f"{label} & {hook_text} & {sdk_text}\\\\\n"
    t+='\\bottomrule\n\\end{tabular}\n'
    (G/'cost-paired-table.tex').write_text(t)
    subprocess.run([sys.executable, str(R/'scripts/render_cost_table.py'),
                    '--output', str(G/'cost-distribution-table.tex')], check=True)

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
    for row,span_y,op_y,label in [(public,4,3,'Public'),(corrected,2,1,'Corrected')]:
        trace_intervals.append(dict(figure='uipath',row=span_y,label=label+' span',start=row['span_start'],end=row['span_end']))
        trace_intervals.append(dict(figure='uipath',row=op_y,label=label+' operation',start=row['op_start'],end=row['op_end']))
    with (F/'trace_intervals.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['figure','row','label','start','end'])
        writer.writeheader();writer.writerows(trace_intervals)
    for name,width,height in [('timeline','0.92','4.4'),('uipath-early-close','0.98','4.3')]:
        (F/(name+'.tex')).write_text('% Timing data: trace_intervals.csv.\n'+
            f'\\includegraphics[width={width}\\columnwidth,height={height}cm]{{figures/{name}.pdf}}\n',encoding='utf-8')
    subprocess.run([sys.executable,str(R/'scripts/render_traces.py'),
                    '--figure-dir',str(F),'--font-root',str(font_root)],check=True)
    subprocess.run([sys.executable,str(R/'scripts/render_costs.py'),
                    '--cost-csv',str(R/'results/summary/cost-summary-us.csv'),
                    '--figure-dir',str(F),'--font-root',str(font_root)],check=True)

    # Conceptual workflow uses the current Python vector renderer and PDF wrapper.
    from workflow_assets import write_workflow_assets
    write_workflow_assets(F)


    (G/'topology-table.tex').write_text(topology_table(R/'results/topology-challenge'), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-root', type=Path)
    parser.add_argument('--paper-dir', type=Path, default=R.parent/'paper')
    args = parser.parse_args(argv)
    try:
        font_root = resolve_font_root(args.font_root)
        preflight_inputs(R)
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    with tempfile.TemporaryDirectory(prefix='.paper-assets-', dir=R) as temp:
        staged = Path(temp) / 'paper'
        generate_assets(R, staged, font_root)
        validate_outputs(staged)
        publish_tree(staged, args.paper_dir.resolve())
    print('Generated and published complete paper asset set.')


if __name__ == '__main__':
    main()
