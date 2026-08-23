# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read-only vertical-tree placement analysis for principle revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .forest import descendants, lineage, validate_forest
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
    operational_skills = {
        child_id
        for child_id in descendants(simulated_tree, principle.id)
        if child_id in skills
    }
    operational_descendants = {
        child_id
        for child_id in operational_skills
        if skills[child_id].status in {"candidate", "validated", "stable"}
    }
    fanout_limit = principle.quality_policy.max_operational_fanout
    hub_overflow = len(operational_descendants) > fanout_limit
    validation_issues = [
        {
            "code": issue.code,
            "subject": issue.subject,
            "message": issue.message,
        }
        for issue in report.issues
    ]
    if hub_overflow:
        validation_issues.append(
            {
                "code": "principle-hub-overflow",
                "subject": principle.id,
                "message": (
                    f"operational fan-out {len(operational_descendants)} "
                    f"exceeds {fanout_limit}; split before review"
                ),
            }
        )
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
        "active_operational_children": len(operational_descendants),
        "operational_fanout_limit": fanout_limit,
        "hub_overflow": hub_overflow,
        "operational_coverage": (
            len(operational_descendants) / len(operational_skills)
            if operational_skills
            else 0.0
        ),
        "reparented_children": reparented_children,
        "potential_cycle": any(issue.code == "tree-cycle" for issue in report.issues),
        "validation_issues": validation_issues,
        "accepted_for_review": report.ok and not hub_overflow,
        "mutation_performed": False,
    }
    return {**payload, "placement_hash": content_hash(payload)}
