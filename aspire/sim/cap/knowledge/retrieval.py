# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic tree-first retrieval and portfolio compilation."""

from __future__ import annotations

from typing import Any, cast

from .checkpoints import instances_at_checkpoint
from .fingerprint import jaccard, text_tokens
from .forest import descendants, validate_forest
from .models import (
    CanonicalSkill,
    KnowledgeManifest,
    OverlayEdge,
    Portfolio,
    Principle,
    TaskContext,
    VerticalTree,
    model_to_dict,
)
from .predicates import evaluate
from .repository import KnowledgeRepository
from .serialization import content_hash


def _latest(values: list[Any]) -> dict[str, Any]:
    result = {}
    for value in sorted(values, key=lambda item: (item.id, tuple(map(int, item.version.split("."))))):
        result[value.id] = value
    return result


def _locked(values: list[Any], revisions: dict[str, str], label: str) -> dict[str, Any]:
    available = {(value.id, value.version): value for value in values}
    missing = [
        f"{logical_id}@{version}"
        for logical_id, version in sorted(revisions.items())
        if (logical_id, version) not in available
    ]
    if missing:
        raise ValueError(f"manifest references missing {label} revisions: {missing}")
    return {
        logical_id: available[(logical_id, version)]
        for logical_id, version in sorted(revisions.items())
    }


def resolve_view(
    repository: KnowledgeRepository,
    manifest: KnowledgeManifest | None,
    *,
    active_overlay_only: bool = False,
) -> tuple[
    dict[str, CanonicalSkill],
    dict[str, Principle],
    dict[str, VerticalTree],
    dict[str, OverlayEdge],
]:
    """Resolve latest or manifest-locked revisions, optionally gating overlays."""
    all_edge_revisions = repository.list_edges()
    if manifest is None:
        result = (
            cast(dict[str, CanonicalSkill], _latest(repository.list_skills())),
            cast(dict[str, Principle], _latest(repository.list_principles())),
            cast(dict[str, VerticalTree], _latest(repository.list_trees())),
            cast(dict[str, OverlayEdge], _latest(all_edge_revisions)),
        )
    else:
        result = (
            cast(
                dict[str, CanonicalSkill],
                _locked(repository.list_skills(), manifest.skill_versions, "skill"),
            ),
            cast(
                dict[str, Principle],
                _locked(repository.list_principles(), manifest.principle_versions, "principle"),
            ),
            cast(
                dict[str, VerticalTree],
                _locked(repository.list_trees(), manifest.tree_versions, "tree"),
            ),
            cast(
                dict[str, OverlayEdge],
                _locked(all_edge_revisions, manifest.edge_versions, "edge"),
            ),
        )
    if not active_overlay_only:
        return result

    from .lifecycle import overlay_revision_promoted

    candidate_revisions = (
        list(result[3].values()) if manifest is not None else all_edge_revisions
    )
    manifests = {
        (value.id, value.version): value for value in repository.list_manifests()
    }
    lifecycle_events = list(repository.iter_evidence("lifecycle"))
    active_edges = [
        edge
        for edge in candidate_revisions
        if edge.status in {"validated", "stable"}
        and not edge.review_required
        and overlay_revision_promoted(
            repository,
            edge,
            edge_revisions=all_edge_revisions,
            manifests=manifests,
            lifecycle_events=lifecycle_events,
        )
    ]
    if manifest is not None and len(active_edges) != len(result[3]):
        active_ids = {edge.id for edge in active_edges}
        rejected = sorted(set(result[3]) - active_ids)
        raise ValueError(f"manifest includes unpromoted overlay edges: {rejected}")
    edges = cast(dict[str, OverlayEdge], _latest(active_edges))
    return result[0], result[1], result[2], edges


def _relevance(context: TaskContext, *values: str) -> float:
    query = text_tokens(context.task_language, context.task_family, " ".join(context.vertical_capabilities))
    document = text_tokens(*values)
    return jaccard(query, document)


def _scope_matches(scope, context: TaskContext) -> bool:
    if scope.suites and context.suite not in scope.suites:
        return False
    if scope.task_families and context.task_family not in scope.task_families:
        return False
    return True


def _principle_allowed(value: Principle, context: TaskContext) -> tuple[bool, str]:
    if value.status not in {"validated", "stable"}:
        return False, f"status:{value.status}"
    if value.review_required:
        return False, "review-required"
    if not _scope_matches(value.scope, context):
        return False, "scope-mismatch"
    applicability = evaluate(value.when, context.facts)
    if applicability is not True:
        return False, "applicability-false-or-unknown"
    for exception in value.exceptions:
        if evaluate(exception.get("when", {}), context.facts) is True:
            return False, f"exception:{exception.get('id', 'unnamed')}"
    return True, "selected"


def _skill_allowed(value: CanonicalSkill, context: TaskContext) -> tuple[bool, str]:
    if value.status not in {"candidate", "validated", "stable"}:
        return False, f"status:{value.status}"
    if not _scope_matches(value.scope, context):
        return False, "scope-mismatch"
    missing = (
        set(value.api_calls) - set(context.available_api_calls)
        if context.available_api_calls
        else set()
    )
    if missing:
        return False, "missing-api:" + ",".join(sorted(missing))
    return True, "selected"


