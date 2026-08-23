# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic read-only projections of the authoritative forest."""

from __future__ import annotations

from .forest import descendants, lineage, validate_forest
from .models import KnowledgeManifest
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash


def vertical_forest(
    repository: KnowledgeRepository,
    *,
    manifest: KnowledgeManifest | None = None,
    vertical: str | None = None,
    task_family: str | None = None,
) -> dict:
    skills, principles, trees, edges = resolve_view(
        repository, manifest, active_overlay_only=True
    )
    validate_forest(
        list(trees.values()), list(skills.values()), list(principles.values()), list(edges.values())
    ).require_ok()
    instances = {value.id: value for value in repository.list_instances()}
    views = []
    for tree in sorted(trees.values(), key=lambda value: value.id):
        if vertical and tree.vertical_capability != vertical:
            continue
        node_ids = set(tree.parent_by_child) | set(tree.parent_by_child.values())
        node_ids.discard(tree.structural_root)
        skill_ids = sorted(node_ids & set(skills))
        principle_ids = sorted(node_ids & set(principles))
        if task_family:
            skill_ids = [
                skill_id
                for skill_id in skill_ids
                if not skills[skill_id].scope.task_families
                or task_family in skills[skill_id].scope.task_families
            ]
            principle_ids = [
                principle_id
                for principle_id in principle_ids
                if (
                    not principles[principle_id].scope.task_families
                    or task_family in principles[principle_id].scope.task_families
                )
                and any(
                    child in skill_ids for child in descendants(tree, principle_id)
                )
            ]
        visible_nodes = set(skill_ids) | set(principle_ids)
        instance_ids = {
            instance_id
            for skill_id in skill_ids
            for instance_id in skills[skill_id].instance_ids
            if instance_id in instances
            and (not task_family or instances[instance_id].task_family == task_family)
        }
        depths = [len(lineage(tree, node_id)) - 1 for node_id in visible_nodes]
        views.append(
            {
                "tree_id": tree.id,
                "tree_version": tree.version,
                "checkpoint_id": tree.checkpoint_id,
                "vertical_capability": tree.vertical_capability,
                "structural_root": tree.structural_root,
                "principle_ids": principle_ids,
                "skill_ids": skill_ids,
                "instance_count": len(instance_ids),
                "max_depth": max(depths, default=0),
                "compression_ratio": (
                    len(instance_ids) / (len(skill_ids) + len(principle_ids))
                    if skill_ids or principle_ids
                    else 0.0
                ),
                "parent_by_child": {
                    child: parent
                    for child, parent in sorted(tree.parent_by_child.items())
                    if child in visible_nodes
                    and parent in set(principle_ids) | {tree.structural_root}
                },
            }
        )
    payload = {
        "schema_version": 1,
        "manifest_id": f"{manifest.id}@{manifest.version}" if manifest else None,
        "task_family": task_family,
        "trees": views,
    }
    return {**payload, "projection_hash": content_hash(payload)}


def overlay_view(
    repository: KnowledgeRepository, *, manifest: KnowledgeManifest | None = None
) -> dict:
    _, _, _, edges = resolve_view(repository, manifest, active_overlay_only=True)
    materialized_edges = [
        {
            "id": value.id,
            "version": value.version,
            "kind": value.kind,
            "source_id": value.source_id,
            "target_id": value.target_id,
            "source_version": value.source_version,
            "target_version": value.target_version,
            "guard": value.guard,
            "rationale": value.rationale,
        }
        for value in sorted(edges.values(), key=lambda value: value.id)
    ]
    outgoing_by_node: dict[str, list[str]] = {}
    incoming_by_node: dict[str, list[str]] = {}
    for edge in materialized_edges:
        outgoing_by_node.setdefault(str(edge["source_id"]), []).append(str(edge["id"]))
        incoming_by_node.setdefault(str(edge["target_id"]), []).append(str(edge["id"]))
    payload = {
        "schema_version": 1,
        "manifest_id": f"{manifest.id}@{manifest.version}" if manifest else None,
        "edges": materialized_edges,
        "outgoing_by_node": {key: sorted(value) for key, value in sorted(outgoing_by_node.items())},
        "incoming_by_node": {key: sorted(value) for key, value in sorted(incoming_by_node.items())},
    }
    return {**payload, "projection_hash": content_hash(payload)}


def lineage_view(
    repository: KnowledgeRepository,
    ref: str,
    *,
    manifest: KnowledgeManifest | None = None,
) -> dict:
    skills, principles, trees, _ = resolve_view(repository, manifest)
    instances = {value.id: value for value in repository.list_instances()}
    if ref not in skills and ref not in principles and ref not in instances:
        raise ValueError(f"knowledge reference not found: {ref}")
    skill_ids = {ref} if ref in skills else set()
    paths = []
    if ref in principles:
        for tree in trees.values():
            if ref in tree.parent_by_child or ref in tree.parent_by_child.values():
                paths.append(lineage(tree, ref))
                skill_ids.update(node for node in descendants(tree, ref) if node in skills)
    instance_ids = {ref} if ref in instances else set()
    for skill_id in skill_ids:
        instance_ids.update(skills[skill_id].instance_ids)
    payload = {
        "schema_version": 1,
        "ref": ref,
        "tree_paths": sorted(paths),
        "skill_ids": sorted(skill_ids),
        "instance_ids": sorted(instance_ids),
        "source_paths": sorted(
            instances[value].source_code_path for value in instance_ids if value in instances
        ),
    }
    return {**payload, "projection_hash": content_hash(payload)}
