"""Versioned public entity bindings derived from perception."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntityBinding:
    entity_name: str
    revision: int
    evidence_refs: tuple[str, ...]
    confidence: float | None


class EntityBindingStore:
    def __init__(self) -> None:
        self._history: dict[str, list[EntityBinding]] = {}

    def append(self, name: str, evidence_refs: tuple[str, ...], confidence: float | None) -> EntityBinding:
        history = self._history.setdefault(name, [])
        binding = EntityBinding(name, len(history) + 1, evidence_refs, confidence)
        history.append(binding)
        return binding

    def latest(self, name: str) -> EntityBinding | None:
        history = self._history.get(name, [])
        return history[-1] if history else None
