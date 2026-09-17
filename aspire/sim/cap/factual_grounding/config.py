"""Validated configuration for dynamic factual grounding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal, TypeVar

RuntimeMode = Literal["observed_only", "development_compare", "held_out_audit"]
FeedbackMode = Literal["shadow", "visible"]

T = TypeVar("T")


def _strict(cls: type[T], value: dict[str, Any] | None) -> T:
    payload = dict(value or {})
    allowed = {item.name for item in fields(cls)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown {cls.__name__} fields: {unknown}")
    return cls(**payload)


@dataclass(frozen=True)
class FactualGroundingConfig:
    enabled: bool = False
    protocol: Literal["legacy-code-v1", "dynamic-v2"] = "legacy-code-v1"
    runtime_mode: RuntimeMode = "observed_only"
    feedback: FeedbackMode = "shadow"
    planner_required: bool = True
    max_targets: int = 24
    max_fg_revisions: int = 6
    max_active_probes_per_turn: int = 3
    max_total_probes: int = 12
    max_protocol_repairs: int = 2
    max_model_calls: int = 32
    allowed_probes: tuple[str, ...] = ("alternate-view", "repeat-synchronized-capture")
    finish_requires_all_required: bool = True
    audit_adapter: str | None = None
    verification_checkpoint: str | None = None
    verification_skill_paths: tuple[str, ...] = ()
    private_artifact_root: str | None = None
    isolated_worker: bool = False

    def __post_init__(self) -> None:
        if self.protocol not in {"legacy-code-v1", "dynamic-v2"}:
            raise ValueError("unsupported factual-grounding protocol")
        if self.runtime_mode not in {
            "observed_only", "development_compare", "held_out_audit"
        }:
            raise ValueError("unsupported factual-grounding runtime mode")
        if self.feedback not in {"shadow", "visible"}:
            raise ValueError("unsupported factual-grounding feedback mode")
        for name in (
            "max_targets", "max_fg_revisions", "max_active_probes_per_turn",
            "max_total_probes", "max_model_calls",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_protocol_repairs < 0:
            raise ValueError("max_protocol_repairs cannot be negative")
        if not self.enabled and self.feedback != "shadow":
            raise ValueError("disabled factual grounding cannot be visible")
        if self.enabled and self.protocol != "dynamic-v2":
            raise ValueError("enabled factual grounding requires dynamic-v2")
        if self.enabled and not self.planner_required:
            raise ValueError("dynamic-v2 requires an explicit initial plan")
        if self.enabled and not self.finish_requires_all_required:
            raise ValueError("dynamic-v2 cannot disable the required-target finish rule")
        if self.runtime_mode != "observed_only" and not self.audit_adapter:
            raise ValueError(f"{self.runtime_mode} requires an audit_adapter")
        if self.runtime_mode != "observed_only" and not self.private_artifact_root:
            raise ValueError(f"{self.runtime_mode} requires private_artifact_root")
        if self.runtime_mode != "observed_only" and not self.isolated_worker:
            raise ValueError(f"{self.runtime_mode} requires isolated_worker")

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "FactualGroundingConfig":
        payload = dict(value or {})
        if "verification_skill_paths" in payload:
            payload["verification_skill_paths"] = tuple(payload["verification_skill_paths"])
        if "allowed_probes" in payload:
            payload["allowed_probes"] = tuple(payload["allowed_probes"])
        return _strict(cls, payload)


@dataclass(frozen=True)
class RuntimeFeatureSet:
    factual_grounding: FactualGroundingConfig = field(default_factory=FactualGroundingConfig)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RuntimeFeatureSet":
        payload = dict(value or {})
        unknown = sorted(set(payload) - {"factual_grounding"})
        if unknown:
            raise ValueError(f"unknown runtime_features fields: {unknown}")
        return cls(
            factual_grounding=FactualGroundingConfig.from_dict(
                payload.get("factual_grounding")
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
