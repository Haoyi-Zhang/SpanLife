#!/usr/bin/env python3
"""Generate every principal numerical table from retained trial JSON, never constants."""
from __future__ import annotations
from collections import Counter, defaultdict
import copy
import argparse
import csv
import json
from pathlib import Path
import statistics
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from spanlife.oracle import qualify

UNCERTAIN = {'batch_pending','export_drop','unknown_intent'}
EXPECTED_FAIL = {('success','affected'), ('queue','affected'), ('handled_inside','affected'),
 ('escaped','affected'), ('repeat','affected'), ('capture_epoch','affected'), ('lifecycle','affected'),
 ('service_async','affected'), ('as_completed_tuple','fixed'), ('as_completed_generator','fixed'),
 ('task_keyword','fixed'), ('thread_uninstrument_live','fixed'), ('service_sync_gap','fixed'),
 ('service_background_gap','fixed')}

def quantile(vals, p):
    v = sorted(vals)
    if not v: return None
    at = (len(v)-1)*p
    lo = int(at); hi = min(lo+1,len(v)-1)
    return v[lo] + (v[hi]-v[lo])*(at-lo)

def dist(vals):
    return dict(n=len(vals), minimum=min(vals), q1=quantile(vals,.25), median=statistics.median(vals),
                q3=quantile(vals,.75), maximum=max(vals))


def bootstrap_median_ci(vals, *, resamples=20000, seed=20261004):
    """Deterministic percentile CI for a paired median difference."""
    vals=list(vals)
    rng=random.Random(seed)
    medians=[]
    for _ in range(resamples):
        medians.append(statistics.median(rng.choice(vals) for _ in vals))
    return {"ci95_low":quantile(medians,.025),"ci95_high":quantile(medians,.975),
            "bootstrap_resamples":resamples}

