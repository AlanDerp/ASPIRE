# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Support metrics and append-only invalidation propagation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from .forest import descendants, lineage
from .models import ImpactReport, Principle, PrincipleMetrics
from .repository import KnowledgeRepository
from .retrieval import resolve_view


def invalidated_refs(repository: KnowledgeRepository) -> set[str]:
    return {
        str(event["subject"])
        for event in repository.iter_evidence("lifecycle")
        if event.get("event") == "knowledge.invalidated" and event.get("subject")
    }


SupportState = Literal["sufficient", "weak", "broken"]


def _support_state(count: int, families: int, fanout: int) -> SupportState:
    if count == 0 or fanout == 0:
        return "broken"
    if count < 3 or families < 2:
        return "weak"
    return "sufficient"


def principle_metrics(
    repository: KnowledgeRepository,
    principle: Principle,
    *,
    invalidated: set[str] | None = None,
) -> PrincipleMetrics:
    invalidated = invalidated if invalidated is not None else invalidated_refs(repository)
    skills, _, trees, _ = resolve_view(repository, None)
    instances = {value.id: value for value in repository.list_instances()}
    supporting_skill_ids: set[str] = set()
    depths: list[int] = []
    for tree in trees.values():
        if principle.id not in tree.parent_by_child and principle.id not in tree.parent_by_child.values():
            continue
        depths.append(len(lineage(tree, principle.id)) - 1)
        supporting_skill_ids.update(
            node_id for node_id in descendants(tree, principle.id) if node_id in skills
        )
    if not supporting_skill_ids:
        supporting_skill_ids = {child for child in principle.child_ids if child in skills}

    active_instances = {
        instance_id
        for skill_id in supporting_skill_ids
        if skill_id not in invalidated
        for instance_id in skills[skill_id].instance_ids
        if instance_id in instances and instance_id not in invalidated
    }
    families = {instances[instance_id].task_family for instance_id in active_instances}
    diversity_signatures = {
        (
            instances[instance_id].task_family,
            str(instances[instance_id].provenance.get("failure_signature", "unknown")),
            str(instances[instance_id].provenance.get("scene_signature", "unknown")),
            instances[instance_id].ast_fingerprint,
        )
        for instance_id in active_instances
    }
    events = list(repository.iter_evidence("lifecycle"))
    contradictions = sum(
        event.get("event") == "knowledge.contradicted" and event.get("subject") == principle.id
        for event in events
    )
    exceptions = sum(
        event.get("event") == "knowledge.exception-observed"
        and event.get("subject") == principle.id
        for event in events
    )
    validations = [
        str(event.get("at"))
        for event in events
        if event.get("event") == "knowledge.validated"
        and event.get("subject") == principle.id
        and event.get("at")
    ]
    total_descendants = len(supporting_skill_ids)
    active_skills = sum(skill_id not in invalidated for skill_id in supporting_skill_ids)
    support_count = len(active_instances)
    actor_nodes = 1 + active_skills
    return PrincipleMetrics(
        principle_id=principle.id,
        principle_version=principle.version,
        support_count=support_count,
        support_task_families=len(families),
        support_diversity=(len(diversity_signatures) / support_count if support_count else 0.0),
        contradiction_count=contradictions,
        exception_rate=(exceptions / (support_count + exceptions) if support_count + exceptions else 0.0),
        operational_fanout=active_skills,
        abstraction_depth=max(depths, default=0),
        canonical_skill_coverage=(active_skills / total_descendants if total_descendants else 0.0),
        compression_ratio=(support_count / actor_nodes if actor_nodes else 0.0),
        last_validated_at=max(validations, default=None),
        support_sufficiency=_support_state(support_count, len(families), active_skills),
    )


def impact_report(repository: KnowledgeRepository, ref: str) -> ImpactReport:
    skills, principles, trees, _ = resolve_view(repository, None)
    instances = {value.id: value for value in repository.list_instances()}
    if ref not in instances and ref not in skills and ref not in principles:
        raise ValueError(f"knowledge reference not found: {ref}")

    affected_skills = {
        skill.id
        for skill in skills.values()
        if skill.id == ref or ref in skill.instance_ids
    }
    affected_principles = {ref} if ref in principles else set()
    for principle in principles.values():
        if affected_skills & set(principle.child_ids):
            affected_principles.add(principle.id)
        for tree in trees.values():
            if principle.id in tree.parent_by_child or principle.id in tree.parent_by_child.values():
                if affected_skills & set(descendants(tree, principle.id)):
                    affected_principles.add(principle.id)

    instance_ids = {ref} if ref in instances else set()
    for skill_id in affected_skills:
        instance_ids.update(skills[skill_id].instance_ids)
    tasks = {instances[value].task for value in instance_ids if value in instances}
    invalidated = invalidated_refs(repository) | {ref}
    support: dict[str, str] = {
        principle_id: principle_metrics(
            repository, principles[principle_id], invalidated=invalidated
        ).support_sufficiency
        for principle_id in sorted(affected_principles)
    }
    return ImpactReport(
        invalidated_ref=ref,
        affected_skill_ids=tuple(sorted(affected_skills)),
        affected_principle_ids=tuple(sorted(affected_principles)),
        affected_task_ids=tuple(sorted(tasks)),
        principle_support=support,
    )


def invalidate(
    repository: KnowledgeRepository,
    ref: str,
    reason: str,
    *,
    source_partition: str = "development",
    at: str | None = None,
) -> ImpactReport:
    if source_partition != "development":
        raise ValueError("held-out outcomes cannot mutate the knowledge lifecycle")
    if not reason.strip():
        raise ValueError("invalidation requires a reason")
    report = impact_report(repository, ref)
    repository.append_evidence(
        {
            "event": "knowledge.invalidated",
            "subject": ref,
            "reason": reason.strip(),
            "source_partition": source_partition,
            "at": at or datetime.now(timezone.utc).isoformat(),
            "affected_skill_ids": report.affected_skill_ids,
            "affected_principle_ids": report.affected_principle_ids,
        },
        stream="lifecycle",
    )
    updated = impact_report(repository, ref)
    return ImpactReport(
        invalidated_ref=updated.invalidated_ref,
        affected_skill_ids=updated.affected_skill_ids,
        affected_principle_ids=updated.affected_principle_ids,
        affected_task_ids=updated.affected_task_ids,
        principle_support=updated.principle_support,
        event_recorded=True,
    )
