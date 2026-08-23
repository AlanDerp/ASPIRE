# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Explicit review and promotion gates for principle revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .compression import build_compression_report, supporting_skills
from .counterexample import validate_counterexample_dispositions
from .models import (
    Principle,
    PrincipleAbstraction,
    PrincipleQualityPolicy,
    Scope,
    model_to_dict,
    validate_version,
)
from .repository import KnowledgeRepository
from .review_artifacts import finalize_leave_family_out_report
from .serialization import content_hash


def _newer(candidate: str, previous: str) -> str:
    validate_version(candidate)
    left = tuple(int(part) for part in candidate.split("."))
    right = tuple(int(part) for part in previous.split("."))
    if left <= right:
        raise ValueError(f"new revision {candidate} must be newer than {previous}")
    return candidate


def validate_principle_review_content(review: dict[str, Any]) -> None:
    """Validate human-authored review fields before persisting derived evidence."""
    expected_effects = review.get("expected_effects")
    if (
        not isinstance(expected_effects, list)
        or not expected_effects
        or any(
            not isinstance(effect, str) or not effect.strip()
            for effect in expected_effects
        )
    ):
        raise ValueError(
            "principle review requires observable expected effects"
        )
    exceptions = review.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ValueError("principle review exceptions must be a list")
    if any(
        not isinstance(exception, dict)
        or not exception.get("id")
        or not isinstance(exception.get("when"), dict)
        or not exception["when"]
        or not isinstance(exception.get("response"), str)
        or not str(exception["response"]).strip()
        for exception in exceptions
    ):
        raise ValueError(
            "reviewed principle exceptions require id, when, and response"
        )


def review_principle(
    proposal: Principle,
    review: dict[str, Any],
    *,
    version: str,
) -> Principle:
    validate_principle_review_content(review)
    if proposal.status != "proposal" or not proposal.review_required:
        raise ValueError("only a review-required proposal can enter principle review")
    required = (
        "reviewer",
        "reviewed_at",
        "when",
        "decision",
        "invariant",
        "expected_effects",
        "falsifiers",
        "abstraction",
        "quality_policy",
        "counterexample_report",
        "counterexample_report_hash",
        "counterexample_artifact_hash",
        "leave_one_family_out_report",
        "leave_one_family_out_report_hash",
        "leave_one_family_out_artifact_hash",
        "compression_report",
        "compression_report_hash",
        "compression_artifact_hash",
    )
    missing = [key for key in required if not review.get(key)]
    if missing:
        raise ValueError(f"principle review is incomplete: {missing}")
    exceptions = tuple(review.get("exceptions", []))
    exception_review = str(review.get("exception_review", "")).strip()
    if not exceptions and not exception_review:
        raise ValueError("review must record exceptions or an explicit empty-exception review")
    normalized_review = bind_principle_review(proposal, review)
    quality_policy = PrincipleQualityPolicy.from_dict(
        normalized_review.get("quality_policy")
    )
    if (
        quality_policy.min_supporting_skills
        < proposal.quality_policy.min_supporting_skills
        or quality_policy.min_task_families
        < proposal.quality_policy.min_task_families
        or quality_policy.max_exception_rate
        > proposal.quality_policy.max_exception_rate
        or quality_policy.max_operational_fanout
        > proposal.quality_policy.max_operational_fanout
    ):
        raise ValueError("principle review cannot weaken its quality policy")
    review_hash = content_hash(normalized_review)
    return replace(
        proposal,
        version=_newer(version, proposal.version),
        title=str(normalized_review.get("title", proposal.title)),
        summary=str(normalized_review.get("summary", proposal.summary)),
        when=dict(normalized_review["when"]),
        decision_mode=normalized_review.get("decision_mode", proposal.decision_mode),
        decision=str(normalized_review["decision"]),
        invariant=str(normalized_review["invariant"]),
        expected_effects=tuple(
            str(value) for value in normalized_review.get("expected_effects", [])
        ),
        exceptions=tuple(normalized_review.get("exceptions", [])),
        exception_review=exception_review,
        falsifiers=tuple(str(value) for value in normalized_review["falsifiers"]),
        abstraction=PrincipleAbstraction.from_dict(
            normalized_review.get("abstraction")
        ),
        quality_policy=quality_policy,
        scope=(
            Scope.from_dict(normalized_review.get("scope"))
            if normalized_review.get("scope")
            else proposal.scope
        ),
        status="candidate",
        review_required=False,
        provenance={
            **proposal.provenance,
            "reviewer": str(normalized_review["reviewer"]),
            "reviewed_at": str(normalized_review["reviewed_at"]),
            "proposal_version": proposal.version,
            "proposal_hash": content_hash(model_to_dict(proposal)),
            "review_artifact": f"proposals/principle-review/{review_hash}.yaml",
            "review_artifact_hash": review_hash,
            "counterexample_report": str(normalized_review["counterexample_report"]),
            "counterexample_report_hash": str(
                normalized_review["counterexample_report_hash"]
            ),
            "counterexample_artifact_hash": str(
                normalized_review["counterexample_artifact_hash"]
            ),
            "counterexample_dispositions": normalized_review.get(
                "counterexample_dispositions", {}
            ),
            "leave_one_family_out_report": str(
                normalized_review["leave_one_family_out_report"]
            ),
            "leave_one_family_out_report_hash": str(
                normalized_review["leave_one_family_out_report_hash"]
            ),
            "leave_one_family_out_artifact_hash": str(
                normalized_review["leave_one_family_out_artifact_hash"]
            ),
            "compression_report": str(normalized_review["compression_report"]),
            "compression_report_hash": str(
                normalized_review["compression_report_hash"]
            ),
            "compression_artifact_hash": str(
                normalized_review["compression_artifact_hash"]
            ),
        },
    )


