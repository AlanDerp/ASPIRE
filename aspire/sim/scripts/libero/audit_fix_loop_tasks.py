#!/usr/bin/env python3
"""Audit fix-loop task completion for one suite against the four required artifacts.

For every task directory under ``outputs/libero_fix_loop/<suite>/`` this checks the
four things a task must have before the loop can be called complete:

1. ``fix_code.py``               -- present, compiles, references no forbidden API
2. ``findings.md``               -- present (a recorded no-op is reported as such)
3. a VERIFIED skill promotion    -- from ``<suite>/skill_promotions.jsonl``
4. one immutable 50-seed manifest-- ``outputs/libero_fix_loop_eval/<suite>/<task>/
                                    runs/<run_id>/manifest.json`` with
                                    ``evidence_scope: heldout_full`` and seeds 1-50

It also reports the held-out pass rate from the run's result directories, and flags
any task with more than one run directory (a re-run means the manifest is no longer
the single immutable record) or any task whose manifest seed list is not exactly 1-50.

Usage:
    .venv/bin/python3 scripts/libero/audit_fix_loop_tasks.py --suite libero_object_swap
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]

FORBIDDEN = (
    "body_xpos", "get_site_xpos", "set_joint_qpos", "body_name2id", "joint_id2name",
    "sim.data.qpos", "sim.forward()", "_step_once", "parsed_problem", "_eval_predicate",
    "obj_body_id", "handle.env", "sim.model",
) + (".bddl", ".urdf")


def forbidden_hits(path: pathlib.Path) -> list[str]:
    text = path.read_text(errors="replace")
    return [tok for tok in FORBIDDEN if tok in text]


def compiles(path: pathlib.Path, python: str) -> bool:
    return subprocess.run(
        [python, "-m", "py_compile", str(path)],
        capture_output=True,
    ).returncode == 0


def promotions(suite: str) -> dict[str, list[dict]]:
    """Map task -> list of completed ledger entries, in file order.

    The ledger is append-only with ONE entry per promotion, written at `finish`.
    A `verify` run does not append; it recomputes the gate and reports, so a
    completed entry here is a claim that this audit re-checks via `--verify`.
    """
    ledger = REPO / "outputs" / "libero_fix_loop" / suite / "skill_promotions.jsonl"
    out: dict[str, list[dict]] = {}
    if not ledger.is_file():
        return out
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("completed_at"):
            continue
        out.setdefault(entry.get("task") or "", []).append(entry)
    return out


def promotion_summary(suite: str, task: str) -> tuple[str, str]:
    """Return (status, detail) for `task` from the completed ledger entries."""
    entries = promotions(suite).get(task, [])
    if not entries:
        return "MISSING", "**no completed promotion in the ledger**"
    e = entries[-1]
    pid = e.get("promotion_id", "?")
    if e.get("no_op"):
        return "NOOP", f"{pid}: no_op=true (reason={e.get('reason', '-')!r})"
    n_skill = len(e.get("changed_skill_files") or [])
    n_know = len(e.get("changed_knowledge_files") or [])
    lib = str(e.get("library_after_sha256") or "")[:8]
    return "OK", f"{pid}: {n_know} knowledge, {n_skill} skill files; library {lib}"


def reverify(suite: str, task: str, python: str) -> bool:
    """Re-run the promotion gate. This is the real check, not the ledger's claim."""
    proc = subprocess.run(
        [python, str(REPO / "scripts" / "libero" / "record_skill_promotion.py"),
         "verify", "--suite", suite, "--task", task],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if proc.returncode == 0:
        return True
    print(f"     verify FAILED: {(proc.stderr or proc.stdout).strip()[:400]}")
    return False


def manifest_status(suite: str, task: str) -> tuple[str, str, str]:
    """Return (status, detail, pass_rate)."""
    base = REPO / "outputs" / "libero_fix_loop_eval" / suite / task / "runs"
    if not base.is_dir():
        return "MISSING", "no eval run directory", "-"
    runs = sorted(p for p in base.iterdir() if p.is_dir())
    if not runs:
        return "MISSING", "no eval run directory", "-"
    note = "" if len(runs) == 1 else f"**{len(runs)} run dirs** (manifest not unique) "
    run = runs[0]
    mpath = run / "manifest.json"
    if not mpath.is_file():
        return "MISSING", note + "no manifest.json", "-"
    m = json.loads(mpath.read_text())
    ident = m.get("identity", {})
    seeds = ident.get("seeds") or []
    problems = []
    if m.get("evidence_scope") != "heldout_full":
        problems.append(f"evidence_scope={m.get('evidence_scope')!r}")
    if list(seeds) != list(range(1, 51)):
        problems.append(f"seeds n={len(seeds)}")
    trials = list(run.glob("results/**/trial_*"))
    passes = [t for t in trials if "reward_1.000" in t.name]
    fails = sorted(t.name.split("trial_")[1].split("_")[0] for t in trials
                   if "reward_1.000" not in t.name)
    rate = f"{len(passes)}/{len(trials)}" if trials else "0/0"
    if not trials:
        problems.append("no trial dirs")
    status = "OK" if not problems else "CHECK"
    detail = note + (", ".join(problems) if problems else "heldout_full, seeds 1-50")
    if fails:
        detail += f"; fail={','.join(fails)}"
    return status, detail, rate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True)
    ap.add_argument("--python", default=str(REPO / ".venv-libero" / "bin" / "python3"))
    ap.add_argument("--verify", action="store_true",
                    help="also re-run the promotion gate for each task (the real check)")
    args = ap.parse_args()

    suite_dir = REPO / "outputs" / "libero_fix_loop" / args.suite
    tasks = sorted(p.name for p in suite_dir.iterdir()
                   if p.is_dir() and p.name.startswith("pick_up_the_"))
    if not tasks:
        print(f"no task directories under {suite_dir}")
        return 1

    print(f"Fix-loop completion audit -- {args.suite} -- {len(tasks)} tasks\n")
    incomplete = 0
    for task in tasks:
        d = suite_dir / task
        fix = d / "fix_code.py"
        findings = d / "findings.md"

        if not fix.is_file():
            fix_s, fix_d = "MISSING", "no fix_code.py"
        else:
            hits = forbidden_hits(fix)
            ok = compiles(fix, args.python)
            fix_s = "OK" if ok and not hits else "CHECK"
            fix_d = ("compiles" if ok else "**does not compile**")
            if hits:
                fix_d += f"; **FORBIDDEN: {', '.join(hits)}**"
            fix_d += f"; md5={subprocess.run(['md5sum', str(fix)], capture_output=True, text=True).stdout.split()[0]}"

        find_s = "OK" if findings.is_file() else "RECORDED-NOOP"
        find_d = (f"{findings.stat().st_size} B" if findings.is_file()
                  else "absent - must have a ledger no-op entry")

        prom_s, prom_d = promotion_summary(args.suite, task)
        if prom_s == "OK" and args.verify:
            if reverify(args.suite, task, args.python):
                prom_d += "  [gate re-verified]"
            else:
                prom_s = "CHECK"

        man_s, man_d, rate = manifest_status(args.suite, task)

        bad = [s for s in (fix_s, prom_s, man_s) if s in ("MISSING", "CHECK")]
        if not findings.is_file():
            bad.append("findings")
        if bad:
            incomplete += 1
        flag = "  " if not bad else "->"
        print(f"{flag} {task}")
        print(f"     fix_code : {fix_s:8} {fix_d}")
        print(f"     findings : {find_s:8} {find_d}")
        print(f"     promotion: {prom_s:8} {prom_d}")
        print(f"     manifest : {man_s:8} {man_d}  held-out pass {rate}")
        print()

    print(f"{len(tasks) - incomplete}/{len(tasks)} tasks complete; {incomplete} flagged.")
    return 0 if incomplete == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
