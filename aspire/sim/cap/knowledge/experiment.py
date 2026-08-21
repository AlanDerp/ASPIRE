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
    irrelevant_exposure: float = 0.0
    relevant_principle_recall: float = 0.0
    relevant_skill_recall: float = 0.0
    requirement_coverage: float = 0.0
    fallback: float = 0.0
    negative_transfer: float = 0.0
    unsupported_principle_escape: float = 0.0
    exception_hard_violation_escape: float = 0.0
    maintenance_cost: float = 0.0
    n_code: int = 0
    token_budget: int = 0
    checkpoint_id: str = ""
    manifest_id: str = ""
    corpus_hash: str = ""
    context_hash: str = ""
    portfolio_hash: str = ""
    model_id: str = ""
    prompt_hash: str = ""
    cross_capability: bool = False

    def __post_init__(self) -> None:
        if self.treatment not in TREATMENTS:
            raise ValueError(f"unknown treatment: {self.treatment}")
        if self.scale < 1 or self.n_code < 0 or self.token_budget < 0:
            raise ValueError("scale must be positive and counts must be non-negative")
        bounded = (
            "success",
            "relevant_principle_recall",
            "relevant_skill_recall",
            "requirement_coverage",
            "fallback",
            "negative_transfer",
            "unsupported_principle_escape",
            "exception_hard_violation_escape",
        )
        if any(not 0 <= getattr(self, field) <= 1 for field in bounded):
            raise ValueError("rates and success observations must be in [0, 1]")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Observation":
        fields = cls.__dataclass_fields__
        return cls(**{key: value[key] for key in fields if key in value})


METRICS = (
    "success",
    "context_tokens",
    "compile_latency_ms",
    "irrelevant_exposure",
    "relevant_principle_recall",
    "relevant_skill_recall",
    "requirement_coverage",
    "fallback",
    "negative_transfer",
    "unsupported_principle_escape",
    "exception_hard_violation_escape",
    "maintenance_cost",
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


def _paired_difference(
    observations: list[Observation], left: str, right: str, metric: str
) -> dict:
    def key(value: Observation):
        return value.corpus_kind, value.scale, value.seed, value.task_id, value.split

    left_values = {key(value): getattr(value, metric) for value in observations if value.treatment == left}
    right_values = {key(value): getattr(value, metric) for value in observations if value.treatment == right}
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
        if treatments != set(TREATMENTS):
            violations.append(
                {
                    "cell": list(cell_key),
                    "field": "treatment-coverage",
                    "values": sorted(treatments),
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


def build_report(observations: list[Observation], preregistration: dict[str, Any]) -> dict:
    """Aggregate observations without mixing organic and synthetic evidence."""
    groups: dict[tuple[str, str], list[Observation]] = {}
    for value in observations:
        groups.setdefault((value.corpus_kind, value.treatment), []).append(value)
    results = {}
    for (corpus_kind, treatment), values in sorted(groups.items()):
        key = f"{corpus_kind}:{treatment}"
        results[key] = {
            "observations": len(values),
            "task_families": sorted({value.task_family for value in values}),
            "means": {metric: mean(getattr(value, metric) for value in values) for metric in METRICS},
            "mean_bootstrap_95_ci": {
                metric: _bootstrap_ci([getattr(value, metric) for value in values])
                for metric in METRICS
            },
            "scale_slopes": {
                metric: _slope(
                    [(value.n_code or value.scale, getattr(value, metric)) for value in values]
                )
                for metric in METRICS
            },
        }
    expected_scales = set(preregistration.get("library_scales", []))
    expected_seeds = set(preregistration.get("seeds", []))
    expected_cells = {
        (corpus_kind, treatment, scale, seed)
        for corpus_kind in ("organic", "synthetic")
        for treatment in TREATMENTS
        for scale in expected_scales
        for seed in expected_seeds
    }
    present_cells = {
        (value.corpus_kind, value.treatment, value.scale, value.seed)
        for value in observations
    }
    missing_cells = sorted(expected_cells - present_cells)
    fairness_violations = _fairness_violations(observations)
    coverage = {
        "all_treatment_scale_corpus_cells_present": not missing_cells,
        "missing_cells": [list(value) for value in missing_cells],
        "organic_and_synthetic_reported_separately": all(":" in key for key in results),
        "artifact_locks_complete_and_fair": not fairness_violations,
        "fairness_violations": fairness_violations,
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
    noninferiority = {}
    for treatment in ("D", "E"):
        comparison = comparisons[f"{treatment}_vs_B_heldout_success"]
        interval = comparison["bootstrap_95_ci"]
        noninferiority[treatment] = bool(interval and interval[0] >= -margin)
    evaluable = (
        coverage["all_treatment_scale_corpus_cells_present"]
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
        "claim_status": (
            "ready-for-prespecified-statistical-analysis" if evaluable else "not-evaluable"
        ),
        "claim_reason": (
            "Engineering aggregation is complete; inferential analysis and confidence intervals remain required."
            if evaluable
            else "Required treatments or scales are missing; no research hypothesis may be claimed."
        ),
    }


def report_from_files(observations_path: Path, preregistration_path: Path) -> dict:
    observations = [Observation.from_dict(value) for value in iter_jsonl(observations_path)]
    return build_report(observations, load_structured(preregistration_path))