def render_portfolio(
    context: TaskContext,
    principles: list[Principle],
    skills: list[CanonicalSkill],
    exclusions: list[dict[str, str]],
) -> str:
    lines = [f"# Knowledge Portfolio: {context.task_id}", "", "## Governing principles", ""]
    if not principles:
        lines.append("No validated principle matched; canonical-skill fallback was used.")
    for principle in principles:
        lines.extend(
            [
                f"### {principle.title}",
                f"When: {principle.when}",
                f"Do: {principle.decision}",
                f"Why: {principle.invariant}",
            ]
        )
        if principle.exceptions:
            lines.append("Exceptions: " + "; ".join(str(item) for item in principle.exceptions))
        lines.append("")
    lines.extend(["## Operational patterns", ""])
    for skill in skills:
        lines.extend(
            [
                f"### {skill.title}",
                f"Trigger: {skill.trigger or 'task/context match'}",
                f"Goal: {skill.goal}",
                f"Procedure: {skill.operation_template}",
                f"Expected effect: {skill.effect}",
                "",
            ]
        )
    if exclusions:
        lines.extend(["## Explicit exclusions", ""])
        lines.extend(f"- `{item['id']}`: {item['reason']}" for item in exclusions)
    return "\n".join(lines).rstrip() + "\n"


