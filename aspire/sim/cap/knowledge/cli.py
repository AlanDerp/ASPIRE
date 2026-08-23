# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Command-line interface for the ASPIRE consolidation forest."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .checkpoints import freeze_checkpoint, instances_at_checkpoint
from .case_review import review_negative_transfer
from .claim_audit import audit_claim_files
from .completion import audit_blueprint_completion
from .compression import build_compression_report, supporting_skills
from .consolidation import canonicalize_cluster, propose_principle
from .cost import build_cost_report
from .counterexample import (
    search_counterexamples,
    validate_counterexample_dispositions,
    validate_counterexample_report,
)
from .experiment import compile_treatment, report_from_files
from .forest import validate_forest
from .integrity import validate_repository
from .golden import evaluate_golden_file
from .index import index_metadata, rebuild_index
from .ingest import build_instance
from .lifecycle import impact_report, invalidate, principle_metrics
from .maintenance import audit_maintenance, simulate_maintenance
from .models import (
    CanonicalSkill,
    ConsolidationPolicy,
    KnowledgeManifest,
    OverlayEdge,
    Principle,
    TaskContext,
    VerticalTree,
    model_to_dict,
)
from .overlay_review import (
    promote_overlay_edge,
    review_overlay_edge,
    validate_overlay_manifest_binding,
    validate_overlay_proposal,
)
from .placement import analyze_placement
from .preregistration import freeze_preregistration
from .projection import lineage_view, overlay_view, vertical_forest
from .repository import KnowledgeRepository
from .review_artifacts import (
    finalize_leave_family_out_report,
    validate_leave_family_out_report,
)
from .repetition import audit_repetition
from .retrieval import compile_portfolio, resolve_view
from .review import (
    bind_principle_review,
    promote_principle,
    review_principle,
    validate_principle_candidate_evidence,
)
from .runtime import build_runtime_config
from .run_plan import execute_experiment_plan, materialize_experiment_plan
from .serialization import content_hash, load_structured, write_structured_atomic
from .stress import audit_stress_snapshot, build_stress_corpus
from .tree_review import (
    prepare_tree_review,
    validate_tree_proposal,
    validate_tree_review,
)
from .verification import verify_deterministic_rebuild


def _json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _policy(path: Path | None) -> ConsolidationPolicy:
    return ConsolidationPolicy.from_dict(load_structured(path) if path else None)


def _repository(args: argparse.Namespace) -> KnowledgeRepository:
    repository = KnowledgeRepository(args.root)
    repository.initialize()
    return repository


def _audit(repository: KnowledgeRepository, checkpoint_id: str, policy: ConsolidationPolicy):
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances = instances_at_checkpoint(repository, checkpoint)
    return audit_repetition(instances, checkpoint, policy), instances


def _principle_revision(
    repository: KnowledgeRepository, principle_id: str, version: str | None = None
) -> Principle:
    matches = [value for value in repository.list_principles() if value.id == principle_id]
    if version:
        matches = [value for value in matches if value.version == version]
    if not matches:
        suffix = f"@{version}" if version else ""
        raise ValueError(f"principle not found: {principle_id}{suffix}")
    return max(matches, key=lambda value: tuple(int(part) for part in value.version.split(".")))


def _canonical_skill_revision(
    repository: KnowledgeRepository,
    reference: str,
) -> CanonicalSkill:
    skill_id, separator, version = reference.rpartition("@")
    if not separator:
        skill_id, version = reference, ""
    matches = [value for value in repository.list_skills() if value.id == skill_id]
    if version:
        matches = [value for value in matches if value.version == version]
    if not matches:
        raise ValueError(f"canonical skill revision not found: {reference}")
    return max(
        matches,
        key=lambda value: tuple(int(part) for part in value.version.split(".")),
    )


def _tree_revision(
    repository: KnowledgeRepository,
    tree_id: str,
    version: str | None = None,
) -> VerticalTree:
    matches = [value for value in repository.list_trees() if value.id == tree_id]
    if version:
        matches = [value for value in matches if value.version == version]
    if not matches:
        suffix = f"@{version}" if version else ""
        raise ValueError(f"vertical tree not found: {tree_id}{suffix}")
    return max(
        matches,
        key=lambda value: tuple(int(part) for part in value.version.split(".")),
    )