def promote_principle(candidate: Principle, *, version: str) -> Principle:
    if candidate.status != "candidate" or candidate.review_required:
        raise ValueError("only a reviewed candidate can be promoted")
    if len(set(candidate.child_ids)) < candidate.quality_policy.min_supporting_skills:
        raise ValueError("principle candidate does not meet its support policy")
    if (
        len(set(candidate.scope.task_families))
        < candidate.quality_policy.min_task_families
    ):
        raise ValueError("principle candidate does not meet its family policy")
    return replace(
        candidate,
        version=_newer(version, candidate.version),
        status="validated",
        provenance={
            **candidate.provenance,
            "candidate_version": candidate.version,
            "candidate_hash": content_hash(model_to_dict(candidate)),
        },
    )


def bind_principle_review(
    proposal: Principle, review: dict[str, Any]
) -> dict[str, Any]:
    """Add immutable proposal identity to a normalized review artifact."""
    expected = {
        "proposal_id": proposal.id,
        "proposal_version": proposal.version,
        "proposal_hash": content_hash(model_to_dict(proposal)),
        "checkpoint_id": proposal.provenance["checkpoint_id"],
    }
    mismatches = [
        key
        for key, value in expected.items()
        if key in review and review.get(key) != value
    ]
    if mismatches:
        raise ValueError(f"principle review proposal binding mismatch: {mismatches}")
    return {**review, **expected}


