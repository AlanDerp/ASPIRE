# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic controlled-growth corpora that cannot become evidence."""

from __future__ import annotations

import random

from .checkpoints import instances_at_checkpoint
from .repository import KnowledgeRepository
from .serialization import content_hash


STRESS_KINDS = (
    "paraphrase-duplicate",
    "same-principle-different-implementation",
    "narrow-scope-specialization",
    "contradictory-advice",
    "stale-api-pattern",
    "irrelevant-domain-distractor",
    "rare-safety-critical-exception",
    "over-broad-false-principle",
)


def build_stress_corpus(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    scales: list[int],
    *,
    seed: int,
) -> dict:
    if not scales or any(scale < 1 for scale in scales):
        raise ValueError("stress corpus scales must be positive")
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances = instances_at_checkpoint(repository, checkpoint)
    if not instances:
        raise ValueError("stress corpus requires at least one source instance")
    randomizer = random.Random(seed)
    snapshots = []
    for scale in sorted(set(scales)):
        target = len(instances) * scale
        records = []
        for index in range(target):
            source = instances[index % len(instances)]
            kind = STRESS_KINDS[(index + randomizer.randrange(len(STRESS_KINDS))) % len(STRESS_KINDS)]
            record = {
                "id": f"stress.{scale}.{index + 1:06d}",
                "source_instance_id": source.id,
                "vertical_capability": source.vertical_capability,
                "task_family": source.task_family,
                "kind": kind,
                "goal": f"[{kind}] {source.goal}",
                "trigger": source.trigger,
                "observed_effect": source.observed_effect,
                "code": source.code,
                "synthetic": True,
                "evidence_eligible": False,
                "success_outcome_eligible": False,
            }
            record["content_hash"] = content_hash(record)
            records.append(record)
        snapshots.append(
            {
                "scale": scale,
                "record_count": len(records),
                "records": records,
            }
        )
    payload = {
        "schema_version": 1,
        "corpus_kind": "synthetic",
        "checkpoint_id": checkpoint_id,
        "checkpoint_hash": content_hash(checkpoint),
        "seed": seed,
        "stress_kinds": list(STRESS_KINDS),
        "source_instance_count": len(instances),
        "snapshots": snapshots,
        "partition_guard": (
            "This corpus is retrieval/maintenance stress only and must not be used for "
            "success evidence, canonicalization, or principle support."
        ),
    }
    return {**payload, "corpus_hash": content_hash(payload)}
