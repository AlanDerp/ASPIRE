from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.agent_protocol.parser import parse_agent_turn
from aspire.sim.cap.factual_grounding.config import FactualGroundingConfig
from aspire.sim.cap.factual_grounding.coordinator import FGCoordinator
from aspire.sim.cap.factual_grounding.persistence import FGStore
from aspire.sim.cap.factual_grounding.prompt_projection import project_public
from aspire.sim.cap.factual_grounding.registry import default_registry
from aspire.sim.cap.perception.capability_registry import default_capabilities
from aspire.sim.cap.perception.observation_broker import ObservationBroker


class Source:
    def public_observation(self):
        return {"calibration_version": "c1", "sensor_refs": ["main", "wrist"], "fg_measurements": {"contact": {"status": "known", "value": False, "confidence": .8, "independent_views": 2}}}


class EndToEndTests(unittest.TestCase):
    def test_plan_dynamic_target_evidence_verdict_projection_and_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = FGCoordinator(FactualGroundingConfig(enabled=True, protocol="dynamic-v2", feedback="visible"), default_registry(), default_capabilities(), ObservationBroker(Source()), FGStore(Path(directory)))
            raw = json.dumps({"protocol_version": "agent-turn-v2", "turn_id": "t1", "turn_kind": "plan_action", "decision": "execute", "plan": {"revision": 1, "stages": [{"id": "s1", "goal": "avoid contact", "requirement_ids": ["r1"]}]}, "fg_patch": {"base_revision": 0, "operations": [{"op": "add", "target": {"id": "fg.no-contact", "stage_id": "s1", "subject": "cube", "predicate": "contact", "object": "platform", "operator": "equals", "expected": False, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r1"], "evidence_policy": {"min_independent_views": 2}}}]}, "action": {"kind": "python", "code": "pass"}, "verification_requests": ["fg.no-contact"]})
            error = coordinator.accept_turn(parse_agent_turn(raw), requirement_ids=("r1",))  # type: ignore[arg-type]
            self.assertIsNone(error)
            snapshot = coordinator.verify(("fg.no-contact",), phase="post", tick_start=1, tick_end=1)
            self.assertTrue(coordinator.finish().admitted)
            self.assertIn("FINISH is admissible", project_public(coordinator.spec, snapshot))
            self.assertTrue((Path(directory) / "evidence/derived/measurements.jsonl").is_file())


if __name__ == "__main__": unittest.main()
