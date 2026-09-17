#!/usr/bin/env python3
"""Fail-closed checker for a dynamic-FG acceptance campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_CASES = tuple(f"F{index:02d}" for index in range(1, 19))


def audit(manifest: dict, root: Path) -> dict:
    cases = manifest.get("cases", {})
    statuses = {case: str(cases.get(case, {}).get("status", "not_run")) for case in REQUIRED_CASES}
    missing_artifacts = []
    for case, value in cases.items():
        for relative in value.get("artifacts", []):
            if not (root / relative).is_file():
                missing_artifacts.append(f"{case}:{relative}")
    passed = all(value == "passed" for value in statuses.values()) and not missing_artifacts
    return {"schema_version": 1, "passed": passed, "case_statuses": statuses, "missing_artifacts": sorted(missing_artifacts)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.manifest.read_text()), args.root)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__": main()
