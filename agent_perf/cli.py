"""Command line entry point: python -m agent_perf benchmark|forecast."""
import argparse
import asyncio
import json
from pathlib import Path
from .env import load_project_env
from .models import Suite
from .runner import run_suite
from .report import save_benchmark
from .capacity import CapacityInputs, write_capacity_report


def main():
    load_project_env()
    ap=argparse.ArgumentParser(description='Agent Performance Toolkit: safe mock/live perf tests and planning estimates')
    sub=ap.add_subparsers(dest='task',required=True)
    bench=sub.add_parser('benchmark')
    bench.add_argument('--config',default='examples/benchmark_suite.json')
    bench.add_argument('--out',default='results/benchmark')
    bench.add_argument('--ack-live',action='store_true',help='Explicitly approve limited live traffic')
    plan=sub.add_parser('forecast')
    plan.add_argument('--config',default='examples/capacity_template.json')
    plan.add_argument('--out',default='results/capacity')
    args=ap.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if args.task=='forecast':
        out=write_capacity_report(CapacityInputs.from_dict(config),args.out)
        print(f'Capacity report: {args.out}/CAPACITY_REPORT.md')
        print(f'Peak workflow TPS: {out["workflows_tps_peak"]}; pods: {out["total_replicas"]}; node minimum floor: {out["node_floor"]}')
    else:
        suite=Suite.from_dict(config)
        if args.ack_live:suite.ack_live=True
        observations,summary=asyncio.run(run_suite(suite))
        save_benchmark(args.out,observations,summary,suite)
        print(f'Benchmark results: {args.out}/REPORT.md and {args.out}/dashboard.html')
        for x in summary:print(x)

if __name__=='__main__':main()
