"""Budgeted selection of allowlisted public observation probes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeOption:
    id: str
    expected_information_gain: float
    action_cost: float
    requires_motion: bool = False
    safety_preconditions_met: bool = True


def select_probe(options: tuple[ProbeOption, ...], *, remaining_budget: float) -> ProbeOption | None:
    eligible = [
        item for item in options
        if item.action_cost <= remaining_budget
        and (not item.requires_motion or item.safety_preconditions_met)
    ]
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (-item.expected_information_gain / max(item.action_cost, 1e-9), item.id))[0]
