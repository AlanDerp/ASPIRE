"""Deterministic adapters over public, provenance-bearing measurements."""

from __future__ import annotations

from aspire.sim.cap.perception.evidence import EvidenceRecord
from aspire.sim.cap.perception.observation_broker import SensorBundle
from aspire.sim.cap.factual_grounding.targets import FGTarget

import numpy as np


def _points(bundle: SensorBundle, entity: str):
    clouds = bundle.public_data.get("entity_point_clouds", {})
    value = clouds.get(entity) if isinstance(clouds, dict) else None
    if value is None:
        return None
    array = np.asarray(value, dtype=float)
    return array if array.ndim == 2 and array.shape[1] == 3 and len(array) else None


def _derived(target: FGTarget, bundle: SensorBundle, method: str):
    subject = _points(bundle, target.subject.name)
    object_points = _points(bundle, target.object.name) if target.object else None
    occluded = set(bundle.public_data.get("occluded_entities", ()))
    if target.subject.name in occluded or (target.object and target.object.name in occluded):
        return {"status": "unknown", "uncertainty": {"reason_code": "occluded-contact-region"}}
    if target.predicate == "above" and subject is not None and object_points is not None:
        clearance = float(np.min(subject[:, 2]) - np.max(object_points[:, 2]))
        return {"status": "known", "value": clearance, "confidence": bundle.public_data.get("geometry_confidence"), "independent_views": len(set(bundle.sensor_refs))}
    if target.predicate == "contact" and subject is not None and object_points is not None:
        # Chunking avoids materializing an unbounded NxM distance matrix.
        minimum = min(float(np.min(np.linalg.norm(chunk[:, None, :] - object_points[None, :, :], axis=2))) for chunk in np.array_split(subject, max(1, (len(subject) + 255) // 256)))
        resolution = float(bundle.public_data.get("geometry_resolution_m", 0.005))
        threshold = float(target.tolerance if target.tolerance is not None else resolution)
        if minimum <= resolution and target.tolerance is None:
            return {"status": "unknown", "uncertainty": {"reason_code": "below-geometry-resolution", "minimum_gap_m": minimum}}
        return {"status": "known", "value": minimum <= threshold, "confidence": bundle.public_data.get("geometry_confidence"), "independent_views": len(set(bundle.sensor_refs))}
    if target.predicate == "held_by" and subject is not None:
        gripper = bundle.public_data.get("gripper_state", {})
        relative_error = bundle.public_data.get("relative_motion_error_m")
        identity_confidence = float(bundle.public_data.get("entity_identity_confidence", 0.0))
        if relative_error is None or identity_confidence < 0.5:
            return {"status": "unknown", "uncertainty": {"reason_code": "identity-or-motion-unresolved"}}
        held = bool(gripper.get("closed")) and float(relative_error) <= float(bundle.public_data.get("held_motion_tolerance_m", 0.02))
        return {"status": "known", "value": held, "confidence": identity_confidence, "independent_views": len(set(bundle.sensor_refs))}
    return None


def _measurement(target: FGTarget, bundle: SensorBundle, key: str, method: str) -> EvidenceRecord:
    measurements = bundle.public_data.get("fg_measurements", {})
    value = measurements.get(key)
    if not isinstance(value, dict):
        value = _derived(target, bundle, method)
    if not isinstance(value, dict):
        payload = {"status": "unknown", "uncertainty": {"reason_code": "measurement-unavailable"}}
    else:
        payload = dict(value)
        status = payload.get("status", "unknown")
        if status != "known":
            payload["value"] = None
            payload.setdefault("uncertainty", {"reason_code": "measurement-unknown"})
        if int(payload.get("independent_views", 1)) < target.evidence_policy.min_independent_views:
            payload = {"status": "unknown", "value": None, "uncertainty": {"reason_code": "insufficient-independent-views"}}
    return EvidenceRecord("fg-measurement", bundle.event_id, bundle.capture_id, method, "1", bundle.sensor_refs, payload)


def held_by(target: FGTarget, bundle: SensorBundle) -> EvidenceRecord:
    return _measurement(target, bundle, "held_by", "visual-held-by-v1")


def above(target: FGTarget, bundle: SensorBundle) -> EvidenceRecord:
    return _measurement(target, bundle, "above", "depth-clearance-v1")


def contact(target: FGTarget, bundle: SensorBundle) -> EvidenceRecord:
    return _measurement(target, bundle, "contact", "multiview-contact-v1")
