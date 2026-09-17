"""Compile FG targets to allowlisted verifier calls."""

from __future__ import annotations

from dataclasses import dataclass

from aspire.sim.cap.factual_grounding.targets import FGTarget
from .capability_registry import CapabilityRegistry


@dataclass(frozen=True)
class VerificationStep:
    target_id: str
    method_id: str | None
    status: str


def build_verification_plan(
    targets: list[FGTarget], registry: CapabilityRegistry
) -> tuple[VerificationStep, ...]:
    return tuple(
        VerificationStep(target.id, cap.method_id if cap else None, "ready" if cap else "unsupported")
        for target in targets
        for cap in [registry.resolve(target)]
    )
