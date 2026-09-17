from __future__ import annotations

import unittest

from aspire.sim.scripts.fg.acceptance import REQUIRED_CASES, audit


class AcceptanceTests(unittest.TestCase):
    def test_not_run_never_counts_as_pass(self):
        self.assertFalse(audit({"cases": {}}, __import__("pathlib").Path("."))["passed"])
        complete = {"cases": {case: {"status": "passed"} for case in REQUIRED_CASES}}
        self.assertTrue(audit(complete, __import__("pathlib").Path("."))["passed"])


if __name__ == "__main__": unittest.main()
