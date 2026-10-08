from copy import deepcopy
from itertools import product
from pathlib import Path
import ast
import json
import hashlib
import pytest
from spanlife.oracle import qualify
from spanlife.baselines import direct_assertions
from spanlife.ledger import Ledger, tolerance


def example(role='execution'):
    return {'ledger':[{'operation_id':'x','kind':k,'wall_ns':v,'monotonic_ns':v,
                       'outcome':'returned' if k=='exit' else None,'exception_type':None}
                      for k,v in [('submit_enter',1),('submit_exit',2),('queue_release',7),('enter',10),('exit',20)]],
            'spans':[{'span_id':'s','name':'worker','start_ns':9,'end_ns':21,
                      'parent_id':'root','status':'UNSET','events':[]}],
            'policies':[{'operation_id':'x','role':role,'span_ids':['s'],'span_name':'worker',
                         'error_on_escape':True,'exception_event':True,'expected_parent':'root'}],
            'contexts':{},'drained':True,'always_on':True,
            'clock':{'epsilon_ns':0,'timing_eligible':True}}


def test_ledger_has_no_sdk_imports():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'src/spanlife/ledger.py').read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert all('opentelemetry' not in (i or '') for i in imports)


def test_boundary_and_equal_duration_shift():
    run=example(); assert qualify(run)['verdict']=='pass'
    run['spans'][0].update(start_ns=0,end_ns=12) # duration unchanged
    assert qualify(run)['verdict']=='fail'


@pytest.mark.parametrize('field', ['drained', 'always_on'])
def test_present_candidate_cannot_pass_pending_collection(field):
    run = example(); run[field] = False
    assert qualify(run)['verdict'] == 'inconclusive'
    assert direct_assertions(run)['verdict'] == 'inconclusive'
    run['spans'][0]['parent_id'] = 'wrong'
    assert qualify(run)['verdict'] == 'inconclusive'
    run['policies'][0]['expected_context'] = 'expected'
    run['contexts']['x'] = 'observed'
    assert qualify(run)['verdict'] == 'fail'
    assert direct_assertions(run)['verdict'] == 'fail'


def test_explicit_id_does_not_collapse_cross_trace_candidates():
    run = example()
    run['spans'][0]['trace_id'] = 'a'
    other = deepcopy(run['spans'][0]); other['trace_id'] = 'b'
    run['spans'].append(other)
    assert qualify(run)['verdict'] == 'inconclusive'
    assert direct_assertions(run)['verdict'] == 'inconclusive'


def test_submission_is_not_execution():
    run=example('submission');run['spans'][0].update(start_ns=0,end_ns=3)
    assert qualify(run)['verdict']=='pass'
    run['policies'][0]['role']='execution';assert qualify(run)['verdict']=='fail'


def test_parent_may_have_already_ended():
    run=example();run['spans'].append({'span_id':'root','name':'ended','start_ns':0,'end_ns':1})
    assert qualify(run)['verdict']=='pass'


def test_caught_inside_not_error_but_escape_is():
    run=example(); assert qualify(run)['verdict']=='pass'
    run['ledger'][-1].update(outcome='raised',exception_type='ValueError')
    assert qualify(run)['verdict']=='fail'
    run['spans'][0].update(status='ERROR',events=['exception'])
    assert qualify(run)['verdict']=='pass'


@pytest.mark.parametrize('drained,witness,expected',[(False,0,'inconclusive'),(True,1,'inconclusive'),(True,0,'fail')])
def test_missing_classification(drained,witness,expected):
    run=example();run['spans']=[];run['policies'][0]['span_ids']=[]
    run['drained']=drained;run['policies'][0]['ended_witness']=witness
    assert qualify(run)['verdict']==expected
    assert direct_assertions(run)['verdict']==expected


def test_duplicate_association_is_not_defect():
    run=example();run['policies'][0]['span_ids']=['s','other']
    assert qualify(run)['verdict']=='inconclusive'


def test_missing_boundaries_inconclusive():
    run=example();run['ledger']=[]
    assert qualify(run)['verdict']=='inconclusive'


def test_clock_uncertainty_inconclusive():
    run=example();run['clock']['timing_eligible']=False
    run['spans'][0]['end_ns']=1
    assert qualify(run)['verdict']=='inconclusive'


def test_unknown_intent():
    run=example('unknown');assert qualify(run)['verdict']=='inconclusive'


def test_context_only_has_no_span_obligation():
    run=example('context-only');run['spans']=[];run['policies'][0]['span_ids']=[]
    run['policies'][0]['expected_context']='A';run['contexts']['x']='A'
    assert qualify(run)['verdict']=='pass'
    run['contexts']['x']='B';assert qualify(run)['verdict']=='fail'


def test_exception_recording_uses_escape_boundary():
    ledger=Ledger()
    with ledger.operation('caught'):
        try: raise ValueError('internal')
        except ValueError: pass
    with pytest.raises(ValueError):
        with ledger.operation('escape'): raise ValueError('external')
    ends=[e for e in ledger.snapshot() if e['kind']=='exit']
    assert [e['outcome'] for e in ends]==['returned','raised']


def test_clock_cap():
    b={'median_offset_ns':0,'max_bracket_ns':100}
    assert tolerance(b,b)['epsilon_ns']==1000
    assert not tolerance(b,dict(b,median_offset_ns=1000000))['timing_eligible']


@pytest.mark.parametrize('start,end,epsilon',[(a,b,e) for a in range(0,25,2)
                         for b in range(a,26,2) for e in (0,1,2)])
def test_exhaustive_small_interval_spec(start,end,epsilon):
    run=example();run['spans'][0].update(start_ns=start,end_ns=end)
    run['clock']['epsilon_ns']=epsilon
    # Independent truth table of the declared inclusion inequalities.
    expected='pass' if start<=10+epsilon and end>=20-epsilon else 'fail'
    assert qualify(run)['verdict']==expected
    assert direct_assertions(run)['verdict']==expected
