# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Explicit review and promotion gates for principle revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import Principle, Scope, validate_version


def _newer(candidate: str, previous: str) -> str:
    validate_version(candidate)
    left = tuple(int(part) for part in candidate.split("."))
    right = tuple(int(part) for part in previous.split("."))
    if left <= right:
        raise ValueError(f"new revision {candidate} must be newer than {previous}")
    return candidate


def review_principle(
    proposal: Principle,
    review: dict[str, Any],
    *,
    version: str,
) -> Principle:
    if proposal.status != "proposal" or not proposal.review_required:
        raise ValueError("only a review-required proposal can enter principle review")
    required = (
        "reviewer",
        "reviewed_at",
        "when",
        "decision",
        "invariant",
        "falsifiers",
        "counterexample_report",
        "counterexample_report_hash",
        "leave_one_family_out_report",
        "leave_one_family_out_report_hash",
    )
    missing = [key for key in required if not review.get(key)]
    if missing:
        raise ValueError(f"principle review is incomplete: {missing}")
    exceptions = tuple(review.get("exceptions", []))
    exception_review = str(review.get("exception_review", "")).strip()
    if not exceptions and not exception_review:
        raise ValueError("review must record exceptions or an explicit empty-exception review")
    return replace(
        proposal,
        version=_newer(version, proposal.version),
        title=str(review.get("title", proposal.title)),
        summary=str(review.get("summary", proposal.summary)),
        when=dict(review["when"]),
        decision_mode=review.get("decision_mode", proposal.decision_mode),
        decision=str(review["decision"]),
        invariant=str(review["invariant"]),
        expected_effects=tuple(str(value) for value in review.get("expected_effects", [])),
        exceptions=exceptions,
        exception_review=exception_review,
        falsifiers=tuple(str(value) for value in review["falsifiers"]),
        scope=Scope.from_dict(review.get("scope")) if review.get("scope") else proposal.scope,
        status="candidate",
        review_required=False,
        provenance={
            **proposal.provenance,
            "reviewer": str(review["reviewer"]),
            "reviewed_at": str(review["reviewed_at"]),
            "counterexample_report": str(review["counterexample_report"]),
            "counterexample_report_hash": str(review["counterexample_report_hash"]),
            "counterexample_dispositions": review.get(
                "counterexample_dispositions", {}
            ),
            "leave_one_family_out_report": str(review["leave_one_family_out_report"]),
            "leave_one_family_out_report_hash": str(
                review["leave_one_family_out_report_hash"]
            ),
        },
    )


def promote_principle(candidate: Principle, *, version: str) -> Principle:
    if candidate.status != "candidate" or candidate.review_required:
        raise ValueError("only a reviewed candidate can be promoted")
    return replace(candidate, version=_newer(version, candidate.version), status="validated")
