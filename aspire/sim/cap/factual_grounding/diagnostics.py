"""Finite mismatch diagnoses; diagnoses are hypotheses, never facts."""

from __future__ import annotations

from dataclasses import dataclass

from .observations import FGComparison


@dataclass(frozen=True)
class DiagnosticHypothesis:
    code: str
    target_id: str
    suggested_probe: str
    audit_influenced: bool


def diagnose(comparison: FGComparison) -> tuple[DiagnosticHypothesis, ...]:
    if comparison.alignment != "mismatch":
        return ()
    return (
        DiagnosticHypothesis("occlusion-or-threshold", comparison.target_id, "alternate-view", True),
        DiagnosticHypothesis("temporal-misalignment", comparison.target_id, "repeat-synchronized-capture", True),
    )
