"""Metadata for reusable public perception components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionComponent:
    id: str
    version: str
    input_kinds: tuple[str, ...]
    output_kind: str
    transferable_to_robot: bool


BUILTIN_COMPONENTS = (
    PerceptionComponent("sam3-segmentation", "service-config", ("rgb", "text"), "mask", True),
    PerceptionComponent("depth-point-cloud", "1", ("mask", "depth", "calibration"), "point-cloud", True),
    PerceptionComponent("robot-state", "1", ("joint", "gripper"), "robot-state", True),
)
