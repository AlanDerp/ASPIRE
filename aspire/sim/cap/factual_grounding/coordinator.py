"""Per-trial dynamic FG state machine and public verification coordinator."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from aspire.sim.cap.agent_protocol.models import AgentTurn, ProtocolError
from aspire.sim.cap.agent_protocol.validator import validate_agent_turn
from aspire.sim.cap.perception.capability_registry import CapabilityRegistry
from aspire.sim.cap.perception.observation_broker import ObservationBroker
from .config import FactualGroundingConfig
from .audit_protocol import AuditAdapter
from .comparator import compare
from .finish_gate import FinishDecision, evaluate_finish
from .observations import FGSnapshot, FGVerdict
from .persistence import FGStore
from .registry import PredicateRegistry
from .targets import FGSpec
from .temporal import temporal_verdict
from .verifier import observation_from_evidence, verify_target, verdict_from_observation
from aspire.sim.cap.agent_protocol.spec_critic import review_spec
from aspire.sim.cap.agent_protocol.task_requirements import TaskRequirement
from aspire.sim.cap.knowledge.serialization import content_hash

State = Literal["PLAN_REQUIRED", "READY_TO_EXECUTE", "VERDICT_READY", "COMPLETED", "ABORTED"]


class FGCoordinator:
    def __init__(self, config: FactualGroundingConfig, predicates: PredicateRegistry, capabilities: CapabilityRegistry, broker: ObservationBroker, store: FGStore | None = None, audit_adapter: AuditAdapter | None = None, vdm_verifier=None) -> None:
        self.config = config
        self.predicates = predicates
        self.capabilities = capabilities
        self.broker = broker
        self.store = store
        self.audit_adapter = audit_adapter
        self.vdm_verifier = vdm_verifier
        self.spec = FGSpec()
        self.state: State = "PLAN_REQUIRED"
        self.seen_turn_ids: set[str] = set()
        self.observations: dict[str, list] = {}
        self.latest: dict[str, FGVerdict] = {}
        self.milestones: set[str] = set()
        self._events = 0
        self.plan_revision = 0
        self.latest_snapshot_hash: str | None = None

    def accept_turn(
        self, turn: AgentTurn, *, requirement_ids: tuple[str, ...] | None = None,
        requirements: tuple[TaskRequirement, ...] | None = None,
    ) -> ProtocolError | None:
        if self.state == "PLAN_REQUIRED" and turn.turn_kind != "plan_action":
            return ProtocolError("plan-required", "the first accepted turn must be plan_action")
        if turn.turn_kind == "plan_action" and self.plan_revision != 0:
            return ProtocolError("plan-already-exists", "use revise_plan after the first plan")
        if turn.turn_kind == "revise_plan" and (
            turn.plan is None or turn.plan.revision != self.plan_revision + 1
        ):
            return ProtocolError("stale-plan", "plan revision must increase by exactly one")
        if (
            self.config.feedback == "visible"
            and
            self.latest_snapshot_hash is not None
            and turn.turn_kind in {"action", "observe", "revise_plan", "finish_request"}
            and turn.based_on_snapshot != self.latest_snapshot_hash
        ):
            return ProtocolError("stale-snapshot", "turn must reference the latest public snapshot")
        next_spec, error = validate_agent_turn(turn, spec=self.spec, registry=self.predicates, seen_turn_ids=self.seen_turn_ids, max_targets=self.config.max_targets)
        if error:
            return error
        if next_spec.revision > self.config.max_fg_revisions:
            return ProtocolError("revision-budget", "FG revision budget exceeded")
        if turn.plan is not None and requirement_ids is not None:
            critique = review_spec(requirement_ids, next_spec, requirements)
            if not critique.accepted:
                return ProtocolError("spec-coverage", "; ".join(critique.reasons))
        previous_ids = set(self.spec.active)
        self.spec = next_spec
        if turn.plan is not None:
            self.plan_revision = turn.plan.revision
        self.seen_turn_ids.add(turn.turn_id)
        if self.store:
            self.store.append_public("agent/turns.jsonl", {"turn": asdict(turn), "spec_revision": self.spec.revision})
            if turn.fg_patch is not None:
                spec_payload = {
                    "revision": self.spec.revision,
                    "active": {
                        target_id: asdict(target)
                        for target_id, target in sorted(self.spec.active.items())
                    },
                    "retired": self.spec.retired,
                    "patch": asdict(turn.fg_patch),
                }
                self.store.append_public("fg/spec_revisions.jsonl", {
                    **spec_payload, "content_hash": content_hash(spec_payload),
                })
            if turn.plan is not None:
                self.store.append_public("plan/revisions.jsonl", turn.plan)
            for target_id in sorted(set(self.spec.active) - previous_ids):
                self.store.append_public("fg/targets.jsonl", {
                    "spec_revision": self.spec.revision,
                    "target": asdict(self.spec.active[target_id]),
                })
        if turn.decision == "abort":
            self.state = "ABORTED"
        elif turn.decision == "finish_request":
            decision = self.finish()
            self.state = "COMPLETED" if decision.admitted else "VERDICT_READY"
        else:
            self.state = "READY_TO_EXECUTE"
        return None

    def next_event_id(self) -> str:
        self._events += 1
        return f"fg-event-{self._events:06d}"

    def verify(self, target_ids: tuple[str, ...], *, phase: str, tick_start: int, tick_end: int, event_id: str | None = None) -> FGSnapshot:
        event_id = event_id or self.next_event_id()
        bundle = self.broker.freeze(event_id=event_id, spec_revision=self.spec.revision, phase=phase, tick_start=tick_start, tick_end=tick_end)
        unknown_targets = tuple(target_id for target_id in target_ids if target_id not in self.spec.active)
        if unknown_targets:
            raise ValueError(f"verification requested unknown targets: {unknown_targets}")
        targets = tuple(self.spec.active[target_id] for target_id in target_ids)
        vdm_report = (
            self.vdm_verifier.evaluate(targets, bundle)
            if self.vdm_verifier is not None else None
        )
        vdm_evidence = (
            self.vdm_verifier.evidence_records(vdm_report, bundle)
            if self.vdm_verifier is not None and vdm_report is not None else {}
        )
        observed = []
        verdicts = []
        for target_id in target_ids:
            target = self.spec.active.get(target_id)
            if target is None:
                raise ValueError(f"verification requested unknown target: {target_id}")
            if target_id in vdm_evidence:
                evidence = vdm_evidence[target_id]
                observation = observation_from_evidence(target, bundle, evidence)
                recommended = evidence.payload.get("recommended_probe")
                probes = (str(recommended),) if recommended else ()
            else:
                observation, probes, evidence = verify_target(target, bundle, self.capabilities)
            observed.append(observation)
            history = self.observations.setdefault(target_id, [])
            history.append(observation)
            verdict = temporal_verdict(target, history) if target.temporal.kind == "continuous" else verdict_from_observation(target, observation, probes)
            self.latest[target_id] = verdict
            if verdict.state == "satisfied" and target.temporal.role == "milestone":
                self.milestones.add(target_id)
            verdicts.append(verdict)
            if self.store and evidence is not None:
                self.store.append_public("evidence/derived/measurements.jsonl", evidence)
        audit = []
        comparisons = []
        if self.audit_adapter is not None and self.config.runtime_mode != "observed_only":
            for target_id in target_ids:
                target = self.spec.active[target_id]
                try:
                    audit_item = self.audit_adapter.observe(target, bundle)
                except Exception as error:
                    if self.store:
                        self.store.append_private("fg/audit_errors.jsonl", {
                            "target_id": target_id, "event_id": event_id,
                            "error_type": type(error).__name__,
                        })
                    continue
                audit.append(audit_item)
                comparisons.append(compare(next(item for item in observed if item.target_id == target_id), audit_item, tolerance=target.tolerance))
        snapshot = FGSnapshot(
            self.spec.revision, event_id, tuple(observed), tuple(audit),
            tuple(comparisons), tuple(verdicts),
            vdm_report.scene_change_summary if vdm_report is not None else None,
        )
        if self.store:
            if vdm_report is not None:
                self.store.append_public("fg/vdm_reports.jsonl", {
                    "event_id": vdm_report.event_id,
                    "scene_change_summary": vdm_report.scene_change_summary,
                    "target_results": [asdict(item) for item in vdm_report.target_results],
                    "raw_response": vdm_report.raw_response,
                    "response_hash": vdm_report.response_hash,
                })
            self.store.append_public("evidence/manifest.jsonl", {
                "capture_id": bundle.capture_id, "event_id": bundle.event_id,
                "spec_revision": bundle.spec_revision, "phase": bundle.phase,
                "tick_start": bundle.tick_start, "tick_end": bundle.tick_end,
                "calibration_version": bundle.calibration_version,
                "entity_binding_revision": bundle.entity_binding_revision,
                "sensor_refs": bundle.sensor_refs,
            })
            for item in observed:
                self.store.append_public("fg/observations.observed.jsonl", item)
            for item in verdicts:
                self.store.append_public("fg/verdicts.jsonl", item)
            self.store.append_public("fg/snapshots.jsonl", {
                "public_hash": snapshot.public_hash,
                "event_id": snapshot.event_id,
                "spec_revision": snapshot.spec_revision,
                "observed": [asdict(item) for item in snapshot.observed],
                "public_verdicts": [asdict(item) for item in snapshot.public_verdicts],
                "vdm_description": snapshot.vdm_description,
            })
            for item in audit:
                self.store.append_private("fg/observations.audit.jsonl", item)
            for item in comparisons:
                self.store.append_private("fg/comparisons.jsonl", item)
        self.state = "VERDICT_READY"
        self.latest_snapshot_hash = snapshot.public_hash
        return snapshot

    def finish(self) -> FinishDecision:
        return evaluate_finish(self.spec, self.latest, self.milestones)
