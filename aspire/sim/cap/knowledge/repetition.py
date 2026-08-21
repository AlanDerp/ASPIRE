# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Evidence-aware repetition audit for skill-code instances."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

from .fingerprint import jaccard, text_tokens
from .models import CanonicalSkill, Checkpoint, ConsolidationPolicy, SkillCodeInstance
from .serialization import content_hash


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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PairAssessment":
        return cls(
            left_id=str(value["left_id"]),
            right_id=str(value["right_id"]),
            classification=str(value["classification"]),
            score=float(value["score"]),
            structure_similarity=float(value["structure_similarity"]),
            contract_similarity=float(value["contract_similarity"]),
            effect_similarity=float(value["effect_similarity"]),
            evidence_diversity=float(value["evidence_diversity"]),
        )


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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RepetitionCluster":
        return cls(
            id=str(value["id"]),
            vertical_capability=str(value["vertical_capability"]),
            instance_ids=tuple(str(item) for item in value.get("instance_ids", [])),
            task_count=int(value["task_count"]),
            successful_instance_count=int(value["successful_instance_count"]),
            max_single_task_share=float(value["max_single_task_share"]),
            accepted=bool(value["accepted"]),
            rejection_reasons=tuple(
                str(item) for item in value.get("rejection_reasons", [])
            ),
        )


@dataclass(frozen=True)
class RepetitionReport:
    checkpoint_id: str
    pairs: tuple[PairAssessment, ...]
    clusters: tuple[RepetitionCluster, ...]
    policy: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RepetitionReport":
        return cls(
            checkpoint_id=str(value["checkpoint_id"]),
            pairs=tuple(PairAssessment.from_dict(item) for item in value.get("pairs", [])),
            clusters=tuple(
                RepetitionCluster.from_dict(item) for item in value.get("clusters", [])
            ),
            policy=dict(value.get("policy", {})),
        )

    @property
    def content_hash(self) -> str:
        return content_hash(asdict(self))


@dataclass(frozen=True)
class PrinciplePairAssessment:
    left_id: str
    right_id: str
    classification: str
    contract_similarity: float
    effect_similarity: float
    implementation_diversity: float

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrinciplePairAssessment":
        return cls(
            left_id=str(value["left_id"]),
            right_id=str(value["right_id"]),
            classification=str(value["classification"]),
            contract_similarity=float(value["contract_similarity"]),
            effect_similarity=float(value["effect_similarity"]),
            implementation_diversity=float(value["implementation_diversity"]),
        )


@dataclass(frozen=True)
class PrincipleRepetitionReport:
    checkpoint_id: str
    skill_ids: tuple[str, ...]
    skill_versions: dict[str, str]
    vertical_capability: str
    task_families: tuple[str, ...]
    pairs: tuple[PrinciplePairAssessment, ...]
    accepted: bool
    rejection_reasons: tuple[str, ...]
    policy: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrincipleRepetitionReport":
        return cls(
            checkpoint_id=str(value["checkpoint_id"]),
            skill_ids=tuple(str(item) for item in value.get("skill_ids", [])),
            skill_versions={
                str(key): str(item) for key, item in value.get("skill_versions", {}).items()
            },
            vertical_capability=str(value.get("vertical_capability", "")),
            task_families=tuple(str(item) for item in value.get("task_families", [])),
            pairs=tuple(
                PrinciplePairAssessment.from_dict(item) for item in value.get("pairs", [])
            ),
            accepted=bool(value.get("accepted", False)),
            rejection_reasons=tuple(
                str(item) for item in value.get("rejection_reasons", [])
            ),
            policy=dict(value.get("policy", {})),
        )

    @property
    def content_hash(self) -> str:
        return content_hash(asdict(self))


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


def assess_principle_pair(
    left: CanonicalSkill,
    right: CanonicalSkill,
) -> PrinciplePairAssessment:
    if left.vertical_capability != right.vertical_capability:
        return PrinciplePairAssessment(
            left.id,
            right.id,
            "cross-vertical",
            0.0,
            0.0,
            1.0,
        )
    contract = jaccard(
        text_tokens(left.goal, left.trigger),
        text_tokens(right.goal, right.trigger),
    )
    effect = jaccard(text_tokens(left.effect), text_tokens(right.effect))
    implementation = jaccard(
        set(left.api_calls) | text_tokens(left.operation_template),
        set(right.api_calls) | text_tokens(right.operation_template),
    )
    classification = (
        "shared-invariant-candidate"
        if contract >= 0.25 and effect >= 0.25
        else "insufficient-shared-signal"
    )
    return PrinciplePairAssessment(
        left.id,
        right.id,
        classification,
        round(contract, 6),
        round(effect, 6),
        round(1.0 - implementation, 6),
    )


def audit_principle_repetition(
    skills: list[CanonicalSkill],
    checkpoint: Checkpoint,
    policy: ConsolidationPolicy,
) -> PrincipleRepetitionReport:
    """Audit repeated invariants across canonical skills before abstraction."""
    unique = {value.id: value for value in skills}
    selected = [unique[skill_id] for skill_id in sorted(unique)]
    pairs = tuple(
        assess_principle_pair(left, right) for left, right in combinations(selected, 2)
    )
    reasons: list[str] = []
    if len(selected) < policy.min_canonical_skills_for_principle:
        reasons.append(
            f"requires {policy.min_canonical_skills_for_principle} canonical skills"
        )
    verticals = {value.vertical_capability for value in selected}
    if len(verticals) != 1:
        reasons.append("canonical skills must share one vertical capability")
    families = sorted(
        {family for value in selected for family in value.scope.task_families}
    )
    if len(families) < policy.min_task_families_for_principle:
        reasons.append(
            f"requires {policy.min_task_families_for_principle} task families"
        )
    outside_checkpoint = sorted(
        {
            instance_id
            for skill in selected
            for instance_id in skill.instance_ids
            if instance_id not in checkpoint.instance_ids
        }
    )
    if outside_checkpoint:
        reasons.append(f"instances outside checkpoint: {outside_checkpoint}")

    connected: dict[str, set[str]] = {value.id: set() for value in selected}
    for pair in pairs:
        if pair.classification == "shared-invariant-candidate":
            connected[pair.left_id].add(pair.right_id)
            connected[pair.right_id].add(pair.left_id)
    if selected:
        reached: set[str] = set()
        pending = [selected[0].id]
        while pending:
            current = pending.pop()
            if current in reached:
                continue
            reached.add(current)
            pending.extend(sorted(connected[current] - reached))
        if len(reached) != len(selected):
            reasons.append("canonical-skill repetition graph is disconnected")

    return PrincipleRepetitionReport(
        checkpoint_id=checkpoint.id,
        skill_ids=tuple(value.id for value in selected),
        skill_versions={value.id: value.version for value in selected},
        vertical_capability=(next(iter(verticals)) if len(verticals) == 1 else ""),
        task_families=tuple(families),
        pairs=pairs,
        accepted=not reasons,
        rejection_reasons=tuple(reasons),
        policy=asdict(policy),
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
    return RepetitionReport(checkpoint.id, pairs, tuple(clusters), asdict(policy))
