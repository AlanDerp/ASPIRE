"""Paired old/new verifier evaluation evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationEvaluation:
    id: str
    source: str
    source_version: str
    method_version: str
    task_family: str
    scene_id: str
    expected_status: str
    old_status: str
    new_status: str
    old_correct: bool
    new_correct: bool
    old_latency_ms: float
    new_latency_ms: float
    evidence_ref: str
    change_kind: str = "verifier_revision"

    def __post_init__(self) -> None:
        if self.source != "development":
            raise ValueError("verification evaluation must come from development")
        if self.expected_status not in {"positive", "negative", "unknown"}:
            raise ValueError("unsupported expected verification status")
        if self.old_status not in {"known", "unknown", "unsupported", "error"}:
            raise ValueError("unsupported old verifier status")
        if self.new_status not in {"known", "unknown", "unsupported", "error"}:
            raise ValueError("unsupported new verifier status")
        if self.change_kind != "verifier_revision":
            raise ValueError("task repair is not verifier evidence")
        if min(self.old_latency_ms, self.new_latency_ms) < 0:
            raise ValueError("verification latency cannot be negative")
        if not self.evidence_ref:
            raise ValueError("verification evaluation requires evidence_ref")
