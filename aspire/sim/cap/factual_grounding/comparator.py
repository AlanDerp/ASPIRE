"""Align observed and audit records without changing either source."""

from __future__ import annotations

from .observations import FGComparison, FGObservation


def compare(observed: FGObservation, audit: FGObservation, *, tolerance: float | None = None) -> FGComparison:
    if observed.source_channel != "observed" or audit.source_channel != "audit":
        raise ValueError("comparison requires observed and audit channels")
    identity_matches = (
        observed.target_id == audit.target_id
        and observed.spec_revision == audit.spec_revision
        and observed.event_id == audit.event_id
        and observed.semantic_hash == audit.semantic_hash
        and observed.entity_binding_revision == audit.entity_binding_revision
        and observed.unit == audit.unit
    )
    if not identity_matches:
        return FGComparison(observed.target_id, observed.event_id, observed.ref, audit.ref, "stale", "alignment-mismatch", False, tolerance)
    if observed.status != "known" or audit.status != "known":
        return FGComparison(observed.target_id, observed.event_id, observed.ref, audit.ref, "indeterminate", f"{observed.status}-vs-{audit.status}", False, tolerance)
    if isinstance(observed.value, (int, float)) and not isinstance(observed.value, bool) and isinstance(audit.value, (int, float)) and not isinstance(audit.value, bool):
        matches = abs(float(observed.value) - float(audit.value)) <= float(tolerance or 0)
    else:
        matches = observed.value == audit.value
    return FGComparison(observed.target_id, observed.event_id, observed.ref, audit.ref, "match" if matches else "mismatch", None if matches else "value-mismatch", True, tolerance)
