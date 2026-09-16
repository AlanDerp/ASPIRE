#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Re-verify that recorded skill-code instances really came from their claimed source.

The knowledge store's provenance guarantee is that an instance's `code` is the
*exact executed text*, bound to the file by `source_code_path` / `source_code_sha256`.
Nothing re-checks that after ingest, so a copied-then-edited snippet or a source file
that has since changed would go unnoticed.

For each instance this script checks:
  1. `code` appears **verbatim** in the file at `source_code_path`;
  2. the file's current sha256 equals `source_code_sha256`;
  3. `code_hash` equals sha256(code);
  4. `ast_fingerprint` is present (the parseability fingerprint recorded at ingest).

Use it after a promotion, or across the whole store before freezing a checkpoint:

    .venv/bin/python3 scripts/libero/verify_instance_provenance.py            # store-wide
    .venv/bin/python3 scripts/libero/verify_instance_provenance.py --task X   # one task

Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "knowledge" / "skill-code-instances"

# Reuse the store's own fingerprint function rather than re-deriving it: `code_hash` is
# sha256 of the *normalized* code (`code.strip() + "\n"`), not of the raw string, and the
# ast_fingerprint is a hash of the AST shape. Importing the real implementation keeps this
# check honest if the normalization ever changes.
sys.path.insert(0, str(REPO))
from aspire.sim.cap.knowledge.fingerprint import fingerprint_code  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(path: Path) -> list[str]:
    """Return a list of failure descriptions for one instance file (empty == clean)."""
    record = json.loads(path.read_text())
    name = record.get("id", path.stem)
    failures: list[str] = []

    code = record.get("code", "")
    if not code:
        failures.append("no `code` recorded")
    else:
        try:
            expected = fingerprint_code(code)
        except ValueError as exc:
            failures.append(f"code is not parseable: {exc}")
        else:
            if record.get("code_hash") != expected.code_hash:
                failures.append("code_hash does not match the normalized-code hash")
            if record.get("ast_fingerprint") != expected.ast_fingerprint:
                failures.append("ast_fingerprint does not match the code's AST shape")
    if not record.get("ast_fingerprint"):
        failures.append("no ast_fingerprint recorded")

    source_rel = record.get("source_code_path", "")
    if not source_rel:
        failures.append("no source_code_path")
        return failures

    # source_code_path is relative to the workspace root as invoked, so try both the
    # repo root and the aspire/sim root before giving up.
    candidates = [REPO / source_rel, REPO / "aspire" / "sim" / source_rel]
    source = next((c for c in candidates if c.is_file()), None)
    if source is None:
        failures.append(f"source file not found: {source_rel}")
        return failures

    text = source.read_text()
    if code not in text:
        failures.append("`code` is NOT verbatim in the source file")
    recorded = record.get("source_code_sha256")
    if recorded and recorded != sha256_file(source):
        failures.append("source_code_sha256 does not match the file on disk")

    return [f"{name}: {f}" for f in failures]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", help="only check instances for this task")
    args = parser.parse_args()

    if not STORE.is_dir():
        print(f"no instance store at {STORE}", file=sys.stderr)
        return 2

    files = sorted(STORE.rglob("*.yaml"))
    checked = failures = 0
    for path in files:
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"UNREADABLE {path.name}: {exc}")
            failures += 1
            continue
        if args.task and record.get("task") != args.task:
            continue
        checked += 1
        for line in check(path):
            print("FAIL " + line)
            failures += 1

    scope = f"task {args.task}" if args.task else "whole store"
    print(f"\n{checked} instance(s) checked in {scope}; {failures} failure(s)")
    if failures == 0 and checked:
        # per-task coverage summary is the useful sanity signal for a promotion
        by_task: dict[str, int] = {}
        for path in files:
            record = json.loads(path.read_text())
            if args.task and record.get("task") != args.task:
                continue
            by_task[record.get("task", "?")] = by_task.get(record.get("task", "?"), 0) + 1
        for task, count in sorted(by_task.items()):
            print(f"  {count:3d}  {task}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
