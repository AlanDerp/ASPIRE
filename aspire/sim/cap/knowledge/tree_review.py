# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Review and promotion evidence for immutable vertical-tree revisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .forest import validate_forest
from .models import KnowledgeManifest, VerticalTree, model_to_dict
from .repository import KnowledgeRepository
from .serialization import content_hash, load_structured


def _nodes(tree: VerticalTree) -> set[str]:
    return set(tree.parent_by_child) | (
        set(tree.parent_by_child.values()) - {tree.structural_root}
    )


def validate_tree_proposal(
    repository: KnowledgeRepository, tree: VerticalTree
) -> None:
    repository.load_checkpoint(tree.checkpoint_id)
    available = repository.all_node_ids()
    missing = sorted(_nodes(tree) - available)
    if missing:
        raise ValueError(f"tree proposal references missing nodes: {missing}")
    trees = {
        value.id: value for value in repository.list_trees() if value.id != tree.id
    }
    trees[tree.id] = tree
    validate_forest(
        list(trees.values()),
        repository.list_skills(),
        repository.list_principles(),
        repository.list_edges(),
    ).require_ok()


def _validate_manifest_binding(
    tree: VerticalTree, manifest: KnowledgeManifest
) -> dict[str, str]:
    if manifest.source_partition != "development":
        raise ValueError("held-out manifests cannot authorize tree review")
    if manifest.checkpoint_id != tree.checkpoint_id:
        raise ValueError("tree review manifest checkpoint does not match proposal")
    node_versions = {**manifest.skill_versions, **manifest.principle_versions}
    missing = sorted(_nodes(tree) - set(node_versions))
    if missing:
        raise ValueError(f"tree review manifest does not lock nodes: {missing}")
    return {node_id: node_versions[node_id] for node_id in sorted(_nodes(tree))}


def _validate_placement_report(
    report: dict[str, Any],
    tree: VerticalTree,
    principle_id: str,
    principle_version: str,
) -> None:
    unsigned = {key: value for key, value in report.items() if key != "placement_hash"}
    if report.get("placement_hash") != content_hash(unsigned):
        raise ValueError(f"placement report hash mismatch: {principle_id}")
    expected = {
        "principle_id": principle_id,
        "principle_version": principle_version,
        "tree_id": tree.id,
        "tree_version": tree.version,
        "checkpoint_id": tree.checkpoint_id,
        "primary_parent": tree.parent_by_child.get(principle_id),
        "accepted_for_review": True,
        "mutation_performed": False,
        "potential_cycle": False,
    }
    mismatches = [key for key, value in expected.items() if report.get(key) != value]
    if mismatches or report.get("validation_issues"):
        raise ValueError(
            f"placement report does not bind an accepted tree placement: "
            f"{principle_id}:{mismatches}"
        )


def prepare_tree_review(
    repository: KnowledgeRepository,
    tree: VerticalTree,
    manifest: KnowledgeManifest,
    raw_review: dict[str, Any],
) -> dict[str, Any]:
    """Validate and internalize placement artifacts for one tree review."""
    required = (
        "decision",
        "reviewer",
        "reviewed_at",
        "rationale",
        "tree_hash",
        "checkpoint_id",
        "manifest_id",
        "manifest_version",
        "manifest_hash",
        "placement_reports",
    )
    missing = [
        key
        for key in required
        if key not in raw_review or raw_review[key] in (None, "")
    ]
    if missing:
        raise ValueError(f"tree review is incomplete: {missing}")
    if not str(raw_review["reviewer"]).strip() or not str(
        raw_review["rationale"]
    ).strip():
        raise ValueError("tree review requires a reviewer and rationale")
    if raw_review["decision"] != "accept":
        raise ValueError("only an accepted tree review can be promoted")

    node_versions = _validate_manifest_binding(tree, manifest)
    expected = {
        "tree_hash": content_hash(model_to_dict(tree)),
        "checkpoint_id": tree.checkpoint_id,
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_hash": content_hash(model_to_dict(manifest)),
    }
    mismatches = [key for key, value in expected.items() if raw_review.get(key) != value]
    if mismatches:
        raise ValueError(f"tree review does not bind proposal exactly: {mismatches}")

    raw_placements = raw_review["placement_reports"]
    if not isinstance(raw_placements, dict):
        raise ValueError("tree review placement_reports must be an object")
    principle_ids = sorted(set(tree.parent_by_child) & set(manifest.principle_versions))
    if set(raw_placements) != set(principle_ids):
        raise ValueError(
            "tree review must cover every placed principle exactly; "
            f"expected={principle_ids} actual={sorted(raw_placements)}"
        )

    loaded_reports: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, str]] = {}
    for principle_id in principle_ids:
        path = Path(str(raw_placements[principle_id]))
        report = load_structured(path)
        _validate_placement_report(
            report,
            tree,
            principle_id,
            manifest.principle_versions[principle_id],
        )
        artifact_hash = content_hash(report)
        loaded_reports[principle_id] = report
        bindings[principle_id] = {
            "artifact": f"proposals/tree-placement/{artifact_hash}.yaml",
            "artifact_hash": artifact_hash,
            "placement_hash": str(report["placement_hash"]),
        }

    for principle_id, report in loaded_reports.items():
        repository.save_audit(
            "tree-placement",
            bindings[principle_id]["artifact_hash"],
            report,
        )
    return {
        "schema_version": 1,
        "decision": "accept",
        "reviewer": str(raw_review["reviewer"]),
        "reviewed_at": str(raw_review["reviewed_at"]),
        "rationale": str(raw_review["rationale"]).strip(),
        **expected,
        "node_versions": node_versions,
        "placement_reports": bindings,
    }


