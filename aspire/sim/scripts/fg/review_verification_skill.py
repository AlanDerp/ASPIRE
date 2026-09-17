#!/usr/bin/env python3
"""Review and freeze a VerificationSkill from paired development evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aspire.sim.cap.knowledge.verification_evidence import VerificationEvaluation
from aspire.sim.cap.knowledge.verification_review import review_verification_skill
from aspire.sim.cap.knowledge.verification_skill import load_verification_skill, save_verification_skill


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--skill", type=Path, required=True)
    parser.add_argument("--evaluations", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    values = json.loads(args.evaluations.read_text())
    if not isinstance(values, list):
        raise ValueError("evaluations must be a JSON list")
    frozen = review_verification_skill(
        load_verification_skill(args.skill),
        [VerificationEvaluation(**value) for value in values],
        reviewer=args.reviewer,
    )
    path = save_verification_skill(args.root, frozen)
    print(json.dumps({"path": str(path), "content_hash": frozen.content_hash}, sort_keys=True))


if __name__ == "__main__": main()
