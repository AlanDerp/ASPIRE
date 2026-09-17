"""Freeze event-aligned public sensor bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from aspire.sim.cap.knowledge.serialization import content_hash


class PublicSensorSource(Protocol):
    def public_observation(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SensorBundle:
    capture_id: str
    event_id: str
    spec_revision: int
    phase: str
    tick_start: int
    tick_end: int
    calibration_version: str
    entity_binding_revision: int
    sensor_refs: tuple[str, ...]
    public_data: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return content_hash(self)


class ObservationBroker:
    def __init__(self, source: PublicSensorSource) -> None:
        self.source = source
        self._serial = 0

    def freeze(
        self, *, event_id: str, spec_revision: int, phase: str, tick_start: int, tick_end: int
    ) -> SensorBundle:
        if tick_end < tick_start:
            raise ValueError("sensor bundle tick range is reversed")
        value = self.source.public_observation()
        if not isinstance(value, dict):
            raise TypeError("public observation source must return a dictionary")
        value = dict(value)
        self._serial += 1
        return SensorBundle(
            capture_id=f"capture-{self._serial:06d}", event_id=event_id,
            spec_revision=spec_revision, phase=phase, tick_start=tick_start,
            tick_end=tick_end, calibration_version=str(value.pop("calibration_version", "unknown")),
            entity_binding_revision=int(value.pop("entity_binding_revision", 1)),
            sensor_refs=tuple(value.pop("sensor_refs", ())), public_data=value,
        )
