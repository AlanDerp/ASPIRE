"""Semantic and capability validation for parsed AgentTurns."""

from __future__ import annotations

from .models import AgentTurn, ProtocolError
from aspire.sim.cap.factual_grounding.registry import PredicateRegistry
from aspire.sim.cap.factual_grounding.targets import FGSpec
from .safety import validate_public_python


def validate_agent_turn(
    turn: AgentTurn,
    *,
    spec: FGSpec,
    registry: PredicateRegistry,
    seen_turn_ids: set[str] | None = None,
    max_targets: int = 24,
) -> tuple[FGSpec | None, ProtocolError | None]:
    if turn.turn_id in (seen_turn_ids or set()):
        return None, ProtocolError("duplicate-turn", f"turn already committed: {turn.turn_id}")
    expected = {
        "plan_action": "execute", "action": "execute", "observe": "observe", "revise_plan": "revise_plan",
        "finish_request": "finish_request", "abort": "abort",
    }
    if expected.get(turn.turn_kind) != turn.decision:
        return None, ProtocolError("decision-kind-mismatch", "turn_kind and decision disagree")
    if turn.turn_kind == "plan_action" and (turn.plan is None or turn.action is None or turn.fg_patch is None):
        return None, ProtocolError("incomplete-plan-action", "plan_action requires plan, fg_patch, and action")
    if turn.turn_kind == "action" and (
        turn.action is None or turn.plan is not None or turn.fg_patch is not None
    ):
        return None, ProtocolError("invalid-action", "action turn requires only an action")
    if turn.turn_kind in {"finish_request", "abort"} and (turn.action or turn.fg_patch):
        return None, ProtocolError("terminal-turn-has-effects", "terminal turn cannot include action or FG patch")
    if turn.turn_kind == "observe" and (
        turn.action is not None or not turn.verification_requests or not turn.probe_id
    ):
        return None, ProtocolError("invalid-observe", "observe requires probe_id and verification requests, without an action")
    if turn.turn_kind != "observe" and turn.probe_id is not None:
        return None, ProtocolError("unexpected-probe", "probe_id is valid only for observe turns")
    if turn.turn_kind == "revise_plan" and (turn.plan is None or turn.fg_patch is None or turn.action is not None):
        return None, ProtocolError("invalid-replan", "revise_plan requires plan and FG patch, without an action")
    next_spec = spec
    try:
        if turn.action is not None and turn.action.kind == "python":
            validate_public_python(turn.action.code or "")
        if turn.fg_patch:
            for operation in turn.fg_patch.operations:
                if operation.target:
                    registry.validate(operation.target)
            next_spec = spec.apply(turn.fg_patch, max_targets=max_targets)
        if turn.plan is not None:
            stage_ids = {stage.id for stage in turn.plan.stages}
            if any(target.stage_id not in stage_ids for target in next_spec.active.values()):
                raise ValueError("FG target references a missing plan stage")
        if turn.turn_kind == "plan_action":
            if not any(target.criticality == "required" for target in next_spec.active.values()):
                raise ValueError("initial plan requires at least one required FG target")
        unknown_requests = sorted(set(turn.verification_requests) - set(next_spec.active))
        if unknown_requests:
            raise ValueError(f"verification requests unknown targets: {unknown_requests}")
    except ValueError as error:
        return None, ProtocolError("invalid-fg-spec", str(error))
    return next_spec, None
