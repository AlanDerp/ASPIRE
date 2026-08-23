# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Repository-wide validation beyond tree topology."""

from __future__ import annotations

from .checkpoints import instances_at_checkpoint
from .forest import ValidationIssue, ValidationReport, descendants, validate_forest
from .lifecycle import (
    overlay_revision_promoted,
    principle_metrics,
    validated_revisions,
)
from .models import Checkpoint, ConsolidationPolicy, KnowledgeManifest
from .repository import KnowledgeRepository
from .repetition import (
    PrincipleRepetitionReport,
    RepetitionReport,
    audit_principle_repetition,
    audit_repetition,
)
from .retrieval import resolve_view
from .serialization import content_hash


def validate_repository(repository: KnowledgeRepository, *, max_principle_fanout: int = 12) -> ValidationReport:
    issues: list[ValidationIssue] = []
    skills, principles, trees, edges = resolve_view(repository, None)
    issues.extend(
        validate_forest(
            list(trees.values()),
            list(skills.values()),
            list(principles.values()),
            list(edges.values()),
        ).issues
    )
    checkpoints: dict[str, Checkpoint] = {}
    for checkpoint_path in sorted((repository.root / "checkpoints").glob("*.yaml")):
        checkpoint_id = checkpoint_path.stem
        try:
            frozen_checkpoint = repository.load_checkpoint(checkpoint_id)
            instances_at_checkpoint(repository, frozen_checkpoint)
            checkpoints[checkpoint_id] = frozen_checkpoint
        except (OSError, ValueError) as error:
            issues.append(ValidationIssue("invalid-checkpoint", str(error), checkpoint_id))

    membership: dict[str, str] = {}
    instances = {value.id: value for value in repository.list_instances()}
    for instance in instances.values():
        if instance.provenance.get("partition", "development") != "development":
            issues.append(
                ValidationIssue(
                    "held-out-promotion-evidence",
                    "held-out evidence cannot enter the consolidation source",
                    instance.id,
                )
            )
    for skill in skills.values():
        checkpoint_id = str(skill.provenance.get("checkpoint_id", ""))
        checkpoint = checkpoints.get(checkpoint_id)
        if checkpoint is None:
            issues.append(
                ValidationIssue("missing-skill-checkpoint", "skill checkpoint is missing", skill.id)
            )
        elif not set(skill.instance_ids) <= set(checkpoint.instance_ids):
            issues.append(
                ValidationIssue(
                    "skill-outside-checkpoint",
                    "skill instances are not all frozen in its checkpoint",
                    skill.id,
                )
            )
        if not skill.provenance.get("repetition_cluster_id"):
            issues.append(
                ValidationIssue(
                    "missing-repetition-audit",
                    "canonical skill has no repetition-cluster provenance",
                    skill.id,
                )
            )
        if checkpoint is not None:
            try:
                recorded_hash = str(
                    skill.provenance.get("instance_repetition_report_hash", "")
                )
                audit_payload = repository.load_audit(
                    "instance-repetition",
                    recorded_hash,
                )
                recorded_instance_audit = RepetitionReport.from_dict(audit_payload)
                instance_policy = ConsolidationPolicy.from_dict(
                    recorded_instance_audit.policy
                )
                checkpoint_instances = instances_at_checkpoint(repository, checkpoint)
                recomputed_instance_audit = audit_repetition(
                    checkpoint_instances,
                    checkpoint,
                    instance_policy,
                )
                cluster_id = str(skill.provenance.get("repetition_cluster_id", ""))
                cluster = next(
                    (
                        value
                        for value in recomputed_instance_audit.clusters
                        if value.id == cluster_id
                    ),
                    None,
                )
                if (
                    content_hash(audit_payload) != recorded_hash
                    or recomputed_instance_audit.content_hash != recorded_hash
                    or cluster is None
                    or not cluster.accepted
                    or set(cluster.instance_ids) != set(skill.instance_ids)
                ):
                    raise ValueError("recorded audit does not match canonical skill members")
            except (KeyError, OSError, TypeError, ValueError) as error:
                issues.append(
                    ValidationIssue(
                        "invalid-instance-repetition-audit",
                        str(error),
                        skill.id,
                    )
                )
        for instance_id in skill.instance_ids:
            previous = membership.get(instance_id)
            if previous is not None and previous != skill.id:
                issues.append(
                    ValidationIssue(
                        "multiple-instance-membership",
                        "one instance belongs to multiple active canonical skills",
                        instance_id,
                    )
                )
            membership[instance_id] = skill.id

    placed_nodes = {
        node_id
        for tree in trees.values()
        for node_id in set(tree.parent_by_child) | set(tree.parent_by_child.values())
        if node_id != tree.structural_root
    }
    promoted_revisions = validated_revisions(repository)
    for skill in skills.values():
        if skill.status in {"candidate", "validated", "stable"} and skill.id not in placed_nodes:
            issues.append(
                ValidationIssue(
                    "unplaced-active-skill",
                    "active canonical skill is not in a vertical tree",
                    skill.id,
                )
            )

    for tree in trees.values():
        if tree.checkpoint_id not in checkpoints:
            issues.append(
                ValidationIssue(
                    "missing-tree-checkpoint", "tree checkpoint is missing", tree.id
                )
            )

    for principle in principles.values():
        checkpoint_id = str(principle.provenance.get("checkpoint_id", ""))
        checkpoint = checkpoints.get(checkpoint_id)
        if checkpoint is None:
            issues.append(
                ValidationIssue(
                    "missing-principle-checkpoint",
                    "principle checkpoint is missing",
                    principle.id,
                )
            )
        else:
            pending = list(principle.child_ids)
            visited: set[str] = set()
            supporting_skills: set[str] = set()
            while pending:
                child_id = pending.pop()
                if child_id in visited:
                    continue
                visited.add(child_id)
                if child_id in skills:
                    supporting_skills.add(child_id)
                elif child_id in principles:
                    pending.extend(principles[child_id].child_ids)
            outside_checkpoint = sorted(
                {
                    instance_id
                    for skill_id in supporting_skills
                    for instance_id in skills[skill_id].instance_ids
                    if instance_id not in checkpoint.instance_ids
                }
            )
            if outside_checkpoint:
                issues.append(
                    ValidationIssue(
                        "principle-child-outside-checkpoint",
                        f"support instances are not frozen: {outside_checkpoint}",
                        principle.id,
                    )
                )
            principle_audit_payload = principle.provenance.get(
                "canonical_repetition_audit"
            )
            try:
                if not isinstance(principle_audit_payload, dict):
                    raise ValueError("audit payload is not an object")
                recorded_principle_audit = PrincipleRepetitionReport.from_dict(
                    principle_audit_payload
                )
                principle_policy = ConsolidationPolicy.from_dict(
                    recorded_principle_audit.policy
                )
                versions = principle.provenance.get("canonical_skill_versions", {})
                if not isinstance(versions, dict):
                    raise ValueError("canonical_skill_versions is not an object")
                revisions = {
                    (value.id, value.version): value
                    for value in repository.list_skills()
                }
                audited_skills = [
                    revisions[(skill_id, str(versions[skill_id]))]
                    for skill_id in recorded_principle_audit.skill_ids
                ]
                recomputed_principle_audit = audit_principle_repetition(
                    audited_skills,
                    checkpoint,
                    principle_policy,
                )
                recorded_hash = str(
                    principle.provenance.get("canonical_repetition_audit_hash", "")
                )
                if (
                    content_hash(principle_audit_payload) != recorded_hash
                    or recomputed_principle_audit.content_hash != recorded_hash
                    or set(recorded_principle_audit.skill_ids)
                    != set(principle.child_ids)
                ):
                    raise ValueError("recorded audit does not match principle children")
            except (KeyError, TypeError, ValueError) as error:
                issues.append(
                    ValidationIssue(
                        "invalid-principle-repetition-audit",
                        str(error),
                        principle.id,
                    )
                )
        if principle.status in {"validated", "stable"} and principle.id not in placed_nodes:
            issues.append(
                ValidationIssue(
                    "unplaced-active-principle",
                    "actor-visible principle is not in a vertical tree",
                    principle.id,
                )
            )
        if (
            principle.status in {"validated", "stable"}
            and (principle.id, principle.version) not in promoted_revisions
        ):
            issues.append(
                ValidationIssue(
                    "unrecorded-principle-promotion",
                    "actor-visible principle lacks an exact revision promotion event",
                    principle.id,
                )
            )
        missing = set(principle.child_ids) - (set(skills) | set(principles))
        if missing:
            issues.append(
                ValidationIssue(
                    "missing-principle-child", f"missing logical children: {sorted(missing)}", principle.id
                )
            )
        cross_vertical = {
            child_id
            for child_id in principle.child_ids
            if child_id in skills
            and skills[child_id].vertical_capability != principle.vertical_capability
        }
        if cross_vertical:
            issues.append(
                ValidationIssue(
                    "cross-vertical-principle-child",
                    f"children cross verticals: {sorted(cross_vertical)}",
                    principle.id,
                )
            )
        metrics = principle_metrics(repository, principle)
        if principle.status in {"validated", "stable"} and metrics.support_sufficiency != "sufficient":
            issues.append(
                ValidationIssue(
                    "insufficient-principle-support",
                    f"materialized support is {metrics.support_sufficiency}",
                    principle.id,
                )
            )
        if metrics.operational_fanout > max_principle_fanout:
            issues.append(
                ValidationIssue(
                    "principle-hub-overflow",
                    f"fanout {metrics.operational_fanout} exceeds {max_principle_fanout}",
                    principle.id,
                )
            )

    edge_revisions = repository.list_edges()
    manifest_revisions: dict[tuple[str, str], KnowledgeManifest] = {
        (value.id, value.version): value for value in repository.list_manifests()
    }
    lifecycle_events = list(repository.iter_evidence("lifecycle"))
    for edge in edges.values():
        if (
            edge.status in {"validated", "stable"}
            and not overlay_revision_promoted(
                repository,
                edge,
                edge_revisions=edge_revisions,
                manifests=manifest_revisions,
                lifecycle_events=lifecycle_events,
            )
        ):
            issues.append(
                ValidationIssue(
                    "unrecorded-overlay-promotion",
                    "actor-visible overlay edge lacks an exact revision promotion event",
                    edge.id,
                )
            )
        if edge.kind == "exception-to" and not edge.guard:
            issues.append(
                ValidationIssue(
                    "unguarded-cross-tree-exception",
                    "exception-to overlay edges require an explicit guard",
                    edge.id,
                )
            )

    for manifest in repository.list_manifests():
        if manifest.source_partition != "development":
            issues.append(
                ValidationIssue(
                    "held-out-manifest-source",
                    "active manifests must be built from development knowledge",
                    manifest.id,
                )
            )
        try:
            repository.load_checkpoint(manifest.checkpoint_id)
            resolve_view(repository, manifest, active_overlay_only=True)
        except (OSError, ValueError) as error:
            issues.append(ValidationIssue("invalid-manifest", str(error), manifest.id))
    return ValidationReport(tuple(issues))
