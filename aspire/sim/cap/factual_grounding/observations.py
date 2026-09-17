"""Observed/audit records, comparisons, verdicts, and snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from aspire.sim.cap.knowledge.serialization import content_hash

ObservationStatus = Literal["known", "unknown", "unsupported", "error"]


@dataclass(frozen=True)
class FGObservation:
    target_id: str
    spec_revision: int
    event_id: str
    phase: str
    source_channel: Literal["observed", "audit"]
    method_id: str
    value: str | int | float | bool | None
    status: ObservationStatus
    confidence: float | None
    uncertainty: dict[str, Any]
    evidence_refs: tuple[str, ...]
    sensor_refs: tuple[str, ...]
    observed_at_step: int
    valid_until_step: int | None
    semantic_hash: str
    entity_binding_revision: int = 1
    unit: str | None = None
    window_start_step: int | None = None
    window_end_step: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"known", "unknown", "unsupported", "error"}:
            raise ValueError(f"unsupported observation status: {self.status}")
        if self.status == "known" and self.value is None:
            raise ValueError("known observation requires a value")
        if self.status != "known" and self.value is not None:
            raise ValueError("non-known observation cannot carry a value")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if self.status in {"unknown", "unsupported", "error"} and not self.uncertainty.get("reason_code"):
            raise ValueError("non-known observation requires uncertainty.reason_code")
        if self.source_channel not in {"observed", "audit"}:
            raise ValueError("unsupported source channel")

    @property
    def ref(self) -> str:
        return f"fgobs:{content_hash(asdict(self))}"


@dataclass(frozen=True)
class FGComparison:
    target_id: str
    event_id: str
    observed_ref: str
    audit_ref: str
    alignment: Literal["match", "mismatch", "indeterminate", "stale"]
    mismatch_class: str | None
    comparable: bool
    tolerance_used: str | int | float | bool | None


@dataclass(frozen=True)
class FGVerdict:
    target_id: str
    state: Literal["satisfied", "violated", "unknown", "conflicted", "expired"]
    confidence: float | None
    based_on: tuple[str, ...]
    next_probe_options: tuple[str, ...]
    observed_only: bool = True
    reason_code: str | None = None
    progress: str | None = None


@dataclass(frozen=True)
class FGSnapshot:
    spec_revision: int
    event_id: str
    observed: tuple[FGObservation, ...] = ()
    audit: tuple[FGObservation, ...] = ()
    comparisons: tuple[FGComparison, ...] = ()
    public_verdicts: tuple[FGVerdict, ...] = ()
    vdm_description: str | None = None

    @property
    def public_hash(self) -> str:
        return content_hash({
            "spec_revision": self.spec_revision,
            "event_id": self.event_id,
            "observed": self.observed,
            "public_verdicts": self.public_verdicts,
            "vdm_description": self.vdm_description,
        })

    @property
    def private_hash(self) -> str:
        return content_hash(asdict(self))
