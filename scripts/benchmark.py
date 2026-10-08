#!/usr/bin/env python3
"""Paired randomized local cost experiment. Each sample is a fresh process."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MODES = ('none', 'hook', 'hook_sdk')
WORKLOADS = ('direct', 'to_thread')

def sample(mode: str, workload: str, n: int, warmup: int) -> dict:
    from spanlife.ledger import Ledger
    ledger = Ledger(max_events=(n + warmup + 1)*2)
    capture = inst = None
    def work():
        if mode == 'none':
            return sum(range(16))
        with ledger.operation('cost'):
            return sum(range(16))
    target = work
    if mode == 'hook_sdk':
        os.environ['OTEL_PYTHON_ASYNCIO_TO_THREAD_FUNCTION_NAMES_TO_TRACE'] = 'work'
        from spanlife.capture import Capture, select_revision
        capture = Capture()
        inst = select_revision('fixed')()
        inst.instrument(tracer_provider=capture.provider, meter_provider=capture.meter_provider)
        if workload == 'direct':
            target = inst.wrap_to_thread_func(work)
    async def dispatch(count):
        for _ in range(count):
            assert await asyncio.to_thread(work) == 120
    if workload == 'direct':
        for _ in range(warmup):
            assert target() == 120
        start = time.perf_counter_ns()
        for _ in range(n):
            assert target() == 120
        elapsed = time.perf_counter_ns() - start
    else:
        async def timed():
            # One event loop and a warmed executor for warm-up and measurement.
            await dispatch(warmup)
            start = time.perf_counter_ns()
            await dispatch(n)
            return time.perf_counter_ns() - start
        elapsed = asyncio.run(timed())
    result = {'mode': mode, 'workload': workload, 'operations': n, 'warmup': warmup,
              'elapsed_ns': elapsed, 'ns_per_operation': elapsed / n,
              'ledger_events': len(ledger.snapshot()), 'pid': os.getpid(),
              'automatic_spans': len(capture.spans()) if capture else 0}
    if inst:
        inst.uninstrument()
        capture.close()
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', action='store_true')
    ap.add_argument('--mode', choices=MODES)
    ap.add_argument('--workload', choices=WORKLOADS)
    ap.add_argument('--n', type=int, default=1000)
    ap.add_argument('--warmup', type=int, default=200)
    ap.add_argument('--blocks', type=int, default=15)
    ap.add_argument('--output', type=Path, default=ROOT/'results/costs')
    args = ap.parse_args()
    if not 1 <= args.blocks <= 100 or not 1 <= args.n <= 10000 or not 0 <= args.warmup <= 10000:
        ap.error('bounded inputs required: blocks 1..100, n 1..10000, warmup 0..10000')
    if args.sample and (args.mode is None or args.workload is None):
        ap.error('--sample requires --mode and --workload')
    if args.sample:
        print(json.dumps(sample(args.mode, args.workload, args.n, args.warmup)))
        return
    args.output = args.output.resolve()
    if (args.output/'costs.json').exists():
        ap.error('output already contains cost evidence; choose a new --output directory')
    args.output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260929)
    records = []
    env = {k: v for k, v in os.environ.items() if not k.startswith('OTEL_')}
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT/'src'), str(ROOT/'vendor')])
    for block in range(args.blocks):
        order = [(w, m) for w in WORKLOADS for m in MODES]
        rng.shuffle(order)
        for ordinal, (workload, mode) in enumerate(order):
            cmd = [sys.executable, __file__, '--sample', '--mode', mode, '--workload', workload,
                   '--n', str(args.n), '--warmup', str(args.warmup)]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env, cwd=ROOT)
            base = f'{block:02d}-{ordinal}-{workload}-{mode}'
            (args.output/(base+'.log')).write_text(p.stderr)
            if p.returncode:
                raise RuntimeError(f'benchmark child failed: {base}: {p.stderr}')
            row = dict(json.loads(p.stdout), block=block, ordinal=ordinal, command=cmd)
            (args.output/(base+'.json')).write_text(json.dumps(row, indent=2)+'\n')
            records.append(row)
    (args.output/'costs.json').write_text(json.dumps({'seed':20260929,'blocks':args.blocks,'samples':records},indent=2)+'\n')
    print(f'Completed {len(records)} fresh-process samples in {args.blocks} randomized blocks.')
if __name__ == '__main__':
    main()
