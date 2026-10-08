#!/usr/bin/env python3
"""Replay upstream assertion methods with a documented local SDK fixture."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
ROOT=Path(__file__).resolve().parents[1]


def child(suite, revision, method):
    from spanlife.capture import select_revision
    select_revision(revision)
    sys.path.insert(0,str(ROOT/'tests'))
    from native_fixture import TestBase
    sys.modules['opentelemetry.test']=types.ModuleType('opentelemetry.test')
    compat=types.ModuleType('opentelemetry.test.test_base')
    compat.TestBase=TestBase
    sys.modules['opentelemetry.test.test_base']=compat
    path=ROOT/'tests/native'/f'test_to_thread_{suite}.py'
    spec=importlib.util.spec_from_file_location('upstream_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=unittest.TestResult()
    module.TestAsyncioToThread(method).run(result)
    return {'suite':suite,'revision':revision,'method':method,
            'passed':result.wasSuccessful(),'tests_run':result.testsRun,
            'failures':[text for _,text in result.failures],
            'errors':[text for _,text in result.errors]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,default=ROOT/'results/native.json')
    ap.add_argument('--child',nargs=3,metavar=('SUITE','REVISION','METHOD'))
    args=ap.parse_args()
    if args.child:
        print(json.dumps(child(*args.child)))
        return 0
    env={k:v for k,v in os.environ.items() if not k.startswith('OTEL_')}
    env['PYTHONPATH']=os.pathsep.join([str(ROOT/'src'),str(ROOT/'vendor')])
    rows=[]
    for suite in ('legacy','updated'):
        tree=ast.parse((ROOT/'tests/native'/f'test_to_thread_{suite}.py').read_text())
        methods=[n.name for c in tree.body if isinstance(c,ast.ClassDef)
                 for n in c.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
        for revision in ('affected','fixed'):
            for method in methods:
                p=subprocess.run([sys.executable,__file__,'--child',suite,revision,method],
                                 capture_output=True,text=True,env=env,cwd=ROOT,timeout=15)
                if p.returncode:
                    rows.append({'suite':suite,'revision':revision,'method':method,
                                 'execution_error':p.stderr,'passed':False})
                else:
                    row=json.loads(p.stdout);row['stderr']=p.stderr;rows.append(row)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'fixture':'local compatibility; upstream methods unchanged',
                                     'results':rows},indent=2)+'\n')
    for suite in ('legacy','updated'):
        for revision in ('affected','fixed'):
            selected=[r for r in rows if r['suite']==suite and r['revision']==revision]
            print(suite,revision,sum(r['passed'] for r in selected),'/',len(selected))
    # Fail only on infrastructure errors; expected old-code assertion failures
    # are preserved as the principal native-baseline observation.
    return int(any(r.get('execution_error') or r.get('errors') for r in rows))

if __name__=='__main__':
    sys.exit(main())
