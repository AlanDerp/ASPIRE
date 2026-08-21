# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Domain models for the ASPIRE skill consolidation forest.

The core models intentionally use the standard library. ASPIRE deployments may
have Pydantic installed, but repository inspection and unit tests should not
require simulator dependencies or a prepared virtual environment.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Literal


JsonValue = Any
Status = Literal[
    "proposal", "candidate", "validated", "stable", "rejected", "deprecated", "blocked"
]
STATUSES = {"proposal", "candidate", "validated", "stable", "rejected", "deprecated", "blocked"}
ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERTICAL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ModelError(ValueError):
    """Raised when a knowledge model violates a persistent invariant."""


def _require_text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ModelError(f"{label} must not be empty")
    return value


def validate_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ModelError(f"invalid knowledge id: {value!r}")
    return value


def validate_version(value: str) -> str:
    if not VERSION_RE.fullmatch(value):
        raise ModelError(f"invalid semantic version: {value!r}")
    return value


def validate_vertical(value: str) -> str:
    if not VERTICAL_RE.fullmatch(value):
        raise ModelError(f"invalid vertical capability: {value!r}")
    return value


def _strings(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in (values or []) if str(value).strip()))


@dataclass(frozen=True)
class Scope:
    suites: tuple[str, ...] = ()
    task_families: tuple[str, ...] = ()
    embodiments: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "Scope":
        value = value or {}
        return cls(
            suites=_strings(value.get("suites")),
            task_families=_strings(value.get("task_families")),
            embodiments=_strings(value.get("embodiments")),
            environments=_strings(value.get("environments")),
            labels={str(k): str(v) for k, v in value.get("labels", {}).items()},
        )


