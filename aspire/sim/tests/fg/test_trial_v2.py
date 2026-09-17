from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path

import numpy as np

try:
    from aspire.sim.cap.envs.agent_turn_loop import run_dynamic_trial
except ModuleNotFoundError as error:
    run_dynamic_trial = None
    MISSING_DEPENDENCY = str(error)
else:
    MISSING_DEPENDENCY = ""
from aspire.sim.cap.factual_grounding.config import RuntimeFeatureSet
from aspire.sim.cap.factual_grounding.audit_protocol import register_audit_adapter
from aspire.sim.cap.factual_grounding.observations import FGObservation
from aspire.sim.cap.factual_grounding.verifier import semantic_hash
from aspire.sim.cap.factual_grounding.vdm_verifier import VDMFGVerifier


class TestAudit:
    def observe(self, target, bundle):
        return FGObservation(target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "audit", "test", True, "known", 1.0, {}, ("private",), (), bundle.tick_end, None, semantic_hash(target))


class FixedAudit:
    def __init__(self, value):
        self.value = value

    def observe(self, target, bundle):
        return FGObservation(target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "audit", "fixed", self.value, "known", 1.0, {}, ("private",), (), bundle.tick_end, None, semantic_hash(target))


try:
    register_audit_adapter("test-development-audit", lambda _: TestAudit())
except ValueError:
    pass
for adapter_name, adapter_value in (("test-heldout-true", True), ("test-heldout-false", False)):
    try:
        register_audit_adapter(
            adapter_name, lambda _, value=adapter_value: FixedAudit(value)
        )
    except ValueError:
        pass


class FakeEnv:
    def __init__(self):
        self._runtime_features = RuntimeFeatureSet.from_dict({"factual_grounding": {"enabled": True, "protocol": "dynamic-v2", "feedback": "visible"}})
        self.step_calls = 0
        self.value = True
    def public_observation(self):
        return {"sensor_refs": ["cam"], "fg_measurements": {"held_by": {"status": "known", "value": self.value, "confidence": .9}}}
    def step_public(self, code):
        self.step_calls += 1
        return {}, 0.0, False, False, {"sandbox_rc": 0, "stdout": "", "stderr": "", "task_completed": False}
    def run_public_probe(self, probe_id):
        self.value = True
    def render(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)


