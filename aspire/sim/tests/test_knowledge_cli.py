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
            result = self.run_cli(
                "skill",
                "canonicalize",
                "--checkpoint",
                "snapshot-n6",
                "--cluster",
                cluster["id"],
                "--policy",
                str(policy),
            )
            skill_ids.append(result["skill"]["id"])
        self.assertEqual(len(set(skill_ids)), 3)

        proposal = self.run_cli(
            "principle",
            "propose",
            "--checkpoint",
            "snapshot-n6",
            "--skills",
            *skill_ids,
            "--policy",
            str(policy),
        )["principle"]
        self.assertEqual(proposal["status"], "proposal")
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
                "counterexample_report": "reports/counterexamples.yaml",
                "leave_one_family_out_report": "reports/lofo.yaml",
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
        for treatment in "ABCDEF":
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
            )
            self.assertEqual(result["portfolio"]["treatment"], treatment)
            self.assertLessEqual(result["portfolio"]["estimated_tokens"], 2400)
            hashes.add(result["portfolio_hash"])
        self.assertGreaterEqual(len(hashes), 4)

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
