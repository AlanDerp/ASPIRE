# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aspire.sim.cap.knowledge.serialization import content_hash, sha256_file


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class KnowledgeCliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.knowledge = self.workspace / "knowledge"
        self.environment = {**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)}

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "aspire.sim.cap.knowledge",
                "--root",
                str(self.knowledge),
                *arguments,
            ],
            cwd=REPOSITORY_ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def write_json(self, name: str, value: dict) -> Path:
        path = self.workspace / name
        path.write_text(json.dumps(value, indent=2) + "\n")
        return path

    def test_freeze_preregistration_locks_all_experimental_inputs(self):
        draft = self.write_json(
            "draft.yaml",
            {
                "status": "preregistered-engineering-draft",
                "hypotheses": {
                    f"H{index}": {
                        "claim": f"claim {index}",
                        "refutation": f"refutation {index}",
                    }
                    for index in range(1, 7)
                },
                "treatments": {treatment: treatment for treatment in "ABCDEF"},
                "evaluation_partitions": {
                    "organic": ["held-out", "adversarial", "maintenance"],
                    "synthetic": ["held-out", "adversarial", "maintenance"],
                },
                "library_scales": [1, 4],
                "seeds": [11, 29],
                "token_budget": 2400,
                "decision_rules": {
                    "task_noninferiority_margin": 0.03,
                    "principle_recall_at_8_min": 0.9,
                    "operational_skill_recall_margin": 0.03,
                    "unsupported_principle_escape_max": 0,
                    "exception_hard_violation_escape_max": 0,
                    "shadow_fallback_rate_max": 0.1,
                    "compile_latency_p95_ms_max": 300,
                    "claim_min_independent_tasks": 2,
                    "claim_min_task_families": 2,
                    "claim_min_advantage_scales": 2,
                    "claim_requires_slope_comparison": True,
                },
            },
        )
        prompt = self.workspace / "prompt.txt"
        prompt.write_text("fixed task prompt\n")
        task_split = self.write_json(
            "task-split.yaml",
            {
                "development": ["dev-1"],
                "held-out": ["test-1"],
                "adversarial": ["adversarial-1"],
                "maintenance": ["maintenance-1"],
            },
        )
        task_ids = ("dev-1", "test-1", "adversarial-1", "maintenance-1")
        catalog_tasks = {}
        for task_id in task_ids:
            context = self.write_json(
                f"context-{task_id}.yaml",
                {
                    "task_id": task_id,
                    "suite": "libero",
                    "task_language": f"perform {task_id}",
                    "task_family": task_id,
                    "token_budget": 2400,
                },
            )
            env_config = self.write_json(
                f"env-{task_id}.yaml", {"env": {"cfg": {"prompt": task_id}}}
            )
            catalog_tasks[task_id] = {
                "context_path": str(context.resolve()),
                "context_hash": content_hash(json.loads(context.read_text())),
                "env_config_path": str(env_config.resolve()),
                "env_config_hash": content_hash(json.loads(env_config.read_text())),
            }
        job_catalog = self.write_json("job-catalog.yaml", {"tasks": catalog_tasks})
        checkpoint_map = self.write_json(
            "checkpoint-map.yaml",
            {
                corpus_kind: {
                    str(scale): {
                        "checkpoint_id": f"{corpus_kind}-n{scale}",
                        "corpus_hash": f"{corpus_kind}-hash-{scale}",
                        "n_code": scale,
                        "evidence_eligible": corpus_kind == "organic",
                    }
                    for scale in (1, 4)
                }
                for corpus_kind in ("organic", "synthetic")
            },
        )
        execution_config = self.write_json(
            "execution-config.yaml",
            {
                "model_id": "model-pinned-v1",
                "temperature": 0,
                "simulator": "libero-pro-long-v1",
                "execution_api": "aspire-cap-v1",
                "perception_backend": "ground-truth-v1",
                "task_seeds": [11, 29],
                "token_budget": 2400,
                "max_runs": 1,
                "max_retries": 2,
                "retrieval_lexical_normalization": "v1",
                "held_out_writeback": False,
                "runner_command": [
                    sys.executable,
                    "--config={config_path}",
                    "--model={model_id}",
                    "--prompt={prompt_path}",
                    "--seed={seed}",
                    "--observation={observation_path}",
                ],
                "runner_executable_hash": sha256_file(Path(sys.executable)),
                "runner_timeout_seconds": 3600,
            },
        )
        output = self.workspace / "frozen.yaml"

        result = self.run_cli(
            "experiment",
            "freeze-preregistration",
            "--draft",
            str(draft),
            "--model-id",
            "model-pinned-v1",
            "--prompt",
            str(prompt),
            "--task-split",
            str(task_split),
            "--checkpoint-map",
            str(checkpoint_map),
            "--execution-config",
            str(execution_config),
            "--job-catalog",
            str(job_catalog),
            "--frozen-at",
            "2026-08-21T00:00:00+00:00",
            "--output",
            str(output),
        )

        self.assertEqual(result["status"], "frozen")
        self.assertTrue(output.is_file())
        completion = self.run_cli(
            "completion", "audit", "--preregistration", str(output)
        )
        self.assertNotIn("preregistration-frozen", completion["failed_check_ids"])
        self.assertNotIn("fixed-experimental-artifacts", completion["failed_check_ids"])

        prompt.write_text("prompt changed after freeze\n")
        tampered = self.run_cli(
            "completion", "audit", "--preregistration", str(output)
        )
        self.assertIn("preregistration-frozen", tampered["failed_check_ids"])

    def test_full_skill_code_to_treatment_pipeline(self):
        self.run_cli("init")
        policy = self.write_json(
            "policy.yaml",
            {
                "checkpoint_every_instances": 6,
                "min_distinct_tasks": 6,
                "min_cluster_instances": 2,
                "min_cluster_tasks": 2,
                "min_successful_instances": 2,
                "max_single_task_share": 0.5,
                "min_canonical_skills_for_principle": 3,
                "min_task_families_for_principle": 2,
            },
        )
        families = ("pick-place", "long-horizon")
        cluster_names = ("alpha", "beta", "gamma")
        for cluster_index, cluster_name in enumerate(cluster_names):
            for member in range(2):
                task_index = cluster_index * 2 + member + 1
                source = self.workspace / f"task-{task_index}.py"
                source.write_text(f"get_observation()\nmove_{cluster_name}()\n")
                self.run_cli(
                    "instance",
                    "ingest",
                    "--id",
                    f"skill-code.libero.task-{task_index}.transport",
                    "--vertical",
                    "transport",
                    "--task",
                    f"task-{task_index}",
                    "--task-family",
                    families[member],
                    "--code",
                    str(source),
                    "--goal",
                    f"transport {cluster_name} safely",
                    "--trigger",
                    "object is grasped",
                    "--effect",
                    "safe transport completes",
                    "--successful-seeds",
                    str(51 + task_index),
                )

        self.run_cli(
            "checkpoint",
            "freeze",
            "--id",
            "snapshot-n6",
            "--policy",
            str(policy),
        )
        audit = self.run_cli(
            "repetition",
            "audit",
            "--checkpoint",
            "snapshot-n6",
            "--policy",
            str(policy),
        )
        accepted = [cluster for cluster in audit["clusters"] if cluster["accepted"]]
        self.assertEqual(len(accepted), 3)

        skill_ids = []
        for cluster in accepted:
            cluster_review = self.write_json(
                f"review-{cluster['id']}.yaml",
                {
                    "cluster_id": cluster["id"],
                    "decision": "accept",
                    "reviewer": "reviewer-a",
                    "reviewed_at": "2026-01-01T00:00:00+00:00",
                    "rationale": "same operation contract across distinct tasks",
                    "pair_assessments_reviewed": True,
                },
            )
            result = self.run_cli(
                "skill",
                "canonicalize",
                "--checkpoint",
                "snapshot-n6",
                "--cluster",
                cluster["id"],
                "--policy",
                str(policy),
                "--review",
                str(cluster_review),
            )
            skill_ids.append(result["skill"]["id"])
        self.assertEqual(len(set(skill_ids)), 3)
        self.assertEqual(
            len(
                list(
                    (self.knowledge / "proposals" / "instance-repetition").glob(
                        "*.yaml"
                    )
                )
            ),
            1,
        )

        proposal = self.run_cli(
            "principle",
            "propose",
            "--checkpoint",
            "snapshot-n6",
            "--skills",
            *(f"{skill_id}@1.0.0" for skill_id in skill_ids),
            "--policy",
            str(policy),
        )["principle"]
        self.assertEqual(proposal["status"], "proposal")
        counterexample_path = self.workspace / "counterexamples.yaml"
        counterexamples = self.run_cli(
            "principle",
            "counterexamples",
            "--id",
            proposal["id"],
            "--from-version",
            "1.0.0",
            "--output",
            str(counterexample_path),
        )
        self.assertEqual(counterexamples["source_partition"], "development")
        self.assertTrue(counterexamples["report_hash"])
        lofo_input = self.write_json(
            "lofo-input.yaml",
            {
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-02T00:00:00+00:00",
                "family_results": {
                    family: {
                        "passed": True,
                        "evaluated_task_ids": [f"lofo-{family}-task"],
                        "supporting_skill_ids": skill_ids,
                        "notes": "rule remains grounded when this family is held out",
                    }
                    for family in families
                },
            },
        )
        lofo_path = self.workspace / "lofo.yaml"
        lofo = self.run_cli(
            "principle",
            "finalize-lofo",
            "--id",
            proposal["id"],
            "--from-version",
            "1.0.0",
            "--report",
            str(lofo_input),
            "--output",
            str(lofo_path),
        )
        self.assertTrue(lofo["passed"])
        review = self.write_json(
            "review.yaml",
            {
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-02T00:00:00+00:00",
                "when": {"fact": "state.object_grasped", "op": "eq", "value": True},
                "decision_mode": "require",
                "decision": "select a transport implementation that preserves clearance",
                "invariant": "safe transport preserves clearance while retaining the grasp",
                "expected_effects": ["fewer collisions"],
                "exceptions": [
                    {
                        "id": "continuous-contact",
                        "when": {"fact": "task.continuous_contact", "op": "eq", "value": True},
                    }
                ],
                "falsifiers": ["clearance-preserving transport does not reduce collisions"],
                "counterexample_report": str(counterexample_path),
                "leave_one_family_out_report": str(lofo_path),
            },
        )
        self.run_cli(
            "principle",
            "review",
            "--id",
            proposal["id"],
            "--from-version",
            "1.0.0",
            "--version",
            "1.1.0",
            "--review",
            str(review),
        )
        validated = self.run_cli(
            "principle",
            "promote",
            "--id",
            proposal["id"],
            "--from-version",
            "1.1.0",
            "--version",
            "1.2.0",
        )["principle"]
        self.assertEqual(validated["status"], "validated")

        parents = self.write_json(
            "parents.yaml",
            {
                "parent_by_child": {
                    proposal["id"]: "root.transport",
                    **{skill_id: proposal["id"] for skill_id in skill_ids},
                }
            },
        )
        self.run_cli(
            "forest",
            "save-tree",
            "--id",
            "tree.transport",
            "--vertical",
            "transport",
            "--structural-root",
            "root.transport",
            "--checkpoint",
            "snapshot-n6",
            "--parents",
            str(parents),
        )
        placement_path = self.workspace / "placement.yaml"
        placement = self.run_cli(
            "forest",
            "placement",
            "--principle",
            proposal["id"],
            "--principle-version",
            "1.2.0",
            "--tree",
            "tree.transport",
            "--tree-version",
            "1.0.0",
            "--parent",
            "root.transport",
            "--output",
            str(placement_path),
        )
        self.assertTrue(placement["accepted_for_review"])
        self.assertFalse(placement["mutation_performed"])
        self.assertEqual(placement["direct_fanout"], 3)
        manifest = self.write_json(
            "manifest.yaml",
            {
                "id": "libero-active",
                "version": "1.0.0",
                "checkpoint_id": "snapshot-n6",
                "skill_versions": {skill_id: "1.0.0" for skill_id in skill_ids},
                "principle_versions": {proposal["id"]: "1.2.0"},
                "tree_versions": {"tree.transport": "1.0.0"},
                "edge_versions": {},
                "created_at": "2026-01-03T00:00:00+00:00",
                "source_partition": "development",
            },
        )
        self.run_cli("manifest", "save", "--file", str(manifest))
        self.assertTrue(self.run_cli("forest", "validate")["ok"])
        overlay_validation = self.run_cli(
            "overlay",
            "validate",
            "--manifest",
            "libero-active",
            "--manifest-version",
            "1.0.0",
        )
        self.assertTrue(overlay_validation["ok"])

        context = self.write_json(
            "context.yaml",
            {
                "task_id": "held-out-task",
                "suite": "libero",
                "task_language": "transport the grasped object safely",
                "task_family": "pick-place",
                "vertical_capabilities": ["transport"],
                "facts": {
                    "state": {"object_grasped": True},
                    "task": {"continuous_contact": False},
                },
                "available_api_calls": [
                    "get_observation",
                    "move_alpha",
                    "move_beta",
                    "move_gamma",
                ],
                "token_budget": 2400,
            },
        )
        hashes = set()
        portfolio_paths = {}
        for treatment in "ABCDEF":
            portfolio_path = self.workspace / f"portfolio-{treatment}.yaml"
            result = self.run_cli(
                "experiment",
                "compile",
                "--treatment",
                treatment,
                "--checkpoint",
                "snapshot-n6",
                "--manifest",
                "libero-active",
                "--manifest-version",
                "1.0.0",
                "--context",
                str(context),
                "--output",
                str(portfolio_path),
            )
            self.assertEqual(result["portfolio"]["treatment"], treatment)
            self.assertLessEqual(result["portfolio"]["estimated_tokens"], 2400)
            hashes.add(result["portfolio_hash"])
            portfolio_paths[treatment] = portfolio_path
        self.assertGreaterEqual(len(hashes), 4)
        runtime_config = self.workspace / "knowledge-runtime.yaml"
        generated = self.run_cli(
            "experiment",
            "runtime-config",
            "--mode",
            "shadow",
            *(
                argument
                for treatment in "ABCDEF"
                for argument in ("--portfolio", f"{treatment}={portfolio_paths[treatment]}")
            ),
            "--output",
            str(runtime_config),
        )
        self.assertTrue(runtime_config.is_file())
        self.assertEqual(set(generated["knowledge"]["shadow_hashes"]), set("ABCDEF"))

        determinism_path = self.workspace / "determinism.yaml"
        determinism = self.run_cli(
            "experiment",
            "verify-determinism",
            "--checkpoint",
            "snapshot-n6",
            "--manifest",
            "libero-active",
            "--manifest-version",
            "1.0.0",
            "--context",
            str(context),
            "--output",
            str(determinism_path),
        )
        self.assertTrue(determinism["tree_index_portfolio_deterministic"])
        self.assertEqual(determinism["first"], determinism["second"])

        preregistration = self.write_json(
            "preregistration.yaml",
            {
                "status": "preregistered-engineering-draft",
                "hypotheses": {f"H{index}": "test" for index in range(1, 7)},
                "treatments": {treatment: treatment for treatment in "ABCDEF"},
                "library_scales": [1, 4, 16, 64],
                "seeds": [11, 29, 47],
                "token_budget": 2400,
            },
        )
        completion = self.run_cli(
            "completion",
            "audit",
            "--preregistration",
            str(preregistration),
            "--determinism-report",
            str(determinism_path),
        )
        self.assertEqual(completion["status"], "incomplete")
        self.assertEqual(completion["maximum_justified_actor_mode"], "off")
        self.assertIn("preregistration-frozen", completion["failed_check_ids"])
        self.assertNotIn("deterministic-rebuild", completion["failed_check_ids"])

        database = self.workspace / "knowledge.sqlite3"
        index = self.run_cli(
            "index",
            "build",
            "--checkpoint",
            "snapshot-n6",
            "--manifest",
            "libero-active",
            "--manifest-version",
            "1.0.0",
            "--output",
            str(database),
        )
        self.assertTrue(database.is_file())
        self.assertEqual(
            self.run_cli("index", "verify", str(database))["metadata"]["source_hash"],
            index["source_hash"],
        )


if __name__ == "__main__":
    unittest.main()
