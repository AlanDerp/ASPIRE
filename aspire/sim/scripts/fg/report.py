#!/usr/bin/env python3
"""Aggregate FG observations into missing-safe engineering metrics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def report(rows: list[dict]) -> dict:
    statuses = Counter(str(row.get("status", "invalid")) for row in rows)
    known = statuses["known"]
    return {
        "schema_version": 1, "observation_count": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "known_coverage": known / len(rows) if rows else None,
        "unknown_rate": statuses["unknown"] / len(rows) if rows else None,
        "unsupported_rate": statuses["unsupported"] / len(rows) if rows else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.observations.read_text().splitlines() if line.strip()]
    args.output.write_text(json.dumps(report(rows), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__": main()
