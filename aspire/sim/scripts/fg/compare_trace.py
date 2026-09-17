#!/usr/bin/env python3
"""Summarize private FG comparison JSONL without exposing audit values."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    alignments = Counter(str(row.get("alignment", "invalid")) for row in rows)
    comparable = sum(bool(row.get("comparable")) for row in rows)
    return {
        "schema_version": 1, "total": len(rows), "comparable": comparable,
        "alignment_counts": dict(sorted(alignments.items())),
        "match_rate": (alignments["match"] / comparable) if comparable else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("comparisons", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.comparisons), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__": main()