@dataclass(frozen=True)
class SkillCodeInstance:
    KIND: ClassVar[str] = "skill-code-instance"

    id: str
    vertical_capability: str
    task: str
    task_family: str
    source_code_path: str
    source_code_sha256: str
    code: str
    goal: str
    trigger: str
    observed_effect: str
    code_hash: str
    ast_fingerprint: str
    api_calls: tuple[str, ...] = ()
    development_outcomes: dict[str, JsonValue] = field(default_factory=dict)
    checkpoint_id: str | None = None
    provenance: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_vertical(self.vertical_capability)
        _require_text(self.task, "task")
        _require_text(self.task_family, "task_family")
        _require_text(self.source_code_path, "source_code_path")
        _require_text(self.code, "code")
        _require_text(self.goal, "goal")
        _require_text(self.code_hash, "code_hash")
        _require_text(self.ast_fingerprint, "ast_fingerprint")

    @property
    def has_positive_outcome(self) -> bool:
        successes = self.development_outcomes.get("successes", [])
        improved = self.development_outcomes.get("improved", False)
        return bool(successes) or improved is True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SkillCodeInstance":
        return cls(
            id=value["id"],
            vertical_capability=value["vertical_capability"],
            task=value["task"],
            task_family=value.get("task_family", value["task"]),
            source_code_path=value["source_code_path"],
            source_code_sha256=value["source_code_sha256"],
            code=value["code"],
            goal=value["goal"],
            trigger=value.get("trigger", ""),
            observed_effect=value.get("observed_effect", ""),
            code_hash=value["code_hash"],
            ast_fingerprint=value["ast_fingerprint"],
            api_calls=_strings(value.get("api_calls")),
            development_outcomes=value.get("development_outcomes", {}),
            checkpoint_id=value.get("checkpoint_id"),
            provenance=value.get("provenance", {}),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class CanonicalSkill:
    KIND: ClassVar[str] = "skill"

    id: str
    version: str
    vertical_capability: str
    title: str
    goal: str
    trigger: str
    operation_template: str
    effect: str
    instance_ids: tuple[str, ...]
    api_calls: tuple[str, ...] = ()
    contraindications: tuple[str, ...] = ()
    variable_parameters: tuple[str, ...] = ()
    scope: Scope = field(default_factory=Scope)
    status: Status = "candidate"
    provenance: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_version(self.version)
        validate_vertical(self.vertical_capability)
        _require_text(self.title, "title")
        _require_text(self.goal, "goal")
        if self.status not in STATUSES:
            raise ModelError(f"invalid knowledge status: {self.status}")
        if len(set(self.instance_ids)) < 2:
            raise ModelError("canonical skill requires at least two distinct code instances")
        for instance_id in self.instance_ids:
            validate_id(instance_id)
        if not self.provenance.get("checkpoint_id"):
            raise ModelError("canonical skill requires checkpoint provenance")
        if not self.provenance.get("repetition_cluster_id"):
            raise ModelError("canonical skill requires repetition-audit provenance")
        if not self.provenance.get("instance_repetition_report_hash"):
            raise ModelError("canonical skill requires an instance repetition report hash")
        cluster_review = self.provenance.get("cluster_review")
        if not isinstance(cluster_review, dict):
            raise ModelError("canonical skill requires an explicit cluster review")
        if (
            cluster_review.get("cluster_id") != self.provenance.get("repetition_cluster_id")
            or cluster_review.get("decision") != "accept"
            or cluster_review.get("pair_assessments_reviewed") is not True
            or not cluster_review.get("reviewer")
            or not cluster_review.get("reviewed_at")
            or not cluster_review.get("rationale")
        ):
            raise ModelError("canonical skill cluster review is incomplete or inconsistent")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalSkill":
        return cls(
            id=value["id"],
            version=value["version"],
            vertical_capability=value["vertical_capability"],
            title=value["title"],
            goal=value["goal"],
            trigger=value.get("trigger", ""),
            operation_template=value.get("operation_template", ""),
            effect=value.get("effect", ""),
            instance_ids=_strings(value.get("instance_ids")),
            api_calls=_strings(value.get("api_calls")),
            contraindications=_strings(value.get("contraindications")),
            variable_parameters=_strings(value.get("variable_parameters")),
            scope=Scope.from_dict(value.get("scope")),
            status=value.get("status", "candidate"),
            provenance=value.get("provenance", {}),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class Principle:
    KIND: ClassVar[str] = "principle"

    id: str
    version: str
    vertical_capability: str
    title: str
    summary: str
    when: dict[str, JsonValue]
    decision_mode: Literal["prefer", "avoid", "require"]
    decision: str
    invariant: str
    expected_effects: tuple[str, ...]
    exceptions: tuple[dict[str, JsonValue], ...]
    falsifiers: tuple[str, ...]
    child_ids: tuple[str, ...]
    exception_review: str = ""
    scope: Scope = field(default_factory=Scope)
    status: Status = "proposal"
    review_required: bool = True
    provenance: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_version(self.version)
        validate_vertical(self.vertical_capability)
        _require_text(self.title, "title")
        _require_text(self.decision, "decision")
        _require_text(self.invariant, "invariant")
        if self.status not in STATUSES:
            raise ModelError(f"invalid knowledge status: {self.status}")
        if self.decision_mode not in {"prefer", "avoid", "require"}:
            raise ModelError(f"invalid principle decision mode: {self.decision_mode}")
        if len(set(self.child_ids)) < 2:
            raise ModelError("principle requires at least two distinct children")
        for child_id in self.child_ids:
            validate_id(child_id)
        if not self.provenance.get("checkpoint_id"):
            raise ModelError("principle requires checkpoint provenance")
        if self.provenance.get("proposal_method") != "canonical-skill-repetition-audit":
            raise ModelError("principle must originate from repetition-audited canonical skills")
        if not isinstance(self.provenance.get("canonical_repetition_audit"), dict):
            raise ModelError("principle requires its canonical-skill repetition audit")
        if not self.provenance.get("canonical_repetition_audit_hash"):
            raise ModelError("principle requires a canonical-skill repetition audit hash")
        if not isinstance(self.provenance.get("canonical_skill_versions"), dict):
            raise ModelError("principle requires exact canonical-skill revisions")
        if self.status in {"validated", "stable"}:
            if self.review_required:
                raise ModelError("validated principle cannot require review")
            if len(set(self.child_ids)) < 3:
                raise ModelError("validated principle requires at least three children")
            if len(set(self.scope.task_families)) < 2:
                raise ModelError("validated principle requires support from at least two task families")
            if not self.exceptions and not self.exception_review.strip():
                raise ModelError(
                    "validated principle requires an exception or an explicit empty-exception review"
                )
            if not self.falsifiers:
                raise ModelError("validated principle requires a falsifier")
            if any(not exception.get("id") or "when" not in exception for exception in self.exceptions):
                raise ModelError("validated principle exceptions require id and when")
            required_review = (
                "reviewer",
                "counterexample_report",
                "leave_one_family_out_report",
            )
            missing_review = [key for key in required_review if not self.provenance.get(key)]
            if missing_review:
                raise ModelError(
                    f"validated principle lacks promotion evidence: {missing_review}"
                )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Principle":
        rule = value.get("rule", {})
        return cls(
            id=value["id"],
            version=value["version"],
            vertical_capability=value["vertical_capability"],
            title=value["title"],
            summary=value.get("summary", ""),
            when=rule.get("when", value.get("when", {})),
            decision_mode=rule.get("decision_mode", value.get("decision_mode", "prefer")),
            decision=rule.get("decision", value.get("decision", "")),
            invariant=rule.get("invariant", value.get("invariant", "")),
            expected_effects=_strings(rule.get("expected_effects", value.get("expected_effects"))),
            exceptions=tuple(value.get("exceptions", [])),
            falsifiers=_strings(value.get("falsifiers")),
            child_ids=_strings(value.get("child_ids")),
            exception_review=value.get("exception_review", ""),
            scope=Scope.from_dict(value.get("scope")),
            status=value.get("status", "proposal"),
            review_required=bool(value.get("review_required", True)),
            provenance=value.get("provenance", {}),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class VerticalTree:
    id: str
    version: str
    vertical_capability: str
    structural_root: str
    checkpoint_id: str
    parent_by_child: dict[str, str]
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_version(self.version)
        validate_vertical(self.vertical_capability)
        validate_id(self.structural_root)
        if self.structural_root in self.parent_by_child:
            raise ModelError("structural root cannot have a parent")
        for child, parent in self.parent_by_child.items():
            validate_id(child)
            validate_id(parent)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerticalTree":
        return cls(
            id=value["id"],
            version=value["version"],
            vertical_capability=value["vertical_capability"],
            structural_root=value["structural_root"],
            checkpoint_id=value["checkpoint_id"],
            parent_by_child={str(k): str(v) for k, v in value.get("parent_by_child", {}).items()},
            schema_version=int(value.get("schema_version", 1)),
        )


OVERLAY_KINDS = {"requires", "can-follow", "exception-to", "contradicts"}


@dataclass(frozen=True)
class OverlayEdge:
    id: str
    version: str
    kind: str
    source_id: str
    target_id: str
    guard: dict[str, JsonValue] = field(default_factory=dict)
    rationale: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_version(self.version)
        validate_id(self.source_id)
        validate_id(self.target_id)
        if self.kind not in OVERLAY_KINDS:
            raise ModelError(f"unsupported overlay edge kind: {self.kind}")
        if self.source_id == self.target_id:
            raise ModelError("overlay edge cannot reference itself")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OverlayEdge":
        return cls(
            id=value["id"],
            version=value["version"],
            kind=value["kind"],
            source_id=value["source_id"],
            target_id=value["target_id"],
            guard=value.get("guard", {}),
            rationale=value.get("rationale", ""),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class ConsolidationPolicy:
    checkpoint_every_instances: int = 20
    min_distinct_tasks: int = 5
    min_cluster_instances: int = 3
    min_cluster_tasks: int = 3
    min_successful_instances: int = 2
    max_single_task_share: float = 0.5
    min_canonical_skills_for_principle: int = 3
    min_task_families_for_principle: int = 2
    leave_one_family_out_required: bool = True

    def __post_init__(self) -> None:
        integers = (
            self.checkpoint_every_instances,
            self.min_distinct_tasks,
            self.min_cluster_instances,
            self.min_cluster_tasks,
            self.min_successful_instances,
            self.min_canonical_skills_for_principle,
            self.min_task_families_for_principle,
        )
        if any(value < 1 for value in integers):
            raise ModelError("consolidation thresholds must be positive")
        if not 0 < self.max_single_task_share <= 1:
            raise ModelError("max_single_task_share must be in (0, 1]")

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ConsolidationPolicy":
        value = value or {}
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})


@dataclass(frozen=True)
class Checkpoint:
    id: str
    instance_ids: tuple[str, ...]
    instance_hashes: dict[str, str]
    created_at: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        if set(self.instance_ids) != set(self.instance_hashes):
            raise ModelError("checkpoint ids and hashes must describe the same instances")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Checkpoint":
        return cls(
            id=value["id"],
            instance_ids=_strings(value.get("instance_ids")),
            instance_hashes={str(k): str(v) for k, v in value.get("instance_hashes", {}).items()},
            created_at=value["created_at"],
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class KnowledgeManifest:
    """Version lock for one reproducible knowledge view."""

    id: str
    version: str
    checkpoint_id: str
    skill_versions: dict[str, str]
    principle_versions: dict[str, str]
    tree_versions: dict[str, str]
    edge_versions: dict[str, str]
    created_at: str
    source_partition: Literal["development", "held-out"] = "development"
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_version(self.version)
        validate_id(self.checkpoint_id)
        for revisions in (
            self.skill_versions,
            self.principle_versions,
            self.tree_versions,
            self.edge_versions,
        ):
            for logical_id, version in revisions.items():
                validate_id(logical_id)
                validate_version(version)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowledgeManifest":
        return cls(
            id=value["id"],
            version=value["version"],
            checkpoint_id=value["checkpoint_id"],
            skill_versions={str(k): str(v) for k, v in value.get("skill_versions", {}).items()},
            principle_versions={
                str(k): str(v) for k, v in value.get("principle_versions", {}).items()
            },
            tree_versions={str(k): str(v) for k, v in value.get("tree_versions", {}).items()},
            edge_versions={str(k): str(v) for k, v in value.get("edge_versions", {}).items()},
            created_at=value["created_at"],
            source_partition=value.get("source_partition", "development"),
            schema_version=int(value.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    suite: str
    task_language: str
    task_family: str
    vertical_capabilities: tuple[str, ...] = ()
    facts: dict[str, JsonValue] = field(default_factory=dict)
    available_api_calls: tuple[str, ...] = ()
    token_budget: int = 2400

    def __post_init__(self) -> None:
        _require_text(self.task_id, "task_id")
        _require_text(self.suite, "suite")
        _require_text(self.task_language, "task_language")
        _require_text(self.task_family, "task_family")
        if self.token_budget < 1:
            raise ModelError("task context token budget must be positive")
        for vertical in self.vertical_capabilities:
            validate_vertical(vertical)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskContext":
        return cls(
            task_id=value["task_id"],
            suite=value["suite"],
            task_language=value["task_language"],
            task_family=value.get("task_family", value["task_id"]),
            vertical_capabilities=_strings(value.get("vertical_capabilities")),
            facts=value.get("facts", {}),
            available_api_calls=_strings(value.get("available_api_calls")),
            token_budget=int(value.get("token_budget", 2400)),
        )


@dataclass(frozen=True)
class Portfolio:
    context_hash: str
    checkpoint_id: str
    tree_ids: tuple[str, ...]
    principle_ids: tuple[str, ...]
    skill_ids: tuple[str, ...]
    overlay_edge_ids: tuple[str, ...]
    exclusions: tuple[dict[str, str], ...]
    estimated_tokens: int
    markdown: str
    manifest_id: str | None = None
    treatment: str = "E"
    instance_ids: tuple[str, ...] = ()
    node_versions: dict[str, str] = field(default_factory=dict)
    fallback_used: bool = False
    schema_version: int = 1


@dataclass(frozen=True)
class PrincipleMetrics:
    principle_id: str
    principle_version: str
    support_count: int
    support_task_families: int
    support_diversity: float
    contradiction_count: int
    exception_rate: float
    operational_fanout: int
    abstraction_depth: int
    canonical_skill_coverage: float
    compression_ratio: float
    last_validated_at: str | None
    support_sufficiency: Literal["sufficient", "weak", "broken"]


@dataclass(frozen=True)
class ImpactReport:
    invalidated_ref: str
    affected_skill_ids: tuple[str, ...]
    affected_principle_ids: tuple[str, ...]
    affected_task_ids: tuple[str, ...]
    principle_support: dict[str, str]
    event_recorded: bool = False


def model_to_dict(value: Any) -> dict[str, Any]:
    """Return a JSON-compatible dictionary for a domain dataclass."""
    result = asdict(value)
    if hasattr(value, "KIND"):
        result["kind"] = value.KIND
    return result
