# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic counterexample candidate search for principle proposals."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .checkpoints import instances_at_checkpoint
from .fingerprint import jaccard, text_tokens
from .models import Principle
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash, load_structured


def _constants(code: str) -> list[str]:
    values = {
        repr(node.value)
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.Constant)
        and not isinstance(node.value, (bool, type(None)))
        and isinstance(node.value, (int, float, str))
    }
    return sorted(values)


def search_counterexamples(
    repository: KnowledgeRepository,
    proposal: Principle,
) -> dict[str, Any]:
    """Search development evidence; candidates still require human disposition."""
    checkpoint_id = str(proposal.provenance["checkpoint_id"])
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances = instances_at_checkpoint(repository, checkpoint)
    skills, principles, _, edges = resolve_view(repository, None)
    child_skills = [skills[child_id] for child_id in proposal.child_ids if child_id in skills]
    child_instance_ids = {
        instance_id for skill in child_skills for instance_id in skill.instance_ids
    }
    query = text_tokens(
        proposal.title,
        proposal.summary,
        *(value for skill in child_skills for value in (skill.goal, skill.trigger, skill.effect)),
    )
    raw_candidates: list[dict[str, Any]] = []

    for instance in instances:
        similarity = jaccard(
            query,
            text_tokens(instance.goal, instance.trigger, instance.observed_effect),
        )
        failures = instance.development_outcomes.get("failures", [])
        forbidden = instance.development_outcomes.get("forbidden_actions", [])
        if instance.id in child_instance_ids and failures:
            raw_candidates.append(
                {
                    "kind": "failed-support-variant",
                    "subject": instance.id,
                    "severity": "medium",
                    "similarity": round(similarity, 6),
                    "evidence": {"failures": failures},
                }
            )
        if forbidden:
            raw_candidates.append(
                {
                    "kind": "forbidden-action",
                    "subject": instance.id,
                    "severity": "high",
                    "similarity": round(similarity, 6),
                    "evidence": {"forbidden_actions": forbidden},
                }
            )
        constants = _constants(instance.code) if instance.id in child_instance_ids else []
        if constants:
            raw_candidates.append(
                {
                    "kind": "hidden-task-constant",
                    "subject": instance.id,
                    "severity": "low",
                    "similarity": round(similarity, 6),
                    "evidence": {"constants": constants},
                }
            )

    for skill in skills.values():
        if skill.id in proposal.child_ids or skill.vertical_capability != proposal.vertical_capability:
            continue
        similarity = jaccard(
            query,
            text_tokens(skill.goal, skill.trigger, skill.effect),
        )
        if similarity >= 0.25:
            raw_candidates.append(
                {
                    "kind": "near-scope-alternative",
                    "subject": skill.id,
                    "severity": "medium",
                    "similarity": round(similarity, 6),
                    "evidence": {"contraindications": skill.contraindications},
                }
            )

    relevant_ids = set(proposal.child_ids) | {proposal.id}
    for edge in edges.values():
        if edge.kind == "contradicts" and (
            edge.source_id in relevant_ids or edge.target_id in relevant_ids
        ):
            raw_candidates.append(
                {
                    "kind": "existing-contradiction",
                    "subject": edge.id,
                    "severity": "high",
                    "similarity": 1.0,
                    "evidence": {
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "guard": edge.guard,
                    },
                }
            )

    ordered = sorted(
        raw_candidates,
        key=lambda value: (
            {"high": 0, "medium": 1, "low": 2}[str(value["severity"])],
            str(value["kind"]),
            str(value["subject"]),
        ),
    )
    candidates = [
        {"id": f"counterexample-{index:04d}", **value}
        for index, value in enumerate(ordered, start=1)
    ]
    payload = {
        "schema_version": 1,
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "checkpoint_id": checkpoint_id,
        "source_partition": "development",
        "search_scope": {
            "checkpoint_instances": len(instances),
            "child_skills": len(child_skills),
            "neighbor_skills": len(skills) - len(child_skills),
            "existing_principles": len(principles),
            "overlay_edges": len(edges),
            "searched_failure_outcomes": True,
            "searched_hidden_constants": True,
            "searched_forbidden_actions": True,
            "searched_existing_conflicts": True,
        },
        "candidates": candidates,
        "high_severity_candidate_ids": [
            value["id"] for value in candidates if value["severity"] == "high"
        ],
        "no_result_boundary": (
            "No candidate was found inside the frozen development checkpoint and active forest; "
            "this is not evidence that no counterexample exists."
            if not candidates
            else "Candidates are search leads, not automatically confirmed counterexamples."
        ),
    }
    return {**payload, "report_hash": content_hash(payload)}


def validate_counterexample_report(path: Path, proposal: Principle) -> dict[str, Any]:
    report = load_structured(path)
    report_hash = str(report.get("report_hash", ""))
    payload = {key: value for key, value in report.items() if key != "report_hash"}
    if content_hash(payload) != report_hash:
        raise ValueError("counterexample report hash mismatch")
    expected = {
        "principle_id": proposal.id,
        "principle_version": proposal.version,
        "checkpoint_id": proposal.provenance.get("checkpoint_id"),
        "source_partition": "development",
    }
    mismatches = {
        key: {"expected": value, "found": report.get(key)}
        for key, value in expected.items()
        if report.get(key) != value
    }
    if mismatches:
        raise ValueError(f"counterexample report provenance mismatch: {mismatches}")
    scope = report.get("search_scope", {})
    required_scope = {
        "searched_failure_outcomes",
        "searched_hidden_constants",
        "searched_forbidden_actions",
        "searched_existing_conflicts",
    }
    if not isinstance(scope, dict) or any(scope.get(key) is not True for key in required_scope):
        raise ValueError("counterexample report search scope is incomplete")
    return report


def validate_counterexample_dispositions(
    report: dict[str, Any],
    dispositions: Any,
) -> dict[str, Any]:
    if not isinstance(dispositions, dict):
        raise ValueError("counterexample_dispositions must be an object")
    unresolved = []
    for candidate_id in report.get("high_severity_candidate_ids", []):
        disposition = dispositions.get(candidate_id)
        if (
            not isinstance(disposition, dict)
            or disposition.get("decision")
            not in {"exception-added", "not-applicable", "principle-rejected"}
            or not disposition.get("rationale")
        ):
            unresolved.append(candidate_id)
    if unresolved:
        raise ValueError(f"high-severity counterexamples lack disposition: {unresolved}")
    return dispositions
