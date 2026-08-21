# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Aggregate reviewer-level golden labels without erasing disagreement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from .serialization import content_hash, iter_jsonl


DIMENSIONS = {
    "faithfulness",
    "coverage",
    "purity",
    "discriminativeness",
    "grounding",
    "falsifiability",
    "compression",
    "transfer",
    "blast-radius",
}
POLARITIES = {"support", "hard-negative", "exception", "falsifier"}


@dataclass(frozen=True)
class GoldenLabel:
    principle_id: str
    task_family: str
    reviewer: str
    dimension: str
    score: float
    polarity: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"unknown golden-label dimension: {self.dimension}")
        if self.polarity not in POLARITIES:
            raise ValueError(f"unknown golden-label polarity: {self.polarity}")
        if not 0 <= self.score <= 1:
            raise ValueError("golden-label score must be in [0, 1]")
        if not self.reviewer.strip():
            raise ValueError("golden label requires reviewer identity")

    @classmethod
    def from_dict(cls, value: dict) -> "GoldenLabel":
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})


def evaluate_golden(labels: list[GoldenLabel], *, faithfulness_gate: float = 0.85) -> dict:
    by_dimension: dict[str, list[float]] = {}
    by_item: dict[tuple[str, str, str, str], list[GoldenLabel]] = {}
    for label in labels:
        by_dimension.setdefault(label.dimension, []).append(label.score)
        key = label.principle_id, label.task_family, label.dimension, label.polarity
        by_item.setdefault(key, []).append(label)
    disagreements = []
    for key, values in sorted(by_item.items()):
        scores = [value.score for value in values]
        if len(set(scores)) > 1:
            disagreements.append(
                {
                    "principle_id": key[0],
                    "task_family": key[1],
                    "dimension": key[2],
                    "polarity": key[3],
                    "reviewers": {value.reviewer: value.score for value in values},
                    "range": max(scores) - min(scores),
                }
            )
    faithfulness = by_dimension.get("faithfulness", [])
    principle_ids = {value.principle_id for value in labels}
    complete_principles = all(
        POLARITIES <= {value.polarity for value in labels if value.principle_id == principle_id}
        and len({value.reviewer for value in labels if value.principle_id == principle_id}) >= 2
        for principle_id in principle_ids
    )
    payload = {
        "schema_version": 1,
        "label_count": len(labels),
        "principle_count": len(principle_ids),
        "reviewers": sorted({value.reviewer for value in labels}),
        "task_families": sorted({value.task_family for value in labels}),
        "polarity_counts": {
            polarity: sum(value.polarity == polarity for value in labels)
            for polarity in sorted(POLARITIES)
        },
        "dimension_means": {
            dimension: mean(values) for dimension, values in sorted(by_dimension.items())
        },
        "disagreements": disagreements,
        "faithfulness_gate": faithfulness_gate,
        "faithfulness_gate_passed": (
            mean(faithfulness) >= faithfulness_gate if faithfulness else None
        ),
        "ready": 10 <= len(principle_ids) <= 20 and complete_principles,
    }
    return {**payload, "report_hash": content_hash(payload)}


def evaluate_golden_file(path: Path, *, faithfulness_gate: float = 0.85) -> dict:
    return evaluate_golden(
        [GoldenLabel.from_dict(value) for value in iter_jsonl(path)],
        faithfulness_gate=faithfulness_gate,
    )
