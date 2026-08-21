# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Freeze immutable skill-code corpora before consolidation."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Checkpoint, ConsolidationPolicy, SkillCodeInstance
from .repository import KnowledgeRepository
from .serialization import content_hash


def checkpoint_eligibility(
    instances: list[SkillCodeInstance], policy: ConsolidationPolicy
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    unique = {instance.id: instance for instance in instances}
    if len(unique) < policy.checkpoint_every_instances:
        reasons.append(
            f"requires {policy.checkpoint_every_instances} unique instances; found {len(unique)}"
        )
    tasks = {instance.task for instance in unique.values()}
    if len(tasks) < policy.min_distinct_tasks:
        reasons.append(f"requires {policy.min_distinct_tasks} distinct tasks; found {len(tasks)}")
    return not reasons, reasons


def freeze_checkpoint(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    policy: ConsolidationPolicy,
    *,
    created_at: str | None = None,
) -> Checkpoint:
    instances = repository.list_instances()
    eligible, reasons = checkpoint_eligibility(instances, policy)
    if not eligible:
        raise ValueError("checkpoint is not eligible: " + "; ".join(reasons))
    ordered = sorted(instances, key=lambda value: value.id)
    checkpoint = Checkpoint(
        id=checkpoint_id,
        instance_ids=tuple(value.id for value in ordered),
        instance_hashes={value.id: content_hash(value) for value in ordered},
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
    repository.save_checkpoint(checkpoint)
    return checkpoint


def instances_at_checkpoint(
    repository: KnowledgeRepository, checkpoint: Checkpoint
) -> list[SkillCodeInstance]:
    by_id = {value.id: value for value in repository.list_instances()}
    missing = sorted(set(checkpoint.instance_ids) - set(by_id))
    if missing:
        raise ValueError(f"checkpoint references missing instances: {missing}")
    instances = [by_id[instance_id] for instance_id in checkpoint.instance_ids]
    changed = [
        value.id
        for value in instances
        if content_hash(value) != checkpoint.instance_hashes[value.id]
    ]
    if changed:
        raise ValueError(f"checkpoint instance content changed: {changed}")
    return instances
