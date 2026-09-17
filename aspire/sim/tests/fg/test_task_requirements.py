from __future__ import annotations

import unittest

from aspire.sim.cap.agent_protocol.spec_critic import review_spec
from aspire.sim.cap.agent_protocol.task_requirements import extract_task_requirements
from aspire.sim.cap.factual_grounding.targets import FGSpec, FGTarget


class TaskRequirementTests(unittest.TestCase):
    def test_compound_task_gets_independent_dynamic_requirements(self):
        requirements = extract_task_requirements("Hold the cube above the platform without touching it")
        self.assertEqual({item.predicate_hint for item in requirements}, {"held_by", "above", "contact"})

    def test_easy_target_cannot_claim_different_requirement(self):
        requirements = extract_task_requirements("Hold the cube above the platform without touching it")
        above_requirement = next(item for item in requirements if item.predicate_hint == "above")
        target = FGTarget.from_dict({"id": "fg.easy", "stage_id": "s", "subject": "cube", "predicate": "held_by", "object": "gripper", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": [above_requirement.id]})
        report = review_spec((above_requirement.id,), FGSpec(1, {target.id: target}), requirements)
        self.assertFalse(report.accepted)
        self.assertIn("does not cover above", report.reasons[0])

    def test_negative_contact_requirement_cannot_be_inverted(self):
        requirements = extract_task_requirements(
            "Hold the cube above the platform without touching it"
        )
        contact_requirement = next(
            item for item in requirements if item.predicate_hint == "contact"
        )
        self.assertFalse(contact_requirement.expected_hint)
        target = FGTarget.from_dict({
            "id": "fg.bad-contact", "stage_id": "s", "subject": "cube",
            "predicate": "contact", "object": "platform", "operator": "equals",
            "expected": True, "value_type": "boolean", "criticality": "required",
            "requirement_ids": [contact_requirement.id],
        })
        report = review_spec(
            (contact_requirement.id,), FGSpec(1, {target.id: target}), requirements
        )
        self.assertFalse(report.accepted)
        self.assertTrue(any("contradicts" in reason for reason in report.reasons))

    def test_pick_and_place_keeps_terminal_placement_requirement(self):
        requirements = extract_task_requirements(
            "Pick up the black bowl and place it on the plate"
        )
        hints = {item.predicate_hint for item in requirements}
        self.assertIn("held_by", hints)
        self.assertIn("on", hints)


if __name__ == "__main__": unittest.main()
