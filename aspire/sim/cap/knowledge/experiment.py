# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Comparable A--F retrieval treatments and scale-aware experiment reports."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from .checkpoints import instances_at_checkpoint
from .fingerprint import jaccard, text_tokens
from .models import KnowledgeManifest, Portfolio, TaskContext, model_to_dict
from .preregistration import validate_frozen_preregistration
from .repository import KnowledgeRepository
from .retrieval import compile_portfolio, resolve_view
from .serialization import content_hash, iter_jsonl, load_structured


Treatment = Literal["A", "B", "C", "D", "E", "F"]
TREATMENTS: dict[str, str] = {
    "A": "flat-code",
    "B": "canonical-skill",
    "C": "summary-tree",
    "D": "principle-tree",
    "E": "forest-overlay-graph",
    "F": "principle-tree-without-exceptions",
}


def _score(context: TaskContext, *text: str) -> float:
    query = text_tokens(
        context.task_language, context.task_family, " ".join(context.vertical_capabilities)
    )
    return jaccard(query, text_tokens(*text))


def _fits(markdown: str, token_budget: int) -> bool:
    return max(1, len(markdown) // 4) <= token_budget


def _flat_code(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    context: TaskContext,
    manifest: KnowledgeManifest | None,
) -> Portfolio:
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances = instances_at_checkpoint(repository, checkpoint)
    verticals = set(context.vertical_capabilities)
    candidates = [
        value
        for value in instances
        if not verticals or value.vertical_capability in verticals
    ] or instances
    ranked = sorted(
        candidates,
        key=lambda value: (
            -_score(context, value.goal, value.trigger, value.observed_effect),
            value.id,
        ),
    )
    selected = []
    lines = [f"# Flat skill code: {context.task_id}", ""]
    for value in ranked:
        addition = [f"## {value.id}", "```python", value.code, "```", ""]
        candidate = "\n".join([*lines, *addition]).rstrip() + "\n"
        if _fits(candidate, context.token_budget):
            selected.append(value)
            lines.extend(addition)
    markdown = "\n".join(lines).rstrip() + "\n"
    return Portfolio(
        context_hash=content_hash(model_to_dict(context)),
        checkpoint_id=checkpoint_id,
        tree_ids=(),
        principle_ids=(),
        skill_ids=(),
        overlay_edge_ids=(),
        exclusions=(),
        estimated_tokens=max(1, len(markdown) // 4),
        markdown=markdown,
        manifest_id=f"{manifest.id}@{manifest.version}" if manifest else None,
        treatment="A",
        instance_ids=tuple(value.id for value in selected),
        fallback_used=False,
    )


def _canonical_only(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    context: TaskContext,
    manifest: KnowledgeManifest | None,
    max_skills: int,
) -> Portfolio:
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances_at_checkpoint(repository, checkpoint)
    skills, _, _, _ = resolve_view(repository, manifest)
    verticals = set(context.vertical_capabilities)
    candidates = [
        value
        for value in skills.values()
        if value.status in {"candidate", "validated", "stable"}
        and (not verticals or value.vertical_capability in verticals)
        and (not value.scope.suites or context.suite in value.scope.suites)
        and (not value.scope.task_families or context.task_family in value.scope.task_families)
        and (
            not context.available_api_calls
            or set(value.api_calls) <= set(context.available_api_calls)
        )
    ]
    ranked = sorted(
        candidates,
        key=lambda value: (-_score(context, value.title, value.goal, value.trigger, value.effect), value.id),
    )
    selected = []
    lines = [f"# Canonical skills: {context.task_id}", ""]
    for value in ranked[:max_skills]:
        addition = [
            f"## {value.title}",
            f"Trigger: {value.trigger or 'task/context match'}",
            f"Goal: {value.goal}",
            f"Procedure: {value.operation_template}",
            f"Expected effect: {value.effect}",
            "",
        ]
        candidate = "\n".join([*lines, *addition]).rstrip() + "\n"
        if _fits(candidate, context.token_budget):
            selected.append(value)
            lines.extend(addition)
    markdown = "\n".join(lines).rstrip() + "\n"
    return Portfolio(
        context_hash=content_hash(model_to_dict(context)),
        checkpoint_id=checkpoint_id,
        tree_ids=(),
        principle_ids=(),
        skill_ids=tuple(value.id for value in selected),
        overlay_edge_ids=(),
        exclusions=(),
        estimated_tokens=max(1, len(markdown) // 4),
        markdown=markdown,
        manifest_id=f"{manifest.id}@{manifest.version}" if manifest else None,
        treatment="B",
        node_versions={f"skill:{value.id}": value.version for value in selected},
        fallback_used=False,
    )


def _as_summary_tree(
    portfolio: Portfolio,
    repository: KnowledgeRepository,
    manifest: KnowledgeManifest | None,
) -> Portfolio:
    _, principles, _, _ = resolve_view(repository, manifest)
    lines = ["# Summary tree", ""]
    for principle_id in portfolio.principle_ids:
        value = principles[principle_id]
        lines.extend([f"## {value.title}", value.summary, ""])
    lines.extend(["## Selected canonical skills", ""])
    lines.extend(f"- {skill_id}" for skill_id in portfolio.skill_ids)
    markdown = "\n".join(lines).rstrip() + "\n"
    return replace(
        portfolio,
        treatment="C",
        overlay_edge_ids=(),
        markdown=markdown,
        estimated_tokens=max(1, len(markdown) // 4),
    )


def compile_treatment(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    context: TaskContext,
    treatment: Treatment,
    *,
    manifest: KnowledgeManifest | None = None,
    max_principles: int = 4,
    max_skills: int = 8,
    max_children_per_principle: int = 3,
) -> Portfolio:
    """Compile one treatment while holding checkpoint and token budget fixed."""
    if treatment not in TREATMENTS:
        raise ValueError(f"unknown treatment: {treatment}")
    if manifest is not None and manifest.checkpoint_id != checkpoint_id:
        raise ValueError("all treatments must use the manifest checkpoint")
    if manifest is not None and manifest.source_partition != "development":
        raise ValueError("held-out knowledge cannot be used to compile an actor portfolio")
    if treatment == "A":
        return _flat_code(repository, checkpoint_id, context, manifest)
    if treatment == "B":
        return _canonical_only(repository, checkpoint_id, context, manifest, max_skills)
    portfolio = compile_portfolio(
        repository,
        checkpoint_id,
        context,
        max_principles=max_principles,
        max_skills=max_skills,
        max_children_per_principle=max_children_per_principle,
        manifest=manifest,
        include_overlay=treatment in {"E", "F"},
        enforce_exceptions=treatment != "F",
        treatment=treatment,
    )
    if treatment == "C":
        return _as_summary_tree(portfolio, repository, manifest)
    return portfolio


@dataclass(frozen=True)
class Observation:
    treatment: Treatment
    scale: int
    seed: int
    task_id: str
    task_family: str
    corpus_kind: Literal["organic", "synthetic"]
    split: Literal["development", "held-out", "adversarial", "maintenance"]
    success: float
    context_tokens: int
    compile_latency_ms: float
    reward: float | None = None
    crash: float | None = None
    forbidden_api: float | None = None
    irrelevant_exposure: float | None = None
    redundancy_exposure: float | None = None
    relevant_principle_precision: float | None = None
    relevant_principle_recall: float | None = None
    relevant_skill_recall: float | None = None
    requirement_coverage: float | None = None
    fallback: float | None = None
    negative_transfer: float | None = None
    unsupported_principle_escape: float | None = None
    exception_hard_violation_escape: float | None = None
    stale_conflict_escape: float | None = None
    principle_faithfulness: float | None = None
    principle_purity: float | None = None
    exception_precision: float | None = None
    exception_recall: float | None = None
    support_diversity: float | None = None
    compression_ratio: float | None = None
    grounding_success: float | None = None
    operational_fanout: float | None = None
    unsupported_principle_rate: float | None = None
    duplicate_triage_precision: float | None = None
    nodes_reviewed: float | None = None
    invalidation_recall: float | None = None
    false_affected_nodes: float | None = None
    review_time_minutes: float | None = None
    tree_overlay_edits: float | None = None
    construction_cost: float | None = None
    maintenance_cost: float | None = None
    blast_radius: float | None = None
    n_code: int = 0
    token_budget: int = 0
    checkpoint_id: str = ""
    manifest_id: str = ""
    corpus_hash: str = ""
    context_hash: str = ""
    portfolio_hash: str = ""
    model_id: str = ""
    prompt_hash: str = ""
    run_job_id: str = ""
    cross_capability: bool = False

    def __post_init__(self) -> None:
        if self.treatment not in TREATMENTS:
            raise ValueError(f"unknown treatment: {self.treatment}")
        if self.scale < 1 or self.n_code < 0 or self.token_budget < 0:
            raise ValueError("scale must be positive and counts must be non-negative")
        bounded = (
            "success",
            "crash",
            "forbidden_api",
            "irrelevant_exposure",
            "redundancy_exposure",
            "relevant_principle_precision",
            "relevant_principle_recall",
            "relevant_skill_recall",
            "requirement_coverage",
            "fallback",
            "negative_transfer",
            "unsupported_principle_escape",
            "exception_hard_violation_escape",
            "stale_conflict_escape",
            "principle_faithfulness",
            "principle_purity",
            "exception_precision",
            "exception_recall",
            "grounding_success",
            "unsupported_principle_rate",
            "duplicate_triage_precision",
            "invalidation_recall",
        )
        if any(
            value is not None and not 0 <= value <= 1
            for field in bounded
            if (value := getattr(self, field)) is not None
        ):
            raise ValueError("rates and success observations must be in [0, 1]")
        nonnegative = (
            "context_tokens",
            "compile_latency_ms",
            "support_diversity",
            "compression_ratio",
            "operational_fanout",
            "nodes_reviewed",
            "false_affected_nodes",
            "review_time_minutes",
            "tree_overlay_edits",
            "construction_cost",
            "maintenance_cost",
            "blast_radius",
        )
        if any(
            value is not None and value < 0
            for field in nonnegative
            if (value := getattr(self, field)) is not None
        ):
            raise ValueError("counts, costs, latency, and token values must be non-negative")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Observation":
        fields = cls.__dataclass_fields__
        unknown = set(value) - set(fields) - {"schema_version"}
        if unknown:
            raise ValueError(f"unknown observation fields: {sorted(unknown)}")
        return cls(**{key: value[key] for key in fields if key in value})


METRICS = (
    "success",
    "reward",
    "crash",
    "forbidden_api",
    "context_tokens",
    "compile_latency_ms",
    "irrelevant_exposure",
    "redundancy_exposure",
    "relevant_principle_precision",
    "relevant_principle_recall",
    "relevant_skill_recall",
    "requirement_coverage",
    "fallback",
    "negative_transfer",
    "unsupported_principle_escape",
    "exception_hard_violation_escape",
    "stale_conflict_escape",
    "principle_faithfulness",
    "principle_purity",
    "exception_precision",
    "exception_recall",
    "support_diversity",
    "compression_ratio",
    "grounding_success",
    "operational_fanout",
    "unsupported_principle_rate",
    "duplicate_triage_precision",
    "nodes_reviewed",
    "invalidation_recall",
    "false_affected_nodes",
    "review_time_minutes",
    "tree_overlay_edits",
    "construction_cost",
    "maintenance_cost",
    "blast_radius",
)


def _slope(points: list[tuple[int, float]]) -> float | None:
    if len({scale for scale, _ in points}) < 2:
        return None
    xs = [math.log2(scale) for scale, _ in points]
    ys = [value for _, value in points]
    x_bar, y_bar = mean(xs), mean(ys)
    denominator = sum((value - x_bar) ** 2 for value in xs)
    return sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys)) / denominator


def _bootstrap_ci(values: list[float], *, seed: int = 20260821, samples: int = 1000):
    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    randomizer = random.Random(seed)
    estimates = sorted(
        mean(randomizer.choice(values) for _ in values) for _ in range(samples)
    )
    return [estimates[int(samples * 0.025)], estimates[min(samples - 1, int(samples * 0.975))]]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[max(0, index)]


def _paired_difference(
    observations: list[Observation], left: str, right: str, metric: str
) -> dict:
    def key(value: Observation):
        return value.corpus_kind, value.scale, value.seed, value.task_id, value.split

    left_values = {
        key(value): metric_value
        for value in observations
        if value.treatment == left
        and (metric_value := getattr(value, metric)) is not None
    }
    right_values = {
        key(value): metric_value
        for value in observations
        if value.treatment == right
        and (metric_value := getattr(value, metric)) is not None
    }
    shared = sorted(set(left_values) & set(right_values))
    differences = [left_values[item] - right_values[item] for item in shared]
    return {
        "left": left,
        "right": right,
        "metric": metric,
        "paired_observations": len(differences),
        "mean_difference": mean(differences) if differences else None,
        "bootstrap_95_ci": _bootstrap_ci(differences),
    }


def _fairness_violations(observations: list[Observation]) -> list[dict]:
    fixed_fields = (
        "checkpoint_id",
        "manifest_id",
        "corpus_hash",
        "context_hash",
        "model_id",
        "prompt_hash",
        "token_budget",
        "n_code",
    )
    groups: dict[tuple, list[Observation]] = {}
    for value in observations:
        key = (value.corpus_kind, value.scale, value.seed, value.task_id, value.split)
        groups.setdefault(key, []).append(value)
    violations = []
    for cell_key, values in sorted(groups.items()):
        treatments = {value.treatment for value in values}
        treatment_counts = {
            treatment: sum(value.treatment == treatment for value in values)
            for treatment in TREATMENTS
        }
        if treatments != set(TREATMENTS) or any(
            count != 1 for count in treatment_counts.values()
        ):
            violations.append(
                {
                    "cell": list(cell_key),
                    "field": "treatment-coverage",
                    "values": treatment_counts,
                }
            )
        for field in fixed_fields:
            observed = {getattr(value, field) for value in values}
            if len(observed) != 1 or next(iter(observed), "") in {"", 0}:
                violations.append(
                    {
                        "cell": list(cell_key),
                        "field": field,
                        "values": sorted(observed, key=str),
                    }
                )
        if any(not value.portfolio_hash for value in values):
            violations.append(
                {
                    "cell": list(cell_key),
                    "field": "portfolio_hash",
                    "values": ["missing"],
                }
            )
    return violations


def _preregistered_artifact_violations(
    observations: list[Observation], preregistration: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    integrity_errors = validate_frozen_preregistration(preregistration)
    if integrity_errors:
        return (
            [
                {
                    "field": "preregistration-integrity",
                    "values": integrity_errors,
                }
            ],
            None,
        )
    fixed = preregistration["fixed_artifacts"]
    task_split = load_structured(Path(str(fixed["task_split_path"])))
    checkpoint_map = load_structured(Path(str(fixed["checkpoint_map_path"])))
    expected_scales = {int(value) for value in preregistration["library_scales"]}
    expected_seeds = {int(value) for value in preregistration["seeds"]}
    expected_model = str(fixed["model_id"])
    expected_prompt = str(fixed["prompt_hash"])
    expected_budget = int(preregistration["token_budget"])
    violations: list[dict[str, Any]] = []
    job_ids = [value.run_job_id for value in observations]
    if any(not value for value in job_ids) or len(set(job_ids)) != len(job_ids):
        violations.append(
            {
                "field": "run_job_id",
                "values": "job ids must be nonempty and unique",
            }
        )
    for index, value in enumerate(observations):
        expected_tasks = task_split.get(value.split, [])
        checkpoint = checkpoint_map.get(value.corpus_kind, {}).get(str(value.scale))
        checks = {
            "scale": value.scale in expected_scales,
            "seed": value.seed in expected_seeds,
            "task-split": value.task_id in expected_tasks,
            "model_id": value.model_id == expected_model,
            "prompt_hash": value.prompt_hash == expected_prompt,
            "token_budget": value.token_budget == expected_budget,
            "checkpoint_id": bool(
                checkpoint and value.checkpoint_id == checkpoint.get("checkpoint_id")
            ),
            "corpus_hash": bool(
                checkpoint and value.corpus_hash == checkpoint.get("corpus_hash")
            ),
            "n_code": bool(checkpoint and value.n_code == checkpoint.get("n_code")),
        }
        if checkpoint and checkpoint.get("manifest_id"):
            expected_manifest = str(checkpoint["manifest_id"])
            if checkpoint.get("manifest_version"):
                expected_manifest += f"@{checkpoint['manifest_version']}"
            checks["manifest_id"] = value.manifest_id == expected_manifest
        for field, passed in checks.items():
            if not passed:
                violations.append(
                    {
                        "observation_index": index,
                        "task_id": value.task_id,
                        "treatment": value.treatment,
                        "field": field,
                        "value": getattr(value, field, None),
                    }
                )
    return violations, task_split


def _expected_cells(
    preregistration: dict[str, Any], task_split: dict[str, Any] | None
) -> set[tuple[Any, ...]]:
    scales = set(preregistration.get("library_scales", []))
    seeds = set(preregistration.get("seeds", []))
    evaluation_partitions = preregistration.get("evaluation_partitions", {})
    if not task_split or not isinstance(evaluation_partitions, dict) or not evaluation_partitions:
        return {
            (corpus_kind, treatment, scale, seed)
            for corpus_kind in ("organic", "synthetic")
            for treatment in TREATMENTS
            for scale in scales
            for seed in seeds
        }
    return {
        (corpus_kind, treatment, scale, seed, split, str(task_id))
        for corpus_kind, splits in evaluation_partitions.items()
        for split in splits
        for task_id in task_split.get(split, [])
        for treatment in TREATMENTS
        for scale in scales
        for seed in seeds
    }


def build_report(observations: list[Observation], preregistration: dict[str, Any]) -> dict:
    """Aggregate observations without mixing organic and synthetic evidence."""
    groups: dict[tuple[str, str], list[Observation]] = {}
    for value in observations:
        groups.setdefault((value.corpus_kind, value.treatment), []).append(value)
    results = {}
    for (corpus_kind, treatment), values in sorted(groups.items()):
        key = f"{corpus_kind}:{treatment}"
        metric_values = {
            metric: [
                float(metric_value)
                for value in values
                if (metric_value := getattr(value, metric)) is not None
            ]
            for metric in METRICS
        }
        results[key] = {
            "observations": len(values),
            "task_families": sorted({value.task_family for value in values}),
            "means": {
                metric: mean(samples) if samples else None
                for metric, samples in metric_values.items()
            },
            "mean_bootstrap_95_ci": {
                metric: _bootstrap_ci(samples)
                for metric, samples in metric_values.items()
            },
            "scale_slopes": {
                metric: _slope(
                    [
                        (value.n_code or value.scale, float(metric_value))
                        for value in values
                        if (metric_value := getattr(value, metric)) is not None
                    ]
                )
                for metric in METRICS
            },
        }
    expected_scales = set(preregistration.get("library_scales", []))
    expected_seeds = set(preregistration.get("seeds", []))
    artifact_violations, task_split = _preregistered_artifact_violations(
        observations, preregistration
    )
    expected_cells = _expected_cells(preregistration, task_split)
    detailed_cells = bool(task_split)
    present_cells = {
        (
            value.corpus_kind,
            value.treatment,
            value.scale,
            value.seed,
            *((value.split, value.task_id) if detailed_cells else ()),
        )
        for value in observations
    }
    missing_cells = sorted(expected_cells - present_cells)
    fairness_violations = _fairness_violations(observations)
    coverage = {
        "preregistration_frozen": not validate_frozen_preregistration(preregistration),
        "all_treatment_scale_corpus_cells_present": not missing_cells,
        "missing_cells": [list(value) for value in missing_cells],
        "organic_and_synthetic_reported_separately": all(":" in key for key in results),
        "artifact_locks_complete_and_fair": not fairness_violations
        and not artifact_violations,
        "fairness_violations": [*fairness_violations, *artifact_violations],
    }
    comparisons = {
        "D_vs_B_heldout_success": _paired_difference(
            [value for value in observations if value.split == "held-out"], "D", "B", "success"
        ),
        "E_vs_B_heldout_success": _paired_difference(
            [value for value in observations if value.split == "held-out"], "E", "B", "success"
        ),
        "E_vs_D_cross_capability_coverage": _paired_difference(
            [value for value in observations if value.cross_capability],
            "E",
            "D",
            "requirement_coverage",
        ),
        "F_vs_E_negative_transfer": _paired_difference(
            observations, "F", "E", "negative_transfer"
        ),
    }
    margin = float(
        preregistration.get("decision_rules", {}).get("task_noninferiority_margin", 0.03)
    )
    decision_rules = preregistration.get("decision_rules", {})
    principle_recall_min = float(decision_rules.get("principle_recall_at_8_min", 0.90))
    skill_recall_margin = float(
        decision_rules.get("operational_skill_recall_margin", 0.03)
    )
    unsupported_escape_max = float(
        decision_rules.get("unsupported_principle_escape_max", 0)
    )
    exception_escape_max = float(
        decision_rules.get("exception_hard_violation_escape_max", 0)
    )
    fallback_max = float(decision_rules.get("shadow_fallback_rate_max", 0.10))
    latency_p95_max = float(
        decision_rules.get("compile_latency_p95_ms_max", 300)
    )
    noninferiority = {}
    for treatment in ("D", "E"):
        comparison = comparisons[f"{treatment}_vs_B_heldout_success"]
        interval = comparison["bootstrap_95_ci"]
        noninferiority[treatment] = bool(interval and interval[0] >= -margin)

    runtime_observations = [
        value for value in observations if value.corpus_kind == "organic"
    ]
    treatment_means: dict[str, dict[str, float]] = {}
    for treatment in TREATMENTS:
        values = [
            value for value in runtime_observations if value.treatment == treatment
        ]
        if values:
            treatment_means[treatment] = {}
            for metric in METRICS:
                samples = [
                    float(metric_value)
                    for value in values
                    if (metric_value := getattr(value, metric)) is not None
                ]
                if samples:
                    treatment_means[treatment][metric] = mean(samples)
    structured = [
        value for value in runtime_observations if value.treatment in {"D", "E"}
    ]
    baseline_skill_recall = treatment_means.get("B", {}).get("relevant_skill_recall")
    structured_skill_recalls = [
        treatment_means[treatment]["relevant_skill_recall"]
        for treatment in ("D", "E")
        if "relevant_skill_recall" in treatment_means.get(treatment, {})
    ]
    principle_recalls = [
        treatment_means[treatment]["relevant_principle_recall"]
        for treatment in ("D", "E")
        if "relevant_principle_recall" in treatment_means.get(treatment, {})
    ]
    runtime_values = {
        "minimum_principle_recall_at_8": min(principle_recalls, default=None),
        "minimum_operational_skill_recall": min(structured_skill_recalls, default=None),
        "canonical_baseline_skill_recall": baseline_skill_recall,
        "maximum_unsupported_principle_escape": max(
            (
                value.unsupported_principle_escape
                for value in structured
                if value.unsupported_principle_escape is not None
            ),
            default=None,
        ),
        "maximum_exception_hard_violation_escape": max(
            (
                value.exception_hard_violation_escape
                for value in structured
                if value.exception_hard_violation_escape is not None
            ),
            default=None,
        ),
        "maximum_fallback_rate": max(
            (
                treatment_means[treatment]["fallback"]
                for treatment in ("D", "E")
                if "fallback" in treatment_means.get(treatment, {})
            ),
            default=None,
        ),
        "compile_latency_p95_ms": _percentile(
            [value.compile_latency_ms for value in structured],
            0.95,
        ),
    }
    runtime_checks = {
        "principle_recall_at_8": (
            runtime_values["minimum_principle_recall_at_8"] is not None
            and runtime_values["minimum_principle_recall_at_8"]
            >= principle_recall_min
        ),
        "operational_skill_recall": (
            runtime_values["minimum_operational_skill_recall"] is not None
            and baseline_skill_recall is not None
            and runtime_values["minimum_operational_skill_recall"]
            >= baseline_skill_recall - skill_recall_margin
        ),
        "unsupported_principle_escape": (
            runtime_values["maximum_unsupported_principle_escape"] is not None
            and runtime_values["maximum_unsupported_principle_escape"]
            <= unsupported_escape_max
        ),
        "exception_hard_violation_escape": (
            runtime_values["maximum_exception_hard_violation_escape"] is not None
            and runtime_values["maximum_exception_hard_violation_escape"]
            <= exception_escape_max
        ),
        "fallback_rate": (
            runtime_values["maximum_fallback_rate"] is not None
            and runtime_values["maximum_fallback_rate"] < fallback_max
        ),
        "compile_latency_p95": (
            runtime_values["compile_latency_p95_ms"] is not None
            and runtime_values["compile_latency_p95_ms"] <= latency_p95_max
        ),
    }
    runtime_gates = {
        "thresholds": {
            "principle_recall_at_8_min": principle_recall_min,
            "operational_skill_recall_margin": skill_recall_margin,
            "unsupported_principle_escape_max": unsupported_escape_max,
            "exception_hard_violation_escape_max": exception_escape_max,
            "shadow_fallback_rate_max": fallback_max,
            "compile_latency_p95_ms_max": latency_p95_max,
        },
        "values": runtime_values,
        "checks": runtime_checks,
        "passed": all(runtime_checks.values()),
    }
    evaluable = (
        coverage["preregistration_frozen"]
        and bool(expected_scales)
        and bool(expected_seeds)
        and coverage["all_treatment_scale_corpus_cells_present"]
        and coverage["artifact_locks_complete_and_fair"]
    )
    return {
        "schema_version": 1,
        "preregistration_hash": content_hash(preregistration),
        "observation_count": len(observations),
        "coverage": coverage,
        "results": results,
        "paired_comparisons": comparisons,
        "noninferiority_margin": margin,
        "heldout_success_noninferior_to_B": noninferiority,
        "runtime_gates": runtime_gates,
        "prespecified_conclusion": {
            "status": "not-evaluable",
            "reason": "A final supported/partial/not-supported claim requires the prespecified claim audit.",
        },
        "claim_status": (
            "ready-for-prespecified-statistical-analysis" if evaluable else "not-evaluable"
        ),
        "claim_reason": (
            "Engineering aggregation is complete; the prespecified claim audit remains required."
            if evaluable
            else (
                "Preregistration, required cells, or fairness locks are incomplete; "
                "no research hypothesis may be claimed."
            )
        ),
    }


def report_from_files(observations_path: Path, preregistration_path: Path) -> dict:
    observations = [Observation.from_dict(value) for value in iter_jsonl(observations_path)]
    return build_report(observations, load_structured(preregistration_path))
