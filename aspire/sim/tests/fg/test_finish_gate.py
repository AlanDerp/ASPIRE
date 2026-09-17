from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.finish_gate import evaluate_finish
from aspire.sim.cap.factual_grounding.observations import FGVerdict
from aspire.sim.cap.factual_grounding.targets import FGSpec, FGTarget


class FinishGateTests(unittest.TestCase):
    def test_historical_milestone_need_not_be_current(self):
        milestone = FGTarget.from_dict({"id": "fg.was-held", "stage_id": "s", "subject": "cube", "predicate": "held_by", "object": "gripper", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": ["pick"], "temporal": {"role": "milestone"}})
        terminal = FGTarget.from_dict({"id": "fg.placed", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": ["place"]})
        spec = FGSpec(1, {milestone.id: milestone, terminal.id: terminal})
        latest = {terminal.id: FGVerdict(terminal.id, "satisfied", 1.0, (), ())}
        self.assertTrue(evaluate_finish(spec, latest, {milestone.id}).admitted)


if __name__ == "__main__": unittest.main()
