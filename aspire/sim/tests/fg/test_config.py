from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.config import RuntimeFeatureSet


class FGConfigTests(unittest.TestCase):
    def test_defaults_leave_feature_disabled_and_shadowed(self):
        cfg = RuntimeFeatureSet.from_dict(None).factual_grounding
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.protocol, "legacy-code-v1")

    def test_observed_dynamic_config(self):
        cfg = RuntimeFeatureSet.from_dict({"factual_grounding": {
            "enabled": True, "protocol": "dynamic-v2", "feedback": "visible"
        }}).factual_grounding
        self.assertEqual(cfg.runtime_mode, "observed_only")

    def test_private_modes_require_adapter_and_private_root(self):
        with self.assertRaisesRegex(ValueError, "audit_adapter"):
            RuntimeFeatureSet.from_dict({"factual_grounding": {
                "enabled": True, "protocol": "dynamic-v2",
                "runtime_mode": "held_out_audit",
            }})

    def test_unknown_fields_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            RuntimeFeatureSet.from_dict({"factual_grounding": {"enabled": False, "typo": 1}})

    def test_disabled_feature_cannot_be_visible(self):
        with self.assertRaisesRegex(ValueError, "cannot be visible"):
            RuntimeFeatureSet.from_dict({"factual_grounding": {"feedback": "visible"}})


if __name__ == "__main__":
    unittest.main()
