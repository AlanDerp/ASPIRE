# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tempfile
import unittest
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

from aspire.sim.cap.knowledge.checkpoints import freeze_checkpoint
from aspire.sim.cap.knowledge.consolidation import canonicalize_cluster, propose_principle
from aspire.sim.cap.knowledge.fingerprint import fingerprint_code
from aspire.sim.cap.knowledge.golden import GoldenLabel, evaluate_golden
from aspire.sim.cap.knowledge.experiment import Observation, build_report, compile_treatment
from aspire.sim.cap.knowledge.forest import descendants, validate_forest
from aspire.sim.cap.knowledge.index import index_metadata, rebuild_index
from aspire.sim.cap.knowledge.ingest import build_instance
from aspire.sim.cap.knowledge.integrity import validate_repository
from aspire.sim.cap.knowledge.lifecycle import invalidate, principle_metrics
from aspire.sim.cap.knowledge.maintenance import audit_maintenance
from aspire.sim.cap.knowledge.models import (
    CanonicalSkill,
    Checkpoint,
    ConsolidationPolicy,
    KnowledgeManifest,
    ModelError,
    OverlayEdge,
    Principle,
    Scope,
    SkillCodeInstance,
    TaskContext,
    VerticalTree,
)
from aspire.sim.cap.knowledge.predicates import evaluate
from aspire.sim.cap.knowledge.projection import lineage_view, overlay_view, vertical_forest
from aspire.sim.cap.knowledge.repository import KnowledgeRepository, RepositoryConflict
from aspire.sim.cap.knowledge.review import promote_principle, review_principle
from aspire.sim.cap.knowledge.repetition import (
    assess_pair,
    audit_principle_repetition,
    audit_repetition,
)
from aspire.sim.cap.knowledge.retrieval import compile_portfolio
from aspire.sim.cap.knowledge.serialization import content_hash
from aspire.sim.cap.knowledge.stress import build_stress_corpus


def make_instance(
    index: int,
    *,
    vertical: str = "transport",
    code: str | None = None,
    task_family: str = "pick-place",
) -> SkillCodeInstance:
    code = code or "def reset():\n    goto_home_joint_position()\n    return get_observation()\n"
    fingerprint = fingerprint_code(code)
    return SkillCodeInstance(
        id=f"skill-code.libero.task-{index}.reset",
        vertical_capability=vertical,
        task=f"task-{index}",
        task_family=task_family,
        source_code_path=f"outputs/task-{index}/fix_code.py",
        source_code_sha256=f"source-{index}",
        code=code,
        goal="reset robot configuration before next subtask",
        trigger="remaining subtasks after a configuration-changing action",
        observed_effect="fresh observation and fewer inverse kinematics failures",
        code_hash=fingerprint.code_hash,
        ast_fingerprint=fingerprint.ast_fingerprint,
        api_calls=fingerprint.api_calls,
        development_outcomes={"successes": [51 + index]},
    )


def make_skill(index: int, *, vertical: str = "transport") -> CanonicalSkill:
    return CanonicalSkill(
        id=f"skill.{vertical}.pattern-{index}",
        version="1.0.0",
        vertical_capability=vertical,
        title=f"Transport pattern {index}",
        goal=f"move object safely using pattern {index}",
        trigger="object is grasped and a target remains",
        operation_template="goto_home_joint_position -> get_observation",
        effect="object reaches a safe state",
        instance_ids=(f"instance-{index}-a", f"instance-{index}-b"),
        api_calls=("goto_home_joint_position", "get_observation"),
        scope=Scope(task_families=("pick-place", "long-horizon")),
        status="validated",
        provenance={
            "checkpoint_id": "snapshot-n20",
            "repetition_cluster_id": f"cluster-{index}",
            "instance_repetition_report_hash": f"report-{index}",
            "cluster_review": {
                "cluster_id": f"cluster-{index}",
                "decision": "accept",
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "rationale": "reviewed repeated implementation evidence",
                "pair_assessments_reviewed": True,
            },
        },
    )


def checkpoint_for_skills(*skills: CanonicalSkill) -> Checkpoint:
    instance_ids = tuple(
        sorted({instance_id for skill in skills for instance_id in skill.instance_ids})
    )
    return Checkpoint(
        id="snapshot-n20",
        instance_ids=instance_ids,
        instance_hashes={instance_id: f"hash-{instance_id}" for instance_id in instance_ids},
        created_at="2026-01-01T00:00:00+00:00",
    )


