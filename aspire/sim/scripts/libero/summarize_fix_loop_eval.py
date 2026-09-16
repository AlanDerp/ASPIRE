#!/usr/bin/env python3
"""Summarise fix-loop held-out eval manifests for one suite.

Reads every ``outputs/libero_fix_loop_eval/<suite>/<task>/runs/<run_id>/manifest.json``
and prints, per task: run id, status, passes/trials, pass rate, the failing
held-out seeds, and the results directory that holds the traces, keyframes and
videos for that run.

Usage:
    .venv/bin/python3 scripts/libero/summarize_fix_loop_eval.py --suite libero_goal_swap
"""
from __future__ import annotations

import argparse
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def summarize(suite: str, root: pathlib.Path) -> int:
    base = root / suite
    if not base.is_dir():
        print(f"no eval output at {base}")
        return 1

    rows, complete = [], 0
    for manifest_path in sorted(base.glob("*/runs/*/manifest.json")):
        task = manifest_path.parents[2].name
        data = json.loads(manifest_path.read_text())
        results = data.get("results", {})
        fails = sorted(int(s) for s, v in results.items() if float(v.get("reward", 0.0)) < 1.0)
        # NOTE: a non-zero sandbox_rc is NOT by itself a failure signal in this
        # harness - successful trials (reward 1.0, task_completed 1) routinely
        # carry sandboxrc_1 in their directory name. Only report it for trials
        # that actually failed, where it distinguishes a crash from a clean miss.
        crash_fails = sorted(
            int(s)
            for s, v in results.items()
            if float(v.get("reward", 0.0)) < 1.0 and int(v.get("sandbox_rc", 0)) != 0
        )
        rows.append(
            {
                "task": task,
                "run_id": data.get("run_id", manifest_path.parent.name),
                "status": data.get("status"),
                "passes": data.get("passes"),
                "trials": data.get("trials"),
                "rate": data.get("pass_rate"),
                "fails": fails,
                "crash_fails": crash_fails,
                "results_dir": str(manifest_path.parent / "results"),
            }
        )
        if data.get("status") == "complete":
            complete += 1

    width = max([len(r["task"]) for r in rows] + [4])
    print(f"suite: {suite}   manifests: {len(rows)}   complete: {complete}")
    print(f"{'task':<{width}}  {'run_id':<17} {'status':<9} {'passes':>9}  {'rate':>6}")
    for r in rows:
        rate = f"{r['rate']:.2f}" if isinstance(r["rate"], (int, float)) else "-"
        print(
            f"{r['task']:<{width}}  {r['run_id']:<17} {r['status']:<9} "
            f"{r['passes']}/{r['trials']:<5}  {rate:>6}"
        )
    print()
    for r in rows:
        print(f"{r['task']}:")
        print(f"  results: {r['results_dir']}")
        print(f"  failing seeds ({len(r['fails'])}): {r['fails']}")
        if r["crash_fails"]:
            print(f"  of which crashed (sandbox_rc != 0): {r['crash_fails']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True)
    ap.add_argument("--root", default=str(REPO / "outputs" / "libero_fix_loop_eval"))
    args = ap.parse_args()
    return summarize(args.suite, pathlib.Path(args.root))


if __name__ == "__main__":
    raise SystemExit(main())
