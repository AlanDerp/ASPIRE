# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic Principle-versus-children compression evidence."""

from __future__ import annotations

from typing import Any

from .models import CanonicalSkill, Principle, model_to_dict
from .repository import KnowledgeRepository
from .serialization import canonical_json, content_hash


def _estimated_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _skill_actor_text(skill: CanonicalSkill) -> str:
    return "\n".join(
        (
            skill.title,
            skill.trigger,
            skill.goal,
            skill.operation_template,
            skill.effect,
        )
    )


def _principle_actor_text(
    proposal: Principle,
    review: dict[str, Any],
) -> str:
    abstraction = review.get("abstraction", {})
    if not isinstance(abstraction, dict):
        raise ValueError("principle compression requires an abstraction object")
    return "\n".join(
        (
            str(review.get("title", proposal.title)),
            str(review.get("summary", proposal.summary)),
            canonical_json(review.get("when", {})),
            str(review.get("decision", "")),
            str(review.get("invariant", "")),
            canonical_json(review.get("expected_effects", [])),
            canonical_json(review.get("exceptions", [])),
            str(abstraction.get("common_core", "")),
            canonical_json(abstraction.get("preserved_variations", [])),
        )
    )


def supporting_skills(
    repository: KnowledgeRepository,
    proposal: Principle,
) -> list[CanonicalSkill]:
    """Load the exact canonical-skill revisions bound by a proposal."""
    versions = proposal.provenance.get("canonical_skill_versions")
    if not isinstance(versions, dict) or set(versions) != set(proposal.child_ids):
        raise ValueError("principle proposal has incomplete canonical-skill bindings")
    available = {
        (skill.id, skill.version): skill for skill in repository.list_skills()
    }
    missing = [
        f"{skill_id}@{versions[skill_id]}"
        for skill_id in sorted(proposal.child_ids)
        if (skill_id, str(versions[skill_id])) not in available
    ]
    if missing:
        raise ValueError(f"principle compression lacks supporting skills: {missing}")
    return [
        available[(skill_id, str(versions[skill_id]))]
        for skill_id in sorted(proposal.child_ids)
    ]


def build_compression_report(
    proposal: Principle,
    review: dict[str, Any],
    skills: list[CanonicalSkill],
) -> dict[str, Any]:
    """Compare the reviewed Principle section with direct child injection."""
    by_id = {skill.id: skill for skill in skills}
    if set(by_id) != set(proposal.child_ids):
        raise ValueError("compression report must cover every child exactly")
    versions = {
        str(key): str(value)
        for key, value in proposal.provenance["canonical_skill_versions"].items()
    }
    if any(by_id[skill_id].version != versions[skill_id] for skill_id in by_id):
        raise ValueError("compression report child revision mismatch")
    direct_tokens = sum(
        _estimated_tokens(_skill_actor_text(by_id[skill_id]))
        for skill_id in sorted(by_id)
    )
    principle_tokens = _estimated_tokens(_principle_actor_text(proposal, review))
    payload = {
        "schema_version": 1,
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "proposal_hash": content_hash(model_to_dict(proposal)),
        "checkpoint_id": proposal.provenance["checkpoint_id"],
        "source_partition": "development",
        "child_versions": versions,
        "child_hashes": {
            skill_id: content_hash(model_to_dict(by_id[skill_id]))
            for skill_id in sorted(by_id)
        },
        "direct_child_tokens": direct_tokens,
        "principle_tokens": principle_tokens,
        "compression_ratio": round(direct_tokens / principle_tokens, 6),
        "passed": principle_tokens < direct_tokens,
    }
    return {**payload, "report_hash": content_hash(payload)}
