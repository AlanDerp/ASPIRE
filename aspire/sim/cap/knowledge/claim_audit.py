# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prespecified, fail-closed audit of the upward-abstraction research claim."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import mean
from typing import Any

from .experiment import Observation, _bootstrap_ci, _slope, build_report
from .preregistration import validate_frozen_preregistration
from .serialization import content_hash, iter_jsonl, load_structured


Metric = Callable[[Observation], float | None]


def _metric(name: str) -> Metric:
    return lambda observation: getattr(observation, name)


def _paired_task_difference(
    observations: list[Observation],
    left: str,
    right: str,
    metric: Metric,
    *,
    split: str | None = None,
    cross_capability: bool = False,
    minimum_scale: int | None = None,
) -> dict[str, Any]:
    cells: dict[tuple[Any, ...], dict[str, float]] = defaultdict(dict)
    families: dict[str, str] = {}
    for value in observations:
        if value.corpus_kind != "organic" or value.treatment not in {left, right}:
            continue
        if split is not None and value.split != split:
            continue
        if cross_capability and not value.cross_capability:
            continue
        if minimum_scale is not None and value.scale < minimum_scale:
            continue
        metric_value = metric(value)
        if metric_value is None:
            continue
        key = (value.scale, value.seed, value.task_id, value.split)
        cells[key][value.treatment] = float(metric_value)
        families[value.task_id] = value.task_family

    by_task: dict[str, list[float]] = defaultdict(list)
    for cell_key, treatments in cells.items():
        if left in treatments and right in treatments:
            by_task[str(cell_key[2])].append(treatments[left] - treatments[right])
    task_differences = {
        task_id: mean(values) for task_id, values in sorted(by_task.items())
    }
    samples = list(task_differences.values())
    return {
        "left": left,
        "right": right,
        "task_count": len(samples),
        "task_family_count": len({families[task_id] for task_id in task_differences}),
        "mean_difference": mean(samples) if samples else None,
        "task_clustered_bootstrap_95_ci": _bootstrap_ci(samples),
        "task_differences": task_differences,
    }


def _paired_task_slope_difference(
    observations: list[Observation],
    left: str,
    right: str,
    metric: Metric,
) -> dict[str, Any]:
    points: dict[tuple[str, str, int], list[tuple[int, float]]] = defaultdict(list)
    families: dict[str, str] = {}
    for value in observations:
        if (
            value.corpus_kind != "organic"
            or value.split != "held-out"
            or value.treatment not in {left, right}
        ):
            continue
        metric_value = metric(value)
        if metric_value is None:
            continue
        key = (value.treatment, value.task_id, value.seed)
        points[key].append((value.n_code or value.scale, float(metric_value)))
        families[value.task_id] = value.task_family

    task_seed_differences: dict[str, list[float]] = defaultdict(list)
    task_seeds = sorted({(task_id, seed) for _, task_id, seed in points})
    for task_id, seed in task_seeds:
        left_slope = _slope(points.get((left, task_id, seed), []))
        right_slope = _slope(points.get((right, task_id, seed), []))
        if left_slope is not None and right_slope is not None:
            task_seed_differences[task_id].append(left_slope - right_slope)
    task_differences = {
        task_id: mean(values)
        for task_id, values in sorted(task_seed_differences.items())
    }
    samples = list(task_differences.values())
    return {
        "left": left,
        "right": right,
        "metric": "slope_over_log2_n_code",
        "task_count": len(samples),
        "task_family_count": len({families[task_id] for task_id in task_differences}),
        "mean_slope_difference": mean(samples) if samples else None,
        "task_clustered_bootstrap_95_ci": _bootstrap_ci(samples),
        "task_slope_differences": task_differences,
    }


