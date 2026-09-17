from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.targets import FGTarget
from aspire.sim.cap.perception.capability_registry import default_capabilities
from aspire.sim.cap.perception.verification_plan import build_verification_plan


class CapabilityResolutionTests(unittest.TestCase):
    def test_supported_and_missing_predicates_are_explicit(self):
        target = FGTarget.from_dict({"id": "fg.x", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": False, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]})
        plan = build_verification_plan([target], default_capabilities())
        self.assertEqual(plan[0].status, "ready")


if __name__ == "__main__": unittest.main()
