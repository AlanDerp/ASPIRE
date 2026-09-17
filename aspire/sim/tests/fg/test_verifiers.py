from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.targets import FGTarget
from aspire.sim.cap.factual_grounding.verifier import verify_target, verdict_from_observation
from aspire.sim.cap.perception.capability_registry import default_capabilities
from aspire.sim.cap.perception.observation_broker import SensorBundle


def target(predicate="contact", expected=False, views=2):
    return FGTarget.from_dict({
        "id": f"fg.{predicate}", "stage_id": "s1", "subject": "cube", "predicate": predicate,
        "object": "platform", "operator": "equals", "expected": expected, "value_type": "boolean",
        "criticality": "required", "requirement_ids": ["r1"],
        "evidence_policy": {"min_independent_views": views},
    })


def bundle(payload):
    return SensorBundle("c1", "e1", 1, "post", 1, 1, "cal1", 1, ("cam1", "cam2"), {"fg_measurements": payload})


class VerifierTests(unittest.TestCase):
    def test_known_false_is_distinct_from_unknown(self):
        obs, probes, evidence = verify_target(target(), bundle({"contact": {"status": "known", "value": False, "confidence": .8, "independent_views": 2}}), default_capabilities())
        self.assertEqual(obs.status, "known")
        self.assertIs(obs.value, False)
        self.assertEqual(verdict_from_observation(target(), obs, probes).state, "satisfied")
        self.assertEqual(obs.evidence_refs, (evidence.ref,))

    def test_insufficient_independent_views_is_unknown(self):
        obs, _, _ = verify_target(target(), bundle({"contact": {"status": "known", "value": False, "independent_views": 1}}), default_capabilities())
        self.assertEqual(obs.status, "unknown")
        self.assertEqual(obs.uncertainty["reason_code"], "insufficient-independent-views")

    def test_missing_capability_is_unsupported(self):
        unknown = target(predicate="new_predicate")
        obs, _, _ = verify_target(unknown, bundle({}), default_capabilities())
        self.assertEqual(obs.status, "unsupported")

    def test_contact_can_be_derived_from_public_point_clouds(self):
        value = target(views=1)
        value = FGTarget.from_dict({**value.__dict__, "subject": "cube", "object": "platform", "temporal": {}, "evidence_policy": {"min_independent_views": 1}, "tolerance": 0.005})
        points = {"cube": [[0, 0, .1]], "platform": [[0, 0, 0]]}
        obs_value, _, _ = verify_target(value, SensorBundle("c", "e", 1, "p", 1, 1, "cal", 1, ("cam",), {"entity_point_clouds": points}), default_capabilities())
        self.assertEqual(obs_value.status, "known")
        self.assertIs(obs_value.value, False)


if __name__ == "__main__":
    unittest.main()
