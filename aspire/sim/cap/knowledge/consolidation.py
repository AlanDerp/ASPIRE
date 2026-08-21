# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Create reviewable canonical-skill and principle proposals."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from .fingerprint import text_tokens
from .models import (
    CanonicalSkill,
    Checkpoint,
    ConsolidationPolicy,
    Principle,
    Scope,
    SkillCodeInstance,
)
from .repetition import (
    RepetitionCluster,
    RepetitionReport,
    audit_principle_repetition,
    audit_repetition,
)


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or fallback


def _common_tokens(values: list[str]) -> list[str]:
    if not values:
        return []
    common = text_tokens(values[0])
    for value in values[1:]:
        common &= text_tokens(value)
    return sorted(common - {"a", "an", "and", "the", "to", "of", "in"})


def canonicalize_cluster(
    cluster: RepetitionCluster,
    instances: list[SkillCodeInstance],
    checkpoint: Checkpoint,
    policy: ConsolidationPolicy,
    report: RepetitionReport,
    review: dict[str, Any],
) -> CanonicalSkill:
    recomputed = audit_repetition(instances, checkpoint, policy)
    if report.content_hash != recomputed.content_hash:
        raise ValueError("instance repetition report does not match checkpoint and policy")
    audited_cluster = next(
        (value for value in recomputed.clusters if value.id == cluster.id),
        None,
    )
    if audited_cluster != cluster:
        raise ValueError("canonical skill cluster does not match the repetition report")
    if not cluster.accepted:
        raise ValueError(f"cluster is not eligible for canonicalization: {cluster.rejection_reasons}")
    required_review = ("reviewer", "reviewed_at", "rationale")
    missing_review = [key for key in required_review if not review.get(key)]
    if missing_review:
        raise ValueError(f"canonical cluster review is incomplete: {missing_review}")
    if review.get("cluster_id") != cluster.id:
        raise ValueError("canonical cluster review targets a different cluster")
    if review.get("decision") != "accept":
        raise ValueError("canonicalization requires an explicit accept decision")
    if review.get("pair_assessments_reviewed") is not True:
        raise ValueError("canonicalization requires review of pair assessments")
    by_id = {value.id: value for value in instances}
    group = [by_id[value] for value in cluster.instance_ids]
    missing = sorted(set(cluster.instance_ids) - set(by_id))
    if missing:
        raise ValueError(f"cluster instances are missing: {missing}")
    if len({value.vertical_capability for value in group}) != 1:
        raise ValueError("canonical skill cluster crosses vertical capabilities")

    common_calls = set(group[0].api_calls)
    for value in group[1:]:
        common_calls &= set(value.api_calls)
    goals = [value.goal for value in group]
    goal_tokens = _common_tokens(goals)
    fallback_name = Counter(
        call.rsplit(".", 1)[-1] for value in group for call in value.api_calls
    ).most_common(1)
    label = "-".join(goal_tokens[:6]) or (fallback_name[0][0] if fallback_name else "repeated-skill")
    vertical = group[0].vertical_capability
    task_families = sorted({value.task_family for value in group})
    return CanonicalSkill(
        id=f"skill.{vertical}.{_slug(label, 'repeated-skill')}",
        version="1.0.0",
        vertical_capability=vertical,
        title=" ".join(goal_tokens[:8]).title() or label.replace("-", " ").title(),
        goal=min(goals, key=lambda value: (len(value), value)),
        trigger=min((value.trigger for value in group if value.trigger), key=len, default=""),
        operation_template=" -> ".join(sorted(common_calls)),
        effect=min(
            (value.observed_effect for value in group if value.observed_effect),
            key=len,
            default="",
        ),
        instance_ids=tuple(sorted(cluster.instance_ids)),
        api_calls=tuple(sorted(common_calls)),
        variable_parameters=tuple(
            sorted(set(call for value in group for call in value.api_calls) - common_calls)
        ),
        scope=Scope(task_families=tuple(task_families)),
        provenance={
            "checkpoint_id": checkpoint.id,
            "repetition_cluster_id": cluster.id,
            "instance_repetition_report_hash": report.content_hash,
            "cluster_review": {
                "cluster_id": cluster.id,
                "decision": "accept",
                "reviewer": str(review["reviewer"]),
                "reviewed_at": str(review["reviewed_at"]),
                "rationale": str(review["rationale"]),
                "pair_assessments_reviewed": True,
            },
            "task_count": cluster.task_count,
        },
    )


def propose_principle(
    skills: list[CanonicalSkill],
    checkpoint: Checkpoint,
    policy: ConsolidationPolicy,
) -> Principle:
    audit = audit_principle_repetition(skills, checkpoint, policy)
    if not audit.accepted:
        raise ValueError(
            "canonical-skill repetition audit rejected principle proposal: "
            + "; ".join(audit.rejection_reasons)
        )
    skills_by_id = {value.id: value for value in skills}
    skills = [skills_by_id[skill_id] for skill_id in audit.skill_ids]
    verticals = {value.vertical_capability for value in skills}
    families = {family for value in skills for family in value.scope.task_families}
    common = _common_tokens([value.goal + " " + value.effect for value in skills])
    vertical = next(iter(verticals))
    label = "-".join(common[:6]) or f"{vertical}-shared-invariant"
    # Proposals are deliberately incomplete. A reviewer must replace these
    # markers, add exceptions/falsifiers, and clear review_required before a
    # principle can become validated or actor-visible.
    return Principle(
        id=f"principle.{vertical}.{_slug(label, 'shared-invariant')}",
        version="1.0.0",
        vertical_capability=vertical,
        title=(" ".join(common[:8]).title() or f"{vertical.title()} shared invariant"),
        summary="Drafted from repeated canonical skills; human contrastive review required.",
        when={"review_required": True},
        decision_mode="prefer",
        decision="[review required: state the reusable decision rule]",
        invariant="[review required: state the common invariant]",
        expected_effects=(),
        exceptions=(),
        falsifiers=(),
        child_ids=tuple(sorted(value.id for value in skills)),
        exception_review="",
        scope=Scope(task_families=tuple(sorted(families))),
        status="proposal",
        review_required=True,
        provenance={
            "checkpoint_id": checkpoint.id,
            "proposal_method": "canonical-skill-repetition-audit",
            "canonical_repetition_audit": asdict(audit),
            "canonical_repetition_audit_hash": audit.content_hash,
            "canonical_skill_versions": audit.skill_versions,
        },
    )
