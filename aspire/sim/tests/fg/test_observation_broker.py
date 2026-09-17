from __future__ import annotations

import unittest

from aspire.sim.cap.perception.observation_broker import ObservationBroker


class Source:
    def public_observation(self):
        return {"calibration_version": "c1", "sensor_refs": ["cam-main"], "rgb": "fixture"}


class BrokerTests(unittest.TestCase):
    def test_bundle_is_event_aligned_and_source_is_not_mutated(self):
        source = Source()
        before = source.public_observation()
        bundle = ObservationBroker(source).freeze(event_id="e1", spec_revision=2, phase="post", tick_start=3, tick_end=4)
        self.assertEqual(bundle.event_id, "e1")
        self.assertEqual(bundle.sensor_refs, ("cam-main",))
        self.assertEqual(source.public_observation(), before)

    def test_reversed_tick_range_fails(self):
        with self.assertRaises(ValueError):
            ObservationBroker(Source()).freeze(event_id="e", spec_revision=1, phase="p", tick_start=2, tick_end=1)


if __name__ == "__main__":
    unittest.main()