def _rule(
    rule_id: str,
    comparison: dict[str, Any],
    predicate: Callable[[list[float]], bool],
    requirement: str,
    *,
    minimum_tasks: int,
    minimum_families: int,
) -> dict[str, Any]:
    raw_interval = comparison.get("task_clustered_bootstrap_95_ci")
    interval = (
        [float(value) for value in raw_interval]
        if isinstance(raw_interval, list) and len(raw_interval) == 2
        else None
    )
    enough_tasks = comparison.get("task_count", 0) >= minimum_tasks
    enough_families = comparison.get("task_family_count", 0) >= minimum_families
    evaluable = bool(interval and enough_tasks and enough_families)
    return {
        "id": rule_id,
        "evaluable": evaluable,
        "passed": bool(evaluable and interval is not None and predicate(interval)),
        "requirement": requirement,
        "minimum_independent_tasks": minimum_tasks,
        "minimum_task_families": minimum_families,
        "comparison": comparison,
    }


def _total_cost(value: Observation) -> float | None:
    if value.construction_cost is None or value.maintenance_cost is None:
        return None
    return value.construction_cost + value.maintenance_cost


def _repeatability(
    observations: list[Observation],
    *,
    minimum_scales: int,
    minimum_families: int,
) -> dict[str, Any]:
    by_scale: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_family: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for value in observations:
        if value.corpus_kind != "organic" or value.split != "held-out":
            continue
        if value.treatment not in {"B", "C", "D"}:
            continue
        by_scale[value.scale][value.treatment].append(float(value.context_tokens))
        by_family[value.task_family][value.treatment].append(
            float(value.context_tokens)
        )

    def advantage(groups: dict[Any, dict[str, list[float]]]) -> list[Any]:
        return sorted(
            key
            for key, treatments in groups.items()
            if all(treatment in treatments for treatment in ("B", "C", "D"))
            and mean(treatments["D"])
            < min(mean(treatments["B"]), mean(treatments["C"]))
        )

    scales = advantage(by_scale)
    families = advantage(by_family)
    return {
        "advantage_scales": scales,
        "advantage_task_families": families,
        "minimum_scales": minimum_scales,
        "minimum_task_families": minimum_families,
        "passed": len(scales) >= minimum_scales
        and len(families) >= minimum_families,
    }


def _validate_cost_evidence(
    observations: list[Observation],
    preregistration: dict[str, Any],
    report: dict[str, Any] | None,
) -> list[str]:
    if not report:
        return ["cost report is missing"]
    payload = {key: value for key, value in report.items() if key != "cost_report_hash"}
    errors = []
    if report.get("cost_report_hash") != content_hash(payload):
        errors.append("cost report hash mismatch")
    if report.get("status") != "complete":
        errors.append("cost report is incomplete")
    if report.get("preregistration_hash") != content_hash(preregistration):
        errors.append("cost report preregistration hash mismatch")
    rows = {
        (row.get("treatment"), row.get("scale"), row.get("task_id")): row
        for row in report.get("rows", [])
        if isinstance(row, dict)
    }
    for value in observations:
        if (
            value.corpus_kind != "organic"
            or value.split != "maintenance"
            or value.treatment not in {"B", "E"}
        ):
            continue
        row = rows.get((value.treatment, value.scale, value.task_id))
        if not row:
            errors.append(
                f"cost row missing: {value.treatment}/{value.scale}/{value.task_id}"
            )
            continue
        if value.construction_cost != row.get("construction_cost"):
            errors.append(
                f"construction cost mismatch: {value.treatment}/{value.scale}/{value.task_id}"
            )
        if value.maintenance_cost != row.get("maintenance_cost"):
            errors.append(
                f"maintenance cost mismatch: {value.treatment}/{value.scale}/{value.task_id}"
            )
    return sorted(set(errors))


def _validate_maintenance_evidence(
    report: dict[str, Any] | None,
    *,
    minimum_scenarios: int,
) -> list[str]:
    if not report:
        return ["maintenance simulation is missing"]
    payload = {
        key: value for key, value in report.items() if key != "simulation_hash"
    }
    errors = []
    if report.get("simulation_hash") != content_hash(payload):
        errors.append("maintenance simulation hash mismatch")
    if report.get("mutation_performed") is not False:
        errors.append("maintenance simulation must be read-only")
    scenarios = report.get("scenarios", [])
    if not isinstance(scenarios, list) or len(scenarios) < minimum_scenarios:
        errors.append(f"maintenance simulation needs at least {minimum_scenarios} scenarios")
        return errors
    for scenario in scenarios:
        treatment = scenario.get("treatments", {}).get("E", {})
        if scenario.get("task_impact_recall") != 1.0:
            errors.append(f"task impact recall is incomplete: {scenario.get('id')}")
        if treatment.get("invalidation_recall") != 1.0:
            errors.append(f"invalidation recall is incomplete: {scenario.get('id')}")
    return errors