def _rebuild_principle_candidate(
    repository: KnowledgeRepository,
    principle: Principle,
    *,
    candidate_version: str,
    revisions: list[Principle] | None = None,
) -> tuple[Principle, list[Principle]]:
    """Rebuild one reviewed candidate from its immutable evidence."""
    values = revisions if revisions is not None else repository.list_principles()
    proposal_version = str(principle.provenance["proposal_version"])
    proposal_hash = str(principle.provenance["proposal_hash"])
    proposals = [
        value
        for value in values
        if value.id == principle.id
        and value.version == proposal_version
        and value.status == "proposal"
        and content_hash(model_to_dict(value)) == proposal_hash
    ]
    if len(proposals) != 1:
        raise ValueError("principle evidence does not identify exactly one proposal")
    proposal = proposals[0]

    review_hash = str(principle.provenance["review_artifact_hash"])
    if principle.provenance.get("review_artifact") != (
        f"proposals/principle-review/{review_hash}.yaml"
    ):
        raise ValueError("principle review path is not content-addressed")
    review = repository.load_audit("principle-review", review_hash)

    counterexample_hash = str(principle.provenance["counterexample_artifact_hash"])
    if principle.provenance.get("counterexample_report") != (
        f"proposals/principle-counterexample/{counterexample_hash}.yaml"
    ):
        raise ValueError("principle counterexample path is not content-addressed")
    counterexample = repository.load_audit(
        "principle-counterexample", counterexample_hash
    )
    counterexample_unsigned = {
        key: value for key, value in counterexample.items() if key != "report_hash"
    }
    if (
        counterexample.get("report_hash") != content_hash(counterexample_unsigned)
        or counterexample.get("report_hash")
        != principle.provenance.get("counterexample_report_hash")
    ):
        raise ValueError("principle counterexample report hash mismatch")
    counterexample_expected = {
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "checkpoint_id": proposal.provenance.get("checkpoint_id"),
        "source_partition": "development",
    }
    if any(
        counterexample.get(field) != value
        for field, value in counterexample_expected.items()
    ):
        raise ValueError("principle counterexample provenance mismatch")
    scope = counterexample.get("search_scope", {})
    searched = (
        "searched_failure_outcomes",
        "searched_hidden_constants",
        "searched_forbidden_actions",
        "searched_existing_conflicts",
    )
    if not isinstance(scope, dict) or any(
        scope.get(field) is not True for field in searched
    ):
        raise ValueError("principle counterexample search scope is incomplete")

    validate_counterexample_dispositions(
        counterexample,
        review.get("counterexample_dispositions", {}),
    )

    lofo_hash = str(principle.provenance["leave_one_family_out_artifact_hash"])
    if principle.provenance.get("leave_one_family_out_report") != (
        f"proposals/principle-lofo/{lofo_hash}.yaml"
    ):
        raise ValueError("principle LOFO path is not content-addressed")
    lofo = repository.load_audit("principle-lofo", lofo_hash)
    lofo_unsigned = {key: value for key, value in lofo.items() if key != "report_hash"}
    if (
        lofo.get("report_hash") != content_hash(lofo_unsigned)
        or lofo.get("report_hash")
        != principle.provenance.get("leave_one_family_out_report_hash")
    ):
        raise ValueError("principle LOFO report hash mismatch")
    if finalize_leave_family_out_report(proposal, lofo) != lofo:
        raise ValueError("principle LOFO report is not canonical")

    compression_hash = str(principle.provenance["compression_artifact_hash"])
    if principle.provenance.get("compression_report") != (
        f"proposals/principle-compression/{compression_hash}.yaml"
    ):
        raise ValueError("principle compression path is not content-addressed")
    compression = repository.load_audit(
        "principle-compression",
        compression_hash,
    )
    expected_compression = build_compression_report(
        proposal,
        review,
        supporting_skills(repository, proposal),
    )
    if (
        compression != expected_compression
        or compression.get("passed") is not True
        or compression.get("report_hash")
        != principle.provenance.get("compression_report_hash")
    ):
        raise ValueError("principle compression evidence mismatch")

    expected_candidate = review_principle(
        proposal,
        review,
        version=candidate_version,
    )
    return expected_candidate, values


def validate_principle_candidate_evidence(
    repository: KnowledgeRepository,
    candidate: Principle,
    *,
    revisions: list[Principle] | None = None,
) -> None:
    """Reject a candidate that cannot be replayed from its stored review."""
    if candidate.status != "candidate":
        raise ValueError("principle evidence target is not a candidate")
    expected, _ = _rebuild_principle_candidate(
        repository,
        candidate,
        candidate_version=candidate.version,
        revisions=revisions,
    )
    if content_hash(model_to_dict(expected)) != content_hash(
        model_to_dict(candidate)
    ):
        raise ValueError("principle candidate differs from its review artifact")


def validate_principle_evidence(
    repository: KnowledgeRepository,
    principle: Principle,
    *,
    revisions: list[Principle] | None = None,
) -> None:
    """Rebuild proposal → review → candidate → validated principle exactly."""
    if principle.status not in {"validated", "stable"}:
        raise ValueError("principle evidence target is not promoted")
    candidate_version = str(principle.provenance["candidate_version"])
    expected_candidate, values = _rebuild_principle_candidate(
        repository,
        principle,
        candidate_version=candidate_version,
        revisions=revisions,
    )
    candidate_hash = content_hash(model_to_dict(expected_candidate))
    if candidate_hash != principle.provenance.get("candidate_hash"):
        raise ValueError("principle candidate hash mismatch")
    candidates = [
        value
        for value in values
        if value.id == principle.id
        and value.version == candidate_version
        and value.status == "candidate"
        and content_hash(model_to_dict(value)) == candidate_hash
    ]
    if len(candidates) != 1:
        raise ValueError("principle evidence lacks its exact reviewed candidate")
    expected_validated = promote_principle(
        expected_candidate,
        version=principle.version,
    )
    if content_hash(model_to_dict(expected_validated)) != content_hash(
        model_to_dict(principle)
    ):
        raise ValueError("validated principle differs from its reviewed candidate")
