# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Non-destructive merge, split, conflict, hub, and pruning audits."""

from __future__ import annotations

from typing import Any

from .lifecycle import invalidated_refs, principle_metrics
from .models import CanonicalSkill, Principle
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash


def _principle_signature(value) -> str:
    return content_hash(
        {
            "vertical_capability": value.vertical_capability,
            "when": value.when,
            "decision_mode": value.decision_mode,
            "decision": value.decision,
            "invariant": value.invariant,
            "scope": value.scope,
            "exceptions": value.exceptions,
        }
    )


def audit_maintenance(
    repository: KnowledgeRepository,
    *,
    max_principle_fanout: int = 12,
    max_exception_rate: float = 0.2,
) -> dict:
    skills, principles, _, edges = resolve_view(repository, None)
    invalidated = invalidated_refs(repository)
    signatures: dict[str, list[str]] = {}
    metrics = {}
    for principle in principles.values():
        signatures.setdefault(_principle_signature(principle), []).append(principle.id)
        metrics[principle.id] = principle_metrics(
            repository, principle, invalidated=invalidated
        )

    merge_candidates = [
        {
            "principle_ids": sorted(ids),
            "reason": "equivalent rule, scope, exceptions, and invariant",
        }
        for ids in signatures.values()
        if len(ids) > 1
    ]
    split_candidates = []
    for principle_id, metric in sorted(metrics.items()):
        signals = []
        if metric.operational_fanout > max_principle_fanout:
            signals.append(f"operational-fanout:{metric.operational_fanout}")
        if metric.exception_rate > max_exception_rate:
            signals.append(f"exception-rate:{metric.exception_rate:.3f}")
        if signals:
            split_candidates.append({"principle_id": principle_id, "signals": signals})

    conflicts = [
        {
            "edge_id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "guard": edge.guard,
        }
        for edge in sorted(edges.values(), key=lambda value: value.id)
        if edge.kind == "contradicts"
    ]
    prune_candidates: list[dict[str, Any]] = []
    nodes: list[CanonicalSkill | Principle] = [*skills.values(), *principles.values()]
    for node in nodes:
        reasons = []
        if node.status in {"rejected", "deprecated"}:
            reasons.append(f"status:{node.status}")
        if node.id in invalidated:
            reasons.append("invalidated-from-runtime")
        if reasons:
            prune_candidates.append(
                {
                    "id": node.id,
                    "revision": node.version,
                    "reasons": reasons,
                    "action": "remove-from-active-view; preserve revision and evidence",
                }
            )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "merge_candidates": sorted(merge_candidates, key=lambda value: value["principle_ids"]),
        "split_candidates": split_candidates,
        "conflicts": conflicts,
        "prune_candidates": sorted(prune_candidates, key=lambda value: value["id"]),
        "invalidated_refs": sorted(invalidated),
        "destructive_changes_performed": False,
    }
    return {**payload, "audit_hash": content_hash(payload)}