def _validate_negative_transfer_evidence(
    observations: list[Observation],
    report: dict[str, Any] | None,
) -> tuple[list[str], float | None]:
    if not report:
        return ["negative-transfer review is missing"], None
    payload = {key: value for key, value in report.items() if key != "review_hash"}
    errors = []
    if report.get("review_hash") != content_hash(payload):
        errors.append("negative-transfer review hash mismatch")
    if report.get("ready") is not True:
        errors.append("negative-transfer review is not ready")
    if report.get("observations_hash") != content_hash(observations):
        errors.append("negative-transfer review observations hash mismatch")
    adverse = {
        value.run_job_id: value
        for value in observations
        if value.corpus_kind == "organic"
        and value.negative_transfer is not None
        and value.negative_transfer > 0
    }
    cases = {
        str(case.get("run_job_id")): case
        for case in report.get("cases", [])
        if isinstance(case, dict)
    }
    if set(cases) != set(adverse):
        errors.append("negative-transfer reviewed cases do not match adverse jobs")
    if report.get("adverse_observation_count") != len(adverse):
        errors.append("negative-transfer adverse observation count mismatch")
    f_jobs = {job_id for job_id, value in adverse.items() if value.treatment == "F"}
    if not f_jobs:
        errors.append("negative-transfer review has no adverse F cases")
        return errors, None
    attributed = {
        job_id
        for job_id in f_jobs
        if cases.get(job_id, {}).get("final_attribution") == "knowledge-caused"
        and cases.get(job_id, {}).get("mechanism")
        in {
            "over-broad-principle",
            "missed-exception",
            "stale-guidance",
            "unresolved-conflict",
            "wrong-grounding",
        }
    }
    return errors, len(attributed) / len(f_jobs)


