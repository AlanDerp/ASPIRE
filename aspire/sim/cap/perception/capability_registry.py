"""Allowlisted verifier and probe registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .observation_broker import SensorBundle
from .evidence import EvidenceRecord
from aspire.sim.cap.factual_grounding.targets import FGTarget

VerifierFn = Callable[[FGTarget, SensorBundle], EvidenceRecord]


@dataclass(frozen=True)
class VerificationCapability:
    method_id: str
    predicate: str
    required_sensors: tuple[str, ...]
    runner: VerifierFn
    probe_options: tuple[str, ...] = ()
    priority: int = 0


class CapabilityRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, VerificationCapability] = {}

    def register(self, capability: VerificationCapability) -> None:
        if capability.method_id in self._methods:
            raise ValueError(f"duplicate capability: {capability.method_id}")
        self._methods[capability.method_id] = capability

    def resolve(self, target: FGTarget) -> VerificationCapability | None:
        preferred = target.evidence_policy.preferred_methods
        candidates = [v for v in self._methods.values() if v.predicate == target.predicate]
        if preferred:
            candidates.sort(key=lambda item: (item.method_id not in preferred, -item.priority, item.method_id))
        else:
            candidates.sort(key=lambda item: (-item.priority, item.method_id))
        return candidates[0] if candidates else None

    def get(self, method_id: str) -> VerificationCapability:
        return self._methods[method_id]

    def public_manifest(self) -> tuple[dict[str, object], ...]:
        """Return deterministic public metadata without runner objects."""
        return tuple(
            {
                "method_id": item.method_id,
                "predicate": item.predicate,
                "required_sensors": item.required_sensors,
                "probe_options": item.probe_options,
            }
            for item in sorted(self._methods.values(), key=lambda value: value.method_id)
        )


def default_capabilities() -> CapabilityRegistry:
    from aspire.sim.cap.factual_grounding.verifiers import above, contact, held_by

    registry = CapabilityRegistry()
    registry.register(VerificationCapability("visual-held-by-v1", "held_by", ("rgb", "robot_state"), held_by, ("alternate-view",)))
    registry.register(VerificationCapability("depth-clearance-v1", "above", ("rgb", "depth", "calibration"), above, ("alternate-view",)))
    registry.register(VerificationCapability("multiview-contact-v1", "contact", ("rgb", "depth", "calibration"), contact, ("alternate-view",)))
    return registry


def install_frozen_verification_skills(
    registry: CapabilityRegistry,
    skill_paths,
    *,
    checkpoint_id: str,
) -> None:
    """Install aliases for reviewed methods from one frozen checkpoint."""
    from aspire.sim.cap.knowledge.verification_skill import load_verification_skill

    for path in skill_paths:
        skill = load_verification_skill(path)
        if skill.status != "frozen" or skill.checkpoint_id != checkpoint_id:
            raise ValueError(f"verification skill is not frozen at {checkpoint_id}: {skill.id}")
        base = registry.get(skill.verifier_id)
        for predicate in skill.supported_predicates:
            registry.register(VerificationCapability(
                method_id=f"{skill.id}@{skill.version}", predicate=predicate,
                required_sensors=skill.required_capabilities, runner=base.runner,
                probe_options=tuple(
                    str(item.get("probe")) for item in skill.observation_plan if item.get("probe")
                ),
                priority=10,
            ))
