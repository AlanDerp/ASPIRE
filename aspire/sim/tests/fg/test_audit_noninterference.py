from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.comparator import compare
from aspire.sim.cap.factual_grounding.observations import FGObservation, FGSnapshot, FGVerdict


def record(channel, value):
    return FGObservation("fg.x", 1, "e", "post", channel, "m", value, "known", 1.0, {}, ("ev",), (), 1, None, "sem")


class AuditNoninterferenceTests(unittest.TestCase):
    def test_public_hash_and_verdict_do_not_depend_on_audit(self):
        observed = record("observed", False)
        verdict = FGVerdict("fg.x", "satisfied", 1.0, (observed.ref,), ())
        left = FGSnapshot(1, "e", (observed,), (record("audit", True),), (compare(observed, record("audit", True)),), (verdict,))
        right = FGSnapshot(1, "e", (observed,), (record("audit", False),), (compare(observed, record("audit", False)),), (verdict,))
        self.assertEqual(left.public_hash, right.public_hash)
        self.assertNotEqual(left.private_hash, right.private_hash)


if __name__ == "__main__": unittest.main()
