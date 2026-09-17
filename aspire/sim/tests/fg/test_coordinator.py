from __future__ import annotations

import json
import unittest

from aspire.sim.cap.agent_protocol.models import ProtocolError
from aspire.sim.cap.agent_protocol.parser import parse_agent_turn
from aspire.sim.cap.factual_grounding.config import FactualGroundingConfig
from aspire.sim.cap.factual_grounding.coordinator import FGCoordinator
from aspire.sim.cap.factual_grounding.registry import default_registry
from aspire.sim.cap.perception.capability_registry import default_capabilities
from aspire.sim.cap.perception.observation_broker import ObservationBroker


class Source:
    def __init__(self): self.value = True
    def public_observation(self):
        return {"sensor_refs": ["cam"], "fg_measurements": {"held_by": {"status": "known", "value": self.value, "confidence": .9}}}


def plan_turn():
    return {
        "protocol_version": "agent-turn-v2", "turn_id": "t1", "turn_kind": "plan_action", "decision": "execute",
        "plan": {"revision": 1, "stages": [{"id": "s1", "goal": "hold", "requirement_ids": ["r"]}]},
        "fg_patch": {"base_revision": 0, "operations": [{"op": "add", "target": {"id": "fg.held", "stage_id": "s1", "subject": "cube", "predicate": "held_by", "object": "gripper", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]}}]},
        "action": {"kind": "python", "code": "pass"}, "verification_requests": ["fg.held"]
    }


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.source = Source()
        self.coordinator = FGCoordinator(FactualGroundingConfig(enabled=True, protocol="dynamic-v2"), default_registry(), default_capabilities(), ObservationBroker(self.source))

    def test_plan_verify_finish(self):
        turn = parse_agent_turn(json.dumps(plan_turn()))
        self.assertNotIsInstance(turn, ProtocolError)
        self.assertIsNone(self.coordinator.accept_turn(turn))  # type: ignore[arg-type]
        self.coordinator.verify(("fg.held",), phase="post", tick_start=1, tick_end=1)
        self.assertTrue(self.coordinator.finish().admitted)

    def test_finish_unknown_is_blocked(self):
        self.coordinator.accept_turn(parse_agent_turn(json.dumps(plan_turn())))  # type: ignore[arg-type]
        self.assertFalse(self.coordinator.finish().admitted)


if __name__ == "__main__":
    unittest.main()
