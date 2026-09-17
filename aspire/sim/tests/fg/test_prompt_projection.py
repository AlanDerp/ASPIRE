from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.observations import FGSnapshot, FGVerdict
from aspire.sim.cap.factual_grounding.prompt_projection import project_public
from aspire.sim.cap.factual_grounding.targets import FGSpec, FGTarget


class ProjectionTests(unittest.TestCase):
    def test_required_unknown_is_never_truncated_away(self):
        target = FGTarget.from_dict({"id": "fg.x", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": False, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]})
        spec = FGSpec(1, {target.id: target})
        text = project_public(spec, FGSnapshot(1, "e", public_verdicts=(FGVerdict("fg.x", "unknown", None, (), (), reason_code="occluded"),)))
        self.assertIn("fg.x: UNKNOWN", text)
        self.assertIn("not admissible", text)

    def test_projection_includes_public_evidence_confidence_and_probes(self):
        target = FGTarget.from_dict({"id": "fg.x", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": False, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]})
        spec = FGSpec(1, {target.id: target})
        verdict = FGVerdict(
            "fg.x", "unknown", 0.625, ("fgobs:123",), ("alternate-view",),
            reason_code="occluded",
        )
        text = project_public(spec, FGSnapshot(1, "e", public_verdicts=(verdict,)))
        self.assertIn("confidence=0.625", text)
        self.assertIn("evidence=fgobs:123", text)
        self.assertIn("probes=alternate-view", text)

    def test_projection_places_vdm_description_beside_fg_verdicts(self):
        target = FGTarget.from_dict({"id": "fg.x", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": True, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]})
        spec = FGSpec(1, {target.id: target})
        snapshot = FGSnapshot(
            1, "e", public_verdicts=(
                FGVerdict("fg.x", "satisfied", .9, ("fgobs:1",), ()),
            ), vdm_description="The cube came to rest on the table.",
        )
        text = project_public(spec, snapshot)
        self.assertIn("[VDM EXECUTION DESCRIPTION]", text)
        self.assertIn("The cube came to rest", text)
        self.assertIn("[AGENT-DEFINED FG VERIFICATION]", text)
        self.assertIn("fg.x: SATISFIED", text)


if __name__ == "__main__": unittest.main()