def compile_portfolio(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    context: TaskContext,
    *,
    max_principles: int = 4,
    max_skills: int = 8,
    max_children_per_principle: int = 3,
    manifest: KnowledgeManifest | None = None,
    include_overlay: bool = True,
    enforce_exceptions: bool = True,
    treatment: str = "E",
) -> Portfolio:
    if min(max_principles, max_skills, max_children_per_principle) < 1:
        raise ValueError("retrieval limits must be positive")
    if manifest is not None:
        if manifest.source_partition != "development":
            raise ValueError("held-out knowledge cannot be used to compile an actor portfolio")
        if manifest.checkpoint_id != checkpoint_id:
            raise ValueError(
                f"manifest checkpoint {manifest.checkpoint_id} does not match {checkpoint_id}"
            )
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances_at_checkpoint(repository, checkpoint)
    skills_by_id, principles_by_id, trees_by_id, edges_by_id = resolve_view(
        repository, manifest, active_overlay_only=True
    )
    trees = list(trees_by_id.values())
    edges = list(edges_by_id.values())
    validate_forest(trees, list(skills_by_id.values()), list(principles_by_id.values()), edges).require_ok()
    # Local import avoids coupling lifecycle's graph traversal back into module
    # initialization while still removing invalidated/weak nodes at runtime.
    from .lifecycle import invalidated_refs, principle_metrics, validated_revisions

    invalidated = invalidated_refs(repository)
    promoted = validated_revisions(repository)

    requested_verticals = set(context.vertical_capabilities)
    selected_trees = [
        tree
        for tree in trees
        if not requested_verticals or tree.vertical_capability in requested_verticals
    ]
    if not selected_trees:
        selected_trees = trees

    exclusions: list[dict[str, str]] = []
    principle_candidates: list[tuple[float, Principle]] = []
    tree_node_ids = {node for tree in selected_trees for node in tree.parent_by_child}
    for value in principles_by_id.values():
        if value.id not in tree_node_ids:
            continue
        allowed, reason = _principle_allowed(value, context)
        if not enforce_exceptions and reason.startswith("exception:"):
            allowed, reason = True, "selected-without-exception-gate"
        if value.id in invalidated:
            allowed, reason = False, "invalidated"
        elif (value.id, value.version) not in promoted:
            allowed, reason = False, "unrecorded-promotion"
        elif allowed:
            support = principle_metrics(repository, value, invalidated=invalidated)
            if support.support_sufficiency != "sufficient":
                allowed, reason = False, f"support:{support.support_sufficiency}"
        if not allowed:
            exclusions.append({"id": value.id, "reason": reason})
            continue
        score = _relevance(context, value.title, value.summary, value.decision, value.invariant)
        principle_candidates.append((score, value))
    selected_principles = [
        value for _, value in sorted(principle_candidates, key=lambda item: (-item[0], item[1].id))[:max_principles]
    ]

    candidate_skill_ids: set[str] = set()
    for principle in selected_principles:
        for tree in selected_trees:
            if principle.id in tree.parent_by_child or principle.id in tree.parent_by_child.values():
                principle_skills = [
                    skills_by_id[value]
                    for value in descendants(tree, principle.id)
                    if value in skills_by_id
                ]
                ranked_children = sorted(
                    principle_skills,
                    key=lambda value: (
                        -_relevance(
                            context, value.title, value.goal, value.trigger, value.effect
                        ),
                        value.id,
                    ),
                )
                candidate_skill_ids.update(
                    value.id for value in ranked_children[:max_children_per_principle]
                )
    if not candidate_skill_ids:
        candidate_skill_ids = {
            node_id
            for tree in selected_trees
            for node_id in tree.parent_by_child
            if node_id in skills_by_id
        }

    skill_candidates: list[tuple[float, CanonicalSkill]] = []
    for skill_id in sorted(candidate_skill_ids):
        skill = skills_by_id[skill_id]
        allowed, reason = _skill_allowed(skill, context)
        if skill.id in invalidated:
            allowed, reason = False, "invalidated"
        if not allowed:
            exclusions.append({"id": skill.id, "reason": reason})
            continue
        score = _relevance(context, skill.title, skill.goal, skill.trigger, skill.effect)
        skill_candidates.append((score, skill))
    selected_skills = [
        value for _, value in sorted(skill_candidates, key=lambda item: (-item[0], item[1].id))[:max_skills]
    ]

    selected_ids = {value.id for value in selected_principles} | {
        value.id for value in selected_skills
    }
    selected_edges: list[OverlayEdge] = []
    for edge in sorted(edges if include_overlay else [], key=lambda value: value.id):
        if evaluate(edge.guard, context.facts) is not True:
            continue
        if edge.kind == "exception-to" and edge.target_id in selected_ids:
            blocked_ids = {edge.target_id}
            for tree in selected_trees:
                blocked_ids.update(descendants(tree, edge.target_id))
            selected_principles = [
                value for value in selected_principles if value.id not in blocked_ids
            ]
            selected_skills = [
                value for value in selected_skills if value.id not in blocked_ids
            ]
            source = skills_by_id.get(edge.source_id)
            if source is not None:
                allowed, reason = _skill_allowed(source, context)
                if source.id in invalidated:
                    allowed, reason = False, "invalidated"
                if allowed and source.id not in {value.id for value in selected_skills}:
                    selected_skills.append(source)
                elif not allowed:
                    exclusions.append({"id": source.id, "reason": f"exception-{reason}"})
            exclusions.append(
                {"id": edge.target_id, "reason": f"overlay-exception:{edge.id}"}
            )
            selected_edges.append(edge)
            selected_ids = {value.id for value in selected_principles} | {
                value.id for value in selected_skills
            }
            continue
        if edge.kind == "contradicts" and {
            edge.source_id,
            edge.target_id,
        } <= selected_ids:
            blocked_ids = {edge.target_id}
            for tree in selected_trees:
                blocked_ids.update(descendants(tree, edge.target_id))
            selected_principles = [
                value for value in selected_principles if value.id not in blocked_ids
            ]
            selected_skills = [
                value for value in selected_skills if value.id not in blocked_ids
            ]
            exclusions.append(
                {"id": edge.target_id, "reason": f"overlay-conflict:{edge.id}"}
            )
            selected_edges.append(edge)
            selected_ids = {value.id for value in selected_principles} | {
                value.id for value in selected_skills
            }
            continue
        if edge.source_id not in selected_ids:
            continue
        if edge.kind == "requires" and edge.target_id in skills_by_id:
            target = skills_by_id[edge.target_id]
            allowed, reason = _skill_allowed(target, context)
            if allowed and target.id not in selected_ids:
                selected_skills.append(target)
                selected_ids.add(target.id)
            elif not allowed:
                exclusions.append({"id": target.id, "reason": f"required-{reason}"})
        if edge.target_id in selected_ids:
            selected_edges.append(edge)

    markdown = render_portfolio(context, selected_principles, selected_skills, exclusions)
    estimated_tokens = max(1, len(markdown) // 4)
    if estimated_tokens > context.token_budget:
        # Drop lowest-priority optional skills until the rendered artifact fits.
        required_ids = {edge.target_id for edge in selected_edges if edge.kind == "requires"}
        while estimated_tokens > context.token_budget and selected_skills:
            removable = [value for value in reversed(selected_skills) if value.id not in required_ids]
            if not removable:
                raise ValueError("portfolio token budget cannot satisfy required overlay dependencies")
            removed = removable[0]
            selected_skills.remove(removed)
            exclusions.append({"id": removed.id, "reason": "token-budget"})
            markdown = render_portfolio(context, selected_principles, selected_skills, exclusions)
            estimated_tokens = max(1, len(markdown) // 4)

    return Portfolio(
        context_hash=content_hash(model_to_dict(context)),
        checkpoint_id=checkpoint_id,
        tree_ids=tuple(tree.id for tree in selected_trees),
        principle_ids=tuple(value.id for value in selected_principles),
        skill_ids=tuple(value.id for value in selected_skills),
        overlay_edge_ids=tuple(value.id for value in selected_edges),
        exclusions=tuple(exclusions),
        estimated_tokens=estimated_tokens,
        markdown=markdown,
        manifest_id=f"{manifest.id}@{manifest.version}" if manifest else None,
        treatment=treatment,
        node_versions={
            **{f"skill:{value.id}": value.version for value in selected_skills},
            **{f"principle:{value.id}": value.version for value in selected_principles},
            **{f"tree:{value.id}": value.version for value in selected_trees},
            **{f"edge:{value.id}": value.version for value in selected_edges},
        },
        fallback_used=not selected_principles,
    )
