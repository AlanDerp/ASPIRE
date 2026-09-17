"""Private suite adapter for simulator-provided semantic FG audit values.

This module is imported only by the harness. Generated programs receive neither
the adapter nor the low-level environment.
"""

from __future__ import annotations

from typing import Any, Mapping

from aspire.sim.cap.factual_grounding.audit_protocol import register_audit_adapter
from aspire.sim.cap.factual_grounding.observations import FGObservation
from aspire.sim.cap.factual_grounding.targets import FGTarget
from aspire.sim.cap.factual_grounding.verifier import semantic_hash
from aspire.sim.cap.perception.observation_broker import SensorBundle


class FrankaSemanticAuditAdapter:
    def __init__(self, source: Any) -> None:
        self.source = source

    def observe(self, target: FGTarget, bundle: SensorBundle) -> FGObservation:
        reader = getattr(self.source, "get_factual_grounding_audit", None)
        if not callable(reader):
            return self._unknown(target, bundle, "audit-unsupported", "unsupported")
        values = reader(target_id=target.id, predicate=target.predicate)
        if not isinstance(values, Mapping) or "value" not in values:
            return self._unknown(target, bundle, "audit-invalid-result", "error")
        return FGObservation(
            target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "audit",
            str(values.get("method_id", "franka-semantic-audit-v1")), values["value"], "known",
            values.get("confidence"), {}, tuple(values.get("evidence_refs", ())), (),
            bundle.tick_end, None, semantic_hash(target), bundle.entity_binding_revision,
            target.unit, bundle.tick_start, bundle.tick_end,
        )

    @staticmethod
    def _unknown(target: FGTarget, bundle: SensorBundle, reason: str, status: str) -> FGObservation:
        return FGObservation(
            target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "audit",
            "franka-semantic-audit-v1", None, status, None, {"reason_code": reason}, (), (),
            bundle.tick_end, None, semantic_hash(target), bundle.entity_binding_revision, target.unit,
        )


register_audit_adapter("franka-semantic-v1", FrankaSemanticAuditAdapter)
