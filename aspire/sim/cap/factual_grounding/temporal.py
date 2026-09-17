"""Tick-based temporal aggregation for continuous targets."""

from __future__ import annotations

from .observations import FGObservation, FGVerdict
from .targets import FGTarget
from .verifier import verdict_from_observation


def temporal_verdict(target: FGTarget, observations: list[FGObservation]) -> FGVerdict:
    if target.temporal.kind == "instant":
        if not observations:
            return FGVerdict(target.id, "unknown", None, (), (), reason_code="no-observation")
        return verdict_from_observation(target, observations[-1])
    known = sorted(
        (item for item in observations if item.status == "known"),
        key=lambda item: item.observed_at_step,
    )
    if not known:
        return FGVerdict(target.id, "unknown", None, (), (), reason_code="no-known-samples", progress=f"0/{target.temporal.duration_steps}")
    for item in known:
        verdict = verdict_from_observation(target, item)
        if verdict.state == "violated":
            return FGVerdict(target.id, "violated", item.confidence, (item.ref,), (), reason_code="window-violation")
    steps = [item.observed_at_step for item in known]
    covered = steps[-1] - steps[0] + 1
    gap_limit = target.temporal.sample_interval_steps + target.temporal.max_gap_steps
    if any(right - left > gap_limit for left, right in zip(steps, steps[1:])):
        return FGVerdict(target.id, "unknown", None, tuple(item.ref for item in known), (), reason_code="sampling-gap", progress=f"{covered}/{target.temporal.duration_steps}")
    if covered < target.temporal.duration_steps:
        return FGVerdict(target.id, "unknown", None, tuple(item.ref for item in known), (), reason_code="window-incomplete", progress=f"{covered}/{target.temporal.duration_steps}")
    return FGVerdict(target.id, "satisfied", min((item.confidence for item in known if item.confidence is not None), default=None), tuple(item.ref for item in known), ())
