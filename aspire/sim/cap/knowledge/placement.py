# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read-only vertical-tree placement analysis for principle revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .forest import lineage, validate_forest
from .models import Principle, VerticalTree
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash


def analyze_placement(
    repository: KnowledgeRepository,
    principle: Principle,
    tree: VerticalTree,
    parent_id: str,
) -> dict[str, Any]:
    """Simulate placement and report identity, fan-out, coverage, and cycles."""
    skills, principles, trees, edges = resolve_view(repository, None)
    if principle.vertical_capability != tree.vertical_capability:
        raise ValueError("principle and tree vertical capabilities do not match")
    if principle.provenance.get("checkpoint_id") != tree.checkpoint_id:
        raise ValueError("principle and tree checkpoints do not match")
    if parent_id != tree.structural_root:
        parent = principles.get(parent_id)
        if parent is None:
            raise ValueError("placement parent must be the structural root or a principle")
        if parent.vertical_capability != tree.vertical_capability:
            raise ValueError("placement parent belongs to another vertical capability")

    simulated_parents = dict(tree.parent_by_child)
    previous_parent = simulated_parents.get(principle.id)
    simulated_parents[principle.id] = parent_id
    reparented_children = {
        child_id: simulated_parents.get(child_id)
        for child_id in principle.child_ids
        if simulated_parents.get(child_id) not in {None, principle.id}
    }
    for child_id in principle.child_ids:
        simulated_parents[child_id] = principle.id
    simulated_tree = replace(tree, parent_by_child=simulated_parents)
    simulated_trees = [
        simulated_tree if value.id == tree.id else value for value in trees.values()
    ]
    report = validate_forest(
        simulated_trees,
        list(skills.values()),
        list(principles.values()),
        list(edges.values()),
    )
    placement_lineage: tuple[str, ...] = ()
    if not any(issue.code == "tree-cycle" for issue in report.issues):
        placement_lineage = lineage(simulated_tree, principle.id)
    active_children = [
        child_id
        for child_id in principle.child_ids
        if child_id in skills
        and skills[child_id].status in {"candidate", "validated", "stable"}
    ]
    payload = {
        "schema_version": 1,
        "principle_id": principle.id,
        "principle_version": principle.version,
        "tree_id": tree.id,
        "tree_version": tree.version,
        "checkpoint_id": tree.checkpoint_id,
        "primary_parent": parent_id,
        "previous_parent": previous_parent,
        "depth": max(0, len(placement_lineage) - 1) if placement_lineage else None,
        "direct_fanout": len(principle.child_ids),
        "active_operational_children": len(active_children),
        "operational_coverage": (
            len(active_children) / len(principle.child_ids)
            if principle.child_ids
            else 0.0
        ),
        "reparented_children": reparented_children,
        "potential_cycle": any(issue.code == "tree-cycle" for issue in report.issues),
        "validation_issues": [
            {
                "code": issue.code,
                "subject": issue.subject,
                "message": issue.message,
            }
            for issue in report.issues
        ],
        "accepted_for_review": report.ok,
        "mutation_performed": False,
    }
    return {**payload, "placement_hash": content_hash(payload)}
