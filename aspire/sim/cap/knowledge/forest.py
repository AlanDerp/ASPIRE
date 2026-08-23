# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validation and traversal for vertical trees plus overlay relations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CanonicalSkill, OverlayEdge, Principle, VerticalTree


def _version_key(value: str) -> tuple[int, int, int]:
    parts = tuple(int(part) for part in value.split("."))
    return parts[0], parts[1], parts[2]


def _latest(values: list[Any]) -> list[Any]:
    """Materialize one active revision per logical id for validation."""
    result = {}
    for value in sorted(values, key=lambda item: (item.id, _version_key(item.version))):
        result[value.id] = value
    return list(result.values())


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    subject: str


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def require_ok(self) -> None:
        if self.issues:
            details = "; ".join(f"{issue.code}:{issue.subject}" for issue in self.issues)
            raise ValueError(f"knowledge forest validation failed: {details}")


def validate_forest(
    trees: list[VerticalTree],
    skills: list[CanonicalSkill],
    principles: list[Principle],
    edges: list[OverlayEdge],
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    trees = _latest(trees)
    skills = _latest(skills)
    principles = _latest(principles)
    edges = _latest(edges)
    node_by_id: dict[str, CanonicalSkill | Principle] = {
        value.id: value for value in skills
    }
    node_by_id.update({value.id: value for value in principles})
    if set(value.id for value in skills) & set(value.id for value in principles):
        issues.append(ValidationIssue("duplicate-node-id", "logical node ids must be unique", "forest"))

    seen_children: dict[str, str] = {}
    for tree in trees:
        referenced_nodes = set(tree.parent_by_child) | (
            set(tree.parent_by_child.values()) - {tree.structural_root}
        )
        missing_primary_parents = referenced_nodes - set(tree.parent_by_child)
        for node_id in sorted(missing_primary_parents):
            issues.append(
                ValidationIssue(
                    "missing-primary-parent",
                    "every non-structural tree node must have one primary parent",
                    node_id,
                )
            )
        if any(
            node_id in node_by_id
            and node_by_id[node_id].vertical_capability != tree.vertical_capability
            for node_id in referenced_nodes
        ):
            issues.append(
                ValidationIssue(
                    "cross-vertical-membership",
                    "tree parent or child belongs to another vertical",
                    tree.id,
                )
            )
        for child, parent in tree.parent_by_child.items():
            if child not in node_by_id:
                issues.append(ValidationIssue("dangling-child", "tree child does not exist", child))
            if parent != tree.structural_root and parent not in node_by_id:
                issues.append(ValidationIssue("dangling-parent", "tree parent does not exist", parent))
            previous = seen_children.get(child)
            if previous is not None and previous != tree.id:
                issues.append(ValidationIssue("multiple-primary-parents", "child appears in two trees", child))
            seen_children[child] = tree.id

        for start in tree.parent_by_child:
            visited: set[str] = set()
            current = start
            while current in tree.parent_by_child:
                if current in visited:
                    issues.append(ValidationIssue("tree-cycle", "primary parent cycle detected", start))
                    break
                visited.add(current)
                current = tree.parent_by_child[current]

    for principle in principles:
        actual_children = {
            child
            for tree in trees
            for child, parent in tree.parent_by_child.items()
            if parent == principle.id
        }
        missing = set(principle.child_ids) - actual_children
        unexpected = actual_children - set(principle.child_ids)
        if missing or unexpected:
            issues.append(
                ValidationIssue(
                    "principle-child-mismatch",
                    (
                        f"missing from tree: {sorted(missing)}; "
                        f"undeclared direct children: {sorted(unexpected)}"
                    ),
                    principle.id,
                )
            )

    for edge in edges:
        if edge.source_id not in node_by_id:
            issues.append(ValidationIssue("dangling-edge-source", "overlay source missing", edge.id))
        elif node_by_id[edge.source_id].version != edge.source_version:
            issues.append(
                ValidationIssue(
                    "edge-source-version-mismatch",
                    "overlay source revision does not match the materialized node",
                    edge.id,
                )
            )
        if edge.target_id not in node_by_id:
            issues.append(ValidationIssue("dangling-edge-target", "overlay target missing", edge.id))
        elif node_by_id[edge.target_id].version != edge.target_version:
            issues.append(
                ValidationIssue(
                    "edge-target-version-mismatch",
                    "overlay target revision does not match the materialized node",
                    edge.id,
                )
            )
    return ValidationReport(tuple(issues))


def descendants(tree: VerticalTree, node_id: str) -> tuple[str, ...]:
    children: dict[str, list[str]] = {}
    for child, parent in tree.parent_by_child.items():
        children.setdefault(parent, []).append(child)
    result: list[str] = []
    pending = list(reversed(sorted(children.get(node_id, []))))
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(reversed(sorted(children.get(current, []))))
    return tuple(result)


def lineage(tree: VerticalTree, node_id: str) -> tuple[str, ...]:
    result = [node_id]
    current = node_id
    while current in tree.parent_by_child:
        current = tree.parent_by_child[current]
        result.append(current)
    return tuple(reversed(result))
