"""Evidence gate for freezing VerificationSkills."""

from __future__ import annotations

from dataclasses import replace

from .serialization import content_hash
from .verification_evidence import VerificationEvaluation
from .verification_skill import VerificationSkill


def review_verification_skill(
    skill: VerificationSkill,
    evaluations: list[VerificationEvaluation],
    *,
    reviewer: str,
    min_examples: int = 4,
    min_task_families: int = 2,
) -> VerificationSkill:
    if not reviewer.strip():
        raise ValueError("verification review requires a reviewer")
    if len(evaluations) < min_examples:
        raise ValueError("insufficient paired verification evidence")
    if any(item.source != "development" for item in evaluations):
        raise ValueError("held-out evidence cannot promote a verification skill")
    if any(item.change_kind != "verifier_revision" for item in evaluations):
        raise ValueError("task repair is not verifier evidence")
    if len({item.task_family for item in evaluations}) < min_task_families:
        raise ValueError("insufficient task-family diversity")
    if not {item.expected_status for item in evaluations}.issuperset(
        {"positive", "negative", "unknown"}
    ):
        raise ValueError("evidence must cover positive, negative, and unknown cases")
    old_correct = sum(item.old_correct for item in evaluations)
    new_correct = sum(item.new_correct for item in evaluations)
    if new_correct <= old_correct:
        raise ValueError("new verifier does not improve paired correctness")
    if all(item.new_status == "unknown" for item in evaluations):
        raise ValueError("all-unknown verifier cannot be promoted")
    refs = tuple(sorted(item.evidence_ref for item in evaluations))
    return replace(
        skill, status="frozen", development_evidence_refs=refs,
        reviewed_by=reviewer.strip(), candidate_content_hash=skill.content_hash,
        evaluation_content_hash=content_hash(evaluations),
    )