def csv_write(path, rows):
    if not rows: return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trial-dir', action='append', type=Path,
                    help='Repeat for multiple raw directories; defaults to retained evaluation and corrected holdout')
    ap.add_argument('--cost-dir', type=Path, default=ROOT/'results/costs')
    ap.add_argument('--output', type=Path, default=ROOT/'results/summary')
    ap.add_argument('--no-paper', action='store_true', help='Do not replace retained manuscript inputs')
    args = ap.parse_args()
    result=ROOT/'results'; output=args.output;output.mkdir(parents=True,exist_ok=True)
    folders=args.trial_dir or [result/'evaluation',result/'holdout-corrected']
    rows=[]; rejected=[]
    for folder in folders:
        for path in sorted(folder.glob('*__*.json')):
            row=json.loads(path.read_text()); row['_path']=str(path.resolve().relative_to(ROOT)) if path.resolve().is_relative_to(ROOT) else str(path.resolve())
            (rows if row['execution']['status']=='completed' else rejected).append(row)
    assert len({(x['case'],x['revision'],x['repeat']) for x in rows}) == len(rows), 'duplicate successful trials'
    groups=defaultdict(list)
    trial_table=[];timeline=[]
    for r in rows:
        key=(r['case'],r['revision']); groups[key].append(r)
        expected=('inconclusive' if r['case'] in UNCERTAIN else 'fail' if key in EXPECTED_FAIL else 'pass')
        trial_table.append(dict(case=r['case'],revision=r['revision'],repeat=r['repeat'],
           declared_expectation=expected,ledger=r['ledger_check']['verdict'],direct=r['direct_check']['verdict'],
           name=r['name_check']['verdict'],timing_eligible=r['clock']['timing_eligible'],
           epsilon_ns=r['clock']['epsilon_ns'],raw_path=r['_path']))
        spans={s['span_id']:s for s in r['spans']}
        for p in r['policies']:
            ev={e['kind']:e for e in r['ledger'] if e['operation_id']==p['operation_id']}
            if 'enter' not in ev or 'exit' not in ev:continue
            chosen=[spans[s] for s in p['span_ids'] if s in spans]
            s=chosen[0] if len(chosen)==1 else None
            origin=ev.get('submit_enter',ev['enter'])['wall_ns']
            timeline.append(dict(case=r['case'],revision=r['revision'],repeat=r['repeat'],operation=p['operation_id'],
              role=p['role'],entry_ms=(ev['enter']['wall_ns']-origin)/1e6,
              exit_ms=(ev['exit']['wall_ns']-origin)/1e6,
              span_start_ms=(s['start_ns']-origin)/1e6 if s else '',
              span_end_ms=(s['end_ns']-origin)/1e6 if s else '',
              execution_ms=(ev['exit']['monotonic_ns']-ev['enter']['monotonic_ns'])/1e6,
              span_ms=(s['end_ns']-s['start_ns'])/1e6 if s else '',
              epsilon_us=r['clock']['epsilon_ns']/1000))
    group_table=[]
    for (case,revision), rs in sorted(groups.items()):
        row=dict(case=case,revision=revision,trials=len(rs))
        for comparator in ('ledger','direct','name'):
            c=Counter(x[f'{comparator}_check']['verdict'] for x in rs)
            row.update({f'{comparator}_{v}':c[v] for v in ('pass','fail','inconclusive')})
        row['clock_ineligible']=sum(not x['clock']['timing_eligible'] for x in rs)
        group_table.append(row)
    csv_write(output/'trials.csv',trial_table);csv_write(output/'case-configurations.csv',group_table)
    csv_write(output/'operation-timing.csv',timeline)
    sensitivity=[]
    for multiplier in (.5,1,2,4):
        verdicts=[];changed=0
        for r in rows:
            x=copy.deepcopy(r)
            x['clock']['epsilon_ns']=round(x['clock']['epsilon_ns']*multiplier)
            # Never rescue an originally ineligible clock; enlarging past cap abstains.
            x['clock']['timing_eligible']=r['clock']['timing_eligible'] and x['clock']['epsilon_ns']<=x['clock']['cap_ns']
            verdict=qualify(x)['verdict'];verdicts.append(verdict)
            changed+=verdict!=r['ledger_check']['verdict']
        c=Counter(verdicts)
        sensitivity.append(dict(multiplier=multiplier,changed=changed,**{v:c[v] for v in ('pass','fail','inconclusive')}))
    csv_write(output/'tolerance-sensitivity.csv',sensitivity)
    counts=Counter(r['ledger_check']['verdict'] for r in rows)
    report={'completed_trials':len(rows),'configurations':len(groups),'initial_failed_attempts':len(rejected),
       'counts':dict(counts),'name_counts':dict(Counter(r['name_check']['verdict'] for r in rows)),
       'direct_disagreements':sum(r['ledger_check']['verdict']!=r['direct_check']['verdict'] for r in rows),
       'clock_ineligible':sum(not r['clock']['timing_eligible'] for r in rows),
       'epsilon_us':dist([r['clock']['epsilon_ns']/1000 for r in rows]),
       'declared_valid_controls':dict(Counter(x['ledger'] for x in trial_table if x['declared_expectation']=='pass')),
       'declared_discrepancies':dict(Counter(x['ledger'] for x in trial_table if x['declared_expectation']=='fail')),
       'name_misses_with_ledger_fail':sum(x['ledger']=='fail' and x['name']=='pass' for x in trial_table),
       'sensitivity':sensitivity,
       'failed_attempts':[{'path':r['_path'],'case':r['case'],'error':r['execution']['error']} for r in rejected]}
    if (args.cost_dir/'costs.json').exists():
        costs=json.loads((args.cost_dir/'costs.json').read_text())['samples'];cg=defaultdict(list)
        for c in costs:cg[c['workload'],c['mode']].append(c['ns_per_operation']/1000)
        cr=[dict(workload=w,mode=m,**dist(v)) for (w,m),v in sorted(cg.items())]
        csv_write(output/'cost-summary-us.csv',cr)
        csv_write(output/'cost-raw-us.csv',[dict(block=c['block'],ordinal=c['ordinal'],workload=c['workload'],mode=c['mode'],us_per_operation=c['ns_per_operation']/1000) for c in costs])
        report['costs_us']=cr
        paired={}; paired_rows=[]
        for w in ('direct','to_thread'):
            maps={m:{c['block']:c['ns_per_operation']/1000 for c in costs if c['workload']==w and c['mode']==m} for m in ('none','hook','hook_sdk')}
            comparisons={
                'hook-minus-none':[maps['hook'][b]-maps['none'][b] for b in maps['none']],
                'hook-sdk-minus-none':[maps['hook_sdk'][b]-maps['none'][b] for b in maps['none']],
                'sdk-increment':[maps['hook_sdk'][b]-maps['hook'][b] for b in maps['none']],
            }
            paired[w]={}
            for i,(label,values) in enumerate(comparisons.items()):
                summary=dict(**dist(values),**bootstrap_median_ci(values,seed=20261004+i+(0 if w=='direct' else 100)))
                paired[w][label]=summary
                paired_rows.append(dict(workload=w,comparison=label,**summary))
        csv_write(output/'cost-paired-differences-us.csv',paired_rows)
        report['paired_cost_differences_us']=paired

    # Independently generated evaluation extensions are intentionally not
    # folded into the principal 800-trial matrix.  They serve different units:
    # fresh-process public-source holdout runs, derived oracle mutations, and
    # policy counterfactuals over retained observations.
    extension_files = {
        'speaches_holdout': ROOT/'results/speaches-holdout/summary.json',
        'uipath_holdout': ROOT/'results/uipath-holdout/summary.json',
        'uipath_local_correction': ROOT/'results/uipath-local-correction/summary.json',
        'native_mutation_matrix': ROOT/'results/native-mutation-matrix/summary.json',
        'gate_ablation': ROOT/'results/gate-ablation/summary.json',
        'mutation_challenge': ROOT/'results/mutation-challenge/summary.json',
        'policy_counterfactual': ROOT/'results/policy-counterfactual/summary.json',
        'independent_replay': ROOT/'results/replay-20261003-comparison.json',
        'executable_perturbations': ROOT/'results/executable-perturbations/summary.json',
        'topology_challenge': ROOT/'results/topology-challenge/summary.json',
    }
    extensions = {}
    for name, path in extension_files.items():
        if path.exists():
            extensions[name] = json.loads(path.read_text())
    report['extensions'] = extensions
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.no_paper:
        print(json.dumps({k:v for k,v in report.items() if k != 'failed_attempts'},indent=2))
        return
    paper=ROOT.parent/'paper'; gen=paper/'generated';gen.mkdir(exist_ok=True)
    for p in output.glob('*.csv'):(gen/p.name).write_bytes(p.read_bytes())
    speaches = extensions.get('speaches_holdout', {})
    uipath = extensions.get('uipath_holdout', {})
    uipath_correction = extensions.get('uipath_local_correction', {})
    native_matrix = extensions.get('native_mutation_matrix', {})
    gate_ablation = extensions.get('gate_ablation', {})
    mutation = extensions.get('mutation_challenge', {})
    policy = extensions.get('policy_counterfactual', {})
    replay = extensions.get('independent_replay', {})
    executable = extensions.get('executable_perturbations', {})
    topology = extensions.get('topology_challenge', {})
    speaches_verdicts = Counter()
    for case in speaches.get('by_case', {}).values():
        speaches_verdicts.update(case.get('verdicts', {}))
    uipath_verdicts = Counter(uipath.get('verdicts', {}))
    uipath_correction_verdicts = Counter(uipath_correction.get('verdicts', {}))
    native_legacy = native_matrix.get('by_suite', {}).get('legacy', {})
    native_updated = native_matrix.get('by_suite', {}).get('updated', {})
    macro_values = {
       'TrialCount':len(rows),
       'PrincipalTrialCount':len(rows),
       'RuntimeTrialCount':len(rows) + int(speaches.get('trials', 0)) + int(uipath.get('trials', 0)),
       'ConfigCount':len(groups),
       'PassCount':counts['pass'],
       'FailCount':counts['fail'],
       'InconclusiveCount':counts['inconclusive'],
       'ClockIneligible':report['clock_ineligible'],
       'InitialFailures':len(rejected),
       'NameMissCount':report['name_misses_with_ledger_fail'],
       'SpeachesTrialCount':int(speaches.get('trials', 0)),
       'SpeachesPassCount':speaches_verdicts['pass'],
       'SpeachesFailCount':speaches_verdicts['fail'],
       'SpeachesInconclusiveCount':speaches_verdicts['inconclusive'],
       'UiPathTrialCount':int(uipath.get('trials', 0)),
       'UiPathPassCount':uipath_verdicts['pass'],
       'UiPathFailCount':uipath_verdicts['fail'],
       'UiPathInconclusiveCount':uipath_verdicts['inconclusive'],
       'UiPathCorrectionTrialCount':int(uipath_correction.get('trials', 0)),
       'UiPathCorrectionPassCount':uipath_correction_verdicts['pass'],
       'UiPathCorrectionFailCount':uipath_correction_verdicts['fail'],
       'UiPathCorrectionInconclusiveCount':uipath_correction_verdicts['inconclusive'],
       'NativeMutationMethodRuns':int(native_matrix.get('fresh_process_methods', 0)),
       'NativeLegacyDetected':int(native_legacy.get('detected_perturbations', 0)),
       'NativeUpdatedDetected':int(native_updated.get('detected_perturbations', 0)),
       'GateAblationJudgments':int(gate_ablation.get('derived_judgments', 0)),
       'GateAblationUnsupportedPasses':int(gate_ablation.get('unsupported_passes', 0)),
       'GateAblationUnsupportedFailures':int(gate_ablation.get('unsupported_failures', 0)),
       'MutationKinds':int(mutation.get('mutations', 0)),
       'MutationJudgments':int(mutation.get('derived_trials', 0)),
       'MutationExactVerdicts':int(mutation.get('exact_expected_verdicts', 0)),
       'MutationExactDiagnostics':int(mutation.get('exact_expected_diagnostics', 0)),
       'PolicyObservations':int(policy.get('source_observations', 0)),
       'PolicyJudgments':int(policy.get('policy_evaluations', 0)),
       'RetainedRuntimeTrialCount':len(rows) + int(speaches.get('trials', 0)) + int(uipath.get('trials', 0)),
       'ReplayTrialCount':int(replay.get('replay_trials', 0)),
       'FreshProcessTrialCount':len(rows) + int(speaches.get('trials', 0)) + int(uipath.get('trials', 0)) + int(uipath_correction.get('trials', 0)) + int(replay.get('replay_trials', 0)) + int(executable.get('fresh_process_trials', 0)) + int(native_matrix.get('fresh_process_methods', 0)) + int(topology.get('fresh_process_trials', 0)),
       'ReplayPassCount':int(replay.get('replay_counts', {}).get('pass', 0)),
       'ReplayFailCount':int(replay.get('replay_counts', {}).get('fail', 0)),
       'ReplayInconclusiveCount':int(replay.get('replay_counts', {}).get('inconclusive', 0)),
       'ReplayVerdictAgreement':int(replay.get('verdict_agreement', 0)),
       'ReplayVerdictChanges':int(replay.get('verdict_changes', 0)),
       'ReplayClockChanges':int(replay.get('clock_qualification_changes', 0)),
       'ReplayPassFailFlips':int(replay.get('pass_fail_flips', 0)),
       'ExecutablePerturbationKinds':int(executable.get('perturbations', 0)),
       'ExecutablePerturbationTrialCount':int(executable.get('fresh_process_trials', 0)),
       'ExecutablePerturbationExactVerdicts':int(executable.get('exact_expected_verdicts', 0)),
       'ExecutablePerturbationExactDiagnostics':int(executable.get('expected_diagnostic_present', 0)),
       'ExecutablePerturbationNameMisses':int(executable.get('name_misses_with_ledger_fail', 0)),
       'ExecutablePerturbationClockIneligible':sum(int(x.get('clock_ineligible', 0)) for x in executable.get('by_perturbation', {}).values()),
       'TopologyTrialCount':int(topology.get('fresh_process_trials', 0)),
       'TopologyOperationContracts':int(topology.get('operation_contracts', 0)),
       'TopologySegmentContracts':int(topology.get('segment_contracts', 0)),
       'TopologyExactVerdicts':int(topology.get('exact_expected_verdicts', 0)),
       'TopologyNameDisagreements':int(topology.get('name_disagreements', 0)),
    }
    macros='\n'.join('\\newcommand{\\'+key+'}{'+str(value)+'}' for key,value in macro_values.items())
    (gen/'numbers.tex').write_text('% Generated by artifact/scripts/summarize.py\n'+macros+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('failed_attempts',)},indent=2))
if __name__=='__main__':main()
