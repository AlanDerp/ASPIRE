# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Evidence-aware repetition audit for skill-code instances."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .fingerprint import jaccard, text_tokens
from .models import Checkpoint, ConsolidationPolicy, SkillCodeInstance


@dataclass(frozen=True)
class PairAssessment:
    left_id: str
    right_id: str
    classification: str
    score: float
    structure_similarity: float
    contract_similarity: float
    effect_similarity: float
    evidence_diversity: float


@dataclass(frozen=True)
class RepetitionCluster:
    id: str
    vertical_capability: str
    instance_ids: tuple[str, ...]
    task_count: int
    successful_instance_count: int
    max_single_task_share: float
    accepted: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RepetitionReport:
    checkpoint_id: str
    pairs: tuple[PairAssessment, ...]
    clusters: tuple[RepetitionCluster, ...]


def assess_pair(left: SkillCodeInstance, right: SkillCodeInstance) -> PairAssessment:
    if left.vertical_capability != right.vertical_capability:
        return PairAssessment(left.id, right.id, "unrelated", 0.0, 0.0, 0.0, 0.0, 1.0)

    api_similarity = jaccard(set(left.api_calls), set(right.api_calls))
    shape_similarity = 1.0 if left.ast_fingerprint == right.ast_fingerprint else 0.0
    structure = 0.6 * shape_similarity + 0.4 * api_similarity
    contract = jaccard(
        text_tokens(left.goal, left.trigger), text_tokens(right.goal, right.trigger)
    )
    effect = jaccard(text_tokens(left.observed_effect), text_tokens(right.observed_effect))
    diversity = 1.0 if left.task != right.task else 0.0
    score = 0.25 * structure + 0.30 * contract + 0.25 * effect + 0.20 * diversity

    if left.code_hash == right.code_hash:
        classification = "exact-duplicate"
    elif score >= 0.68 and api_similarity >= 0.6:
        classification = "same-canonical-skill"
    elif contract >= 0.65 and effect >= 0.5:
        classification = "same-principle-different-skill"
    elif contract >= 0.65 and effect < 0.2:
        classification = "possible-conflict"
    else:
        classification = "unrelated"
    return PairAssessment(
        left.id,
        right.id,
        classification,
        round(score, 6),
        round(structure, 6),
        round(contract, 6),
        round(effect, 6),
        diversity,
    )


class _UnionFind:
    def __init__(self, ids: list[str]):
        self.parent = {value: value for value in ids}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while value != root:
            value, self.parent[value] = self.parent[value], root
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def audit_repetition(
    instances: list[SkillCodeInstance],
    checkpoint: Checkpoint,
    policy: ConsolidationPolicy,
) -> RepetitionReport:
    allowed = set(checkpoint.instance_ids)
    selected = sorted((value for value in instances if value.id in allowed), key=lambda v: v.id)
    if len(selected) != len(allowed):
        missing = sorted(allowed - {value.id for value in selected})
        raise ValueError(f"checkpoint instances missing from audit input: {missing}")

    pairs = tuple(assess_pair(left, right) for left, right in combinations(selected, 2))
    union = _UnionFind([value.id for value in selected])
    for pair in pairs:
        if pair.classification in {"exact-duplicate", "same-canonical-skill"}:
            union.union(pair.left_id, pair.right_id)

    members: dict[str, list[SkillCodeInstance]] = {}
    for instance in selected:
        members.setdefault(union.find(instance.id), []).append(instance)

    clusters: list[RepetitionCluster] = []
    for sequence, group in enumerate(sorted(members.values(), key=lambda values: values[0].id), 1):
        if len(group) < 2:
            continue
        tasks = Counter(value.task for value in group)
        successful = sum(value.has_positive_outcome for value in group)
        share = max(tasks.values()) / len(group)
        reasons: list[str] = []
        if len(group) < policy.min_cluster_instances:
            reasons.append(f"requires {policy.min_cluster_instances} instances")
        if len(tasks) < policy.min_cluster_tasks:
            reasons.append(f"requires {policy.min_cluster_tasks} tasks")
        if successful < policy.min_successful_instances:
            reasons.append(f"requires {policy.min_successful_instances} successful instances")
        if share > policy.max_single_task_share:
            reasons.append(f"single-task share {share:.3f} exceeds {policy.max_single_task_share:.3f}")
        vertical = group[0].vertical_capability
        clusters.append(
            RepetitionCluster(
                id=f"cluster-{vertical}-{sequence:04d}",
                vertical_capability=vertical,
                instance_ids=tuple(value.id for value in group),
                task_count=len(tasks),
                successful_instance_count=successful,
                max_single_task_share=round(share, 6),
                accepted=not reasons,
                rejection_reasons=tuple(reasons),
            )
        )
    return RepetitionReport(checkpoint.id, pairs, tuple(clusters))
