# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Review and promotion gates for cross-tree overlay revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import KnowledgeManifest, OverlayEdge, model_to_dict, validate_version
from .repository import KnowledgeRepository
from .serialization import content_hash


def _newer(candidate: str, previous: str) -> str:
    validate_version(candidate)
    if tuple(map(int, candidate.split("."))) <= tuple(map(int, previous.split("."))):
        raise ValueError(f"new revision {candidate} must be newer than {previous}")
    return candidate


def _node_versions(repository: KnowledgeRepository) -> dict[str, set[str]]:
    revisions: dict[str, set[str]] = {}
    for skill in repository.list_skills():
        revisions.setdefault(skill.id, set()).add(skill.version)
    for principle in repository.list_principles():
        revisions.setdefault(principle.id, set()).add(principle.version)
    return revisions


def validate_overlay_proposal(
    repository: KnowledgeRepository, edge: OverlayEdge
) -> None:
    """Require an unreviewed proposal grounded in exact existing revisions."""
    if edge.status != "proposal" or not edge.review_required:
        raise ValueError("overlay propose accepts only a review-required proposal")
    if edge.kind == "exception-to" and not edge.guard:
        raise ValueError("exception-to overlay proposals require an explicit guard")
    checkpoint_id = str(edge.provenance["checkpoint_id"])
    repository.load_checkpoint(checkpoint_id)
    revisions = _node_versions(repository)
    missing = [
        f"{node_id}@{version}"
        for node_id, version in (
            (edge.source_id, edge.source_version),
            (edge.target_id, edge.target_version),
        )
        if version not in revisions.get(node_id, set())
    ]
    if missing:
        raise ValueError(f"overlay proposal references missing node revisions: {missing}")


def validate_overlay_manifest_binding(
    edge: OverlayEdge, manifest: KnowledgeManifest
) -> None:
    if manifest.source_partition != "development":
        raise ValueError("held-out manifests cannot authorize overlay review")
    checkpoint_id = str(edge.provenance["checkpoint_id"])
    if manifest.checkpoint_id != checkpoint_id:
        raise ValueError("overlay review manifest checkpoint does not match proposal")
    locked = {**manifest.skill_versions, **manifest.principle_versions}
    mismatches = [
        f"{node_id}@{version}"
        for node_id, version in (
            (edge.source_id, edge.source_version),
            (edge.target_id, edge.target_version),
        )
        if locked.get(node_id) != version
    ]
    if mismatches:
        raise ValueError(
            f"overlay review manifest does not lock endpoint revisions: {mismatches}"
        )


def review_overlay_edge(
    proposal: OverlayEdge,
    review: dict[str, Any],
    manifest: KnowledgeManifest,
    *,
    version: str,
) -> OverlayEdge:
    if proposal.status != "proposal" or not proposal.review_required:
        raise ValueError("only a review-required overlay proposal can enter review")
    validate_overlay_manifest_binding(proposal, manifest)
    required = (
        "decision",
        "reviewer",
        "reviewed_at",
        "rationale",
        "proposal_hash",
        "checkpoint_id",
        "manifest_id",
        "manifest_version",
        "manifest_hash",
        "kind",
        "source_id",
        "source_version",
        "target_id",
        "target_version",
        "guard",
    )
    missing = [key for key in required if key not in review or review[key] in (None, "")]
    if missing:
        raise ValueError(f"overlay review is incomplete: {missing}")
    if not str(review["reviewer"]).strip() or not str(review["rationale"]).strip():
        raise ValueError("overlay review requires a reviewer and rationale")
    if review["decision"] != "accept":
        raise ValueError("only an accepted overlay review can create a candidate")

    expected = {
        "proposal_hash": content_hash(model_to_dict(proposal)),
        "checkpoint_id": proposal.provenance["checkpoint_id"],
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_hash": content_hash(model_to_dict(manifest)),
        "kind": proposal.kind,
        "source_id": proposal.source_id,
        "source_version": proposal.source_version,
        "target_id": proposal.target_id,
        "target_version": proposal.target_version,
        "guard": proposal.guard,
    }
    mismatches = [key for key, value in expected.items() if review.get(key) != value]
    if mismatches:
        raise ValueError(f"overlay review does not bind proposal exactly: {mismatches}")

    review_hash = content_hash(review)
    return replace(
        proposal,
        version=_newer(version, proposal.version),
        rationale=str(review["rationale"]).strip(),
        status="candidate",
        review_required=False,
        provenance={
            **proposal.provenance,
            "reviewer": str(review["reviewer"]),
            "reviewed_at": str(review["reviewed_at"]),
            "review_artifact": f"proposals/overlay-review/{review_hash}.yaml",
            "review_artifact_hash": review_hash,
            **{key: expected[key] for key in expected},
        },
    )


