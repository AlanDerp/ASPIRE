# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "libero" / "record_skill_promotion.py"


def load_script():
    spec = importlib.util.spec_from_file_location("record_skill_promotion", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_campaign(tmp_path: Path) -> Path:
    root = tmp_path / "sim"
    skills = root / ".claude" / "libero" / "skills"
    findings = (
        root
        / "outputs"
        / "libero_fix_loop"
        / "libero_goal_swap"
        / "example_task"
        / "findings.md"
    )
    skills.mkdir(parents=True)
    findings.parent.mkdir(parents=True)
    (skills / "grasp.md").write_text("# Grasp\n")
    (skills / "transport.md").write_text("# Transport\n")
    findings.write_text("# Findings\n")
    return root


class RecordSkillPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = make_campaign(Path(self.temporary.name))
        self.promotion = load_script()

    def tearDown(self):
        self.temporary.cleanup()

    def test_records_exact_per_task_patch_and_hashes(self):
        begin = self.promotion.begin_promotion(
            self.root,
            suite="libero_goal_swap",
            task="example_task",
            timestamp=lambda: "2026-01-01T00:00:00+00:00",
        )
        (self.root / ".claude/libero/skills/grasp.md").write_text(
            "# Grasp\n\nReusable pattern.\n"
        )
        record = self.promotion.finish_promotion(
            self.root,
            suite="libero_goal_swap",
            task="example_task",
            timestamp=lambda: "2026-01-01T00:01:00+00:00",
        )

        self.assertNotEqual(begin["library_before_sha256"], record["library_after_sha256"])
        self.assertEqual(record["changed_skill_files"], [".claude/libero/skills/grasp.md"])
        self.assertIn("Reusable pattern.", (self.root / record["patch_path"]).read_text())
        ledger = self.root / "outputs/libero_fix_loop/libero_goal_swap/skill_promotions.jsonl"
        entries = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertEqual(entries, [record])
        self.assertEqual(
            self.promotion.verify_promotion(
                self.root, suite="libero_goal_swap", task="example_task"
            ),
            record,
        )
        self.assertEqual(len(ledger.read_text().splitlines()), 1)

    def test_requires_serial_promotions(self):
        self.promotion.begin_promotion(
            self.root, suite="libero_goal_swap", task="example_task"
        )
        with self.assertRaisesRegex(ValueError, "another promotion is unfinished"):
            self.promotion.begin_promotion(
                self.root, suite="libero_goal_swap", task="second_task"
            )

    def test_no_op_requires_and_records_reason(self):
        self.promotion.begin_promotion(
            self.root, suite="libero_goal_swap", task="example_task"
        )
        with self.assertRaisesRegex(ValueError, "pass --reason"):
            self.promotion.finish_promotion(
                self.root, suite="libero_goal_swap", task="example_task"
            )
        record = self.promotion.finish_promotion(
            self.root,
            suite="libero_goal_swap",
            task="example_task",
            reason="No generalizable Stage 1 finding.",
        )
        self.assertTrue(record["no_op"])
        self.assertEqual(record["changed_skill_files"], [])
        self.assertEqual(record["library_before_sha256"], record["library_after_sha256"])
        self.assertEqual(record["reason"], "No generalizable Stage 1 finding.")

    def test_records_structured_knowledge_change(self):
        knowledge = self.root / "knowledge"
        knowledge.mkdir()
        (knowledge / "schema-version.txt").write_text("1\n")

        self.promotion.begin_promotion(
            self.root, suite="libero_goal_swap", task="example_task"
        )
        (knowledge / "schema-version.txt").write_text("2\n")
        record = self.promotion.finish_promotion(
            self.root, suite="libero_goal_swap", task="example_task"
        )

        self.assertEqual(record["changed_skill_files"], [])
        self.assertEqual(record["changed_knowledge_files"], ["knowledge/schema-version.txt"])
        self.assertFalse(record["no_op"])
        self.assertIn("schema-version.txt", (self.root / record["patch_path"]).read_text())

    def test_verify_fails_before_promotion_finishes(self):
        self.promotion.begin_promotion(
            self.root, suite="libero_goal_swap", task="example_task"
        )
        with self.assertRaisesRegex(ValueError, "promotion is not complete"):
            self.promotion.verify_promotion(
                self.root, suite="libero_goal_swap", task="example_task"
            )


if __name__ == "__main__":
    unittest.main()
