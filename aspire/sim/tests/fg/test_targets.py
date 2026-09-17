from __future__ import annotations

import unittest

from aspire.sim.cap.factual_grounding.targets import FGPatch, FGSpec, FGTarget


def target(**updates):
    value = {
        "id": "fg.contact", "stage_id": "s1", "subject": "cube", "predicate": "contact",
        "object": "platform", "operator": "equals", "expected": False, "value_type": "boolean",
        "criticality": "required", "requirement_ids": ["r.no-contact"],
        "temporal": {"role": "invariant", "kind": "continuous", "duration_steps": 20},
        "tolerance": 0.002,
    }
    value.update(updates)
    return FGTarget.from_dict(value)


class TargetPatchTests(unittest.TestCase):
    def test_stale_patch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            FGSpec().apply(FGPatch.from_dict({
                "base_revision": 1,
                "operations": [{"op": "add", "target": {
                    "id": "fg.x", "stage_id": "s", "subject": "cube",
                    "predicate": "contact", "object": "table", "operator": "equals",
                    "expected": False, "value_type": "boolean",
                    "criticality": "required", "requirement_ids": ["r"],
                }}],
            }))

    def test_empty_patch_and_reused_replacement_id_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            FGPatch.from_dict({"base_revision": 0, "operations": []})
        original = target()
        spec = FGSpec(1, {original.id: original})
        operation_type = __import__(
            "aspire.sim.cap.factual_grounding.targets",
            fromlist=["FGPatchOperation"],
        ).FGPatchOperation
        patch = FGPatch(1, (operation_type(
            "replace", original, parent_target_id=original.id, reason_code="refine"
        ),))
        with self.assertRaisesRegex(ValueError, "never-used"):
            spec.apply(patch)

    def test_required_target_cannot_be_retired(self):
        spec = FGSpec().apply(FGPatch.from_dict({"base_revision": 0, "operations": [{"op": "add", "target": target().__dict__ | {"subject": "cube", "object": "platform", "temporal": {"role": "invariant", "kind": "continuous", "duration_steps": 20}, "evidence_policy": {}}}]}))
        with self.assertRaisesRegex(ValueError, "cannot be retired"):
            spec.apply(FGPatch.from_dict({"base_revision": 1, "operations": [{"op": "retire", "target_id": "fg.contact", "parent_target_id": "fg.contact", "reason_code": "hard"}]}))

    def test_replacement_cannot_shorten_window_or_change_entity(self):
        original = target()
        spec = FGSpec(1, {original.id: original})
        for changed in (target(id="fg.contact-v2", temporal={"role": "invariant", "kind": "continuous", "duration_steps": 5}), target(id="fg.contact-v2", object="table")):
            patch = FGPatch(1, (__import__("aspire.sim.cap.factual_grounding.targets", fromlist=["FGPatchOperation"]).FGPatchOperation("replace", changed, parent_target_id="fg.contact", reason_code="refine"),))
            with self.assertRaises(ValueError):
                spec.apply(patch)


if __name__ == "__main__":
    unittest.main()
