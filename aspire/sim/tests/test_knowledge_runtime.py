# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.knowledge.runtime import (
    KnowledgeRuntimeConfig,
    append_actor_knowledge,
    build_runtime_config,
    load_runtime_knowledge,
    write_runtime_telemetry,
)
from aspire.sim.cap.knowledge.serialization import content_hash, write_structured_atomic


class KnowledgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def portfolio(self, treatment: str, *, context_hash: str = "context-1") -> tuple[str, str]:
        payload = {
            "schema_version": 1,
            "treatment": treatment,
            "context_hash": context_hash,
            "checkpoint_id": "snapshot-n20",
            "manifest_id": "libero-active@1.0.0",
            "estimated_tokens": 100,
            "markdown": f"# Treatment {treatment}\nUse the selected knowledge.\n",
        }
        path = self.root / f"{treatment}.yaml"
        write_structured_atomic(path, payload)
        return str(path), content_hash(payload)

    def test_off_mode_preserves_empty_actor_context(self):
        runtime = load_runtime_knowledge(None)
        self.assertEqual(runtime.actor_markdown, "")
        self.assertFalse(runtime.telemetry["actor_visible"])
        self.assertEqual(append_actor_knowledge("base prompt", runtime), "base prompt")

    def test_production_mode_requires_matching_hash_manifest_and_treatment(self):
        path, digest = self.portfolio("B")
        runtime = load_runtime_knowledge(
            KnowledgeRuntimeConfig(
                mode="canonical",
                portfolio_path=path,
                portfolio_hash=digest,
            )
        )
        self.assertIn("Treatment B", runtime.actor_markdown)
        self.assertTrue(runtime.telemetry["actor_visible"])
        complete_prompt = append_actor_knowledge("base prompt", runtime)
        self.assertTrue(complete_prompt.startswith("base prompt"))
        self.assertIn("# Retrieved operational knowledge", complete_prompt)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            load_runtime_knowledge(
                KnowledgeRuntimeConfig(
                    mode="canonical",
                    portfolio_path=path,
                    portfolio_hash="wrong",
                )
            )
        with self.assertRaisesRegex(ValueError, "expected D"):
            load_runtime_knowledge(
                KnowledgeRuntimeConfig(
                    mode="principle-tree",
                    portfolio_path=path,
                    portfolio_hash=digest,
                )
            )

    def test_shadow_requires_fair_a_to_f_locks_and_never_injects(self):
        artifacts = {treatment: self.portfolio(treatment) for treatment in "ABCDEF"}
        runtime = load_runtime_knowledge(
            KnowledgeRuntimeConfig(
                mode="shadow",
                shadow_portfolios={key: value[0] for key, value in artifacts.items()},
                shadow_hashes={key: value[1] for key, value in artifacts.items()},
            )
        )
        self.assertEqual(runtime.actor_markdown, "")
        self.assertEqual(set(runtime.telemetry["portfolio_hashes"]), set("ABCDEF"))
        self.assertFalse(runtime.telemetry["actor_visible"])
        generated = build_runtime_config(
            "shadow", {key: value[0] for key, value in artifacts.items()}
        )
        self.assertEqual(set(generated["shadow_hashes"]), set("ABCDEF"))

        changed_path, changed_hash = self.portfolio("F", context_hash="context-2")
        paths = {key: value[0] for key, value in artifacts.items()}
        hashes = {key: value[1] for key, value in artifacts.items()}
        paths["F"], hashes["F"] = changed_path, changed_hash
        with self.assertRaisesRegex(ValueError, "one context_hash"):
            load_runtime_knowledge(
                KnowledgeRuntimeConfig(
                    mode="shadow",
                    shadow_portfolios=paths,
                    shadow_hashes=hashes,
                )
            )

    def test_shadow_cannot_silently_omit_a_control_group(self):
        with self.assertRaisesRegex(ValueError, "exact A--F"):
            KnowledgeRuntimeConfig(
                mode="shadow",
                shadow_portfolios={"A": "a.yaml"},
                shadow_hashes={"A": "hash"},
            )

    def test_trial_artifact_persists_runtime_provenance(self):
        telemetry = {
            "mode": "shadow",
            "actor_visible": False,
            "portfolio_hashes": {treatment: f"hash-{treatment}" for treatment in "ABCDEF"},
        }
        artifact = write_runtime_telemetry(self.root, telemetry)
        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(json.loads(artifact.read_text()), telemetry)


if __name__ == "__main__":
    unittest.main()
