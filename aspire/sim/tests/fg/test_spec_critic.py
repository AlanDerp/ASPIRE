from __future__ import annotations

import unittest

from aspire.sim.cap.agent_protocol.spec_critic import review_spec
from aspire.sim.cap.factual_grounding.targets import FGSpec, FGTarget


class SpecCriticTests(unittest.TestCase):
    def test_missing_task_requirement_is_rejected(self):
        target = FGTarget.from_dict({
            "id": "fg.held", "stage_id": "s1", "subject": "cube", "predicate": "held_by",
            "object": "right_gripper", "operator": "equals", "expected": True,
            "value_type": "boolean", "criticality": "required", "requirement_ids": ["holding"],
        })
        report = review_spec(("holding", "no-contact"), FGSpec(1, {target.id: target}))
        self.assertFalse(report.accepted)
        self.assertEqual(report.missing_requirement_ids, ("no-contact",))


if __name__ == "__main__":
    unittest.main()
