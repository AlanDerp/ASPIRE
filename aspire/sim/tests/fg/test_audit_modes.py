from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.factual_grounding.config import FactualGroundingConfig
from aspire.sim.cap.factual_grounding.coordinator import FGCoordinator
from aspire.sim.cap.factual_grounding.observations import FGObservation
from aspire.sim.cap.factual_grounding.persistence import FGStore
from aspire.sim.cap.factual_grounding.registry import default_registry
from aspire.sim.cap.factual_grounding.targets import FGSpec, FGTarget
from aspire.sim.cap.factual_grounding.verifier import semantic_hash
from aspire.sim.cap.perception.capability_registry import default_capabilities
from aspire.sim.cap.perception.observation_broker import ObservationBroker


class Source:
    def public_observation(self):
        return {"sensor_refs": ["cam"], "fg_measurements": {"contact": {"status": "known", "value": False}}}


class Audit:
    def __init__(self, value): self.value = value
    def observe(self, target, bundle):
        return FGObservation(target.id, bundle.spec_revision, bundle.event_id, bundle.phase, "audit", "fake-audit", self.value, "known", 1.0, {}, ("private",), (), bundle.tick_end, None, semantic_hash(target))


def target():
    return FGTarget.from_dict({"id": "fg.contact", "stage_id": "s", "subject": "cube", "predicate": "contact", "object": "table", "operator": "equals", "expected": False, "value_type": "boolean", "criticality": "required", "requirement_ids": ["r"]})


class AuditModeTests(unittest.TestCase):
    def test_audit_is_private_and_does_not_change_public_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = FactualGroundingConfig(enabled=True, protocol="dynamic-v2", runtime_mode="held_out_audit", audit_adapter="fake", private_artifact_root=str(root / "private"), isolated_worker=True)
            store = FGStore(root / "public", root / "private")
            coordinator = FGCoordinator(cfg, default_registry(), default_capabilities(), ObservationBroker(Source()), store, Audit(True))
            value = target()
            coordinator.spec = FGSpec(1, {value.id: value})
            snapshot = coordinator.verify((value.id,), phase="post", tick_start=1, tick_end=1)
            self.assertEqual(snapshot.comparisons[0].alignment, "mismatch")
            self.assertEqual(snapshot.public_verdicts[0].state, "satisfied")
            self.assertFalse((root / "public/fg/observations.audit.jsonl").exists())
            self.assertTrue((root / "private/fg/observations.audit.jsonl").is_file())


if __name__ == "__main__": unittest.main()
