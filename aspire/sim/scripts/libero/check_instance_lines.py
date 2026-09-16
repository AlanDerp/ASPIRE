#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate skill-code-instance line ranges *before* ingesting them.

`aspire.sim.cap.knowledge instance ingest --lines START:END` takes a **1-based
inclusive** range and parses the extracted slice as Python. A range that starts
or ends mid-block produces an extraction that is not valid Python, and the
ingest is rejected with a bare `ast.parse` error whose message does not say
which range failed. When several instances are ingested in one promotion that is
easy to misattribute.

This script takes every candidate range up front, reports the exact syntax error
for each, and prints the first and last extracted line so the range can be
checked by eye against the intended symbol. Use it from the coordinator loop:

    .venv/bin/python3 scripts/libero/check_instance_lines.py \
        outputs/working_codes/<file>.py 60:82 101:110 224:258 261:275

Exit status is non-zero if any range fails to parse.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def check(path: Path, spec: str) -> tuple[bool, str]:
    """Parse the 1-based inclusive START:END slice of `path`; return (ok, report)."""
    try:
        start_text, end_text = spec.split(":", 1)
        start, end = int(start_text), int(end_text)
    except ValueError:
        return False, f"{spec}: not a START:END range"
    if start < 1 or end < start:
        return False, f"{spec}: empty or inverted range"

    lines = path.read_text().splitlines()
    if end > len(lines):
        return False, f"{spec}: file has only {len(lines)} lines"
    chunk = "\n".join(lines[start - 1:end]) + "\n"

    head = lines[start - 1].rstrip()
    tail = lines[end - 1].rstrip()
    span = f"{spec}  first={head[:64]!r}  last={tail[:64]!r}"
    try:
        ast.parse(chunk)
    except SyntaxError as exc:
        return False, f"{span}\n    REJECTED: {type(exc).__name__}: {exc.msg} (line {exc.lineno} of slice)"
    return True, span


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path, help="executed fix_code.py / working code file")
    parser.add_argument("ranges", nargs="+", metavar="START:END",
                        help="1-based inclusive line ranges to validate")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"no such file: {args.file}", file=sys.stderr)
        return 2

    failed = 0
    for spec in args.ranges:
        ok, report = check(args.file, spec)
        print(("OK   " if ok else "FAIL ") + report)
        failed += 0 if ok else 1
    print(f"\n{len(args.ranges) - failed}/{len(args.ranges)} ranges parse")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
