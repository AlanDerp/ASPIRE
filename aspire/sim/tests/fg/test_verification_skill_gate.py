from __future__ import annotations

import unittest

from aspire.sim.cap.knowledge.verification_evidence import VerificationEvaluation
from aspire.sim.cap.knowledge.verification_review import review_verification_skill
from aspire.sim.cap.knowledge.verification_skill import VerificationSkill


def skill():
    return VerificationSkill("verification-skill.contact.multiview", "1.0.0", ("contact",), ("rgb",), {"fact": "public.occluded"}, ({"probe": "alternate-view"},), "multiview-contact-v1", {}, {"on_low_confidence": "unknown"}, (), (), "metrics:1", "fg-v1")


def evaluations(source="development", change="verifier_revision"):
    states = ["positive", "negative", "unknown", "positive"]
    families = ["pick", "place", "pick", "place"]
    return [VerificationEvaluation(
        id=f"e{i}", source=source, source_version="fixture-v1", method_version="m1",
        task_family=families[i], scene_id=f"s{i}", expected_status=states[i],
        old_status="known", new_status="known" if states[i] != "unknown" else "unknown",
        old_correct=False, new_correct=True, old_latency_ms=1, new_latency_ms=2,
        evidence_ref=f"ev:{i}", change_kind=change,
    ) for i in range(4)]


class VerificationSkillGateTests(unittest.TestCase):
    def test_complete_development_evidence_freezes(self):
        frozen = review_verification_skill(skill(), evaluations(), reviewer="r")
        self.assertEqual(frozen.status, "frozen")
        self.assertEqual(frozen.reviewed_by, "r")
        self.assertEqual(frozen.candidate_content_hash, skill().content_hash)
        self.assertTrue(frozen.evaluation_content_hash)

    def test_held_out_and_task_repair_are_rejected(self):
        with self.assertRaises(ValueError): review_verification_skill(skill(), evaluations("held_out"), reviewer="r")
        with self.assertRaises(ValueError): review_verification_skill(skill(), evaluations(change="task_repair"), reviewer="r")


if __name__ == "__main__": unittest.main()
