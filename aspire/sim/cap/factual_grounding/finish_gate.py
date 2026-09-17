"""Evaluate task completion anchors with temporal roles."""

from __future__ import annotations

from dataclasses import dataclass

from .observations import FGVerdict
from .targets import FGSpec


@dataclass(frozen=True)
class FinishDecision:
    admitted: bool
    blocking_target_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def evaluate_finish(spec: FGSpec, latest: dict[str, FGVerdict], milestone_history: set[str]) -> FinishDecision:
    blocking: list[str] = []
    reasons: list[str] = []
    for target in spec.active.values():
        if target.criticality != "required":
            continue
        if target.temporal.role == "milestone":
            ok = target.id in milestone_history
        else:
            ok = target.id in latest and latest[target.id].state == "satisfied"
        if not ok:
            blocking.append(target.id)
            reasons.append(f"{target.id} is not satisfied for role {target.temporal.role}")
    return FinishDecision(not blocking, tuple(sorted(blocking)), tuple(reasons))
