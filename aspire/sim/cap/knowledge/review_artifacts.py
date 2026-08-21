# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Hash-checked human review artifacts required before principle promotion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Principle
from .serialization import content_hash, load_structured


def finalize_leave_family_out_report(
    proposal: Principle,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Validate reviewer coverage and create an immutable LOFO report payload."""
    required = ("reviewer", "reviewed_at", "family_results")
    missing = [key for key in required if not review.get(key)]
    if missing:
        raise ValueError(f"leave-family-out report is incomplete: {missing}")
    family_results = review["family_results"]
    if not isinstance(family_results, dict):
        raise ValueError("leave-family-out family_results must be an object")
    expected_families = set(proposal.scope.task_families)
    if set(family_results) != expected_families:
        raise ValueError(
            "leave-family-out report must cover exactly the principle task families"
        )
    normalized_results: dict[str, Any] = {}
    for family in sorted(expected_families):
        result = family_results[family]
        if not isinstance(result, dict):
            raise ValueError(f"leave-family-out result must be an object: {family}")
        task_ids = result.get("evaluated_task_ids", [])
        supporting_skills = result.get("supporting_skill_ids", [])
        if not isinstance(task_ids, list) or not task_ids:
            raise ValueError(f"leave-family-out result lacks evaluated tasks: {family}")
        if not isinstance(supporting_skills, list) or not supporting_skills:
            raise ValueError(f"leave-family-out result lacks grounding skills: {family}")
        if result.get("passed") is not True:
            raise ValueError(f"leave-family-out validation did not pass: {family}")
        normalized_results[family] = {
            "passed": True,
            "evaluated_task_ids": sorted({str(value) for value in task_ids}),
            "supporting_skill_ids": sorted({str(value) for value in supporting_skills}),
            "notes": str(result.get("notes", "")),
        }
    payload = {
        "schema_version": 1,
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "checkpoint_id": proposal.provenance.get("checkpoint_id"),
        "source_partition": "development",
        "reviewer": str(review["reviewer"]),
        "reviewed_at": str(review["reviewed_at"]),
        "family_results": normalized_results,
        "passed": True,
    }
    return {**payload, "report_hash": content_hash(payload)}


def validate_leave_family_out_report(
    path: Path,
    proposal: Principle,
) -> dict[str, Any]:
    report = load_structured(path)
    report_hash = str(report.get("report_hash", ""))
    payload = {key: value for key, value in report.items() if key != "report_hash"}
    if content_hash(payload) != report_hash:
        raise ValueError("leave-family-out report hash mismatch")
    expected = {
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "checkpoint_id": proposal.provenance.get("checkpoint_id"),
        "source_partition": "development",
        "passed": True,
    }
    mismatches = {
        key: {"expected": value, "found": report.get(key)}
        for key, value in expected.items()
        if report.get(key) != value
    }
    if mismatches:
        raise ValueError(f"leave-family-out report provenance mismatch: {mismatches}")
    finalized = finalize_leave_family_out_report(proposal, report)
    if finalized["report_hash"] != report_hash:
        raise ValueError("leave-family-out report is not in canonical form")
    return report
