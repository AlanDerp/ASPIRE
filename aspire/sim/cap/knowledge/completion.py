# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Evidence-based completion and Actor-mode gate audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .integrity import validate_repository
from .lifecycle import validated_revisions
from .preregistration import validate_frozen_preregistration
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash, load_structured


REQUIRED_TREATMENTS = set("ABCDEF")
REQUIRED_HYPOTHESES = {f"H{index}" for index in range(1, 7)}
REQUIRED_FIXED_FIELDS = {
    "model_id",
    "prompt_hash",
    "task_split_hash",
    "checkpoint_map_hash",
    "execution_config_hash",
    "job_catalog_hash",
    "token_budget",
    "library_scales",
    "seeds",
}
REQUIRED_RUNTIME_CHECKS = {
    "principle_recall_at_8",
    "operational_skill_recall",
    "unsupported_principle_escape",
    "exception_hard_violation_escape",
    "fallback_rate",
    "compile_latency_p95",
}


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return load_structured(path)


def _check(name: str, passed: bool, evidence: Any, requirement: str) -> dict[str, Any]:
    return {
        "id": name,
        "passed": passed,
        "requirement": requirement,
        "evidence": evidence,
    }


def audit_blueprint_completion(
    repository: KnowledgeRepository,
    preregistration_path: Path,
    *,
    golden_report_path: Path | None = None,
    experiment_report_path: Path | None = None,
    determinism_report_path: Path | None = None,
    claim_audit_path: Path | None = None,
) -> dict[str, Any]:
    """Audit research gates without treating absent evidence as success."""
    preregistration = load_structured(preregistration_path)
    golden = _load_optional(golden_report_path)
    experiment = _load_optional(experiment_report_path)
    determinism = _load_optional(determinism_report_path)
    claim = _load_optional(claim_audit_path)

    integrity = validate_repository(repository)
    instances = repository.list_instances()
    skills = repository.list_skills()
    principles = repository.list_principles()
    trees = repository.list_trees()
    manifests = repository.list_manifests()
    _, _, active_tree_view, _ = resolve_view(
        repository,
        None,
        active_overlay_only=True,
        active_tree_only=True,
    )
    promoted_principles = validated_revisions(repository)
    active_manifests = []
    for manifest in manifests:
        try:
            resolve_view(
                repository,
                manifest,
                active_overlay_only=True,
                active_tree_only=True,
            )
        except (OSError, ValueError):
            continue
        active_manifests.append(manifest)
    checkpoints = sorted((repository.root / "checkpoints").glob("*.yaml"))
    contexts = sorted(
        path
        for path in (repository.root / "experiment" / "task-contexts").glob("*.yaml")
        if path.name.lower() != "readme.md"
    )

    hypothesis_payload = preregistration.get("hypotheses", {})
    if not isinstance(hypothesis_payload, dict):
        hypothesis_payload = {}
    hypotheses = set(hypothesis_payload)
    hypotheses_complete = REQUIRED_HYPOTHESES <= hypotheses and all(
        isinstance(hypothesis_payload[hypothesis], dict)
        and bool(hypothesis_payload[hypothesis].get("claim"))
        and bool(hypothesis_payload[hypothesis].get("refutation"))
        for hypothesis in REQUIRED_HYPOTHESES
    )
    treatments = set(preregistration.get("treatments", {}))
    fixed_artifacts = preregistration.get("fixed_artifacts", {})
    if not isinstance(fixed_artifacts, dict):
        fixed_artifacts = {}
    fixed_values = {
        field: preregistration.get(field, fixed_artifacts.get(field))
        for field in REQUIRED_FIXED_FIELDS
    }
    fixed_values_complete = all(
        value not in (None, "", [], {}) for value in fixed_values.values()
    )
    preregistration_errors = validate_frozen_preregistration(preregistration)
    catalog_contexts = [str(path) for path in contexts]
    if not preregistration_errors:
        catalog_path = Path(
            str(preregistration["fixed_artifacts"]["job_catalog_path"])
        )
        catalog = load_structured(catalog_path)
        catalog_contexts = sorted(
            str(value["context_path"])
            for value in catalog.get("tasks", {}).values()
            if isinstance(value, dict) and value.get("context_path")
        )
    design_checks = [
        _check(
            "preregistration-frozen",
            not preregistration_errors,
            {
                "status": preregistration.get("status", "missing"),
                "integrity_errors": preregistration_errors,
            },
            "The preregistration and all hash-locked inputs must remain intact.",
        ),
        _check(
            "hypotheses-h1-h6",
            hypotheses_complete,
            {
                hypothesis: hypothesis_payload.get(hypothesis)
                for hypothesis in sorted(REQUIRED_HYPOTHESES)
            },
            "H1--H6 and their failure conditions must be preregistered.",
        ),
        _check(
            "treatments-a-f",
            treatments == REQUIRED_TREATMENTS,
            sorted(treatments),
            "All A--F controls must be fixed.",
        ),
        _check(
            "fixed-experimental-artifacts",
            fixed_values_complete,
            fixed_values,
            "Model, prompt, split, checkpoints, job catalog, execution config, "
            "budget, scales, and seeds must be fixed.",
        ),
    ]

    corpus_counts = {
        "instances": len(instances),
        "canonical_skills": len({value.id for value in skills}),
        "principles": len({value.id for value in principles}),
        "validated_principles": len(
            {
                value.id
                for value in principles
                if value.status in {"validated", "stable"}
                and (value.id, value.version) in promoted_principles
            }
        ),
        "tree_revisions": len(trees),
        "active_trees": len(active_tree_view),
        "manifest_revisions": len(manifests),
        "active_manifests": len(active_manifests),
        "checkpoints": len(checkpoints),
        "task_contexts": len(catalog_contexts),
    }
    golden_payload = golden or {}
    golden_unsigned = {
        key: value for key, value in golden_payload.items() if key != "report_hash"
    }
    golden_hash_valid = bool(
        golden and golden.get("report_hash") == content_hash(golden_unsigned)
    )
    golden_binding = golden_payload.get("binding", {})
    if not isinstance(golden_binding, dict):
        golden_binding = {}
    bound_manifests = {
        f"{value.id}@{value.version}": value for value in active_manifests
    }
    bound_manifest = bound_manifests.get(str(golden_binding.get("manifest_id", "")))
    golden_manifest_valid = bool(
        bound_manifest
        and golden_binding.get("checkpoint_id") == bound_manifest.checkpoint_id
        and set(golden_payload.get("principle_ids", []))
        <= set(bound_manifest.principle_versions)
        and len(golden_payload.get("principle_ids", []))
        == int(golden_payload.get("principle_count", 0))
    )
    forest_checks = [
        _check(
            "repository-integrity",
            integrity.ok,
            [
                {"code": issue.code, "subject": issue.subject}
                for issue in integrity.issues
            ],
            "The forest, overlay, provenance, and partitions must validate.",
        ),
        _check(
            "organic-code-corpus",
            len(instances) > 0,
            corpus_counts["instances"],
            "Real development SkillCodeInstances must exist.",
        ),
        _check(
            "multiple-frozen-checkpoints",
            len(checkpoints) >= 2,
            [path.stem for path in checkpoints],
            "At least two organic accumulation checkpoints are required.",
        ),
        _check(
            "nonempty-abstraction-forest",
            bool(
                skills
                and corpus_counts["validated_principles"]
                and active_tree_view
                and active_manifests
            ),
            corpus_counts,
            "Canonical skills, principles, trees, and a manifest must be nonempty.",
        ),
        _check(
            "golden-principle-scale",
            10 <= int(golden_payload.get("principle_count", 0)) <= 20
            and golden_hash_valid
            and golden_manifest_valid,
            {
                "principle_count": int(golden_payload.get("principle_count", 0)),
                "hash_valid": golden_hash_valid,
                "manifest_valid": golden_manifest_valid,
            },
            "The golden corpus must cover 10--20 principles.",
        ),
        _check(
            "twenty-task-contexts",
            len(catalog_contexts) >= 20,
            catalog_contexts,
            "The retrieval comparison requires at least 20 task contexts.",
        ),
    ]

    determinism_payload = determinism or {}
    determinism_unsigned = {
        key: value
        for key, value in determinism_payload.items()
        if key != "verification_hash"
    }
    determinism_hash_valid = bool(
        determinism
        and determinism_payload.get("verification_hash")
        == content_hash(determinism_unsigned)
    )
    determinism_manifest = bound_manifests.get(
        str(determinism_payload.get("manifest_id", ""))
    )
    determinism_manifest_valid = bool(
        determinism_manifest
        and determinism_payload.get("checkpoint_id")
        == determinism_manifest.checkpoint_id
    )
    first_rebuild = determinism_payload.get("first", {})
    second_rebuild = determinism_payload.get("second", {})
    required_rebuild_fields = {
        "forest_hash",
        "overlay_hash",
        "index_source_hash",
        "index_logical_hash",
        "portfolio_hashes",
    }
    determinism_outputs_complete = bool(
        isinstance(first_rebuild, dict)
        and isinstance(second_rebuild, dict)
        and required_rebuild_fields <= set(first_rebuild)
        and required_rebuild_fields <= set(second_rebuild)
        and isinstance(first_rebuild.get("portfolio_hashes"), dict)
        and bool(first_rebuild["portfolio_hashes"])
        and first_rebuild == second_rebuild
    )
    shadow_checks = [
        _check(
            "golden-ready",
            bool(golden_payload.get("ready"))
            and golden_hash_valid
            and golden_manifest_valid,
            {
                "ready": golden_payload.get("ready"),
                "hash_valid": golden_hash_valid,
                "manifest_valid": golden_manifest_valid,
            },
            "Golden labels need 10--20 principles, two reviewers, and all polarities.",
        ),
        _check(
            "golden-faithfulness",
            golden_payload.get("faithfulness_gate_passed") is True
            and golden_hash_valid
            and golden_manifest_valid,
            golden_payload.get("faithfulness_gate_passed"),
            "Golden faithfulness must be at least 0.85.",
        ),
        _check(
            "deterministic-rebuild",
            determinism_hash_valid
            and determinism_manifest_valid
            and determinism_outputs_complete
            and determinism_payload.get("tree_index_portfolio_deterministic") is True,
            {
                "hash_valid": determinism_hash_valid,
                "manifest_valid": determinism_manifest_valid,
                "outputs_complete": determinism_outputs_complete,
            },
            "Tree, index, and portfolio rebuilds need recorded deterministic hashes.",
        ),
    ]
    shadow_checks.extend(forest_checks[:1])

    experiment_payload = experiment or {}
    experiment_unsigned = {
        key: value
        for key, value in experiment_payload.items()
        if key != "report_hash"
    }
    experiment_hash_valid = bool(
        experiment
        and experiment_payload.get("report_hash")
        == content_hash(experiment_unsigned)
    )
    experiment_preregistration_bound = bool(
        experiment
        and experiment_payload.get("preregistration_hash")
        == content_hash(preregistration)
    )
    experiment_coverage = experiment_payload.get("coverage", {})
    experiment_evaluable = bool(
        experiment_hash_valid
        and experiment_preregistration_bound
        and isinstance(experiment_coverage, dict)
        and experiment_coverage.get("preregistration_frozen") is True
        and experiment_coverage.get("all_treatment_scale_corpus_cells_present")
        is True
        and experiment_coverage.get("artifact_locks_complete_and_fair") is True
        and experiment_payload.get("claim_status")
        == "ready-for-prespecified-statistical-analysis"
    )
    runtime_gate_payload = experiment_payload.get("runtime_gates", {})
    runtime_gate_checks = (
        runtime_gate_payload.get("checks", {})
        if isinstance(runtime_gate_payload, dict)
        else {}
    )
    runtime_gate_passed = bool(
        experiment_evaluable
        and isinstance(runtime_gate_payload, dict)
        and runtime_gate_payload.get("passed") is True
        and isinstance(runtime_gate_checks, dict)
        and REQUIRED_RUNTIME_CHECKS <= set(runtime_gate_checks)
        and all(runtime_gate_checks[check] is True for check in REQUIRED_RUNTIME_CHECKS)
    )
    runtime_checks = [
        _check(
            "experiment-evaluable",
            experiment_evaluable,
            {
                "hash_valid": experiment_hash_valid,
                "preregistration_bound": experiment_preregistration_bound,
                "claim_status": experiment_payload.get("claim_status"),
            },
            "All preregistered cells and fairness locks must be complete.",
        ),
        _check(
            "principle-runtime-thresholds",
            runtime_gate_passed,
            runtime_gate_payload,
            "Recall, escape, fallback, and p95 latency gates must all pass.",
        ),
    ]

    conclusion_payload = claim or {}
    conclusion_unsigned = {
        key: value
        for key, value in conclusion_payload.items()
        if key != "claim_audit_hash"
    }
    conclusion_hash_valid = bool(
        claim
        and conclusion_payload.get("claim_audit_hash")
        == content_hash(conclusion_unsigned)
    )
    conclusion_status = conclusion_payload.get("status")
    conclusion_bound = bool(
        conclusion_hash_valid
        and experiment
        and conclusion_payload.get("preregistration_hash")
        == content_hash(preregistration)
        and conclusion_payload.get("engineering_report_hash")
        == content_hash(experiment)
        and conclusion_payload.get("observation_count")
        == experiment.get("observation_count")
    )
    conclusion_checks = [
        _check(
            "prespecified-conclusion",
            conclusion_bound
            and conclusion_status
            in {"supported", "partially-supported", "not-supported"},
            {
                "artifact_bound": conclusion_bound,
                "hash_valid": conclusion_hash_valid,
                **conclusion_payload,
            },
            "The final claim must resolve to a prespecified supported/partial/not-supported outcome.",
        )
    ]

    all_checks = [
        *design_checks,
        *forest_checks,
        *shadow_checks,
        *runtime_checks,
        *conclusion_checks,
    ]
    shadow_ready = all(item["passed"] for item in shadow_checks)
    principle_runtime_ready = shadow_ready and all(
        item["passed"] for item in runtime_checks
    )
    complete = all(item["passed"] for item in all_checks)
    maximum_mode = (
        "principle-runtime"
        if principle_runtime_ready
        else "shadow"
        if shadow_ready
        else "off"
    )
    payload = {
        "schema_version": 1,
        "status": "complete" if complete else "incomplete",
        "maximum_justified_actor_mode": maximum_mode,
        "corpus_counts": corpus_counts,
        "checks": {
            "research_design": design_checks,
            "skill_consolidation_forest": forest_checks,
            "shadow_entry": shadow_checks,
            "principle_runtime_entry": runtime_checks,
            "conclusion_quality": conclusion_checks,
        },
        "failed_check_ids": sorted(
            {item["id"] for item in all_checks if not item["passed"]}
        ),
    }
    return {**payload, "audit_hash": content_hash(payload)}