def audit_claim(
    observations: list[Observation],
    preregistration: dict[str, Any],
    *,
    cost_report: dict[str, Any] | None = None,
    maintenance_simulation: dict[str, Any] | None = None,
    negative_transfer_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate only the hypotheses and decision rules fixed in the blueprint."""
    engineering_report = build_report(observations, preregistration)
    preregistration_errors = validate_frozen_preregistration(preregistration)
    decision_rules = preregistration.get("decision_rules", {})
    margin = float(
        decision_rules.get(
            "task_noninferiority_margin", 0.03
        )
    )
    minimum_tasks = int(decision_rules.get("claim_min_independent_tasks", 2))
    minimum_families = int(decision_rules.get("claim_min_task_families", 2))
    minimum_scales = int(decision_rules.get("claim_min_advantage_scales", 2))
    cost_evidence_errors = _validate_cost_evidence(
        observations, preregistration, cost_report
    )
    maintenance_evidence_errors = _validate_maintenance_evidence(
        maintenance_simulation,
        minimum_scenarios=minimum_tasks,
    )
    negative_transfer_errors, negative_transfer_attribution = (
        _validate_negative_transfer_evidence(observations, negative_transfer_review)
    )
    attribution_min = float(
        decision_rules.get("negative_transfer_attribution_min", 0.5)
    )
    scales = sorted(int(value) for value in preregistration.get("library_scales", []))
    medium_scale = scales[len(scales) // 2] if scales else 1

    comparisons = {
        "D_vs_B_active_slope": _paired_task_slope_difference(
            observations, "D", "B", _metric("context_tokens")
        ),
        "D_vs_C_active_slope": _paired_task_slope_difference(
            observations, "D", "C", _metric("context_tokens")
        ),
        "E_vs_D_cross_coverage": _paired_task_difference(
            observations,
            "E",
            "D",
            _metric("requirement_coverage"),
            split="held-out",
            cross_capability=True,
        ),
        "D_vs_B_success": _paired_task_difference(
            observations, "D", "B", _metric("success"), split="held-out"
        ),
        "E_vs_B_success": _paired_task_difference(
            observations, "E", "B", _metric("success"), split="held-out"
        ),
        "D_vs_B_irrelevant": _paired_task_difference(
            observations,
            "D",
            "B",
            _metric("irrelevant_exposure"),
            split="held-out",
        ),
        "E_vs_B_redundancy": _paired_task_difference(
            observations,
            "E",
            "B",
            _metric("redundancy_exposure"),
            split="held-out",
        ),
        "E_vs_B_stale_conflict": _paired_task_difference(
            observations,
            "E",
            "B",
            _metric("stale_conflict_escape"),
            split="adversarial",
        ),
        "E_vs_B_total_cost": _paired_task_difference(
            observations,
            "E",
            "B",
            _total_cost,
            split="maintenance",
            minimum_scale=medium_scale,
        ),
        "E_vs_B_blast_radius": _paired_task_difference(
            observations,
            "E",
            "B",
            _metric("blast_radius"),
            split="maintenance",
        ),
        "F_vs_E_negative_transfer": _paired_task_difference(
            observations,
            "F",
            "E",
            _metric("negative_transfer"),
            split="adversarial",
        ),
    }
    less = lambda interval: interval[1] < 0
    no_more = lambda interval: interval[1] <= 0
    greater = lambda interval: interval[0] > 0
    def make_rule(
        rule_id: str,
        comparison: dict[str, Any],
        predicate: Callable[[list[float]], bool],
        requirement: str,
    ) -> dict[str, Any]:
        return _rule(
            rule_id,
            comparison,
            predicate,
            requirement,
            minimum_tasks=minimum_tasks,
            minimum_families=minimum_families,
        )

    rules = [
        make_rule(
            "principle-slope-vs-canonical",
            comparisons["D_vs_B_active_slope"],
            less,
            "D active-context growth slope must be significantly flatter than B.",
        ),
        make_rule(
            "principle-slope-vs-summary",
            comparisons["D_vs_C_active_slope"],
            less,
            "D active-context growth slope must be significantly flatter than C.",
        ),
        make_rule(
            "overlay-cross-capability-gain",
            comparisons["E_vs_D_cross_coverage"],
            greater,
            "E must improve cross-capability requirement coverage over D.",
        ),
        make_rule(
            "D-heldout-noninferiority",
            comparisons["D_vs_B_success"],
            lambda interval: interval[0] >= -margin,
            f"D held-out success must be noninferior to B at margin {margin}.",
        ),
        make_rule(
            "E-heldout-noninferiority",
            comparisons["E_vs_B_success"],
            lambda interval: interval[0] >= -margin,
            f"E held-out success must be noninferior to B at margin {margin}.",
        ),
        make_rule(
            "irrelevant-exposure-reduction",
            comparisons["D_vs_B_irrelevant"],
            less,
            "D must reduce irrelevant exposure relative to B.",
        ),
        make_rule(
            "redundancy-exposure-reduction",
            comparisons["E_vs_B_redundancy"],
            less,
            "E must reduce redundancy exposure relative to B.",
        ),
        make_rule(
            "stale-conflict-safety",
            comparisons["E_vs_B_stale_conflict"],
            no_more,
            "E stale/conflict escape must not exceed B.",
        ),
        make_rule(
            "total-maintenance-cost",
            comparisons["E_vs_B_total_cost"],
            less,
            "E construction plus maintenance cost must be lower than B at medium/large scale.",
        ),
        make_rule(
            "invalidation-blast-radius",
            comparisons["E_vs_B_blast_radius"],
            less,
            "E invalidation blast radius must be lower than B.",
        ),
        make_rule(
            "exception-gate-necessity",
            comparisons["F_vs_E_negative_transfer"],
            greater,
            "F must show more negative transfer than E.",
        ),
        {
            "id": "exception-gate-human-attribution",
            "evaluable": not negative_transfer_errors
            and negative_transfer_attribution is not None,
            "passed": not negative_transfer_errors
            and negative_transfer_attribution is not None
            and negative_transfer_attribution >= attribution_min,
            "requirement": (
                "The preregistered fraction of adverse F cases must be "
                "human-attributed to knowledge/exception mechanisms."
            ),
            "minimum_attribution_rate": attribution_min,
            "observed_attribution_rate": negative_transfer_attribution,
        },
    ]
    repeatability = _repeatability(
        observations,
        minimum_scales=minimum_scales,
        minimum_families=minimum_families,
    )
    coverage = engineering_report["coverage"]
    design_evaluable = (
        not preregistration_errors
        and not cost_evidence_errors
        and not maintenance_evidence_errors
        and not negative_transfer_errors
        and engineering_report["claim_status"]
        == "ready-for-prespecified-statistical-analysis"
        and coverage["organic_and_synthetic_reported_separately"]
    )
    rules_evaluable = all(rule["evaluable"] for rule in rules)
    evaluable = design_evaluable and rules_evaluable
    passed = evaluable and repeatability["passed"] and all(
        rule["passed"] for rule in rules
    )

    rule_by_id = {rule["id"]: rule for rule in rules}
    hypotheses = {
        "H1": rule_by_id["principle-slope-vs-canonical"]["passed"]
        and rule_by_id["principle-slope-vs-summary"]["passed"],
        "H2": rule_by_id["D-heldout-noninferiority"]["passed"]
        and rule_by_id["E-heldout-noninferiority"]["passed"],
        "H3": rule_by_id["irrelevant-exposure-reduction"]["passed"]
        and rule_by_id["redundancy-exposure-reduction"]["passed"],
        "H4": rule_by_id["total-maintenance-cost"]["passed"]
        and rule_by_id["invalidation-blast-radius"]["passed"],
        "H5": rule_by_id["exception-gate-necessity"]["passed"]
        and rule_by_id["exception-gate-human-attribution"]["passed"],
        "H6": rule_by_id["principle-slope-vs-summary"]["passed"],
    }
    if not evaluable:
        status = "not-evaluable"
        scope = "none"
    elif passed:
        status = "supported"
        scope = "principle-forest-graph"
    elif any(hypotheses.values()):
        status = "partially-supported"
        scope = (
            "principle-tree-only"
            if hypotheses["H1"] and not rule_by_id["overlay-cross-capability-gain"]["passed"]
            else "qualified-subclaims-only"
        )
    else:
        status = "not-supported"
        scope = "none"

    payload = {
        "schema_version": 1,
        "status": status,
        "supported_scope": scope,
        "preregistration_hash": content_hash(preregistration),
        "engineering_report_hash": content_hash(engineering_report),
        "observation_count": len(observations),
        "design_evaluable": design_evaluable,
        "rules_evaluable": rules_evaluable,
        "preregistration_integrity_errors": preregistration_errors,
        "cost_evidence_errors": cost_evidence_errors,
        "maintenance_evidence_errors": maintenance_evidence_errors,
        "negative_transfer_evidence_errors": negative_transfer_errors,
        "cost_report_hash": (cost_report or {}).get("cost_report_hash"),
        "maintenance_simulation_hash": (maintenance_simulation or {}).get(
            "simulation_hash"
        ),
        "negative_transfer_review_hash": (negative_transfer_review or {}).get(
            "review_hash"
        ),
        "engineering_coverage": coverage,
        "rules": rules,
        "repeatability": repeatability,
        "hypotheses": {
            hypothesis: (
                "supported"
                if result
                else "not-supported"
                if evaluable
                else "not-evaluable"
            )
            for hypothesis, result in hypotheses.items()
        },
    }
    return {**payload, "claim_audit_hash": content_hash(payload)}


def audit_claim_files(
    observations_path: Path,
    preregistration_path: Path,
    cost_report_path: Path,
    maintenance_simulation_path: Path,
    negative_transfer_review_path: Path,
) -> dict[str, Any]:
    observations = [
        Observation.from_dict(value) for value in iter_jsonl(observations_path)
    ]
    return audit_claim(
        observations,
        load_structured(preregistration_path),
        cost_report=load_structured(cost_report_path),
        maintenance_simulation=load_structured(maintenance_simulation_path),
        negative_transfer_review=load_structured(negative_transfer_review_path),
    )
