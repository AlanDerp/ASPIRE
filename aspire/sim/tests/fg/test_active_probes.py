from __future__ import annotations

import unittest

from aspire.sim.cap.perception.probe_planner import ProbeOption, select_probe


class ProbeTests(unittest.TestCase):
    def test_probe_obeys_budget_and_motion_safety(self):
        unsafe = ProbeOption("unsafe", 10, 1, True, False)
        safe = ProbeOption("alternate", 2, 1)
        self.assertEqual(select_probe((unsafe, safe), remaining_budget=1).id, "alternate")
        self.assertIsNone(select_probe((safe,), remaining_budget=.5))


if __name__ == "__main__": unittest.main()
