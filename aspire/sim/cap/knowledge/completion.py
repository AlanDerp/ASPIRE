# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Evidence-based completion and Actor-mode gate audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .integrity import validate_repository
from .preregistration import validate_frozen_preregistration
from .repository import KnowledgeRepository
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
            }
        ),
        "trees": len({value.id for value in trees}),
        "manifests": len({value.id for value in manifests}),
        "checkpoints": len(checkpoints),
        "task_contexts": len(contexts),
    }
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
            bool(skills and principles and trees and manifests),
            corpus_counts,
            "Canonical skills, principles, trees, and a manifest must be nonempty.",
        ),
        _check(
            "golden-principle-scale",
            10 <= int((golden or {}).get("principle_count", 0)) <= 20,
            int((golden or {}).get("principle_count", 0)),
            "The golden corpus must cover 10--20 principles.",
        ),
        _check(
            "twenty-task-contexts",
            len(contexts) >= 20,
            len(contexts),
            "The retrieval comparison requires at least 20 task contexts.",
        ),
    ]

    shadow_checks = [
        _check(
            "golden-ready",
            bool((golden or {}).get("ready")),
            (golden or {}).get("ready"),
            "Golden labels need 10--20 principles, two reviewers, and all polarities.",
        ),
        _check(
            "golden-faithfulness",
            (golden or {}).get("faithfulness_gate_passed") is True,
            (golden or {}).get("faithfulness_gate_passed"),
            "Golden faithfulness must be at least 0.85.",
        ),
        _check(
            "deterministic-rebuild",
            (determinism or {}).get("tree_index_portfolio_deterministic") is True,
            (determinism or {}).get("tree_index_portfolio_deterministic"),
            "Tree, index, and portfolio rebuilds need recorded deterministic hashes.",
        ),
    ]
    shadow_checks.extend(forest_checks[:1])

    runtime_gate_payload = (experiment or {}).get("runtime_gates", {})
    runtime_checks = [
        _check(
            "experiment-evaluable",
            (experiment or {}).get("claim_status")
            == "ready-for-prespecified-statistical-analysis",
            (experiment or {}).get("claim_status"),
            "All preregistered cells and fairness locks must be complete.",
        ),
        _check(
            "principle-runtime-thresholds",
            runtime_gate_payload.get("passed") is True,
            runtime_gate_payload,
            "Recall, escape, fallback, and p95 latency gates must all pass.",
        ),
    ]

    conclusion_payload = claim or {}
    conclusion_status = conclusion_payload.get("status")
    conclusion_bound = bool(
        claim
        and experiment
        and claim.get("preregistration_hash") == content_hash(preregistration)
        and claim.get("engineering_report_hash") == content_hash(experiment)
        and claim.get("observation_count") == experiment.get("observation_count")
    )
    conclusion_checks = [
        _check(
            "prespecified-conclusion",
            conclusion_bound
            and conclusion_status
            in {"supported", "partially-supported", "not-supported"},
            {"artifact_bound": conclusion_bound, **conclusion_payload},
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
