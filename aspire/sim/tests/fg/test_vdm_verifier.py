from __future__ import annotations

import json
import unittest

import numpy as np

from aspire.sim.cap.factual_grounding.targets import FGTarget
from aspire.sim.cap.factual_grounding.vdm_verifier import (
    VDMFGVerifier,
    build_vdm_fg_prompt,
    parse_vdm_fg_response,
)
from aspire.sim.cap.perception.observation_broker import SensorBundle


def target(*, views: int = 1) -> FGTarget:
    return FGTarget.from_dict({
        "id": "fg.cube-held",
        "stage_id": "grasp",
        "subject": "cube",
        "predicate": "held_by",
        "object": "gripper",
        "operator": "equals",
        "expected": True,
        "value_type": "boolean",
        "criticality": "required",
        "requirement_ids": ["req.pick"],
        "temporal": {"role": "milestone"},
        "evidence_policy": {"min_independent_views": views},
    })


def bundle() -> SensorBundle:
    return SensorBundle(
        "capture-1", "event-1", 1, "post-action", 10, 20,
        "cal-1", 1, ("main", "wrist"), {},
    )


def response(*, verdict: str = "satisfied", include_wrist: bool = False) -> str:
    evidence = [{
        "view": "main", "time": "during",
        "observation": "The cube moved rigidly with the closed gripper.",
    }]
    if include_wrist:
        evidence.append({
            "view": "wrist", "time": "during",
            "observation": "The cube remained between the fingertips.",
        })
    return json.dumps({
        "protocol_version": "vdm-fg-verifier-v1",
        "event_id": "event-1",
        "scene_change_summary": "The cube was lifted from the table.",
        "target_results": [{
            "target_id": "fg.cube-held",
            "subject_identified": True,
            "object_identified": True,
            "observed_value": True,
            "status": "known",
            "provisional_verdict": verdict,
            "confidence": 0.92,
            "evidence": evidence,
            "uncertainty_reasons": [],
            "recommended_probe": None,
        }],
        "overall_visual_assessment": "all_required_satisfied",
    })


class FakeEnv:
    def __init__(self) -> None:
        self.image = np.zeros((8, 8, 3), dtype=np.uint8)

    def render(self):
        self.image = self.image.copy()
        self.image[0, 0, 0] += 1
        return self.image


class VDMVerifierTests(unittest.TestCase):
    def test_prompt_preserves_actor_authored_target_and_attaches_media(self):
        prompt = build_vdm_fg_prompt(
            task_description="Pick up the cube.", targets=(target(),),
            bundle=bundle(), allowed_probes=("alternate-view",),
            media_content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}],
        )
        text = prompt[1]["content"][0]["text"]
        self.assertIn("fg.cube-held", text)
        self.assertIn("Do not copy expected", text)
        self.assertEqual(prompt[1]["content"][1]["type"], "image_url")

    def test_valid_response_becomes_provenance_bearing_evidence(self):
        verifier = VDMFGVerifier(
            FakeEnv(), lambda _: response(), "Pick up the cube.",
            allowed_probes=("alternate-view",),
        )
        report = verifier.evaluate((target(),), bundle())
        evidence = verifier.evidence_records(report, bundle())["fg.cube-held"]
        self.assertEqual(evidence.payload["status"], "known")
        self.assertIs(evidence.payload["value"], True)
        self.assertIn("cube was lifted", report.scene_change_summary)

    def test_provisional_verdict_mismatch_fails_closed(self):
        report = parse_vdm_fg_response(
            response(verdict="violated"), event_id="event-1", targets=(target(),),
            allowed_probes=("alternate-view",),
        )
        result = report.target_results[0]
        self.assertEqual(result.status, "unknown")
        self.assertIn("vdm-provisional-verdict-mismatch", result.uncertainty_reasons)

    def test_independent_view_policy_fails_closed(self):
        report = parse_vdm_fg_response(
            response(), event_id="event-1", targets=(target(views=2),),
            allowed_probes=("alternate-view",),
        )
        self.assertEqual(report.target_results[0].status, "unknown")
        self.assertIn(
            "insufficient-independent-views",
            report.target_results[0].uncertainty_reasons,
        )

    def test_missing_or_extra_target_is_rejected(self):
        value = json.loads(response())
        value["target_results"] = []
        with self.assertRaisesRegex(ValueError, "exactly match"):
            parse_vdm_fg_response(
                json.dumps(value), event_id="event-1", targets=(target(),),
                allowed_probes=("alternate-view",),
            )


if __name__ == "__main__":
    unittest.main()
