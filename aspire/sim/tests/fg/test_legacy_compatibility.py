from __future__ import annotations

import unittest

from aspire.sim.cap.agent_protocol.legacy import parse_legacy_decision
from aspire.sim.cap.factual_grounding.config import RuntimeFeatureSet


class LegacyCompatibilityTests(unittest.TestCase):
    def test_default_does_not_enable_dynamic_protocol(self):
        cfg = RuntimeFeatureSet.from_dict(None).factual_grounding
        self.assertFalse(cfg.enabled)
        self.assertEqual(parse_legacy_decision("FINISH"), ("finish", None))


if __name__ == "__main__": unittest.main()
