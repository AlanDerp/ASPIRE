"""Content-addressed public evidence records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from aspire.sim.cap.knowledge.serialization import content_hash


@dataclass(frozen=True)
class EvidenceRecord:
    kind: str
    event_id: str
    capture_id: str
    method_id: str
    method_version: str
    sensor_refs: tuple[str, ...]
    payload: dict[str, Any]

    @property
    def ref(self) -> str:
        return f"evidence:{content_hash(asdict(self))}"
