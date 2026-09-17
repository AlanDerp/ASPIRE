#!/usr/bin/env python3
"""Aggregate paired verifier results for review without changing a Skill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def evaluate(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("paired evaluation is empty")
    old = sum(bool(row.get("old_correct")) for row in rows)
    new = sum(bool(row.get("new_correct")) for row in rows)
    return {
        "schema_version": 1, "examples": len(rows),
        "task_families": sorted({str(row["task_family"]) for row in rows}),
        "old_accuracy": old / len(rows), "new_accuracy": new / len(rows),
        "accuracy_gain": (new - old) / len(rows),
        "new_unknown_rate": sum(row.get("new_status") == "unknown" for row in rows) / len(rows),
        "development_only": all(row.get("source") == "development" for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evaluations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.evaluations.read_text()))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__": main()
