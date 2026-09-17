from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from aspire.sim.cap.factual_grounding.observations import FGObservation, FGSnapshot, FGVerdict
from aspire.sim.cap.knowledge.serialization import append_jsonl
from aspire.sim.cap.perception.evidence import EvidenceRecord
from aspire.sim.scripts.fg.check_trace_integrity import check


class TraceIntegrityTests(unittest.TestCase):
    def test_dangling_verdict_reference_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = EvidenceRecord(
                "fg-measurement", "e", "capture-1", "m", "1", ("cam",),
                {"status": "known", "value": True},
            )
            observation = FGObservation("fg.x", 1, "e", "post", "observed", "m", True, "known", 1.0, {}, (evidence.ref,), ("cam",), 1, None, "sem")
            verdict = FGVerdict("fg.x", "satisfied", 1.0, (observation.ref,), ())
            snapshot = FGSnapshot(1, "e", observed=(observation,), public_verdicts=(verdict,))
            append_jsonl(root / "evidence/derived/measurements.jsonl", evidence)
            append_jsonl(root / "fg/observations.observed.jsonl", observation)
            append_jsonl(root / "fg/verdicts.jsonl", verdict)
            append_jsonl(root / "fg/snapshots.jsonl", {
                "public_hash": snapshot.public_hash,
                "event_id": snapshot.event_id,
                "spec_revision": snapshot.spec_revision,
                "observed": [asdict(observation)],
                "public_verdicts": [asdict(verdict)],
            })
            self.assertTrue(check(root)["passed"])
            (root / "fg/verdicts.jsonl").write_text(json.dumps({"based_on": ["missing"]}) + "\n")
            self.assertFalse(check(root)["passed"])

    def test_missing_evidence_and_tampered_snapshot_hash_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = EvidenceRecord("fg-measurement", "e", "c", "m", "1", ("cam",), {"status": "known", "value": True})
            observation = FGObservation("fg.x", 1, "e", "post", "observed", "m", True, "known", 1.0, {}, (evidence.ref,), ("cam",), 1, None, "sem")
            verdict = FGVerdict("fg.x", "satisfied", 1.0, (observation.ref,), ())
            append_jsonl(root / "fg/observations.observed.jsonl", observation)
            append_jsonl(root / "fg/verdicts.jsonl", verdict)
            append_jsonl(root / "fg/snapshots.jsonl", {
                "public_hash": "tampered", "event_id": "e", "spec_revision": 1,
                "observed": [asdict(observation)], "public_verdicts": [asdict(verdict)],
            })
            result = check(root)
            self.assertFalse(result["passed"])
            self.assertTrue(any("dangling evidence" in item for item in result["errors"]))
            self.assertTrue(any("invalid public hash" in item for item in result["errors"]))


if __name__ == "__main__": unittest.main()