def _overlay_revision(
    repository: KnowledgeRepository, edge_id: str, version: str | None = None
) -> OverlayEdge:
    matches = [value for value in repository.list_edges() if value.id == edge_id]
    if version:
        matches = [value for value in matches if value.version == version]
    if not matches:
        suffix = f"@{version}" if version else ""
        raise ValueError(f"overlay edge not found: {edge_id}{suffix}")
    return max(
        matches,
        key=lambda value: tuple(int(part) for part in value.version.split(".")),
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    repository = _repository(args)
    value: Any
    if args.command == "init":
        return {"root": str(repository.root), "initialized": True}

    if args.command == "instance" and args.instance_command == "ingest":
        outcomes = load_structured(args.outcomes) if args.outcomes else {}
        if args.successful_seeds:
            outcomes["successes"] = [
                int(value) for value in args.successful_seeds.split(",") if value.strip()
            ]
        if args.improved:
            outcomes["improved"] = True
        value = build_instance(
            instance_id=args.id,
            vertical_capability=args.vertical,
            task=args.task,
            task_family=args.task_family,
            source_path=args.code,
            goal=args.goal,
            trigger=args.trigger,
            observed_effect=args.effect,
            symbol=args.symbol,
            line_range=args.lines,
            development_outcomes=outcomes,
            source_partition=args.source_partition,
        )
        path = repository.save_instance(value)
        repository.append_evidence(
            {"event": "skill-code-instance.ingested", "subject": value.id, "code_hash": value.code_hash}
        )
        return {"path": str(path), "instance": model_to_dict(value)}

    if args.command == "checkpoint" and args.checkpoint_command == "freeze":
        value = freeze_checkpoint(repository, args.id, _policy(args.policy))
        return {"checkpoint": model_to_dict(value)}

    if args.command == "manifest" and args.manifest_command == "save":
        value = KnowledgeManifest.from_dict(load_structured(args.file))
        repository.load_checkpoint(value.checkpoint_id)
        resolve_view(
            repository,
            value,
            active_overlay_only=True,
            active_tree_only=True,
        )
        path = repository.save_manifest(value)
        return {"path": str(path), "manifest": model_to_dict(value)}

    if args.command == "repetition" and args.repetition_command == "audit":
        report, _ = _audit(repository, args.checkpoint, _policy(args.policy))
        payload = asdict(report)
        repository.save_audit("instance-repetition", report.content_hash, payload)
        if args.output:
            write_structured_atomic(args.output, payload)
        return payload

    if args.command == "skill" and args.skill_command == "canonicalize":
        policy = _policy(args.policy)
        report, instances = _audit(repository, args.checkpoint, policy)
        cluster = next((value for value in report.clusters if value.id == args.cluster), None)
        if cluster is None:
            raise ValueError(f"repetition cluster not found: {args.cluster}")
        repository.save_audit(
            "instance-repetition",
            report.content_hash,
            asdict(report),
        )
        value = canonicalize_cluster(
            cluster,
            instances,
            repository.load_checkpoint(args.checkpoint),
            policy,
            report,
            load_structured(args.review),
        )
        path = repository.save_skill(value)
        return {"path": str(path), "skill": model_to_dict(value)}

    if args.command == "principle" and args.principle_command == "propose":
        checkpoint = repository.load_checkpoint(args.checkpoint)
        instances_at_checkpoint(repository, checkpoint)
        selected_skills = [
            _canonical_skill_revision(repository, reference)
            for reference in args.skills
        ]
        for skill in selected_skills:
            source_checkpoint = repository.load_checkpoint(
                str(skill.provenance["checkpoint_id"])
            )
            instances_at_checkpoint(repository, source_checkpoint)
            if not set(skill.instance_ids) <= set(source_checkpoint.instance_ids):
                raise ValueError(
                    f"canonical skill {skill.id} is not grounded in its source checkpoint"
                )
        value = propose_principle(
            selected_skills,
            checkpoint,
            _policy(args.policy),
        )
        path = repository.save_principle(value)
        return {"path": str(path), "principle": model_to_dict(value)}

    if args.command == "principle" and args.principle_command == "review":
        proposal = _principle_revision(repository, args.id, args.from_version)
        review_payload = load_structured(args.review)
        counterexample_path = Path(str(review_payload["counterexample_report"]))
        counterexample_report = validate_counterexample_report(
            counterexample_path,
            proposal,
        )
        current_counterexample_report = search_counterexamples(repository, proposal)
        if counterexample_report != current_counterexample_report:
            raise ValueError(
                "counterexample report does not match a current deterministic search"
            )
        review_payload["counterexample_dispositions"] = (
            validate_counterexample_dispositions(
                counterexample_report,
                review_payload.get("counterexample_dispositions", {}),
            )
        )
        review_payload["counterexample_report_hash"] = counterexample_report[
            "report_hash"
        ]
        counterexample_artifact_hash = content_hash(counterexample_report)
        repository.save_audit(
            "principle-counterexample",
            counterexample_artifact_hash,
            counterexample_report,
        )
        review_payload["counterexample_report"] = (
            "proposals/principle-counterexample/"
            f"{counterexample_artifact_hash}.yaml"
        )
        review_payload["counterexample_artifact_hash"] = (
            counterexample_artifact_hash
        )
        lofo_path = Path(str(review_payload["leave_one_family_out_report"]))
        lofo_report = validate_leave_family_out_report(lofo_path, proposal)
        review_payload["leave_one_family_out_report_hash"] = lofo_report[
            "report_hash"
        ]
        lofo_artifact_hash = content_hash(lofo_report)
        repository.save_audit(
            "principle-lofo",
            lofo_artifact_hash,
            lofo_report,
        )
        review_payload["leave_one_family_out_report"] = (
            f"proposals/principle-lofo/{lofo_artifact_hash}.yaml"
        )
        review_payload["leave_one_family_out_artifact_hash"] = (
            lofo_artifact_hash
        )
        compression_report = build_compression_report(
            proposal,
            review_payload,
            supporting_skills(repository, proposal),
        )
        if compression_report["passed"] is not True:
            raise ValueError(
                "reviewed principle does not compress direct child injection"
            )
        compression_artifact_hash = content_hash(compression_report)
        repository.save_audit(
            "principle-compression",
            compression_artifact_hash,
            compression_report,
        )
        review_payload["compression_report"] = (
            "proposals/principle-compression/"
            f"{compression_artifact_hash}.yaml"
        )
        review_payload["compression_report_hash"] = compression_report[
            "report_hash"
        ]
        review_payload["compression_artifact_hash"] = compression_artifact_hash
        review_payload = bind_principle_review(proposal, review_payload)
        value = review_principle(
            proposal,
            review_payload,
            version=args.version,
        )
        repository.save_audit(
            "principle-review",
            str(value.provenance["review_artifact_hash"]),
            review_payload,
        )
        path = repository.save_principle(value)
        return {"path": str(path), "principle": model_to_dict(value)}

    if args.command == "principle" and args.principle_command == "counterexamples":
        proposal = _principle_revision(repository, args.id, args.from_version)
        result = search_counterexamples(repository, proposal)
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "principle" and args.principle_command == "finalize-lofo":
        proposal = _principle_revision(repository, args.id, args.from_version)
        result = finalize_leave_family_out_report(
            proposal,
            load_structured(args.report),
        )
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "principle" and args.principle_command == "promote":
        candidate = _principle_revision(repository, args.id, args.from_version)
        validate_principle_candidate_evidence(repository, candidate)
        value = promote_principle(candidate, version=args.version)
        path = repository.save_principle(value)
        repository.append_evidence(
            {
                "event": "knowledge.validated",
                "subject": value.id,
                "version": value.version,
                "principle_hash": content_hash(model_to_dict(value)),
                "candidate_version": value.provenance["candidate_version"],
                "candidate_hash": value.provenance["candidate_hash"],
                "review_artifact_hash": value.provenance[
                    "review_artifact_hash"
                ],
                "checkpoint_id": value.provenance["checkpoint_id"],
                "at": value.provenance.get("reviewed_at"),
                "reviewer": value.provenance.get("reviewer"),
            },
            stream="lifecycle",
        )
        return {"path": str(path), "principle": model_to_dict(value)}

    if args.command == "principle" and args.principle_command == "metrics":
        principles = {value.id: value for value in repository.list_principles()}
        if args.id not in principles:
            raise ValueError(f"principle not found: {args.id}")
        return {"metrics": model_to_dict(principle_metrics(repository, principles[args.id]))}

    if args.command == "forest" and args.forest_command == "propose-tree":
        parents = load_structured(args.parents).get("parent_by_child", {})
        value = VerticalTree(
            id=args.id,
            version=args.version,
            vertical_capability=args.vertical,
            structural_root=args.structural_root,
            checkpoint_id=args.checkpoint,
            parent_by_child=parents,
        )
        validate_tree_proposal(repository, value)
        path = repository.save_tree(value)
        return {"path": str(path), "tree": model_to_dict(value)}

    if args.command == "forest" and args.forest_command == "review-tree":
        tree = _tree_revision(repository, args.id, args.tree_version)
        tree_manifest = repository.load_manifest(
            args.manifest, args.manifest_version
        )
        resolve_view(
            repository,
            tree_manifest,
            active_overlay_only=True,
            active_tree_only=True,
        )
        review_payload = prepare_tree_review(
            repository,
            tree,
            tree_manifest,
            load_structured(args.review),
        )
        review_hash = content_hash(review_payload)
        path = repository.save_audit("tree-review", review_hash, review_payload)
        repository.append_evidence(
            {
                "event": "knowledge.tree-reviewed",
                "subject": tree.id,
                "version": tree.version,
                "tree_hash": content_hash(model_to_dict(tree)),
                "checkpoint_id": tree.checkpoint_id,
                "manifest_id": review_payload["manifest_id"],
                "manifest_version": review_payload["manifest_version"],
                "manifest_hash": review_payload["manifest_hash"],
                "review_artifact_hash": review_hash,
                "at": review_payload["reviewed_at"],
                "reviewer": review_payload["reviewer"],
            },
            stream="lifecycle",
        )
        return {
            "path": str(path),
            "review_artifact_hash": review_hash,
            "tree": model_to_dict(tree),
        }

    if args.command == "forest" and args.forest_command == "promote-tree":
        tree = _tree_revision(repository, args.id, args.tree_version)
        review_payload = validate_tree_review(
            repository, tree, args.review_hash
        )
        repository.append_evidence(
            {
                "event": "knowledge.tree-validated",
                "subject": tree.id,
                "version": tree.version,
                "tree_hash": content_hash(model_to_dict(tree)),
                "checkpoint_id": tree.checkpoint_id,
                "manifest_id": review_payload["manifest_id"],
                "manifest_version": review_payload["manifest_version"],
                "manifest_hash": review_payload["manifest_hash"],
                "review_artifact_hash": args.review_hash,
                "at": review_payload["reviewed_at"],
                "reviewer": review_payload["reviewer"],
            },
            stream="lifecycle",
        )
        return {
            "review_artifact_hash": args.review_hash,
            "tree": model_to_dict(tree),
        }

    if args.command == "forest" and args.forest_command == "placement":
        principle = _principle_revision(
            repository,
            args.principle,
            args.principle_version,
        )
        tree = _tree_revision(repository, args.tree, args.tree_version)
        result = analyze_placement(repository, principle, tree, args.parent)
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "overlay" and args.overlay_command == "propose":
        value = OverlayEdge.from_dict(load_structured(args.file))
        validate_overlay_proposal(repository, value)
        path = repository.save_edge(value)
        return {"path": str(path), "edge": model_to_dict(value)}

    if args.command == "overlay" and args.overlay_command == "review":
        overlay_proposal = _overlay_revision(repository, args.id, args.from_version)
        overlay_manifest = repository.load_manifest(
            args.manifest, args.manifest_version
        )
        resolve_view(
            repository,
            overlay_manifest,
            active_overlay_only=True,
            active_tree_only=True,
        )
        validate_overlay_manifest_binding(overlay_proposal, overlay_manifest)
        review_payload = load_structured(args.review)
        reviewed_edge = review_overlay_edge(
            overlay_proposal,
            review_payload,
            overlay_manifest,
            version=args.version,
        )
        repository.save_audit(
            "overlay-review",
            str(reviewed_edge.provenance["review_artifact_hash"]),
            review_payload,
        )
        path = repository.save_edge(reviewed_edge)
        return {"path": str(path), "edge": model_to_dict(reviewed_edge)}

    if args.command == "overlay" and args.overlay_command == "promote":
        overlay_candidate = _overlay_revision(repository, args.id, args.from_version)
        promoted_edge = promote_overlay_edge(overlay_candidate, version=args.version)
        path = repository.save_edge(promoted_edge)
        repository.append_evidence(
            {
                "event": "knowledge.edge-validated",
                "subject": promoted_edge.id,
                "version": promoted_edge.version,
                "candidate_version": promoted_edge.provenance["candidate_version"],
                "source_id": promoted_edge.source_id,
                "source_version": promoted_edge.source_version,
                "target_id": promoted_edge.target_id,
                "target_version": promoted_edge.target_version,
                "checkpoint_id": promoted_edge.provenance["checkpoint_id"],
                "manifest_id": promoted_edge.provenance["manifest_id"],
                "manifest_version": promoted_edge.provenance["manifest_version"],
                "manifest_hash": promoted_edge.provenance["manifest_hash"],
                "review_artifact_hash": promoted_edge.provenance[
                    "review_artifact_hash"
                ],
                "at": promoted_edge.provenance["reviewed_at"],
                "reviewer": promoted_edge.provenance["reviewer"],
            },
            stream="lifecycle",
        )
        return {"path": str(path), "edge": model_to_dict(promoted_edge)}

    if args.command == "forest" and args.forest_command == "validate":
        report = validate_repository(repository)
        if not report.ok:
            report.require_ok()
        return {"ok": True, "issues": []}

    if args.command == "forest" and args.forest_command == "show":
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        result = vertical_forest(
            repository,
            manifest=manifest,
            vertical=args.vertical,
            task_family=args.task_family,
        )
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "overlay" and args.overlay_command == "show":
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        result = overlay_view(repository, manifest=manifest)
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "overlay" and args.overlay_command == "validate":
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        skills, principles, trees, edges = resolve_view(
            repository,
            manifest,
            active_overlay_only=True,
            active_tree_only=True,
        )
        report = validate_forest(
            list(trees.values()),
            list(skills.values()),
            list(principles.values()),
            list(edges.values()),
        )
        report.require_ok()
        return {
            "ok": True,
            "manifest_id": (
                f"{manifest.id}@{manifest.version}" if manifest else None
            ),
            "edge_count": len(edges),
        }

    if args.command == "lineage" and args.lineage_command == "show":
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        result = lineage_view(repository, args.ref, manifest=manifest)
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "impact" and args.impact_command == "show":
        return {"impact": model_to_dict(impact_report(repository, args.ref))}

    if args.command == "impact" and args.impact_command == "invalidate":
        return {
            "impact": model_to_dict(
                invalidate(
                    repository,
                    args.ref,
                    args.reason,
                    source_partition=args.source_partition,
                )
            )
        }

    if args.command == "maintenance" and args.maintenance_command == "audit":
        result = audit_maintenance(
            repository,
            max_principle_fanout=args.max_principle_fanout,
            max_exception_rate=args.max_exception_rate,
        )
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "maintenance" and args.maintenance_command == "simulate":
        result = simulate_maintenance(repository, args.scenarios)
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "maintenance" and args.maintenance_command == "cost-report":
        result = build_cost_report(args.ledger, args.preregistration)
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "index" and args.index_command == "build":
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        source_hash = rebuild_index(
            repository,
            args.output,
            checkpoint_id=args.checkpoint,
            manifest=manifest,
        )
        return {"path": str(args.output), "source_hash": source_hash}

    if args.command == "index" and args.index_command == "verify":
        return {"path": str(args.path), "metadata": index_metadata(args.path)}

    if args.command == "retrieve":
        validate_repository(repository).require_ok()
        context = TaskContext.from_dict(load_structured(args.context))
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        portfolio = compile_portfolio(
            repository,
            args.checkpoint,
            context,
            max_principles=args.max_principles,
            max_skills=args.max_skills,
            max_children_per_principle=args.max_children_per_principle,
            manifest=manifest,
        )
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(portfolio.markdown)
        if args.output:
            write_structured_atomic(args.output, model_to_dict(portfolio))
        payload = model_to_dict(portfolio)
        return {"portfolio": payload, "portfolio_hash": content_hash(payload)}

    if args.command == "experiment" and args.experiment_command == "compile":
        validate_repository(repository).require_ok()
        context = TaskContext.from_dict(load_structured(args.context))
        manifest = (
            repository.load_manifest(args.manifest, args.manifest_version)
            if args.manifest
            else None
        )
        started = time.perf_counter()
        portfolio = compile_treatment(
            repository,
            args.checkpoint,
            context,
            args.treatment,
            manifest=manifest,
            max_principles=args.max_principles,
            max_skills=args.max_skills,
            max_children_per_principle=args.max_children_per_principle,
        )
        compile_latency_ms = (time.perf_counter() - started) * 1000
        payload = model_to_dict(portfolio)
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(portfolio.markdown)
        if args.output:
            write_structured_atomic(args.output, payload)
        return {
            "portfolio": payload,
            "portfolio_hash": content_hash(payload),
            "compile_latency_ms": compile_latency_ms,
        }

    if args.command == "experiment" and args.experiment_command == "report":
        report = report_from_files(args.observations, args.preregistration)
        if args.output:
            write_structured_atomic(args.output, report)
        return report

    if args.command == "experiment" and args.experiment_command == "claim-audit":
        result = audit_claim_files(
            args.observations,
            args.preregistration,
            args.cost_report,
            args.maintenance_simulation,
            args.negative_transfer_review,
        )
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if (
        args.command == "experiment"
        and args.experiment_command == "negative-transfer-review"
    ):
        result = review_negative_transfer(args.observations, args.labels)
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "experiment" and args.experiment_command == "plan":
        result = materialize_experiment_plan(
            args.preregistration,
            args.portfolio_catalog,
            args.output_root,
        )
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "experiment" and args.experiment_command == "run":
        return execute_experiment_plan(
            args.plan,
            args.state,
            args.observations,
            resume=args.resume,
        )

    if (
        args.command == "experiment"
        and args.experiment_command == "freeze-preregistration"
    ):
        result = freeze_preregistration(
            args.draft,
            model_id=args.model_id,
            prompt_path=args.prompt,
            task_split_path=args.task_split,
            checkpoint_map_path=args.checkpoint_map,
            execution_config_path=args.execution_config,
            job_catalog_path=args.job_catalog,
            frozen_at=args.frozen_at,
        )
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "experiment" and args.experiment_command == "build-corpus":
        result = build_stress_corpus(
            repository,
            args.checkpoint,
            [int(value) for value in args.scales.split(",") if value.strip()],
            seed=args.seed,
        )
        write_structured_atomic(args.output, result)
        return {
            "path": str(args.output),
            "corpus_hash": result["corpus_hash"],
            "snapshots": [
                {"scale": value["scale"], "record_count": value["record_count"]}
                for value in result["snapshots"]
            ],
        }

    if args.command == "experiment" and args.experiment_command == "audit-stress":
        result = audit_stress_snapshot(
            load_structured(args.corpus),
            args.scale,
            _policy(args.policy),
        )
        write_structured_atomic(args.output, result)
        return {
            "path": str(args.output),
            "audit_hash": result["audit_hash"],
            "checkpoint_id": result["checkpoint_id"],
            "record_count": result["record_count"],
            "evidence_eligible": result["evidence_eligible"],
        }

    if args.command == "experiment" and args.experiment_command == "golden-report":
        validate_repository(repository).require_ok()
        manifest = repository.load_manifest(args.manifest, args.manifest_version)
        result = evaluate_golden_file(
            args.labels,
            repository,
            manifest,
            faithfulness_gate=args.faithfulness_gate,
        )
        if args.output:
            write_structured_atomic(args.output, result)
        return result

    if args.command == "experiment" and args.experiment_command == "runtime-config":
        portfolio_paths: dict[str, str] = {}
        for assignment in args.portfolio:
            if "=" not in assignment:
                raise ValueError("portfolio must use TREATMENT=PATH syntax")
            treatment, portfolio_path = assignment.split("=", 1)
            if treatment in portfolio_paths:
                raise ValueError(f"duplicate portfolio treatment: {treatment}")
            portfolio_paths[treatment] = portfolio_path
        result = {
            "knowledge": build_runtime_config(
                args.mode,
                portfolio_paths,
                token_budget=args.token_budget,
            )
        }
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "experiment" and args.experiment_command == "verify-determinism":
        manifest = repository.load_manifest(args.manifest, args.manifest_version)
        result = verify_deterministic_rebuild(
            repository,
            args.checkpoint,
            manifest,
            args.context,
        )
        write_structured_atomic(args.output, result)
        return {"path": str(args.output), **result}

    if args.command == "completion" and args.completion_command == "audit":
        result = audit_blueprint_completion(
            repository,
            args.preregistration
            or repository.root / "experiment" / "preregistration.yaml",
            golden_report_path=args.golden_report,
            experiment_report_path=args.experiment_report,
            determinism_report_path=args.determinism_report,
            claim_audit_path=args.claim_audit,
        )
        if args.output:
            write_structured_atomic(args.output, result)
        return result
    raise ValueError("unsupported command")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("knowledge"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")

    instance = commands.add_parser("instance").add_subparsers(dest="instance_command", required=True)
    ingest = instance.add_parser("ingest")
    ingest.add_argument("--id", required=True)
    ingest.add_argument("--vertical", required=True)
    ingest.add_argument("--task", required=True)
    ingest.add_argument("--task-family", required=True)
    ingest.add_argument("--code", required=True, type=Path)
    ingest.add_argument("--symbol")
    ingest.add_argument("--lines", help="1-based inclusive START:END from the executed file")
    ingest.add_argument("--goal", required=True)
    ingest.add_argument("--trigger", default="")
    ingest.add_argument("--effect", default="")
    ingest.add_argument("--outcomes", type=Path)
    ingest.add_argument("--successful-seeds")
    ingest.add_argument("--improved", action="store_true")
    ingest.add_argument(
        "--source-partition", choices=("development", "held-out"), default="development"
    )

    checkpoint = commands.add_parser("checkpoint").add_subparsers(
        dest="checkpoint_command", required=True
    )
    freeze = checkpoint.add_parser("freeze")
    freeze.add_argument("--id", required=True)
    freeze.add_argument("--policy", type=Path)

    manifest = commands.add_parser("manifest").add_subparsers(
        dest="manifest_command", required=True
    )
    save_manifest = manifest.add_parser("save")
    save_manifest.add_argument("--file", type=Path, required=True)

    repetition = commands.add_parser("repetition").add_subparsers(
        dest="repetition_command", required=True
    )
    audit = repetition.add_parser("audit")
    audit.add_argument("--checkpoint", required=True)
    audit.add_argument("--policy", type=Path)
    audit.add_argument("--output", type=Path)

    skill = commands.add_parser("skill").add_subparsers(dest="skill_command", required=True)
    canonicalize = skill.add_parser("canonicalize")
    canonicalize.add_argument("--checkpoint", required=True)
    canonicalize.add_argument("--cluster", required=True)
    canonicalize.add_argument("--policy", type=Path)
    canonicalize.add_argument("--review", type=Path, required=True)

    principle = commands.add_parser("principle").add_subparsers(
        dest="principle_command", required=True
    )
    propose = principle.add_parser("propose")
    propose.add_argument("--checkpoint", required=True)
    propose.add_argument(
        "--skills",
        nargs="+",
        required=True,
        help="Canonical skill IDs, optionally locked as ID@VERSION",
    )
    propose.add_argument("--policy", type=Path)
    review = principle.add_parser("review")
    review.add_argument("--id", required=True)
    review.add_argument("--from-version")
    review.add_argument("--version", required=True)
    review.add_argument("--review", type=Path, required=True)
    counterexamples = principle.add_parser("counterexamples")
    counterexamples.add_argument("--id", required=True)
    counterexamples.add_argument("--from-version")
    counterexamples.add_argument("--output", type=Path, required=True)
    finalize_lofo = principle.add_parser("finalize-lofo")
    finalize_lofo.add_argument("--id", required=True)
    finalize_lofo.add_argument("--from-version")
    finalize_lofo.add_argument("--report", type=Path, required=True)
    finalize_lofo.add_argument("--output", type=Path, required=True)
    promote = principle.add_parser("promote")
    promote.add_argument("--id", required=True)
    promote.add_argument("--from-version")
    promote.add_argument("--version", required=True)
    principle_metrics_parser = principle.add_parser("metrics")
    principle_metrics_parser.add_argument("--id", required=True)

    forest = commands.add_parser("forest").add_subparsers(dest="forest_command", required=True)
    forest.add_parser("validate")
    show_forest = forest.add_parser("show")
    show_forest.add_argument("--vertical")
    show_forest.add_argument("--task-family")
    show_forest.add_argument("--manifest")
    show_forest.add_argument("--manifest-version")
    show_forest.add_argument("--output", type=Path)
    propose_tree = forest.add_parser("propose-tree")
    propose_tree.add_argument("--id", required=True)
    propose_tree.add_argument("--version", default="1.0.0")
    propose_tree.add_argument("--vertical", required=True)
    propose_tree.add_argument("--structural-root", required=True)
    propose_tree.add_argument("--checkpoint", required=True)
    propose_tree.add_argument("--parents", type=Path, required=True)
    review_tree = forest.add_parser("review-tree")
    review_tree.add_argument("--id", required=True)
    review_tree.add_argument("--tree-version", required=True)
    review_tree.add_argument("--manifest", required=True)
    review_tree.add_argument("--manifest-version", required=True)
    review_tree.add_argument("--review", type=Path, required=True)
    promote_tree = forest.add_parser("promote-tree")
    promote_tree.add_argument("--id", required=True)
    promote_tree.add_argument("--tree-version", required=True)
    promote_tree.add_argument("--review-hash", required=True)
    placement = forest.add_parser("placement")
    placement.add_argument("--principle", required=True)
    placement.add_argument("--principle-version")
    placement.add_argument("--tree", required=True)
    placement.add_argument("--tree-version")
    placement.add_argument("--parent", required=True)
    placement.add_argument("--output", type=Path, required=True)
    overlay = commands.add_parser("overlay").add_subparsers(
        dest="overlay_command", required=True
    )
    propose_overlay = overlay.add_parser("propose")
    propose_overlay.add_argument("--file", type=Path, required=True)
    review_overlay = overlay.add_parser("review")
    review_overlay.add_argument("--id", required=True)
    review_overlay.add_argument("--from-version")
    review_overlay.add_argument("--version", required=True)
    review_overlay.add_argument("--manifest", required=True)
    review_overlay.add_argument("--manifest-version", required=True)
    review_overlay.add_argument("--review", type=Path, required=True)
    promote_overlay = overlay.add_parser("promote")
    promote_overlay.add_argument("--id", required=True)
    promote_overlay.add_argument("--from-version")
    promote_overlay.add_argument("--version", required=True)
    show_overlay = overlay.add_parser("show")
    show_overlay.add_argument("--manifest")
    show_overlay.add_argument("--manifest-version")
    show_overlay.add_argument("--output", type=Path)
    validate_overlay = overlay.add_parser("validate")
    validate_overlay.add_argument("--manifest")
    validate_overlay.add_argument("--manifest-version")

    lineage_parser = commands.add_parser("lineage").add_subparsers(
        dest="lineage_command", required=True
    )
    show_lineage = lineage_parser.add_parser("show")
    show_lineage.add_argument("ref")
    show_lineage.add_argument("--manifest")
    show_lineage.add_argument("--manifest-version")
    show_lineage.add_argument("--output", type=Path)

    impact = commands.add_parser("impact").add_subparsers(
        dest="impact_command", required=True
    )
    show_impact = impact.add_parser("show")
    show_impact.add_argument("ref")
    invalidate_ref = impact.add_parser("invalidate")
    invalidate_ref.add_argument("ref")
    invalidate_ref.add_argument("--reason", required=True)
    invalidate_ref.add_argument(
        "--source-partition", choices=("development", "held-out"), default="development"
    )

    maintenance = commands.add_parser("maintenance").add_subparsers(
        dest="maintenance_command", required=True
    )
    maintenance_audit = maintenance.add_parser("audit")
    maintenance_audit.add_argument("--max-principle-fanout", type=int, default=12)
    maintenance_audit.add_argument("--max-exception-rate", type=float, default=0.2)
    maintenance_audit.add_argument("--output", type=Path)
    maintenance_simulation = maintenance.add_parser("simulate")
    maintenance_simulation.add_argument("--scenarios", type=Path, required=True)
    maintenance_simulation.add_argument("--output", type=Path)
    maintenance_cost = maintenance.add_parser("cost-report")
    maintenance_cost.add_argument("--ledger", type=Path, required=True)
    maintenance_cost.add_argument("--preregistration", type=Path, required=True)
    maintenance_cost.add_argument("--output", type=Path)

    index = commands.add_parser("index").add_subparsers(dest="index_command", required=True)
    build = index.add_parser("build")
    build.add_argument("--checkpoint", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--manifest")
    build.add_argument("--manifest-version")
    verify = index.add_parser("verify")
    verify.add_argument("path", type=Path)

    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("--checkpoint", required=True)
    retrieve.add_argument("--context", type=Path, required=True)
    retrieve.add_argument("--max-principles", type=int, default=4)
    retrieve.add_argument("--max-skills", type=int, default=8)
    retrieve.add_argument("--max-children-per-principle", type=int, default=3)
    retrieve.add_argument("--manifest")
    retrieve.add_argument("--manifest-version")
    retrieve.add_argument("--output", type=Path)
    retrieve.add_argument("--markdown", type=Path)

    experiment = commands.add_parser("experiment").add_subparsers(
        dest="experiment_command", required=True
    )
    compile_experiment = experiment.add_parser("compile")
    compile_experiment.add_argument("--treatment", choices=tuple("ABCDEF"), required=True)
    compile_experiment.add_argument("--checkpoint", required=True)
    compile_experiment.add_argument("--context", type=Path, required=True)
    compile_experiment.add_argument("--manifest")
    compile_experiment.add_argument("--manifest-version")
    compile_experiment.add_argument("--max-principles", type=int, default=4)
    compile_experiment.add_argument("--max-skills", type=int, default=8)
    compile_experiment.add_argument("--max-children-per-principle", type=int, default=3)
    compile_experiment.add_argument("--output", type=Path)
    compile_experiment.add_argument("--markdown", type=Path)
    report = experiment.add_parser("report")
    report.add_argument("--observations", type=Path, required=True)
    report.add_argument("--preregistration", type=Path, required=True)
    report.add_argument("--output", type=Path)
    claim_audit = experiment.add_parser("claim-audit")
    claim_audit.add_argument("--observations", type=Path, required=True)
    claim_audit.add_argument("--preregistration", type=Path, required=True)
    claim_audit.add_argument("--cost-report", type=Path, required=True)
    claim_audit.add_argument("--maintenance-simulation", type=Path, required=True)
    claim_audit.add_argument("--negative-transfer-review", type=Path, required=True)
    claim_audit.add_argument("--output", type=Path)
    negative_transfer_review = experiment.add_parser("negative-transfer-review")
    negative_transfer_review.add_argument("--observations", type=Path, required=True)
    negative_transfer_review.add_argument("--labels", type=Path, required=True)
    negative_transfer_review.add_argument("--output", type=Path)
    plan = experiment.add_parser("plan")
    plan.add_argument("--preregistration", type=Path, required=True)
    plan.add_argument("--portfolio-catalog", type=Path, required=True)
    plan.add_argument("--output-root", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    execute = experiment.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    execute.add_argument("--state", type=Path, required=True)
    execute.add_argument("--observations", type=Path, required=True)
    execute.add_argument("--resume", action="store_true")
    freeze_preregistration_parser = experiment.add_parser("freeze-preregistration")
    freeze_preregistration_parser.add_argument("--draft", type=Path, required=True)
    freeze_preregistration_parser.add_argument("--model-id", required=True)
    freeze_preregistration_parser.add_argument("--prompt", type=Path, required=True)
    freeze_preregistration_parser.add_argument("--task-split", type=Path, required=True)
    freeze_preregistration_parser.add_argument(
        "--checkpoint-map", type=Path, required=True
    )
    freeze_preregistration_parser.add_argument(
        "--execution-config", type=Path, required=True
    )
    freeze_preregistration_parser.add_argument(
        "--job-catalog", type=Path, required=True
    )
    freeze_preregistration_parser.add_argument("--frozen-at", required=True)
    freeze_preregistration_parser.add_argument("--output", type=Path, required=True)
    corpus = experiment.add_parser("build-corpus")
    corpus.add_argument("--checkpoint", required=True)
    corpus.add_argument("--scales", default="1,4,16,64")
    corpus.add_argument("--seed", type=int, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    stress_audit = experiment.add_parser("audit-stress")
    stress_audit.add_argument("--corpus", type=Path, required=True)
    stress_audit.add_argument("--scale", type=int, required=True)
    stress_audit.add_argument("--policy", type=Path)
    stress_audit.add_argument("--output", type=Path, required=True)
    golden = experiment.add_parser("golden-report")
    golden.add_argument("--labels", type=Path, required=True)
    golden.add_argument("--faithfulness-gate", type=float, default=0.85)
    golden.add_argument("--manifest", required=True)
    golden.add_argument("--manifest-version", required=True)
    golden.add_argument("--output", type=Path)
    runtime_config = experiment.add_parser("runtime-config")
    runtime_config.add_argument(
        "--mode",
        choices=(
            "off",
            "shadow",
            "experiment",
            "canonical",
            "principle-tree",
            "principle-graph",
        ),
        required=True,
    )
    runtime_config.add_argument(
        "--portfolio",
        action="append",
        default=[],
        help="Repeat TREATMENT=PATH; shadow requires A through F",
    )
    runtime_config.add_argument("--token-budget", type=int, default=2400)
    runtime_config.add_argument("--output", type=Path, required=True)
    determinism = experiment.add_parser("verify-determinism")
    determinism.add_argument("--checkpoint", required=True)
    determinism.add_argument("--manifest", required=True)
    determinism.add_argument("--manifest-version", required=True)
    determinism.add_argument("--context", action="append", type=Path, required=True)
    determinism.add_argument("--output", type=Path, required=True)

    completion = commands.add_parser("completion").add_subparsers(
        dest="completion_command", required=True
    )
    completion_audit = completion.add_parser("audit")
    completion_audit.add_argument("--preregistration", type=Path)
    completion_audit.add_argument("--golden-report", type=Path)
    completion_audit.add_argument("--experiment-report", type=Path)
    completion_audit.add_argument("--determinism-report", type=Path)
    completion_audit.add_argument("--claim-audit", type=Path)
    completion_audit.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(_json(run(args)))
