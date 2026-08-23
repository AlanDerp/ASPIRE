# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Non-destructive merge, split, conflict, hub, and pruning audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .lifecycle import impact_report, invalidated_refs, principle_metrics
from .models import CanonicalSkill, Principle
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash, load_structured


def _principle_signature(value) -> str:
    return content_hash(
        {
            "vertical_capability": value.vertical_capability,
            "when": value.when,
            "decision_mode": value.decision_mode,
            "decision": value.decision,
            "invariant": value.invariant,
            "scope": value.scope,
            "exceptions": value.exceptions,
            "expected_effects": value.expected_effects,
        }
    )


def audit_maintenance(
    repository: KnowledgeRepository,
    *,
    max_principle_fanout: int = 12,
    max_exception_rate: float = 0.2,
) -> dict:
    skills, principles, _, edges = resolve_view(
        repository,
        None,
        active_overlay_only=True,
        active_tree_only=True,
    )
    invalidated = invalidated_refs(repository)
    signatures: dict[str, list[str]] = {}
    metrics = {}
    for principle in principles.values():
        signatures.setdefault(_principle_signature(principle), []).append(principle.id)
        metrics[principle.id] = principle_metrics(
            repository, principle, invalidated=invalidated
        )

    merge_candidates = [
        {
            "principle_ids": sorted(ids),
            "reason": "equivalent rule, scope, exceptions, and invariant",
        }
        for ids in signatures.values()
        if len(ids) > 1
    ]
    split_candidates = []
    for principle_id, metric in sorted(metrics.items()):
        principle = principles[principle_id]
        signals = []
        fanout_limit = min(
            max_principle_fanout,
            principle.quality_policy.max_operational_fanout,
        )
        exception_limit = min(
            max_exception_rate,
            principle.quality_policy.max_exception_rate,
        )
        if metric.operational_fanout > fanout_limit:
            signals.append(f"operational-fanout:{metric.operational_fanout}")
        if metric.exception_rate > exception_limit:
            signals.append(f"exception-rate:{metric.exception_rate:.3f}")
        if signals:
            split_candidates.append({"principle_id": principle_id, "signals": signals})

    conflicts = [
        {
            "edge_id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "guard": edge.guard,
        }
        for edge in sorted(edges.values(), key=lambda value: value.id)
        if edge.kind == "contradicts"
    ]
    prune_candidates: list[dict[str, Any]] = []
    nodes: list[CanonicalSkill | Principle] = [*skills.values(), *principles.values()]
    for node in nodes:
        reasons = []
        if node.status in {"rejected", "deprecated"}:
            reasons.append(f"status:{node.status}")
        if node.id in invalidated:
            reasons.append("invalidated-from-runtime")
        if reasons:
            prune_candidates.append(
                {
                    "id": node.id,
                    "revision": node.version,
                    "reasons": reasons,
                    "action": "remove-from-active-view; preserve revision and evidence",
                }
            )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "merge_candidates": sorted(merge_candidates, key=lambda value: value["principle_ids"]),
        "split_candidates": split_candidates,
        "conflicts": conflicts,
        "prune_candidates": sorted(prune_candidates, key=lambda value: value["id"]),
        "invalidated_refs": sorted(invalidated),
        "destructive_changes_performed": False,
    }
    return {**payload, "audit_hash": content_hash(payload)}


def _recall(predicted: set[str], expected: set[str]) -> float | None:
    if not expected:
        return None
    return len(predicted & expected) / len(expected)


def simulate_maintenance(
    repository: KnowledgeRepository,
    scenarios_path: Path,
) -> dict[str, Any]:
    """Run read-only invalidation localization scenarios for B and E."""
    document = load_structured(scenarios_path)
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("maintenance simulation requires a nonempty scenarios list")
    skills, principles, _, _ = resolve_view(repository, None)
    instances = {value.id: value for value in repository.list_instances()}
    results = []
    seen_ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("maintenance scenarios must be objects")
        scenario_id = str(scenario.get("id", ""))
        target = str(scenario.get("target_ref", ""))
        if not scenario_id or scenario_id in seen_ids:
            raise ValueError("maintenance scenario ids must be nonempty and unique")
        seen_ids.add(scenario_id)
        if target in principles:
            raise ValueError("B/E maintenance comparisons must target an instance or skill")
        if target in skills:
            vertical = skills[target].vertical_capability
        elif target in instances:
            vertical = instances[target].vertical_capability
        else:
            raise ValueError(f"maintenance target does not exist: {target}")
        expected_skills = {str(value) for value in scenario.get("expected_skill_ids", [])}
        expected_principles = {
            str(value) for value in scenario.get("expected_principle_ids", [])
        }
        expected_tasks = {str(value) for value in scenario.get("expected_task_ids", [])}
        if not expected_skills or not expected_tasks:
            raise ValueError(
                f"maintenance scenario {scenario_id} requires expected skills and tasks"
            )
        measured = scenario.get("measured_review_minutes", {})
        if not isinstance(measured, dict):
            raise ValueError("measured_review_minutes must be an object")
        if any(
            treatment in measured
            and (
                not isinstance(measured[treatment], (int, float))
                or isinstance(measured[treatment], bool)
                or measured[treatment] < 0
            )
            for treatment in ("B", "E")
        ):
            raise ValueError("measured review minutes must be non-negative")

        impact = impact_report(repository, target)
        affected_skills = set(impact.affected_skill_ids)
        affected_principles = set(impact.affected_principle_ids)
        affected_tasks = set(impact.affected_task_ids)
        baseline_reviewed = {
            skill.id
            for skill in skills.values()
            if skill.vertical_capability == vertical
        }
        forest_reviewed = {target, *affected_skills, *affected_principles}
        expected_baseline = {target, *expected_skills}
        expected_forest = {target, *expected_skills, *expected_principles}
        treatment_metrics = {
            "B": {
                "reviewed_refs": sorted(baseline_reviewed | {target}),
                "predicted_affected_refs": sorted(affected_skills),
                "nodes_reviewed": len(baseline_reviewed | {target}),
                "invalidation_recall": _recall(affected_skills, expected_skills),
                "false_affected_nodes": len(
                    (baseline_reviewed | {target}) - expected_baseline
                ),
                "review_time_minutes": measured.get("B"),
            },
            "E": {
                "reviewed_refs": sorted(forest_reviewed),
                "predicted_affected_refs": sorted(
                    affected_skills | affected_principles
                ),
                "nodes_reviewed": len(forest_reviewed),
                "invalidation_recall": _recall(
                    affected_skills | affected_principles,
                    expected_skills | expected_principles,
                ),
                "false_affected_nodes": len(forest_reviewed - expected_forest),
                "review_time_minutes": measured.get("E"),
            },
        }
        results.append(
            {
                "id": scenario_id,
                "target_ref": target,
                "vertical_capability": vertical,
                "expected": {
                    "skill_ids": sorted(expected_skills),
                    "principle_ids": sorted(expected_principles),
                    "task_ids": sorted(expected_tasks),
                },
                "task_impact_recall": _recall(affected_tasks, expected_tasks),
                "false_affected_tasks": sorted(affected_tasks - expected_tasks),
                "blast_radius": len(affected_tasks),
                "treatments": treatment_metrics,
            }
        )
    payload = {
        "schema_version": 1,
        "source_scenarios_hash": content_hash(document),
        "scenario_count": len(results),
        "scenarios": results,
        "mutation_performed": False,
    }
    return {**payload, "simulation_hash": content_hash(payload)}
