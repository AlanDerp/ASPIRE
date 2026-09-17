from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.observations import FGObservation
from aspire.sim.cap.factual_grounding.targets import FGTarget
from aspire.sim.cap.factual_grounding.temporal import temporal_verdict


def target():
    return FGTarget.from_dict({
        "id": "fg.no-contact", "stage_id": "s", "subject": "cube", "predicate": "contact",
        "object": "platform", "operator": "equals", "expected": False, "value_type": "boolean",
        "criticality": "required", "requirement_ids": ["r"],
        "temporal": {"role": "invariant", "kind": "continuous", "duration_steps": 3},
    })


def obs(step, value=False):
    return FGObservation("fg.no-contact", 1, f"e{step}", "during", "observed", "m", value, "known", .8, {}, (f"ev{step}",), ("cam",), step, None, "sem")


class TemporalTests(unittest.TestCase):
    def test_single_frame_does_not_satisfy_continuous_target(self):
        self.assertEqual(temporal_verdict(target(), [obs(1)]).state, "unknown")

    def test_complete_window_satisfies_and_mid_violation_blocks(self):
        self.assertEqual(temporal_verdict(target(), [obs(1), obs(2), obs(3)]).state, "satisfied")
        self.assertEqual(temporal_verdict(target(), [obs(1), obs(2, True), obs(3)]).state, "violated")

    def test_sampling_gap_is_unknown(self):
        self.assertEqual(temporal_verdict(target(), [obs(1), obs(3), obs(4)]).reason_code, "sampling-gap")


if __name__ == "__main__":
    unittest.main()
