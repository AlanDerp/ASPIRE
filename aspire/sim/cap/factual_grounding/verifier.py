"""Convert public evidence into observed observations and verdicts."""

from __future__ import annotations

from aspire.sim.cap.knowledge.serialization import content_hash
from aspire.sim.cap.perception.capability_registry import CapabilityRegistry
from aspire.sim.cap.perception.evidence import EvidenceRecord
from aspire.sim.cap.perception.observation_broker import SensorBundle
from .observations import FGObservation, FGVerdict
from .targets import FGTarget


def semantic_hash(target: FGTarget) -> str:
    return content_hash({
        "subject": target.subject, "predicate": target.predicate, "object": target.object,
        "operator": target.operator, "expected": target.expected, "value_type": target.value_type,
        "unit": target.unit, "temporal": target.temporal,
    })


def unsupported_observation(target: FGTarget, bundle: SensorBundle) -> FGObservation:
    return FGObservation(
        target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "observed",
        "unresolved", None, "unsupported", None, {"reason_code": "missing-capability"},
        (), bundle.sensor_refs, bundle.tick_end, None, semantic_hash(target),
        bundle.entity_binding_revision, target.unit,
    )


def verify_target(
    target: FGTarget, bundle: SensorBundle, registry: CapabilityRegistry
) -> tuple[FGObservation, tuple[str, ...], EvidenceRecord | None]:
    capability = registry.resolve(target)
    if capability is None:
        return unsupported_observation(target, bundle), (), None
    evidence = None
    try:
        evidence = capability.runner(target, bundle)
        observation = observation_from_evidence(target, bundle, evidence)
    except Exception as error:
        observation = FGObservation(
            target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "observed",
            capability.method_id, None, "error", None,
            {"reason_code": "verifier-error", "error_type": type(error).__name__}, (),
            bundle.sensor_refs, bundle.tick_end, None, semantic_hash(target),
            bundle.entity_binding_revision, target.unit,
        )
    return observation, capability.probe_options, evidence


def observation_from_evidence(
    target: FGTarget, bundle: SensorBundle, evidence: EvidenceRecord
) -> FGObservation:
    """Convert a provenance-bearing public evidence record to an observation."""
    payload = evidence.payload
    status = str(payload.get("status", "error"))
    if status not in {"known", "unknown", "unsupported", "error"}:
        status = "error"
        payload = {
            **payload,
            "uncertainty": {"reason_code": "invalid-evidence-status"},
        }
    value = payload.get("value") if status == "known" else None
    uncertainty = dict(payload.get("uncertainty", {}))
    if status != "known" and not uncertainty.get("reason_code"):
        uncertainty["reason_code"] = "measurement-unknown"
    return FGObservation(
        target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "observed",
        evidence.method_id, value, status, payload.get("confidence"),
        uncertainty, (evidence.ref,), bundle.sensor_refs,
        bundle.tick_end, payload.get("valid_until_step"), semantic_hash(target),
        bundle.entity_binding_revision, target.unit, bundle.tick_start, bundle.tick_end,
    )


def verdict_from_observation(
    target: FGTarget, observation: FGObservation, probe_options: tuple[str, ...] = ()
) -> FGVerdict:
    if observation.status != "known":
        return FGVerdict(target.id, "unknown", observation.confidence, (observation.ref,), probe_options, True, str(observation.uncertainty.get("reason_code")))
    if observation.valid_until_step is not None and observation.valid_until_step < observation.observed_at_step:
        return FGVerdict(target.id, "expired", observation.confidence, (observation.ref,), probe_options, True, "expired")
    actual = observation.value
    if target.operator == "equals":
        satisfied = actual == target.expected
    elif target.operator == "gte":
        satisfied = float(actual) >= float(target.expected)  # type: ignore[arg-type]
    elif target.operator == "gt":
        satisfied = float(actual) > float(target.expected)  # type: ignore[arg-type]
    else:
        return FGVerdict(target.id, "unknown", observation.confidence, (observation.ref,), probe_options, True, "unsupported-operator")
    return FGVerdict(target.id, "satisfied" if satisfied else "violated", observation.confidence, (observation.ref,), probe_options)
