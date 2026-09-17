"""Task-requirement coverage review independent of audit data."""

from __future__ import annotations

from dataclasses import dataclass

from aspire.sim.cap.factual_grounding.targets import FGSpec
from .task_requirements import TaskRequirement


@dataclass(frozen=True)
class SpecCritique:
    accepted: bool
    missing_requirement_ids: tuple[str, ...]
    uncovered_required_targets: tuple[str, ...]
    reasons: tuple[str, ...]


def review_spec(
    requirement_ids: tuple[str, ...], spec: FGSpec,
    requirements: tuple[TaskRequirement, ...] | None = None,
) -> SpecCritique:
    required = [value for value in spec.active.values() if value.criticality == "required"]
    covered = {item for target in required for item in target.requirement_ids}
    missing = tuple(sorted(set(requirement_ids) - covered))
    unresolved = tuple(sorted(target.id for target in required if not target.requirement_ids))
    reasons = tuple(
        [f"missing task requirements: {', '.join(missing)}"] if missing else []
    ) + tuple([f"required targets without requirements: {', '.join(unresolved)}"] if unresolved else [])
    if requirements is not None:
        by_id = {item.id: item for item in requirements}
        semantic_errors = []
        for target in required:
            for requirement_id in target.requirement_ids:
                requirement = by_id.get(requirement_id)
                if requirement is None:
                    semantic_errors.append(f"{target.id} references unknown requirement {requirement_id}")
                elif requirement.predicate_hint and requirement.predicate_hint != target.predicate:
                    semantic_errors.append(
                        f"{target.id} predicate {target.predicate} does not cover {requirement.predicate_hint}"
                    )
                elif (
                    requirement.expected_hint is not None
                    and target.expected != requirement.expected_hint
                ):
                    semantic_errors.append(
                        f"{target.id} expected {target.expected!r} contradicts requirement "
                        f"{requirement_id} expected {requirement.expected_hint!r}"
                    )
        reasons += tuple(sorted(semantic_errors))
    return SpecCritique(not reasons, missing, unresolved, reasons)
