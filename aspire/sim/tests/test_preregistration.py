# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.knowledge.claim_audit import audit_claim
from aspire.sim.cap.knowledge.experiment import Observation
from aspire.sim.cap.knowledge.preregistration import freeze_preregistration


class PreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def valid_inputs(self) -> dict[str, Path]:
        draft = self.write(
            "draft.yaml",
            {
                "status": "preregistered-engineering-draft",
                "hypotheses": {
                    f"H{index}": {"claim": "claim", "refutation": "refutation"}
                    for index in range(1, 7)
                },
                "treatments": {treatment: treatment for treatment in "ABCDEF"},
                "library_scales": [1],
                "seeds": [11],
                "token_budget": 2400,
            },
        )
        prompt = self.root / "prompt.txt"
        prompt.write_text("prompt")
        split = self.write(
            "split.yaml",
            {
                "development": ["dev"],
                "held-out": ["held-out"],
                "adversarial": ["adversarial"],
                "maintenance": ["maintenance"],
            },
        )
        checkpoints = self.write(
            "checkpoints.yaml",
            {
                kind: {
                    "1": {
                        "checkpoint_id": f"{kind}-1",
                        "corpus_hash": f"{kind}-hash",
                        "n_code": 1,
                        "evidence_eligible": kind == "organic",
                    }
                }
                for kind in ("organic", "synthetic")
            },
        )
        execution = self.write(
            "execution.yaml",
            {
                "model_id": "model-v1",
                "temperature": 0,
                "simulator": "sim-v1",
                "execution_api": "api-v1",
                "perception_backend": "perception-v1",
                "task_seeds": [11],
                "token_budget": 2400,
                "max_runs": 1,
                "max_retries": 0,
                "retrieval_lexical_normalization": "v1",
                "held_out_writeback": False,
            },
        )
        return {
            "draft": draft,
            "prompt": prompt,
            "split": split,
            "checkpoints": checkpoints,
            "execution": execution,
        }

    def freeze(self, paths: dict[str, Path]) -> dict:
        return freeze_preregistration(
            paths["draft"],
            model_id="model-v1",
            prompt_path=paths["prompt"],
            task_split_path=paths["split"],
            checkpoint_map_path=paths["checkpoints"],
            execution_config_path=paths["execution"],
            frozen_at="2026-08-21T00:00:00+00:00",
        )

    def test_rejects_overlapping_task_partitions(self) -> None:
        paths = self.valid_inputs()
        split = json.loads(paths["split"].read_text())
        split["held-out"] = ["dev"]
        paths["split"].write_text(json.dumps(split))

        with self.assertRaisesRegex(ValueError, "partitions overlap"):
            self.freeze(paths)

    def test_rejects_synthetic_evidence_as_organic(self) -> None:
        paths = self.valid_inputs()
        checkpoints = json.loads(paths["checkpoints"].read_text())
        checkpoints["synthetic"]["1"]["evidence_eligible"] = True
        paths["checkpoints"].write_text(json.dumps(checkpoints))

        with self.assertRaisesRegex(ValueError, "evidence_eligible=false"):
            self.freeze(paths)

    def test_claim_audit_applies_prespecified_rules(self) -> None:
        paths = self.valid_inputs()
        draft = json.loads(paths["draft"].read_text())
        draft["library_scales"] = [1, 4]
        paths["draft"].write_text(json.dumps(draft))
        checkpoints = {
            kind: {
                str(scale): {
                    "checkpoint_id": f"{kind}-{scale}",
                    "corpus_hash": f"{kind}-hash-{scale}",
                    "n_code": scale * 10,
                    "evidence_eligible": kind == "organic",
                }
                for scale in (1, 4)
            }
            for kind in ("organic", "synthetic")
        }
        paths["checkpoints"].write_text(json.dumps(checkpoints))
        frozen = self.freeze(paths)

        observations = []
        tasks = (("task-a", "family-a"), ("task-b", "family-b"))
        for corpus_kind in ("organic", "synthetic"):
            splits = (
                ("held-out", "adversarial", "maintenance")
                if corpus_kind == "organic"
                else ("held-out",)
            )
            for scale in (1, 4):
                for task_id, family in tasks:
                    for split in splits:
                        for treatment in "ABCDEF":
                            context_tokens = {
                                "A": 130 * scale,
                                "B": 100 * scale,
                                "C": 80 * scale,
                                "D": 20 + scale,
                                "E": 20 + scale,
                                "F": 20 + scale,
                            }[treatment]
                            observations.append(
                                Observation(
                                    treatment=treatment,
                                    scale=scale,
                                    seed=11,
                                    task_id=task_id,
                                    task_family=family,
                                    corpus_kind=corpus_kind,
                                    split=split,
                                    success=0.8,
                                    context_tokens=context_tokens,
                                    compile_latency_ms=10,
                                    irrelevant_exposure=(
                                        0.1 if treatment in "DEF" else 0.4
                                    ),
                                    redundancy_exposure=(
                                        0.1 if treatment in "DEF" else 0.4
                                    ),
                                    relevant_principle_recall=(
                                        0.95 if treatment in "DEF" else 0.0
                                    ),
                                    relevant_skill_recall=0.9,
                                    requirement_coverage=(
                                        0.9 if treatment == "E" else 0.7
                                    ),
                                    fallback=0.01,
                                    negative_transfer=(
                                        0.2 if treatment == "F" else 0.05
                                    ),
                                    unsupported_principle_escape=0.0,
                                    exception_hard_violation_escape=0.0,
                                    stale_conflict_escape=(
                                        0.05 if treatment == "E" else 0.1
                                    ),
                                    construction_cost=(
                                        3 if treatment == "E" else 5
                                    ),
                                    maintenance_cost=(
                                        4 if treatment == "E" else 10
                                    ),
                                    blast_radius=(3 if treatment == "E" else 10),
                                    n_code=scale * 10,
                                    token_budget=2400,
                                    checkpoint_id=f"{corpus_kind}-{scale}",
                                    manifest_id=f"manifest-{corpus_kind}-{scale}@1.0.0",
                                    corpus_hash=f"{corpus_kind}-hash-{scale}",
                                    context_hash=f"{task_id}-{split}-{scale}",
                                    portfolio_hash=(
                                        f"{corpus_kind}-{task_id}-{split}-{scale}-{treatment}"
                                    ),
                                    model_id="model-v1",
                                    prompt_hash="prompt-v1",
                                    cross_capability=True,
                                )
                            )

        result = audit_claim(observations, frozen)

        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["supported_scope"], "principle-forest-graph")
        self.assertTrue(all(rule["passed"] for rule in result["rules"]))
        self.assertEqual(set(result["repeatability"]["advantage_scales"]), {1, 4})


if __name__ == "__main__":
    unittest.main()