class KnowledgeModelTests(unittest.TestCase):
    def test_fingerprint_ignores_local_names_but_preserves_calls(self):
        left = fingerprint_code("def f(x):\n    y = x + 1\n    return solve_ik(y, x)\n")
        right = fingerprint_code("def g(a):\n    b = a + 9\n    return solve_ik(b, a)\n")
        self.assertNotEqual(left.code_hash, right.code_hash)
        self.assertEqual(left.ast_fingerprint, right.ast_fingerprint)
        self.assertEqual(left.api_calls, right.api_calls)

    def test_validated_principle_cannot_bypass_review(self):
        with self.assertRaises(ModelError):
            Principle(
                id="principle.transport.unsafe-draft",
                version="1.0.0",
                vertical_capability="transport",
                title="Unsafe draft",
                summary="",
                when={},
                decision_mode="prefer",
                decision="move",
                invariant="clearance",
                expected_effects=(),
                exceptions=(),
                falsifiers=("fails",),
                child_ids=("skill.a", "skill.b", "skill.c"),
                status="validated",
                review_required=True,
            )

    def test_validated_principle_requires_diverse_support_and_exception_review(self):
        with self.assertRaisesRegex(ModelError, "two task families"):
            Principle(
                id="principle.transport.narrow-support",
                version="1.0.0",
                vertical_capability="transport",
                title="Narrow support",
                summary="",
                when={},
                decision_mode="prefer",
                decision="move",
                invariant="clearance",
                expected_effects=(),
                exceptions=(),
                exception_review="no exception found in reviewed evidence",
                falsifiers=("fails",),
                child_ids=("skill.a", "skill.b", "skill.c"),
                scope=Scope(task_families=("pick-place",)),
                status="validated",
                review_required=False,
                provenance={
                    "checkpoint_id": "snapshot-n20",
                    "proposal_method": "canonical-skill-repetition-audit",
                    "canonical_repetition_audit": {},
                    "canonical_repetition_audit_hash": "audit-hash",
                    "canonical_skill_versions": {
                        "skill.a": "1.0.0",
                        "skill.b": "1.0.0",
                        "skill.c": "1.0.0",
                    },
                },
            )

    def test_predicate_unknown_is_not_true(self):
        predicate = {"fact": "state.object_grasped", "op": "eq", "value": True}
        self.assertIsNone(evaluate(predicate, {}))
        self.assertTrue(evaluate(predicate, {"state": {"object_grasped": True}}))

    def test_same_ast_shape_with_different_api_is_not_canonical_duplicate(self):
        left = make_instance(1, code="get_observation()\nmove_alpha()\n")
        right = make_instance(2, code="get_observation()\nmove_beta()\n")
        assessment = assess_pair(left, right)
        self.assertNotIn(
            assessment.classification, {"exact-duplicate", "same-canonical-skill"}
        )

    def test_golden_report_preserves_reviewer_disagreement(self):
        labels = [
            GoldenLabel(
                principle_id=f"principle.transport.p-{index}",
                task_family="pick-place",
                reviewer=reviewer,
                dimension="faithfulness",
                score=0.9 if reviewer == "reviewer-a" else 0.8,
                polarity=polarity,
            )
            for index in range(10)
            for reviewer in ("reviewer-a", "reviewer-b")
            for polarity in ("support", "hard-negative", "exception", "falsifier")
        ]
        report = evaluate_golden(labels)
        self.assertTrue(report["ready"])
        self.assertTrue(report["disagreements"])
        self.assertTrue(report["faithfulness_gate_passed"])


class RepositoryAndConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "knowledge"
        self.repository = KnowledgeRepository(self.root)
        self.repository.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_immutable_instance_and_checkpoint_gate(self):
        first = make_instance(1)
        self.repository.save_instance(first)
        self.repository.save_instance(first)
        changed = SkillCodeInstance.from_dict({**first.__dict__, "goal": "changed goal"})
        with self.assertRaises(RepositoryConflict):
            self.repository.save_instance(changed)
        with self.assertRaises(ValueError):
            freeze_checkpoint(
                self.repository,
                "snapshot-n1",
                ConsolidationPolicy(checkpoint_every_instances=2, min_distinct_tasks=2),
            )

    def test_ingest_extracts_exact_executed_lines_and_rejects_held_out(self):
        source = Path(self.temporary.name) / "fix_code.py"
        source.write_text("observe()\nmove()\nverify()\n")
        instance = build_instance(
            instance_id="skill-code.libero.task-1.transport",
            vertical_capability="transport",
            task="task-1",
            task_family="pick-place",
            source_path=source,
            goal="move then verify",
            line_range="2:3",
            development_outcomes={"successes": [51]},
        )
        self.assertEqual(instance.code, "move()\nverify()")
        self.assertEqual(instance.provenance["partition"], "development")
        with self.assertRaisesRegex(ValueError, "held-out"):
            build_instance(
                instance_id="skill-code.libero.task-1.held-out",
                vertical_capability="transport",
                task="task-1",
                task_family="pick-place",
                source_path=source,
                goal="forbidden evidence",
                source_partition="held-out",
            )

    def test_repetition_audit_precedes_canonical_skill(self):
        instances = [make_instance(index) for index in range(1, 4)]
        for value in instances:
            self.repository.save_instance(value)
        policy = ConsolidationPolicy(
            checkpoint_every_instances=3,
            min_distinct_tasks=3,
            min_cluster_instances=3,
            min_cluster_tasks=3,
            min_successful_instances=2,
            max_single_task_share=0.5,
        )
        checkpoint = freeze_checkpoint(
            self.repository, "snapshot-n3", policy, created_at="2026-01-01T00:00:00+00:00"
        )
        report = audit_repetition(instances, checkpoint, policy)
        self.assertEqual(len(report.clusters), 1)
        self.assertTrue(report.clusters[0].accepted)
        skill = canonicalize_cluster(
            report.clusters[0],
            instances,
            checkpoint,
            policy,
            report,
            {
                "cluster_id": report.clusters[0].id,
                "decision": "accept",
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "rationale": "the pair implements the same operation contract",
                "pair_assessments_reviewed": True,
            },
        )
        self.assertEqual(set(skill.instance_ids), {value.id for value in instances})
        self.assertEqual(skill.provenance["checkpoint_id"], checkpoint.id)
        with self.assertRaisesRegex(ValueError, "explicit accept"):
            canonicalize_cluster(
                report.clusters[0],
                instances,
                checkpoint,
                policy,
                report,
                {
                    "cluster_id": report.clusters[0].id,
                    "decision": "reject",
                    "reviewer": "reviewer-a",
                    "reviewed_at": "2026-01-01T00:00:00+00:00",
                    "rationale": "pair is an alternative, not an equivalent implementation",
                    "pair_assessments_reviewed": True,
                },
            )

    def test_principle_proposal_is_review_required(self):
        skills = [make_skill(index) for index in range(1, 4)]
        principle = propose_principle(
            skills, checkpoint_for_skills(*skills), ConsolidationPolicy()
        )
        self.assertEqual(principle.status, "proposal")
        self.assertTrue(principle.review_required)
        self.assertFalse(principle.falsifiers)

    def test_principle_requires_review_revision_before_promotion(self):
        skills = [make_skill(index) for index in range(1, 4)]
        proposal = propose_principle(
            skills,
            checkpoint_for_skills(*skills),
            ConsolidationPolicy(),
        )
        candidate = review_principle(
            proposal,
            {
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-02T00:00:00+00:00",
                "when": {"fact": "state.object_grasped", "op": "eq", "value": True},
                "decision": "preserve obstacle clearance",
                "invariant": "a grasped object needs a collision-free swept volume",
                "falsifiers": ["clearance does not change collision rate"],
                "exceptions": [
                    {
                        "id": "continuous-contact",
                        "when": {"fact": "task.continuous_contact", "op": "eq", "value": True},
                    }
                ],
                "counterexample_report": "reports/counterexamples.yaml",
                "leave_one_family_out_report": "reports/lofo.yaml",
            },
            version="1.1.0",
        )
        self.assertEqual(candidate.status, "candidate")
        validated = promote_principle(candidate, version="1.2.0")
        self.assertEqual(validated.status, "validated")
        self.assertFalse(validated.review_required)

    def test_principle_proposal_requires_unique_skills_frozen_in_checkpoint(self):
        skills = [make_skill(index) for index in range(1, 4)]
        incomplete = Checkpoint(
            id="snapshot-n20",
            instance_ids=skills[0].instance_ids + skills[1].instance_ids,
            instance_hashes={
                instance_id: f"hash-{instance_id}"
                for instance_id in skills[0].instance_ids + skills[1].instance_ids
            },
            created_at="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaisesRegex(ValueError, "instances outside checkpoint"):
            propose_principle(skills, incomplete, ConsolidationPolicy())
        with self.assertRaisesRegex(ValueError, "requires 3 canonical skills"):
            propose_principle(
                [skills[0], skills[0], skills[1]],
                checkpoint_for_skills(*skills),
                ConsolidationPolicy(),
            )

    def test_principle_repetition_audit_rejects_disconnected_skill(self):
        skills = [make_skill(index) for index in range(1, 4)]
        skills[2] = replace(
            skills[2],
            goal="calibrate camera pixels",
            trigger="camera intrinsics changed",
            effect="image reprojection error decreases",
        )
        checkpoint = checkpoint_for_skills(*skills)
        audit = audit_principle_repetition(
            skills,
            checkpoint,
            ConsolidationPolicy(),
        )
        self.assertFalse(audit.accepted)
        self.assertIn(
            "canonical-skill repetition graph is disconnected",
            audit.rejection_reasons,
        )
        with self.assertRaisesRegex(ValueError, "repetition audit rejected"):
            propose_principle(skills, checkpoint, ConsolidationPolicy())


class ForestAndRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = KnowledgeRepository(Path(self.temporary.name) / "knowledge")
        self.repository.initialize()
        self.instances = [
            make_instance(
                index,
                code=(
                    "get_observation()\n"
                    f"move_group_{(index - 1) // 2 + 1}()\n"
                ),
                task_family="pick-place" if index % 2 else "long-horizon",
            )
            for index in range(1, 7)
        ]
        for value in self.instances:
            self.repository.save_instance(value)
        checkpoint = Checkpoint(
            id="snapshot-n3",
            instance_ids=tuple(value.id for value in self.instances),
            instance_hashes={value.id: content_hash(value) for value in self.instances},
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.repository.save_checkpoint(checkpoint)
        instance_policy = ConsolidationPolicy(
            min_cluster_instances=2,
            min_cluster_tasks=2,
            min_successful_instances=2,
            max_single_task_share=0.5,
        )
        instance_audit = audit_repetition(
            self.instances,
            checkpoint,
            instance_policy,
        )
        self.repository.save_audit(
            "instance-repetition",
            instance_audit.content_hash,
            asdict(instance_audit),
        )
        clusters_by_members = {
            frozenset(cluster.instance_ids): cluster
            for cluster in instance_audit.clusters
        }
        self.skills = [
            replace(
                make_skill(index),
                instance_ids=(self.instances[2 * index - 2].id, self.instances[2 * index - 1].id),
                provenance={
                    "checkpoint_id": "snapshot-n3",
                    "repetition_cluster_id": clusters_by_members[
                        frozenset(
                            (
                                self.instances[2 * index - 2].id,
                                self.instances[2 * index - 1].id,
                            )
                        )
                    ].id,
                    "instance_repetition_report_hash": instance_audit.content_hash,
                    "cluster_review": {
                        "cluster_id": clusters_by_members[
                            frozenset(
                                (
                                    self.instances[2 * index - 2].id,
                                    self.instances[2 * index - 1].id,
                                )
                            )
                        ].id,
                        "decision": "accept",
                        "reviewer": "reviewer-a",
                        "reviewed_at": "2026-01-01T00:00:00+00:00",
                        "rationale": "same contract and API implementation",
                        "pair_assessments_reviewed": True,
                    },
                },
            )
            for index in range(1, 4)
        ]
        for value in self.skills:
            self.repository.save_skill(value)
        principle_audit = audit_principle_repetition(
            self.skills,
            checkpoint,
            ConsolidationPolicy(),
        )
        self.assertTrue(principle_audit.accepted, principle_audit.rejection_reasons)
        self.principle = Principle(
            id="principle.transport.preserve-clearance",
            version="1.0.0",
            vertical_capability="transport",
            title="Preserve clearance during transport",
            summary="Choose transit patterns that preserve grasp and obstacle clearance.",
            when={"fact": "state.object_grasped", "op": "eq", "value": True},
            decision_mode="require",
            decision="select a collision-safe transit pattern",
            invariant="a grasped object needs clearance throughout transport",
            expected_effects=("grasp remains secure",),
            exceptions=(
                {
                    "id": "continuous-contact",
                    "when": {"fact": "task.continuous_contact", "op": "eq", "value": True},
                },
            ),
            falsifiers=("clearance-preserving patterns do not reduce collisions",),
            child_ids=tuple(value.id for value in self.skills),
            scope=Scope(task_families=("pick-place", "long-horizon")),
            status="validated",
            review_required=False,
            provenance={
                "checkpoint_id": "snapshot-n3",
                "proposal_method": "canonical-skill-repetition-audit",
                "canonical_repetition_audit": asdict(principle_audit),
                "canonical_repetition_audit_hash": principle_audit.content_hash,
                "canonical_skill_versions": principle_audit.skill_versions,
                "reviewer": "reviewer-a",
                "counterexample_report": "reports/counterexample-1.yaml",
                "leave_one_family_out_report": "reports/lofo-1.yaml",
            },
        )
        self.repository.save_principle(self.principle)
        self.repository.append_evidence(
            {
                "event": "knowledge.validated",
                "subject": self.principle.id,
                "version": self.principle.version,
                "at": "2026-01-02T00:00:00+00:00",
                "reviewer": "reviewer-a",
            },
            stream="lifecycle",
        )
        self.tree = VerticalTree(
            id="tree.transport",
            version="1.0.0",
            vertical_capability="transport",
            structural_root="root.transport",
            checkpoint_id="snapshot-n3",
            parent_by_child={
                self.principle.id: "root.transport",
                **{value.id: self.principle.id for value in self.skills},
            },
        )
        self.repository.save_tree(self.tree)

    def tearDown(self):
        self.temporary.cleanup()

    def test_forest_validation_and_descendants(self):
        report = validate_forest([self.tree], self.skills, [self.principle], [])
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(set(descendants(self.tree, self.principle.id)), {v.id for v in self.skills})

    def test_repository_integrity_covers_lineage_and_support(self):
        report = validate_repository(self.repository)
        self.assertTrue(report.ok, report.issues)

    def test_integrity_rejects_principle_support_outside_its_checkpoint(self):
        instance_ids = self.skills[0].instance_ids
        checkpoint = Checkpoint(
            id="snapshot-too-early",
            instance_ids=instance_ids,
            instance_hashes={
                instance_id: content_hash(
                    next(value for value in self.instances if value.id == instance_id)
                )
                for instance_id in instance_ids
            },
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.repository.save_checkpoint(checkpoint)
        self.repository.save_principle(
            replace(
                self.principle,
                version="1.1.0",
                provenance={
                    **self.principle.provenance,
                    "checkpoint_id": checkpoint.id,
                },
            )
        )
        report = validate_repository(self.repository)
        self.assertIn(
            "principle-child-outside-checkpoint",
            {issue.code for issue in report.issues},
        )

    def test_integrity_recomputes_principle_repetition_audit(self):
        self.repository.save_principle(
            replace(
                self.principle,
                version="1.1.0",
                provenance={
                    **self.principle.provenance,
                    "canonical_repetition_audit_hash": "tampered",
                },
            )
        )
        report = validate_repository(self.repository)
        self.assertIn(
            "invalid-principle-repetition-audit",
            {issue.code for issue in report.issues},
        )
        metrics = principle_metrics(self.repository, self.principle)
        self.assertEqual(metrics.support_sufficiency, "sufficient")
        self.assertEqual(metrics.support_count, 6)

    def test_integrity_recomputes_instance_repetition_audit(self):
        self.repository.save_skill(
            replace(
                self.skills[0],
                version="1.1.0",
                provenance={
                    **self.skills[0].provenance,
                    "instance_repetition_report_hash": "tampered",
                },
            )
        )
        report = validate_repository(self.repository)
        self.assertIn(
            "invalid-instance-repetition-audit",
            {issue.code for issue in report.issues},
        )

    def test_unrecorded_principle_revision_is_not_actor_visible(self):
        revised = replace(self.principle, version="1.1.0")
        self.repository.save_principle(revised)
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertIn(
            "unrecorded-promotion",
            {item["reason"] for item in portfolio.exclusions},
        )
        self.assertIn(
            "unrecorded-principle-promotion",
            {issue.code for issue in validate_repository(self.repository).issues},
        )

    def test_integrity_rejects_multiple_instance_membership_and_unplaced_skill(self):
        duplicate = replace(
            self.skills[0], id="skill.transport.duplicate-membership"
        )
        self.repository.save_skill(duplicate)
        report = validate_repository(self.repository)
        codes = {issue.code for issue in report.issues}
        self.assertIn("multiple-instance-membership", codes)
        self.assertIn("unplaced-active-skill", codes)

    def test_projections_are_deterministic_and_trace_to_code(self):
        first = vertical_forest(self.repository, vertical="transport")
        second = vertical_forest(self.repository, vertical="transport")
        self.assertEqual(first["projection_hash"], second["projection_hash"])
        self.assertEqual(first["trees"][0]["instance_count"], 6)
        family = vertical_forest(
            self.repository, vertical="transport", task_family="pick-place"
        )
        self.assertEqual(family["trees"][0]["instance_count"], 3)
        lineage_projection = lineage_view(self.repository, self.principle.id)
        self.assertEqual(len(lineage_projection["instance_ids"]), 6)
        self.assertEqual(overlay_view(self.repository)["edges"], [])

    def test_invalidation_localizes_impact_and_removes_weak_principle(self):
        first = invalidate(
            self.repository,
            self.skills[0].id,
            "API removed",
            at="2026-01-02T00:00:00+00:00",
        )
        self.assertIn(self.principle.id, first.affected_principle_ids)
        invalidate(
            self.repository,
            self.skills[1].id,
            "implementation stale",
            at="2026-01-03T00:00:00+00:00",
        )
        metrics = principle_metrics(self.repository, self.principle)
        self.assertEqual(metrics.support_sufficiency, "weak")
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertEqual(portfolio.skill_ids, (self.skills[2].id,))
        self.assertIn("support:weak", {item["reason"] for item in portfolio.exclusions})
        audit = audit_maintenance(self.repository)
        self.assertEqual(
            {item["id"] for item in audit["prune_candidates"]},
            {self.skills[0].id, self.skills[1].id},
        )
        self.assertFalse(audit["destructive_changes_performed"])

    def test_held_out_invalidation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "held-out"):
            invalidate(
                self.repository,
                self.skills[0].id,
                "held-out failure",
                source_partition="held-out",
            )

    def test_forest_validation_materializes_latest_revision(self):
        revised_skill = replace(
            self.skills[0], version="1.1.0", title="Revised transport pattern"
        )
        report = validate_forest(
            [self.tree], [*self.skills, revised_skill], [self.principle], []
        )
        self.assertTrue(report.ok, report.issues)

    def test_forest_rejects_cycles_and_multiple_primary_trees(self):
        cyclic = replace(
            self.tree,
            parent_by_child={
                self.skills[0].id: self.skills[1].id,
                self.skills[1].id: self.skills[0].id,
                self.principle.id: "root.transport",
                self.skills[2].id: self.principle.id,
            },
        )
        cycle_report = validate_forest(
            [cyclic], self.skills, [self.principle], []
        )
        self.assertIn("tree-cycle", {issue.code for issue in cycle_report.issues})
        alternate = replace(
            self.tree,
            id="tree.transport-alternate",
            parent_by_child={self.skills[0].id: "root.transport"},
        )
        parent_report = validate_forest(
            [self.tree, alternate], self.skills, [self.principle], []
        )
        self.assertIn(
            "multiple-primary-parents", {issue.code for issue in parent_report.issues}
        )

    def test_tree_rejects_undeclared_principle_child(self):
        extra = replace(
            self.skills[0],
            id="skill.transport.extra",
            title="Extra transport pattern",
        )
        tree = replace(
            self.tree,
            parent_by_child={**self.tree.parent_by_child, extra.id: self.principle.id},
        )
        report = validate_forest([tree], [*self.skills, extra], [self.principle], [])
        self.assertIn("principle-child-mismatch", {issue.code for issue in report.issues})

    def test_topdown_limits_children_per_principle(self):
        extra = replace(
            self.skills[0],
            id="skill.transport.extra",
            title="Extra transport pattern",
        )
        revised_principle = replace(
            self.principle,
            version="1.1.0",
            child_ids=(*self.principle.child_ids, extra.id),
        )
        revised_tree = replace(
            self.tree,
            version="1.1.0",
            parent_by_child={
                **self.tree.parent_by_child,
                extra.id: revised_principle.id,
            },
        )
        self.repository.save_skill(extra)
        self.repository.save_principle(revised_principle)
        self.repository.save_tree(revised_tree)
        self.repository.append_evidence(
            {
                "event": "knowledge.validated",
                "subject": revised_principle.id,
                "version": revised_principle.version,
                "at": "2026-01-03T00:00:00+00:00",
                "reviewer": "reviewer-a",
            },
            stream="lifecycle",
        )
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(
            self.repository,
            "snapshot-n3",
            context,
            max_skills=8,
            max_children_per_principle=3,
        )
        self.assertEqual(len(portfolio.skill_ids), 3)

    def test_overlay_dangling_reference_is_rejected(self):
        edge = OverlayEdge(
            id="edge.transport.requires-missing",
            version="1.0.0",
            kind="requires",
            source_id=self.skills[0].id,
            target_id="skill.localization.missing",
        )
        report = validate_forest([self.tree], self.skills, [self.principle], [edge])
        self.assertFalse(report.ok)
        self.assertIn("dangling-edge-target", {issue.code for issue in report.issues})

    def test_overlay_projection_materializes_both_query_directions(self):
        edge = OverlayEdge(
            id="edge.transport.can-follow",
            version="1.0.0",
            kind="can-follow",
            source_id=self.skills[0].id,
            target_id=self.skills[1].id,
        )
        self.repository.save_edge(edge)
        projection = overlay_view(self.repository)
        self.assertEqual(
            projection["outgoing_by_node"][self.skills[0].id], [edge.id]
        )
        self.assertEqual(
            projection["incoming_by_node"][self.skills[1].id], [edge.id]
        )

    def test_guarded_overlay_exception_blocks_target_branch(self):
        edge = OverlayEdge(
            id="edge.transport.contact-exception",
            version="1.0.0",
            kind="exception-to",
            source_id=self.skills[0].id,
            target_id=self.principle.id,
            guard={"fact": "task.cross_tree_exception", "op": "eq", "value": True},
        )
        self.repository.save_edge(edge)
        context = TaskContext(
            task_id="task-exception",
            suite="libero",
            task_language="transport with a guarded exception",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={
                "state": {"object_grasped": True},
                "task": {"continuous_contact": False, "cross_tree_exception": True},
            },
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertEqual(portfolio.skill_ids, (self.skills[0].id,))
        self.assertIn(edge.id, portfolio.overlay_edge_ids)
        self.assertIn(
            f"overlay-exception:{edge.id}",
            {item["reason"] for item in portfolio.exclusions},
        )

    def test_index_and_tree_first_portfolio(self):
        database = Path(self.temporary.name) / "akl.sqlite3"
        digest = rebuild_index(self.repository, database, checkpoint_id="snapshot-n3")
        self.assertEqual(index_metadata(database)["source_hash"], digest)
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object with safe obstacle clearance",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}, "task": {"continuous_contact": False}},
            available_api_calls=("goto_home_joint_position", "get_observation"),
            token_budget=2400,
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertEqual(portfolio.principle_ids, (self.principle.id,))
        self.assertTrue(portfolio.skill_ids)
        self.assertIn("Preserve clearance during transport", portfolio.markdown)

    def test_manifest_locks_revisions_and_rejects_held_out_source(self):
        manifest = KnowledgeManifest(
            id="libero-active",
            version="1.0.0",
            checkpoint_id="snapshot-n3",
            skill_versions={value.id: value.version for value in self.skills},
            principle_versions={self.principle.id: self.principle.version},
            tree_versions={self.tree.id: self.tree.version},
            edge_versions={},
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.repository.save_manifest(manifest)
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(
            self.repository, "snapshot-n3", context, manifest=manifest
        )
        self.assertEqual(portfolio.manifest_id, "libero-active@1.0.0")
        self.assertEqual(
            portfolio.node_versions[f"principle:{self.principle.id}"], "1.0.0"
        )
        database = Path(self.temporary.name) / "manifest.sqlite3"
        rebuild_index(
            self.repository,
            database,
            checkpoint_id="snapshot-n3",
            manifest=manifest,
        )
        self.assertEqual(index_metadata(database)["manifest_id"], "libero-active@1.0.0")
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                connection.execute("SELECT support_sufficiency FROM principle_metrics").fetchone()[0],
                "sufficient",
            )
        finally:
            connection.close()
        held_out = KnowledgeManifest.from_dict(
            {**manifest.__dict__, "version": "1.0.1", "source_partition": "held-out"}
        )
        with self.assertRaisesRegex(ValueError, "held-out"):
            compile_portfolio(self.repository, "snapshot-n3", context, manifest=held_out)

    def test_exception_blocks_principle_and_uses_canonical_fallback(self):
        context = TaskContext(
            task_id="task-contact",
            suite="libero",
            task_language="transport while maintaining continuous contact",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}, "task": {"continuous_contact": True}},
            available_api_calls=("goto_home_joint_position", "get_observation"),
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertTrue(portfolio.skill_ids)
        self.assertIn("exception:continuous-contact", {item["reason"] for item in portfolio.exclusions})

    def test_all_preregistered_treatments_compile_under_one_checkpoint(self):
        context = TaskContext(
            task_id="task-eval",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}, "task": {"continuous_contact": False}},
            available_api_calls=("goto_home_joint_position", "get_observation"),
            token_budget=2400,
        )
        portfolios = {
            treatment: compile_treatment(
                self.repository, "snapshot-n3", context, treatment
            )
            for treatment in "ABCDEF"
        }
        self.assertEqual(set(portfolios), set("ABCDEF"))
        self.assertTrue(portfolios["A"].instance_ids)
        self.assertTrue(portfolios["B"].skill_ids)
        self.assertFalse(portfolios["D"].overlay_edge_ids)
        self.assertTrue(
            all(value.estimated_tokens <= context.token_budget for value in portfolios.values())
        )

    def test_experiment_report_refuses_claim_with_missing_cells(self):
        observations = [
            Observation(
                treatment="A",
                scale=scale,
                seed=11,
                task_id=f"task-{scale}",
                task_family="pick-place",
                corpus_kind="organic",
                split="held-out",
                success=1.0,
                context_tokens=100 * scale,
                compile_latency_ms=2.0,
            )
            for scale in (1, 4)
        ]
        report = build_report(observations, {"library_scales": [1, 4, 16, 64]})
        self.assertEqual(report["claim_status"], "not-evaluable")
        self.assertGreater(report["results"]["organic:A"]["scale_slopes"]["context_tokens"], 0)

    def test_experiment_report_accepts_complete_fair_cells_for_analysis(self):
        observations = []
        for corpus_kind in ("organic", "synthetic"):
            for scale in (1, 4):
                for treatment in "ABCDEF":
                    observations.append(
                        Observation(
                            treatment=treatment,
                            scale=scale,
                            seed=11,
                            task_id="task-1",
                            task_family="pick-place",
                            corpus_kind=corpus_kind,
                            split="held-out",
                            success=0.8,
                            context_tokens=100 + scale,
                            compile_latency_ms=2.0,
                            relevant_principle_recall=(
                                0.95 if treatment in {"D", "E"} else 0.0
                            ),
                            relevant_skill_recall=0.80,
                            fallback=(0.05 if treatment in {"D", "E"} else 0.0),
                            n_code=6 * scale,
                            token_budget=2400,
                            checkpoint_id="snapshot-n3",
                            manifest_id="libero-active@1.0.0",
                            corpus_hash=f"{corpus_kind}-{scale}",
                            context_hash=f"context-{scale}",
                            portfolio_hash=f"portfolio-{corpus_kind}-{scale}-{treatment}",
                            model_id="model-v1",
                            prompt_hash="base-prompt-v1",
                        )
                    )
        report = build_report(
            observations,
            {
                "status": "frozen",
                "library_scales": [1, 4],
                "seeds": [11],
                "decision_rules": {"task_noninferiority_margin": 0.03},
            },
        )
        self.assertEqual(report["claim_status"], "ready-for-prespecified-statistical-analysis")
        self.assertTrue(report["heldout_success_noninferior_to_B"]["D"])
        self.assertTrue(report["runtime_gates"]["passed"])
        self.assertFalse(report["coverage"]["fairness_violations"])

    def test_stress_corpus_is_deterministic_and_never_evidence_eligible(self):
        first = build_stress_corpus(
            self.repository, "snapshot-n3", [1, 4], seed=11
        )
        second = build_stress_corpus(
            self.repository, "snapshot-n3", [1, 4], seed=11
        )
        self.assertEqual(first["corpus_hash"], second["corpus_hash"])
        self.assertEqual(first["snapshots"][1]["record_count"], 24)
        self.assertTrue(
            all(
                record["synthetic"] and not record["evidence_eligible"]
                for snapshot in first["snapshots"]
                for record in snapshot["records"]
            )
        )


if __name__ == "__main__":
    unittest.main()
