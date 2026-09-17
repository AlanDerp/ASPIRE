"""Derive independent requirement identifiers from task language."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aspire.sim.cap.knowledge.serialization import sha256_text


@dataclass(frozen=True)
class TaskRequirement:
    id: str
    text: str
    predicate_hint: str | None
    expected_hint: bool | None = None


_PREDICATE_CUES = {
    "held_by": ("hold", "held", "grasp", "pick up", "lift"),
    "above": ("above", "over", "clearance", "on top"),
    "contact": ("contact", "touch", "without touching", "no contact"),
    "on": ("place it on", "put it on"),
    "inside": ("place it in", "put it in", "inside", " into "),
    "open": ("open the",),
    "closed": ("close the",),
    "activated": ("turn on", "switch on", "activate"),
    "inserted": ("insert",),
    "stacked_on": ("stack",),
}

_PREDICATE_PATTERNS = {
    "on": (r"\b(?:place|put)\b.+\bon(?:to)?\b",),
    "inside": (r"\b(?:place|put|insert)\b.+\b(?:in|into|inside)\b",),
}


def extract_task_requirements(task_language: str) -> tuple[TaskRequirement, ...]:
    """Extract allowed predicate requirements without using task IDs or audit state."""
    normalized = " ".join(task_language.lower().split())
    found = []
    for predicate, cues in _PREDICATE_CUES.items():
        matches = [cue for cue in cues if cue in normalized]
        matches.extend(
            pattern for pattern in _PREDICATE_PATTERNS.get(predicate, ())
            if re.search(pattern, normalized)
        )
        if matches:
            text = f"{predicate}: task contains {matches[0]!r} in {task_language.strip()}"
            expected = None
            if predicate == "contact":
                expected = not any(
                    phrase in normalized
                    for phrase in ("without touching", "without contact", "no contact", "not touch")
                )
            elif predicate in {
                "held_by", "on", "inside", "open", "closed", "activated",
                "inserted", "stacked_on",
            }:
                expected = True
            found.append(TaskRequirement(
                f"req.{predicate}.{sha256_text(text)[:10]}", text, predicate, expected
            ))
    if not found:
        text = task_language.strip()
        found.append(TaskRequirement(f"req.task.{sha256_text(text)[:10]}", text, None))
    return tuple(found)