def promote_overlay_edge(candidate: OverlayEdge, *, version: str) -> OverlayEdge:
    if candidate.status != "candidate" or candidate.review_required:
        raise ValueError("only a reviewed overlay candidate can be promoted")
    return replace(
        candidate,
        version=_newer(version, candidate.version),
        status="validated",
        provenance={
            **candidate.provenance,
            "candidate_version": candidate.version,
        },
    )


def validate_overlay_evidence(
    repository: KnowledgeRepository,
    edge: OverlayEdge,
    *,
    edge_revisions: list[OverlayEdge] | None = None,
    manifests: dict[tuple[str, str], KnowledgeManifest] | None = None,
) -> None:
    """Rebuild the complete proposal → review → candidate evidence chain."""
    review_hash = str(edge.provenance["review_artifact_hash"])
    expected_path = f"proposals/overlay-review/{review_hash}.yaml"
    if edge.provenance.get("review_artifact") != expected_path:
        raise ValueError("overlay review artifact path is not content-addressed")
    review = repository.load_audit("overlay-review", review_hash)

    revisions = edge_revisions if edge_revisions is not None else repository.list_edges()
    proposals = [
        value
        for value in revisions
        if value.id == edge.id
        and value.status == "proposal"
        and content_hash(model_to_dict(value)) == edge.provenance.get("proposal_hash")
    ]
    if len(proposals) != 1:
        raise ValueError("overlay evidence does not identify exactly one proposal")
    proposal = proposals[0]

    manifest_ref = (
        str(edge.provenance["manifest_id"]),
        str(edge.provenance["manifest_version"]),
    )
    manifest = (
        manifests.get(manifest_ref)
        if manifests is not None
        else repository.load_manifest(*manifest_ref)
    )
    if manifest is None:
        raise ValueError(f"overlay review base manifest is missing: {manifest_ref}")
    if content_hash(model_to_dict(manifest)) != edge.provenance.get("manifest_hash"):
        raise ValueError("overlay review base manifest hash mismatch")
    validate_overlay_manifest_binding(proposal, manifest)

    immutable_fields = (
        "kind",
        "source_id",
        "source_version",
        "target_id",
        "target_version",
        "guard",
    )
    if any(getattr(edge, field) != getattr(proposal, field) for field in immutable_fields):
        raise ValueError("promoted overlay relation differs from its proposal")
    expected_review = {
        "proposal_hash": content_hash(model_to_dict(proposal)),
        "checkpoint_id": proposal.provenance["checkpoint_id"],
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_hash": content_hash(model_to_dict(manifest)),
        **{field: getattr(proposal, field) for field in immutable_fields},
    }
    if review.get("decision") != "accept" or any(
        review.get(key) != value for key, value in expected_review.items()
    ):
        raise ValueError("stored overlay review does not bind its proposal")
    if (
        review.get("reviewer") != edge.provenance.get("reviewer")
        or review.get("reviewed_at") != edge.provenance.get("reviewed_at")
    ):
        raise ValueError("overlay reviewer provenance mismatch")

    if edge.status in {"validated", "stable"}:
        candidate_provenance = dict(edge.provenance)
        candidate_version = str(candidate_provenance.pop("candidate_version"))
        expected_candidate = replace(
            edge,
            version=candidate_version,
            status="candidate",
            provenance=candidate_provenance,
        )
        candidates = [
            value
            for value in revisions
            if value.id == edge.id
            and content_hash(model_to_dict(value))
            == content_hash(model_to_dict(expected_candidate))
        ]
        if len(candidates) != 1:
            raise ValueError("promoted overlay lacks exactly one reviewed candidate")
