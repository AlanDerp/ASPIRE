"""Strict contracts for one model turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from aspire.sim.cap.factual_grounding.targets import FGPatch


@dataclass(frozen=True)
class ProtocolError:
    code: str
    message: str
    retryable: bool = True


@dataclass(frozen=True)
class PlanStage:
    id: str
    goal: str
    requirement_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanStage":
        unknown = sorted(set(value) - {"id", "goal", "requirement_ids"})
        if unknown:
            raise ValueError(f"unknown PlanStage fields: {unknown}")
        return cls(str(value["id"]), str(value["goal"]), tuple(value.get("requirement_ids", ())))


@dataclass(frozen=True)
class Plan:
    revision: int
    stages: tuple[PlanStage, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Plan":
        unknown = sorted(set(value) - {"revision", "stages"})
        if unknown:
            raise ValueError(f"unknown Plan fields: {unknown}")
        plan = cls(int(value["revision"]), tuple(PlanStage.from_dict(item) for item in value["stages"]))
        if plan.revision < 1 or not plan.stages or len({s.id for s in plan.stages}) != len(plan.stages):
            raise ValueError("plan requires a positive revision and unique nonempty stages")
        return plan


@dataclass(frozen=True)
class AgentAction:
    kind: Literal["python", "skill_call"]
    code: str | None = None
    skill_id: str | None = None
    arguments: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"python", "skill_call"}:
            raise ValueError(f"unsupported action kind: {self.kind}")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentAction":
        unknown = sorted(set(value) - {"kind", "code", "skill_id", "arguments"})
        if unknown:
            raise ValueError(f"unknown AgentAction fields: {unknown}")
        action = cls(**value)
        if action.kind == "python" and (not action.code or action.skill_id):
            raise ValueError("python action requires only code")
        if action.kind == "skill_call" and (not action.skill_id or action.code):
            raise ValueError("skill_call requires only skill_id")
        if action.kind == "skill_call" and action.arguments is not None and not isinstance(action.arguments, dict):
            raise ValueError("skill_call arguments must be an object")
        return action


@dataclass(frozen=True)
class AgentTurn:
    protocol_version: Literal["agent-turn-v2"]
    turn_id: str
    turn_kind: Literal["plan_action", "action", "observe", "revise_plan", "finish_request", "abort"]
    decision: Literal["execute", "observe", "revise_plan", "finish_request", "abort"]
    plan: Plan | None = None
    fg_patch: FGPatch | None = None
    action: AgentAction | None = None
    verification_requests: tuple[str, ...] = ()
    based_on_snapshot: str | None = None
    probe_id: str | None = None

    def __post_init__(self) -> None:
        if self.protocol_version != "agent-turn-v2":
            raise ValueError("unsupported AgentTurn protocol version")
        if self.turn_kind not in {"plan_action", "action", "observe", "revise_plan", "finish_request", "abort"}:
            raise ValueError("unsupported AgentTurn turn_kind")
        if self.decision not in {"execute", "observe", "revise_plan", "finish_request", "abort"}:
            raise ValueError("unsupported AgentTurn decision")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentTurn":
        allowed = {
            "protocol_version", "turn_id", "turn_kind", "decision", "plan", "fg_patch",
            "action", "verification_requests", "based_on_snapshot",
            "probe_id",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown AgentTurn fields: {unknown}")
        payload = dict(value)
        payload["plan"] = Plan.from_dict(payload["plan"]) if payload.get("plan") else None
        payload["fg_patch"] = FGPatch.from_dict(payload["fg_patch"]) if payload.get("fg_patch") else None
        payload["action"] = AgentAction.from_dict(payload["action"]) if payload.get("action") else None
        payload["verification_requests"] = tuple(payload.get("verification_requests", ()))
        turn = cls(**payload)
        if turn.protocol_version != "agent-turn-v2" or not turn.turn_id:
            raise ValueError("unsupported protocol version or empty turn_id")
        return turn
