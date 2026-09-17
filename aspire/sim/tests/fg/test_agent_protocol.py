from __future__ import annotations

import json
import unittest

from aspire.sim.cap.agent_protocol.models import ProtocolError
from aspire.sim.cap.agent_protocol.parser import parse_agent_turn
from aspire.sim.cap.agent_protocol.validator import validate_agent_turn
from aspire.sim.cap.factual_grounding.registry import default_registry
from aspire.sim.cap.factual_grounding.targets import FGSpec


def valid_turn() -> dict:
    return {
        "protocol_version": "agent-turn-v2", "turn_id": "turn-1",
        "turn_kind": "plan_action", "decision": "execute",
        "plan": {"revision": 1, "stages": [{"id": "s1", "goal": "hold cube", "requirement_ids": ["r1"]}]},
        "fg_patch": {"base_revision": 0, "operations": [{"op": "add", "target": {
            "id": "fg.cube-held", "stage_id": "s1", "subject": "cube",
            "predicate": "held_by", "object": "right_gripper", "operator": "equals",
            "expected": True, "value_type": "boolean", "criticality": "required",
            "requirement_ids": ["r1"]
        }}]},
        "action": {"kind": "python", "code": "open_gripper()"},
        "verification_requests": ["fg.cube-held"]
    }


class AgentProtocolTests(unittest.TestCase):
    def test_valid_turn_parses_and_commits_atomically(self):
        turn = parse_agent_turn(json.dumps(valid_turn()))
        self.assertNotIsInstance(turn, ProtocolError)
        spec, error = validate_agent_turn(turn, spec=FGSpec(), registry=default_registry())  # type: ignore[arg-type]
        self.assertIsNone(error)
        self.assertIn("fg.cube-held", spec.active)  # type: ignore[union-attr]

    def test_text_markdown_multiple_json_and_duplicates_fail(self):
        for raw in ("explanation", "```json\n{}\n```", "{}{}", '{"turn_id":"a","turn_id":"b"}'):
            self.assertIsInstance(parse_agent_turn(raw), ProtocolError)

    def test_invalid_plan_action_commits_nothing(self):
        value = valid_turn()
        del value["action"]
        turn = parse_agent_turn(json.dumps(value))
        spec, error = validate_agent_turn(turn, spec=FGSpec(), registry=default_registry())  # type: ignore[arg-type]
        self.assertIsNone(spec)
        self.assertEqual(error.code, "incomplete-plan-action")  # type: ignore[union-attr]

    def test_forbidden_python_is_rejected_before_spec_commit(self):
        value = valid_turn()
        value["action"]["code"] = "env.reset()"
        parsed = parse_agent_turn(json.dumps(value))
        spec, error = validate_agent_turn(parsed, spec=FGSpec(), registry=default_registry())  # type: ignore[arg-type]
        self.assertIsNone(spec)
        self.assertEqual(error.code, "invalid-fg-spec")  # type: ignore[union-attr]

    def test_followup_action_is_a_distinct_turn_kind(self):
        value = {"protocol_version": "agent-turn-v2", "turn_id": "t2", "turn_kind": "action", "decision": "execute", "action": {"kind": "python", "code": "pass"}, "based_on_snapshot": "snapshot"}
        parsed = parse_agent_turn(json.dumps(value))
        self.assertNotIsInstance(parsed, ProtocolError)


if __name__ == "__main__":
    unittest.main()
