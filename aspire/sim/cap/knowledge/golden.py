# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Aggregate reviewer-level golden labels without erasing disagreement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from .models import KnowledgeManifest
from .repository import KnowledgeRepository
from .serialization import content_hash, iter_jsonl, sha256_file


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
SUBJECT_KINDS = {"principle-relevance", "child-relation"}


@dataclass(frozen=True)
class GoldenLabel:
    principle_id: str
    task_family: str
    reviewer: str
    dimension: str
    score: float
    polarity: str
    notes: str = ""
    principle_version: str = ""
    case_id: str = ""
    subject_kind: str = "principle-relevance"
    subject_id: str = ""
    checkpoint_id: str = ""
    manifest_id: str = ""
    evidence_path: str = ""
    evidence_hash: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"unknown golden-label dimension: {self.dimension}")
        if self.polarity not in POLARITIES:
            raise ValueError(f"unknown golden-label polarity: {self.polarity}")
        if not 0 <= self.score <= 1:
            raise ValueError("golden-label score must be in [0, 1]")
        if not self.reviewer.strip():
            raise ValueError("golden label requires reviewer identity")
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(f"unknown golden-label subject kind: {self.subject_kind}")

    @classmethod
    def from_dict(cls, value: dict) -> "GoldenLabel":
        unknown = set(value) - set(cls.__dataclass_fields__) - {"schema_version"}
        if unknown:
            raise ValueError(f"unknown golden-label fields: {sorted(unknown)}")
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})


def evaluate_golden(
    labels: list[GoldenLabel],
    *,
    faithfulness_gate: float = 0.85,
    binding: dict[str, Any] | None = None,
) -> dict:
    by_dimension: dict[str, list[float]] = {}
    by_item: dict[tuple[str, ...], list[GoldenLabel]] = {}
    for label in labels:
        by_dimension.setdefault(label.dimension, []).append(label.score)
        key = (
            label.principle_id,
            label.principle_version,
            label.case_id,
            label.subject_kind,
            label.subject_id,
            label.task_family,
            label.dimension,
            label.polarity,
        )
        by_item.setdefault(key, []).append(label)
    disagreements = []
    for item_key, values in sorted(by_item.items()):
        scores = [value.score for value in values]
        if len(set(scores)) > 1:
            disagreements.append(
                {
                    "principle_id": item_key[0],
                    "task_family": item_key[5],
                    "case_id": item_key[2],
                    "subject_kind": item_key[3],
                    "subject_id": item_key[4],
                    "dimension": item_key[6],
                    "polarity": item_key[7],
                    "reviewers": {value.reviewer: value.score for value in values},
                    "range": max(scores) - min(scores),
                }
            )
    faithfulness = by_dimension.get("faithfulness", [])
    principle_ids = {value.principle_id for value in labels}
    independent_items = all(
        len({value.reviewer for value in values}) >= 2
        and len(values) == len({value.reviewer for value in values})
        for values in by_item.values()
    )
    labels_locked = all(
        label.principle_version
        and label.case_id
        and label.subject_id
        and label.checkpoint_id
        and label.manifest_id
        and label.evidence_path
        and label.evidence_hash
        for label in labels
    )
    complete_principles = all(
        POLARITIES
        <= {
            value.polarity
            for value in labels
            if value.principle_id == principle_id
            and value.subject_kind == "principle-relevance"
        }
        and SUBJECT_KINDS
        <= {
            value.subject_kind
            for value in labels
            if value.principle_id == principle_id
        }
        for principle_id in principle_ids
    )
    payload = {
        "schema_version": 1,
        "label_count": len(labels),
        "principle_count": len(principle_ids),
        "principle_ids": sorted(principle_ids),
        "reviewers": sorted({value.reviewer for value in labels}),
        "task_families": sorted({value.task_family for value in labels}),
        "binding": binding or {},
        "item_count": len(by_item),
        "independent_item_reviews_complete": independent_items,
        "labels_hash_locked": labels_locked,
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
        "ready": 10 <= len(principle_ids) <= 20
        and complete_principles
        and independent_items
        and labels_locked
        and bool(binding),
    }
    return {**payload, "report_hash": content_hash(payload)}


def evaluate_golden_file(
    path: Path,
    repository: KnowledgeRepository,
    manifest: KnowledgeManifest,
    *,
    faithfulness_gate: float = 0.85,
) -> dict:
    if manifest.source_partition != "development":
        raise ValueError("golden labels require a development-only manifest")
    repository.load_checkpoint(manifest.checkpoint_id)
    labels = [GoldenLabel.from_dict(value) for value in iter_jsonl(path)]
    principles = {
        (value.id, value.version): value for value in repository.list_principles()
    }
    manifest_ref = f"{manifest.id}@{manifest.version}"
    for label in labels:
        expected_version = manifest.principle_versions.get(label.principle_id)
        if expected_version != label.principle_version:
            raise ValueError(
                f"golden principle revision is outside the manifest: {label.principle_id}"
            )
        principle = principles.get((label.principle_id, label.principle_version))
        if principle is None:
            raise ValueError(f"golden principle revision does not exist: {label.principle_id}")
        if label.manifest_id != manifest_ref or label.checkpoint_id != manifest.checkpoint_id:
            raise ValueError("golden label manifest or checkpoint lock mismatch")
        if label.subject_kind == "principle-relevance":
            if label.subject_id != label.principle_id:
                raise ValueError("principle-relevance subject_id must equal principle_id")
        elif label.subject_id not in principle.child_ids:
            raise ValueError("child-relation subject_id is not a principle child")
        evidence_path = Path(label.evidence_path)
        if not evidence_path.is_absolute() or not evidence_path.is_file():
            raise ValueError("golden evidence_path must be an existing absolute file")
        if sha256_file(evidence_path) != label.evidence_hash:
            raise ValueError(f"golden evidence hash mismatch: {label.case_id}")
    binding = {
        "manifest_id": manifest_ref,
        "checkpoint_id": manifest.checkpoint_id,
        "labels_source_hash": content_hash(labels),
    }
    return evaluate_golden(
        labels,
        faithfulness_gate=faithfulness_gate,
        binding=binding,
    )
