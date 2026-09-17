from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.comparator import compare
from aspire.sim.cap.factual_grounding.observations import FGObservation


def item(channel, value, **changes):
    payload = dict(target_id="fg.x", spec_revision=1, event_id="e1", phase="post", source_channel=channel, method_id="m", value=value, status="known", confidence=1.0, uncertainty={}, evidence_refs=("ev",), sensor_refs=("s",), observed_at_step=1, valid_until_step=None, semantic_hash="sem")
    payload.update(changes)
    return FGObservation(**payload)


class ComparatorTests(unittest.TestCase):
    def test_opposite_values_are_preserved_as_mismatch(self):
        observed, audit = item("observed", False), item("audit", True)
        result = compare(observed, audit)
        self.assertEqual(result.alignment, "mismatch")
        self.assertIs(observed.value, False)

    def test_misaligned_event_is_stale(self):
        self.assertEqual(compare(item("observed", False), item("audit", False, event_id="e2")).alignment, "stale")


if __name__ == "__main__":
    unittest.main()
