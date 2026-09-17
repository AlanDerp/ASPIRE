"""Gate for the separately preflighted real dynamic-FG acceptance campaign."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get("ASPIRE_INTEGRATION_REAL") == "1", "set ASPIRE_INTEGRATION_REAL=1 after suite preflight")
class RealFGV2AcceptanceTests(unittest.TestCase):
    def test_real_acceptance_report_has_no_missing_cases_or_leakage(self):
        path_value = os.environ.get("ASPIRE_FG_V2_ACCEPTANCE_REPORT")
        self.assertTrue(path_value, "ASPIRE_FG_V2_ACCEPTANCE_REPORT is required")
        report = json.loads(Path(path_value).read_text())
        self.assertTrue(report.get("passed"))
        self.assertEqual(report.get("audit_leakage_incidents"), 0)
        self.assertTrue(report.get("real_simulator"))
        self.assertTrue(report.get("real_perception_services"))


if __name__ == "__main__": unittest.main()
