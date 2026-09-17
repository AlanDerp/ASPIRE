from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aspire.sim.cap.knowledge.verification_skill import VerificationSkill, save_verification_skill
from aspire.sim.cap.perception.capability_registry import default_capabilities, install_frozen_verification_skills


class VerificationSkillRuntimeTests(unittest.TestCase):
    def test_only_exact_frozen_checkpoint_is_installed(self):
        skill = VerificationSkill("verification-skill.contact.alt", "1.0.0", ("contact",), ("rgb",), {"fact": "public.occluded"}, ({"probe": "alternate-view"},), "multiview-contact-v1", {}, {"low": "unknown"}, (), ("e1",), "metrics:1", "cp1", "frozen", "reviewer", "candidate-hash", "evaluation-hash")
        with tempfile.TemporaryDirectory() as directory:
            path = save_verification_skill(Path(directory), skill)
            registry = default_capabilities()
            install_frozen_verification_skills(registry, [path], checkpoint_id="cp1")
            self.assertEqual(registry.get("verification-skill.contact.alt@1.0.0").predicate, "contact")
            class Target:
                predicate = "contact"
                evidence_policy = type("Policy", (), {"preferred_methods": ()})()
            self.assertEqual(registry.resolve(Target()).method_id, "verification-skill.contact.alt@1.0.0")
            with self.assertRaises(ValueError):
                install_frozen_verification_skills(default_capabilities(), [path], checkpoint_id="cp2")
            candidate_path = save_verification_skill(Path(directory), replace(skill, id="verification-skill.contact.candidate", status="candidate"))
            with self.assertRaises(ValueError):
                install_frozen_verification_skills(default_capabilities(), [candidate_path], checkpoint_id="cp1")


if __name__ == "__main__": unittest.main()