def turn(decision="execute", snapshot=None):
    if decision == "finish_request":
        return json.dumps({"protocol_version": "agent-turn-v2", "turn_id": "t2", "turn_kind": "finish_request", "decision": "finish_request", "based_on_snapshot": snapshot})
    return json.dumps({"protocol_version": "agent-turn-v2", "turn_id": "t1", "turn_kind": "plan_action", "decision": "execute", "plan": {"revision": 1, "stages": [{"id": "s", "goal": "hold", "requirement_ids": ["task-success"]}]}, "fg_patch": {"base_revision": 0, "operations": [{"op": "add", "target": {"id": "fg.held", "stage_id": "s", "subject": "cube", "predicate": "held_by", "object": "gripper", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": ["task-success"]}}]}, "action": {"kind": "python", "code": "pass"}, "verification_requests": ["fg.held"]})


@unittest.skipIf(run_dynamic_trial is None, f"optional simulator dependency missing: {MISSING_DEPENDENCY}")
class TrialV2Tests(unittest.TestCase):
    def test_production_loop_plan_action_verify_finish(self):
        env = FakeEnv()
        calls = 0
        def reply(prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                instruction = prompt[-1]["content"][-1]["text"]
                self.assertIn("Allowed verification capabilities", instruction)
                self.assertIn("visual-held-by-v1", instruction)
                return turn()
            text = prompt[-1]["content"][-1]["text"]
            snapshot = text.split("snapshot ", 1)[1].splitlines()[0]
            return turn("finish_request", snapshot)
        result = run_dynamic_trial(env, [{"role": "user", "content": []}], reply, trial_id="x")
        self.assertEqual(env.step_calls, 1)
        self.assertTrue(result.agent_finish_requested)
        self.assertTrue(result.fg_finish_verdict)

    def test_bad_protocol_executes_no_action(self):
        env = FakeEnv()
        result = run_dynamic_trial(env, [{"role": "user", "content": []}], lambda _: "bad", trial_id="x")
        self.assertEqual(env.step_calls, 0)
        self.assertEqual(result.execution_status, "protocol-error")

    def test_model_and_action_exceptions_become_explicit_statuses(self):
        env = FakeEnv()
        model_result = run_dynamic_trial(
            env, [{"role": "user", "content": []}],
            lambda _: (_ for _ in ()).throw(TimeoutError()), trial_id="x",
        )
        self.assertEqual(model_result.execution_status, "model-error")
        self.assertEqual(env.step_calls, 0)

        class BrokenEnv(FakeEnv):
            def step_public(self, code):
                raise RuntimeError("action failed")

        action_result = run_dynamic_trial(
            BrokenEnv(), [{"role": "user", "content": []}], lambda _: turn(),
            trial_id="x", max_turns=1,
        )
        self.assertEqual(action_result.execution_status, "action-error")
        self.assertEqual(action_result.sandbox_rc, 1)

    def test_shadow_records_fg_but_does_not_gate_finish(self):
        env = FakeEnv()
        env.value = False
        env._runtime_features = RuntimeFeatureSet.from_dict({"factual_grounding": {
            "enabled": True, "protocol": "dynamic-v2", "feedback": "shadow",
        }})
        replies = iter([turn(), turn("finish_request", None)])
        result = run_dynamic_trial(
            env, [{"role": "user", "content": []}], lambda _: next(replies),
            trial_id="x",
        )
        self.assertEqual(result.execution_status, "agent-finished-shadow")
        self.assertTrue(result.agent_finish_requested)
        self.assertFalse(result.fg_finish_verdict)

    def test_vdm_description_and_verdict_are_returned_to_actor(self):
        env = FakeEnv()
        actor_calls = 0

        def vdm_reply(prompt):
            request = json.loads(prompt[-1]["content"][0]["text"].split("INPUT:\n", 1)[1])
            event_id = request["execution_interval"]["event_id"]
            return json.dumps({
                "protocol_version": "vdm-fg-verifier-v1",
                "event_id": event_id,
                "scene_change_summary": "The cube moved with the closed gripper.",
                "target_results": [{
                    "target_id": "fg.held", "subject_identified": True,
                    "object_identified": True, "observed_value": True,
                    "status": "known", "provisional_verdict": "satisfied",
                    "confidence": .9,
                    "evidence": [{"view": "main", "time": "final", "observation": "Cube is between the fingers."}],
                    "uncertainty_reasons": [], "recommended_probe": None,
                }],
                "overall_visual_assessment": "all_required_satisfied",
            })

        verifier = VDMFGVerifier(
            env, vdm_reply, "Pick up the cube.",
            allowed_probes=("alternate-view",),
        )

        def actor_reply(prompt):
            nonlocal actor_calls
            actor_calls += 1
            if actor_calls == 1:
                instruction = prompt[-1]["content"][-1]["text"]
                self.assertIn("vdm-fg-verifier-v1", instruction)
                return turn()
            projection = prompt[-1]["content"][-1]["text"]
            self.assertIn("[VDM EXECUTION DESCRIPTION]", projection)
            self.assertIn("fg.held: SATISFIED", projection)
            snapshot = projection.split("snapshot ", 1)[1].splitlines()[0]
            return turn("finish_request", snapshot)

        result = run_dynamic_trial(
            env, [{"role": "user", "content": []}], actor_reply,
            trial_id="x", vdm_verifier=verifier,
        )
        self.assertTrue(result.agent_finish_requested)
        self.assertTrue(result.fg_finish_verdict)

    def test_terminal_environment_still_allows_actor_finish_request(self):
        class TerminalEnv(FakeEnv):
            def step_public(self, code):
                self.step_calls += 1
                return {}, 1.0, True, False, {
                    "sandbox_rc": 0, "stdout": "", "stderr": "",
                    "task_completed": True,
                }

        env = TerminalEnv()
        calls = 0

        def reply(prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                return turn()
            projection = prompt[-1]["content"][-2]["text"]
            snapshot = projection.split("snapshot ", 1)[1].splitlines()[0]
            return turn("finish_request", snapshot)

        result = run_dynamic_trial(
            env, [{"role": "user", "content": []}], reply, trial_id="x",
        )
        self.assertTrue(result.agent_finish_requested)
        self.assertEqual(result.execution_status, "fg-completed")

    def test_development_mismatch_runs_marked_probe_and_saves_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            env = FakeEnv()
            env.value = False
            env._runtime_features = RuntimeFeatureSet.from_dict({"factual_grounding": {
                "enabled": True, "protocol": "dynamic-v2", "feedback": "visible",
                "runtime_mode": "development_compare", "audit_adapter": "test-development-audit",
                "private_artifact_root": str(Path(directory) / "private"), "isolated_worker": True,
            }})
            replies = iter([turn()])
            run_dynamic_trial(env, [{"role": "user", "content": []}], lambda _: next(replies), trial_id="x", public_root=Path(directory) / "public", max_turns=1)
            self.assertTrue((Path(directory) / "private/x/skill_proposals/verification_candidates.jsonl").is_file())
            self.assertTrue((Path(directory) / "public/fg/active_probes.jsonl").is_file())

    def test_held_out_audit_value_does_not_change_public_control_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outcomes = []
            prompts = []
            for suffix in ("true", "false"):
                env = FakeEnv()
                env._runtime_features = RuntimeFeatureSet.from_dict({"factual_grounding": {
                    "enabled": True, "protocol": "dynamic-v2", "feedback": "visible",
                    "runtime_mode": "held_out_audit",
                    "audit_adapter": f"test-heldout-{suffix}",
                    "private_artifact_root": str(root / f"private-{suffix}"),
                    "isolated_worker": True,
                }})
                calls = 0
                run_prompts = []
                def reply(prompt):
                    nonlocal calls
                    calls += 1
                    run_prompts.append(prompt[-1]["content"][-1]["text"])
                    if calls == 1:
                        return turn()
                    snapshot = run_prompts[-1].split("snapshot ", 1)[1].splitlines()[0]
                    return turn("finish_request", snapshot)
                outcomes.append(run_dynamic_trial(
                    env, [{"role": "user", "content": []}], reply,
                    trial_id="x", public_root=root / f"public-{suffix}",
                ))
                prompts.append(run_prompts)
            self.assertEqual(prompts[0], prompts[1])
            comparable = []
            for outcome in outcomes:
                value = outcome.__dict__.copy()
                value.pop("trace_path")
                comparable.append(value)
            self.assertEqual(comparable[0], comparable[1])
            self.assertFalse((root / "public-true/fg/active_probes.jsonl").exists())
            self.assertFalse((root / "public-false/fg/active_probes.jsonl").exists())


if __name__ == "__main__": unittest.main()
