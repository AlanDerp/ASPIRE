"""Dynamic FG target contracts and append-only specification revisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

JsonValue = str | int | float | bool | None
Criticality = Literal["required", "supporting", "diagnostic"]
TemporalRole = Literal["milestone", "terminal", "invariant"]


def _keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {unknown}")


@dataclass(frozen=True)
class EntityRef:
    name: str
    instance_hint: str | None = None

    @classmethod
    def from_value(cls, value: str | dict[str, Any]) -> "EntityRef":
        if isinstance(value, str):
            return cls(value)
        _keys(value, {"name", "instance_hint"}, "EntityRef")
        return cls(name=str(value["name"]), instance_hint=value.get("instance_hint"))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("entity name cannot be empty")


@dataclass(frozen=True)
class TemporalRequirement:
    role: TemporalRole = "terminal"
    kind: Literal["instant", "continuous"] = "instant"
    duration_steps: int = 1
    sample_interval_steps: int = 1
    max_gap_steps: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "TemporalRequirement":
        payload = dict(value or {})
        _keys(payload, {"role", "kind", "duration_steps", "sample_interval_steps", "max_gap_steps"}, "temporal")
        return cls(**payload)

    def __post_init__(self) -> None:
        if self.role not in {"milestone", "terminal", "invariant"}:
            raise ValueError("unsupported temporal role")
        if self.kind not in {"instant", "continuous"}:
            raise ValueError("unsupported temporal kind")
        if min(self.duration_steps, self.sample_interval_steps) < 1 or self.max_gap_steps < 0:
            raise ValueError("invalid temporal sampling requirements")
        if self.kind == "instant" and self.duration_steps != 1:
            raise ValueError("instant target duration_steps must equal 1")


@dataclass(frozen=True)
class EvidencePolicy:
    min_independent_views: int = 1
    preferred_methods: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "EvidencePolicy":
        payload = dict(value or {})
        _keys(payload, {"min_independent_views", "preferred_methods"}, "evidence_policy")
        if "preferred_methods" in payload:
            payload["preferred_methods"] = tuple(payload["preferred_methods"])
        return cls(**payload)

    def __post_init__(self) -> None:
        if self.min_independent_views < 1:
            raise ValueError("min_independent_views must be positive")


@dataclass(frozen=True)
class FGTarget:
    id: str
    stage_id: str
    subject: EntityRef
    predicate: str
    operator: str
    expected: JsonValue
    value_type: Literal["boolean", "number", "string"]
    criticality: Criticality
    requirement_ids: tuple[str, ...]
    temporal: TemporalRequirement = field(default_factory=TemporalRequirement)
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)
    object: EntityRef | None = None
    unit: str | None = None
    tolerance: float | None = None
    threshold_source: Literal["task", "protocol", "agent_assumption"] = "task"
    assumption: str | None = None
    unknown_policy: Literal["probe", "replan", "fail_closed", "report_only"] = "probe"
    created_by_turn: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FGTarget":
        allowed = {item.name for item in __import__("dataclasses").fields(cls)}
        _keys(value, allowed, "FGTarget")
        payload = dict(value)
        payload["subject"] = EntityRef.from_value(payload["subject"])
        if payload.get("object") is not None:
            payload["object"] = EntityRef.from_value(payload["object"])
        payload["requirement_ids"] = tuple(payload.get("requirement_ids", ()))
        payload["temporal"] = TemporalRequirement.from_dict(payload.get("temporal"))
        payload["evidence_policy"] = EvidencePolicy.from_dict(payload.get("evidence_policy"))
        return cls(**payload)

    def __post_init__(self) -> None:
        if not self.id.startswith("fg.") or not self.stage_id or not self.predicate:
            raise ValueError("target requires fg.* id, stage_id, and predicate")
        if self.criticality not in {"required", "supporting", "diagnostic"}:
            raise ValueError("unsupported target criticality")
        if self.value_type not in {"boolean", "number", "string"}:
            raise ValueError("unsupported target value type")
        if self.unknown_policy not in {"probe", "replan", "fail_closed", "report_only"}:
            raise ValueError("unsupported unknown policy")
        if self.criticality == "required" and not self.requirement_ids:
            raise ValueError("required target must bind at least one task requirement")
        if self.value_type == "boolean" and not isinstance(self.expected, bool):
            raise ValueError("boolean target requires boolean expected value")
        if self.value_type == "number" and (
            isinstance(self.expected, bool) or not isinstance(self.expected, (int, float))
        ):
            raise ValueError("number target requires numeric expected value")
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("target tolerance cannot be negative")
        if self.threshold_source == "agent_assumption" and not self.assumption:
            raise ValueError("agent-assumed threshold requires an assumption")


@dataclass(frozen=True)
class FGPatchOperation:
    op: Literal["add", "replace", "retire"]
    target: FGTarget | None = None
    target_id: str | None = None
    parent_target_id: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.op not in {"add", "replace", "retire"}:
            raise ValueError(f"unsupported FG patch operation: {self.op}")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FGPatchOperation":
        _keys(value, {"op", "target", "target_id", "parent_target_id", "reason_code"}, "FGPatchOperation")
        payload = dict(value)
        if payload.get("target") is not None:
            payload["target"] = FGTarget.from_dict(payload["target"])
        return cls(**payload)


@dataclass(frozen=True)
class FGPatch:
    base_revision: int
    operations: tuple[FGPatchOperation, ...]

    def __post_init__(self) -> None:
        if self.base_revision < 0:
            raise ValueError("FG patch base_revision cannot be negative")
        if not self.operations:
            raise ValueError("FG patch requires at least one operation")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FGPatch":
        _keys(value, {"base_revision", "operations"}, "FGPatch")
        return cls(
            base_revision=int(value["base_revision"]),
            operations=tuple(FGPatchOperation.from_dict(item) for item in value["operations"]),
        )


@dataclass(frozen=True)
class FGSpec:
    revision: int = 0
    active: dict[str, FGTarget] = field(default_factory=dict)
    retired: tuple[str, ...] = ()

    def apply(self, patch: FGPatch, *, max_targets: int = 24) -> "FGSpec":
        if patch.base_revision != self.revision:
            raise ValueError(f"stale FG patch: expected revision {self.revision}")
        active = dict(self.active)
        retired = list(self.retired)
        for operation in patch.operations:
            if operation.op == "add":
                if operation.target is None or operation.target.id in active:
                    raise ValueError("add requires a new target")
                active[operation.target.id] = operation.target
                continue
            if not operation.reason_code or not operation.parent_target_id:
                raise ValueError(f"{operation.op} requires reason_code and parent_target_id")
            old_id = operation.target_id or operation.parent_target_id
            if old_id not in active:
                raise ValueError(f"patch target is not active: {old_id}")
            old = active[old_id]
            if operation.op == "retire":
                if old.criticality == "required":
                    raise ValueError("required targets cannot be retired")
                del active[old_id]
                retired.append(old_id)
                continue
            if operation.op != "replace" or operation.target is None:
                raise ValueError("replace requires a replacement target")
            new = operation.target
            if new.id == old_id or new.id in active or new.id in retired:
                raise ValueError("replacement requires a new, never-used target id")
            if old.criticality == "required":
                if new.criticality != "required" or set(new.requirement_ids) != set(old.requirement_ids):
                    raise ValueError("replacement weakens required target coverage")
                if new.subject != old.subject or new.object != old.object:
                    raise ValueError("replacement changes required target entities")
                if (new.predicate, new.operator, new.expected, new.value_type, new.unit) != (
                    old.predicate, old.operator, old.expected, old.value_type, old.unit
                ):
                    raise ValueError("replacement changes required target semantics")
                if new.temporal.duration_steps < old.temporal.duration_steps:
                    raise ValueError("replacement shortens required temporal window")
                if old.tolerance is not None and (new.tolerance is None or new.tolerance > old.tolerance):
                    raise ValueError("replacement loosens required target tolerance")
            del active[old_id]
            retired.append(old_id)
            active[new.id] = new
        if len(active) > max_targets:
            raise ValueError("FG target budget exceeded")
        return replace(self, revision=self.revision + 1, active=active, retired=tuple(retired))
