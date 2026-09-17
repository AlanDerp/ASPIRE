"""Production dynamic-v2 AgentTurn loop."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from aspire.sim.cap.agent_protocol.models import AgentTurn, ProtocolError
from aspire.sim.cap.agent_protocol.parser import parse_agent_turn
from aspire.sim.cap.agent_protocol.prompt import planning_instruction, protocol_error_prompt
from aspire.sim.cap.factual_grounding.coordinator import FGCoordinator
from aspire.sim.cap.factual_grounding.audit_protocol import build_audit_adapter
from aspire.sim.cap.factual_grounding.persistence import FGStore
from aspire.sim.cap.factual_grounding.prompt_projection import project_public
from aspire.sim.cap.factual_grounding.registry import default_registry
from aspire.sim.cap.perception.capability_registry import default_capabilities, install_frozen_verification_skills
from aspire.sim.cap.perception.observation_broker import ObservationBroker
from aspire.sim.cap.knowledge.serialization import sha256_text
from aspire.sim.cap.agent_protocol.task_requirements import TaskRequirement
from aspire.sim.cap.factual_grounding.audit_coach import propose_probe
from aspire.sim.cap.perception.probe_planner import ProbeOption

QueryFn = Callable[[list[dict[str, Any]]], str]


@dataclass(frozen=True)
class DynamicTrialResult:
    execution_status: str
    agent_finish_requested: bool
    fg_finish_verdict: bool
    environment_task_completed: bool | None
    reward: float
    terminated: bool
    truncated: bool
    sandbox_rc: int
    turns: int
    final_code: str
    trace_path: str | None
    log: str


def _append_text(prompt: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    result = copy.deepcopy(prompt)
    result[-1]["content"].append({"type": "text", "text": text})
    return result


def run_dynamic_trial(
    env: Any,
    initial_prompt: list[dict[str, Any]],
    query: QueryFn,
    *,
    trial_id: str,
    public_root: Path | None = None,
    max_turns: int = 32,
    requirement_ids: tuple[str, ...] = ("task-success",),
    requirements: tuple[TaskRequirement, ...] | None = None,
    vdm_verifier=None,
) -> DynamicTrialResult:
    cfg = env._runtime_features.factual_grounding
    private_root = (
        Path(cfg.private_artifact_root) / trial_id
        if public_root and cfg.private_artifact_root else None
    )
    if private_root is not None:
        from aspire.sim.cap.envs.generated_worker import validate_worker_isolation
        private_boundary = Path(cfg.private_artifact_root)
        validate_worker_isolation(
            public_root, private_boundary, isolated_worker=cfg.isolated_worker
        )
        setattr(env, "_fg_private_artifact_root", private_boundary)
    store = FGStore(public_root, private_root) if public_root else None
    audit_adapter = (
        build_audit_adapter(cfg.audit_adapter, getattr(env, "low_level_env", env))
        if cfg.runtime_mode != "observed_only" else None
    )
    capabilities = default_capabilities()
    predicates = default_registry()
    capability_manifest = capabilities.public_manifest()
    if vdm_verifier is not None:
        from aspire.sim.cap.factual_grounding.vdm_verifier import install_vdm_predicates
        install_vdm_predicates(predicates)
        capability_manifest += vdm_verifier.public_manifest()
    if cfg.verification_skill_paths:
        if not cfg.verification_checkpoint:
            raise ValueError("verification_skill_paths require verification_checkpoint")
        install_frozen_verification_skills(
            capabilities, [Path(path) for path in cfg.verification_skill_paths],
            checkpoint_id=cfg.verification_checkpoint,
        )
    coordinator = FGCoordinator(
        cfg, predicates, capabilities, ObservationBroker(env), store,
        audit_adapter, vdm_verifier,
    )
    if requirements is not None:
        requirement_ids = tuple(item.id for item in requirements)
        requirement_text = "\n".join(f"- {item.id}: {item.text}" for item in requirements)
    else:
        requirement_text = "\n".join(f"- {item}" for item in requirement_ids)
    prompt = _append_text(
        initial_prompt,
        planning_instruction(
            requirement_text, capability_manifest, cfg.allowed_probes,
            feedback_visible=cfg.feedback == "visible",
        ),
    )
    repairs = 0
    reward, terminated, truncated = 0.0, False, False
    sandbox_rc, task_completed = -1, None
    logs: list[str] = []
    codes: list[str] = []
    agent_finish_requested = False
    execution_status = "turn-budget-exhausted"
    probe_runs = 0

    for turn_number in range(1, min(max_turns, cfg.max_model_calls) + 1):
        probes_this_turn = 0
        try:
            raw = query(prompt)
        except Exception as error:
            execution_status = "model-error"
            logs.append(f"model query failed: {type(error).__name__}")
            if store:
                store.append_public("agent/model_errors.jsonl", {
                    "turn_number": turn_number, "error_type": type(error).__name__,
                })
            break
        if store:
            store.append_public("agent/raw_turns.jsonl", {
                "turn_number": turn_number, "raw_sha256": sha256_text(raw), "raw": raw,
            })
        parsed = parse_agent_turn(raw)
        if isinstance(parsed, ProtocolError):
            repairs += 1
            if store:
                store.append_public("agent/protocol_errors.jsonl", asdict(parsed))
            if repairs > cfg.max_protocol_repairs:
                execution_status = "protocol-error"
                break
            prompt = _append_text(prompt, protocol_error_prompt(parsed.code, parsed.message, cfg.max_protocol_repairs - repairs + 1))
            continue
        turn: AgentTurn = parsed
        error = coordinator.accept_turn(
            turn, requirement_ids=requirement_ids, requirements=requirements
        )
        if error:
            repairs += 1
            if store:
                store.append_public("agent/protocol_errors.jsonl", asdict(error))
            if repairs > cfg.max_protocol_repairs:
                execution_status = "protocol-error"
                break
            prompt = _append_text(prompt, protocol_error_prompt(error.code, error.message, cfg.max_protocol_repairs - repairs + 1))
            continue
        repairs = 0
        if turn.decision == "abort":
            execution_status = "aborted"
            break
        if turn.decision == "finish_request":
            agent_finish_requested = True
            finish = coordinator.finish()
            if cfg.feedback == "shadow":
                execution_status = "agent-finished-shadow"
                break
            if finish.admitted:
                execution_status = "fg-completed"
                break
            prompt = _append_text(prompt, "Finish rejected: " + "; ".join(finish.reasons))
            continue
        if terminated or truncated:
            prompt = _append_text(
                prompt,
                "The environment has stopped and no further action or probe can run. "
                "Review the latest FG projection and return finish_request or abort.",
            )
            continue
        if turn.action is not None:
            event_id = coordinator.next_event_id()
            tick_start = int(env.public_tick()) if hasattr(env, "public_tick") else turn_number
            if vdm_verifier is not None:
                vdm_verifier.begin_event()
            try:
                if turn.action.kind == "python":
                    codes.append(turn.action.code or "")
                    _, reward_value, terminated, truncated, info = env.step_public(turn.action.code or "")
                elif turn.action.kind == "skill_call":
                    codes.append(f"# skill_call: {turn.action.skill_id}")
                    _, reward_value, terminated, truncated, info = env.step_skill(
                        turn.action.skill_id or "", turn.action.arguments
                    )
                else:
                    execution_status = "unsupported-action-kind"
                    break
            except Exception as error:
                sandbox_rc = 1
                execution_status = "action-error"
                logs.append(f"action execution failed: {type(error).__name__}")
                if store:
                    store.append_public("execution/errors.jsonl", {
                        "event_id": event_id, "turn_id": turn.turn_id,
                        "error_type": type(error).__name__,
                    })
                break
            tick_end = int(env.public_tick()) if hasattr(env, "public_tick") else turn_number
            reward = float(reward_value)
            sandbox_rc = int(info["sandbox_rc"])
            task_completed = info.get("task_completed")
            logs.extend([info.get("stdout", ""), info.get("stderr", "")])
            if store:
                store.append_public("execution/events.jsonl", {
                    "event_id": event_id, "turn_id": turn.turn_id,
                    "kind": "action", "tick_start": tick_start, "tick_end": tick_end,
                    "sandbox_rc": sandbox_rc,
                })
        else:
            event_id = coordinator.next_event_id()
            tick_start = tick_end = int(env.public_tick()) if hasattr(env, "public_tick") else turn_number
            if turn.turn_kind == "observe":
                if vdm_verifier is not None:
                    vdm_verifier.begin_event()
                if turn.probe_id not in cfg.allowed_probes:
                    prompt = _append_text(prompt, f"Probe unsupported: {turn.probe_id}")
                    continue
                if (
                    probes_this_turn >= cfg.max_active_probes_per_turn
                    or probe_runs >= cfg.max_total_probes
                ):
                    execution_status = "probe-budget-exhausted"
                    break
                try:
                    env.run_public_probe(turn.probe_id)
                    probe_runs += 1
                    probes_this_turn += 1
                    tick_end = int(env.public_tick()) if hasattr(env, "public_tick") else turn_number
                except Exception as error:
                    if store:
                        store.append_public("fg/active_probes.jsonl", {
                            "event_id": event_id, "probe_id": turn.probe_id,
                            "status": "error", "error_type": type(error).__name__,
                        })
                    prompt = _append_text(prompt, f"Probe failed: {type(error).__name__}")
                    continue
                if store:
                    store.append_public("fg/active_probes.jsonl", {
                        "event_id": event_id, "probe_id": turn.probe_id,
                        "status": "completed", "audit_influenced": False,
                    })
            if store:
                store.append_public("execution/events.jsonl", {
                    "event_id": event_id, "turn_id": turn.turn_id,
                    "kind": "probe", "tick_start": tick_start, "tick_end": tick_end,
                })
        requested = turn.verification_requests or tuple(coordinator.spec.active)
        snapshot = coordinator.verify(requested, phase="post-action" if turn.action else "probe", tick_start=tick_start, tick_end=tick_end, event_id=event_id)
        if (
            cfg.runtime_mode == "development_compare"
            and snapshot.comparisons
            and probes_this_turn < cfg.max_active_probes_per_turn
            and probe_runs < cfg.max_total_probes
        ):
            options = tuple(
                ProbeOption(probe_id, 1.0, 1.0)
                for probe_id in cfg.allowed_probes
            )
            mismatch = next(
                (item for item in snapshot.comparisons if item.alignment == "mismatch"),
                None,
            )
            proposal = None if mismatch is None else propose_probe(
                cfg, mismatch, options,
                remaining_budget=float(min(
                    cfg.max_active_probes_per_turn - probes_this_turn,
                    cfg.max_total_probes - probe_runs,
                )),
            )
            if proposal is not None:
                if store:
                    store.append_private(
                        "skill_proposals/verification_candidates.jsonl", proposal
                    )
                probe_id = str(proposal["probe"]["id"])
                try:
                    if vdm_verifier is not None:
                        vdm_verifier.begin_event()
                    env.run_public_probe(probe_id)
                    probe_runs += 1
                    probes_this_turn += 1
                    probe_event = coordinator.next_event_id()
                    probe_tick = int(env.public_tick()) if hasattr(env, "public_tick") else turn_number
                    if store:
                        store.append_public("fg/active_probes.jsonl", {
                            "event_id": probe_event, "probe_id": probe_id,
                            "status": "completed", "audit_influenced": True,
                        })
                    snapshot = coordinator.verify(
                        requested, phase="development-audit-probe",
                        tick_start=probe_tick, tick_end=probe_tick,
                        event_id=probe_event,
                    )
                except Exception as error:
                    if store:
                        store.append_private("fg/audit_coach_errors.jsonl", {
                            "probe_id": probe_id, "error_type": type(error).__name__,
                        })
        if cfg.feedback == "visible":
            projection = project_public(coordinator.spec, snapshot)
            if store:
                store.append_public("fg/prompt_projections.jsonl", {
                    "snapshot_hash": snapshot.public_hash,
                    "projection_sha256": sha256_text(projection), "text": projection,
                })
            prompt = _append_text(prompt, projection)
        if terminated or truncated:
            if cfg.feedback == "shadow":
                execution_status = "environment-terminated" if terminated else "environment-truncated"
                break
            prompt = _append_text(
                prompt,
                "The environment has stopped. Use the latest VDM description and FG "
                "verification to return finish_request or abort; do not request another action.",
            )
    finish = coordinator.finish()
    return DynamicTrialResult(
        execution_status, agent_finish_requested, finish.admitted, task_completed,
        reward, terminated, truncated, sandbox_rc, len(coordinator.seen_turn_ids),
        "\n\n".join(codes), str(public_root) if public_root else None,
        "\n".join(item for item in logs if item),
    )
