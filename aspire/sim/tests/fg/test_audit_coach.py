from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.audit_coach import propose_probe
from aspire.sim.cap.factual_grounding.config import FactualGroundingConfig
from aspire.sim.cap.factual_grounding.observations import FGComparison
from aspire.sim.cap.perception.probe_planner import ProbeOption


class AuditCoachTests(unittest.TestCase):
    def test_coach_is_development_only_and_marks_influence(self):
        comparison = FGComparison("fg.x", "e", "o", "a", "mismatch", "value", True, None)
        option = (ProbeOption("alternate", 1, 1),)
        with self.assertRaises(PermissionError):
            propose_probe(FactualGroundingConfig(enabled=True, protocol="dynamic-v2"), comparison, option, remaining_budget=1)
        cfg = FactualGroundingConfig(enabled=True, protocol="dynamic-v2", runtime_mode="development_compare", audit_adapter="x", private_artifact_root="/tmp/private", isolated_worker=True)
        self.assertTrue(propose_probe(cfg, comparison, option, remaining_budget=1)["audit_influenced"])


if __name__ == "__main__": unittest.main()