def validate_tree_review(
    repository: KnowledgeRepository,
    tree: VerticalTree,
    review_hash: str,
    *,
    manifests: dict[tuple[str, str], KnowledgeManifest] | None = None,
    lifecycle_events: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    review = repository.load_audit("tree-review", review_hash)
    manifest_ref = (str(review["manifest_id"]), str(review["manifest_version"]))
    manifest = (
        manifests.get(manifest_ref)
        if manifests is not None
        else repository.load_manifest(*manifest_ref)
    )
    if manifest is None:
        raise ValueError(f"tree review base manifest is missing: {manifest_ref}")
    node_versions = _validate_manifest_binding(tree, manifest)
    expected = {
        "tree_hash": content_hash(model_to_dict(tree)),
        "checkpoint_id": tree.checkpoint_id,
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_hash": content_hash(model_to_dict(manifest)),
        "node_versions": node_versions,
    }
    mismatches = [key for key, value in expected.items() if review.get(key) != value]
    if review.get("decision") != "accept" or mismatches:
        raise ValueError(f"stored tree review does not bind proposal: {mismatches}")

    bindings = review.get("placement_reports")
    principle_ids = sorted(set(tree.parent_by_child) & set(manifest.principle_versions))
    if not isinstance(bindings, dict) or set(bindings) != set(principle_ids):
        raise ValueError("stored tree review placement coverage mismatch")
    for principle_id in principle_ids:
        binding = bindings[principle_id]
        artifact_hash = str(binding["artifact_hash"])
        if binding.get("artifact") != f"proposals/tree-placement/{artifact_hash}.yaml":
            raise ValueError("tree placement artifact path is not content-addressed")
        report = repository.load_audit("tree-placement", artifact_hash)
        if report.get("placement_hash") != binding.get("placement_hash"):
            raise ValueError("tree placement binding hash mismatch")
        _validate_placement_report(
            report,
            tree,
            principle_id,
            manifest.principle_versions[principle_id],
        )

    events = (
        lifecycle_events
        if lifecycle_events is not None
        else list(repository.iter_evidence("lifecycle"))
    )
    reviewed_event = {
        "subject": tree.id,
        "version": tree.version,
        "tree_hash": expected["tree_hash"],
        "checkpoint_id": tree.checkpoint_id,
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_hash": expected["manifest_hash"],
        "review_artifact_hash": review_hash,
    }
    if not any(
        event.get("event") == "knowledge.tree-reviewed"
        and all(event.get(key) == value for key, value in reviewed_event.items())
        for event in events
    ):
        raise ValueError("tree review lacks an exact lifecycle event")
    return review


def tree_revision_promoted(
    repository: KnowledgeRepository,
    tree: VerticalTree,
    *,
    manifests: dict[tuple[str, str], KnowledgeManifest] | None = None,
    lifecycle_events: list[dict[str, object]] | None = None,
) -> bool:
    events = (
        lifecycle_events
        if lifecycle_events is not None
        else list(repository.iter_evidence("lifecycle"))
    )
    candidates = [
        event
        for event in events
        if event.get("event") == "knowledge.tree-validated"
        and event.get("subject") == tree.id
        and event.get("version") == tree.version
        and event.get("tree_hash") == content_hash(model_to_dict(tree))
        and event.get("checkpoint_id") == tree.checkpoint_id
        and event.get("review_artifact_hash")
    ]
    for event in candidates:
        try:
            review = validate_tree_review(
                repository,
                tree,
                str(event["review_artifact_hash"]),
                manifests=manifests,
                lifecycle_events=events,
            )
        except (KeyError, OSError, TypeError, ValueError):
            continue
        expected = {
            "manifest_id": review["manifest_id"],
            "manifest_version": review["manifest_version"],
            "manifest_hash": review["manifest_hash"],
            "reviewer": review["reviewer"],
        }
        if all(event.get(key) == value for key, value in expected.items()):
            return True
    return False
