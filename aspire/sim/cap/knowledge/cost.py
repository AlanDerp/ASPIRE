# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Auditable construction and maintenance total-cost accounting."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .experiment import TREATMENTS
from .preregistration import validate_frozen_preregistration
from .serialization import content_hash, iter_jsonl, load_structured, sha256_file


PHASES = {"construction", "maintenance"}
COST_FIELDS = ("human_minutes", "compute_seconds", "model_tokens", "monetary_cost")


def _validate_event(
    event: dict[str, Any],
    *,
    scales: set[int],
    maintenance_tasks: set[str],
) -> None:
    required = {
        "event_id",
        "treatment",
        "scale",
        "task_id",
        "task_family",
        "phase",
        "source_partition",
        "evidence_path",
        "evidence_hash",
        *COST_FIELDS,
    }
    missing = sorted(required - set(event))
    unknown = sorted(set(event) - required - {"schema_version", "notes"})
    if missing or unknown:
        raise ValueError(f"cost event schema mismatch; missing={missing}, unknown={unknown}")
    if not isinstance(event["event_id"], str) or not event["event_id"].strip():
        raise ValueError("cost event_id must be a nonempty string")
    if event["treatment"] not in TREATMENTS:
        raise ValueError(f"unknown cost treatment: {event['treatment']}")
    if event["phase"] not in PHASES:
        raise ValueError(f"unknown cost phase: {event['phase']}")
    if not isinstance(event["scale"], int) or isinstance(event["scale"], bool):
        raise ValueError("cost scale must be an integer")
    if any(
        not isinstance(event[field], str) or not event[field].strip()
        for field in ("task_id", "task_family")
    ):
        raise ValueError("cost task_id and task_family must be nonempty strings")
    expected_partition = (
        "development" if event["phase"] == "construction" else "maintenance"
    )
    if event["source_partition"] != expected_partition:
        raise ValueError(
            f"{event['phase']} cost must use source_partition={expected_partition}"
        )
    if event["scale"] not in scales:
        raise ValueError(f"cost event uses an unregistered scale: {event['scale']}")
    if event["task_id"] not in maintenance_tasks:
        raise ValueError(f"cost event uses a task outside the maintenance split: {event['task_id']}")
    for field in COST_FIELDS:
        value = event[field]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"cost event {field} must be non-negative")
    evidence_path = Path(str(event["evidence_path"]))
    if not evidence_path.is_absolute() or not evidence_path.is_file():
        raise ValueError("cost evidence_path must be an existing absolute file")
    if sha256_file(evidence_path) != event["evidence_hash"]:
        raise ValueError(f"cost evidence hash mismatch: {event['event_id']}")


def _normalized_cost(event: dict[str, Any], weights: dict[str, Any]) -> float:
    return (
        float(event["human_minutes"])
        + float(event["compute_seconds"]) / 60 * float(weights["compute_minute"])
        + float(event["model_tokens"]) / 1000 * float(weights["model_1k_tokens"])
        + float(event["monetary_cost"]) * float(weights["monetary_unit"])
    )


def build_cost_report(
    ledger_path: Path, preregistration_path: Path
) -> dict[str, Any]:
    """Aggregate trace-backed resource costs under preregistered weights."""
    preregistration = load_structured(preregistration_path)
    errors = validate_frozen_preregistration(preregistration)
    if errors:
        raise ValueError(f"cost report requires a valid frozen preregistration: {errors}")
    fixed = preregistration["fixed_artifacts"]
    task_split = load_structured(Path(str(fixed["task_split_path"])))
    scales = {int(value) for value in preregistration["library_scales"]}
    maintenance_tasks = {str(value) for value in task_split["maintenance"]}
    weights = preregistration["decision_rules"]["total_cost_weights"]
    events = list(iter_jsonl(ledger_path))
    if not events:
        raise ValueError("cost ledger is empty")
    seen_ids: set[str] = set()
    grouped: dict[tuple[str, int, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "construction_cost": 0.0,
            "maintenance_cost": 0.0,
            "event_ids": [],
            "phase_event_counts": {phase: 0 for phase in sorted(PHASES)},
            "resources": {field: 0.0 for field in COST_FIELDS},
        }
    )
    for event in events:
        _validate_event(event, scales=scales, maintenance_tasks=maintenance_tasks)
        event_id = str(event["event_id"])
        if event_id in seen_ids:
            raise ValueError(f"duplicate cost event id: {event_id}")
        seen_ids.add(event_id)
        key = (
            str(event["treatment"]),
            int(event["scale"]),
            str(event["task_id"]),
            str(event["task_family"]),
        )
        group = grouped[key]
        phase_field = f"{event['phase']}_cost"
        group[phase_field] += _normalized_cost(event, weights)
        group["event_ids"].append(event_id)
        group["phase_event_counts"][event["phase"]] += 1
        for field in COST_FIELDS:
            group["resources"][field] += float(event[field])

    rows = []
    for key, group in sorted(grouped.items()):
        treatment, scale, task_id, task_family = key
        rows.append(
            {
                "treatment": treatment,
                "scale": scale,
                "task_id": task_id,
                "task_family": task_family,
                **group,
                "total_cost": group["construction_cost"]
                + group["maintenance_cost"],
            }
        )
    expected = {
        (treatment, scale, task_id)
        for treatment in ("B", "E")
        for scale in scales
        for task_id in maintenance_tasks
    }
    present = {
        (row["treatment"], row["scale"], row["task_id"])
        for row in rows
        if all(row["phase_event_counts"][phase] > 0 for phase in PHASES)
    }
    incomplete_phases = [
        [row["treatment"], row["scale"], row["task_id"]]
        for row in rows
        if row["treatment"] in {"B", "E"}
        and any(row["phase_event_counts"][phase] == 0 for phase in PHASES)
    ]
    missing = sorted(expected - present)
    payload = {
        "schema_version": 1,
        "status": "complete" if not missing and not incomplete_phases else "incomplete",
        "preregistration_hash": content_hash(preregistration),
        "ledger_hash": content_hash(events),
        "total_cost_unit": "preregistered-human-minute-equivalent",
        "weights": weights,
        "event_count": len(events),
        "rows": rows,
        "missing_b_e_cells": [list(value) for value in missing],
        "incomplete_phase_cells": incomplete_phases,
    }
    return {**payload, "cost_report_hash": content_hash(payload)}
