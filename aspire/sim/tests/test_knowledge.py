# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
import unittest
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

from aspire.sim.cap.knowledge.checkpoints import freeze_checkpoint
from aspire.sim.cap.knowledge.compression import (
    build_compression_report,
    supporting_skills,
)
from aspire.sim.cap.knowledge.consolidation import canonicalize_cluster, propose_principle
from aspire.sim.cap.knowledge.counterexample import (
    search_counterexamples,
    validate_counterexample_dispositions,
    validate_counterexample_report,
)
from aspire.sim.cap.knowledge.fingerprint import fingerprint_code
from aspire.sim.cap.knowledge.golden import (
    GoldenLabel,
    evaluate_golden,
    evaluate_golden_file,
)
from aspire.sim.cap.knowledge.experiment import Observation, build_report, compile_treatment
from aspire.sim.cap.knowledge.forest import descendants, validate_forest
from aspire.sim.cap.knowledge.index import index_metadata, rebuild_index
from aspire.sim.cap.knowledge.ingest import build_instance
from aspire.sim.cap.knowledge.integrity import validate_repository
from aspire.sim.cap.knowledge.lifecycle import invalidate, principle_metrics
from aspire.sim.cap.knowledge.maintenance import audit_maintenance, simulate_maintenance
from aspire.sim.cap.knowledge.models import (
    CanonicalSkill,
    Checkpoint,
    ConsolidationPolicy,
    KnowledgeManifest,
    ModelError,
    OverlayEdge,
    Principle,
    PrincipleAbstraction,
    PrincipleQualityPolicy,
    Scope,
    SkillCodeInstance,
    TaskContext,
    VerticalTree,
    model_to_dict,
)
from aspire.sim.cap.knowledge.predicates import evaluate
from aspire.sim.cap.knowledge.overlay_review import (
    promote_overlay_edge,
    review_overlay_edge,
)
from aspire.sim.cap.knowledge.placement import analyze_placement
from aspire.sim.cap.knowledge.projection import lineage_view, overlay_view, vertical_forest
from aspire.sim.cap.knowledge.repository import KnowledgeRepository, RepositoryConflict
from aspire.sim.cap.knowledge.review import (
    bind_principle_review,
    promote_principle,
    review_principle,
    validate_principle_review_content,
)
from aspire.sim.cap.knowledge.review_artifacts import (
    finalize_leave_family_out_report,
    validate_leave_family_out_report,
)
from aspire.sim.cap.knowledge.repetition import (
    assess_pair,
    audit_principle_repetition,
    audit_repetition,
)
from aspire.sim.cap.knowledge.retrieval import compile_portfolio
from aspire.sim.cap.knowledge.serialization import (
    content_hash,
    sha256_file,
    write_structured_atomic,
)
from aspire.sim.cap.knowledge.stress import (
    STRESS_KINDS,
    audit_stress_snapshot,
    build_stress_corpus,
)
from aspire.sim.cap.knowledge.tree_review import (
    prepare_tree_review,
    validate_tree_review,
)


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
    def test_principle_v1_requires_reviewed_migration(self):
        with self.assertRaisesRegex(ModelError, "historical evidence"):
            Principle.from_dict({"schema_version": 1})

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
                abstraction=PrincipleAbstraction(
                    common_core="preserve clearance",
                    preserved_variations=("path shape varies",),
                ),
                quality_policy=PrincipleQualityPolicy(
                    min_supporting_skills=3,
                    min_task_families=2,
                    max_exception_rate=0.3,
                    max_operational_fanout=12,
                ),
                status="validated",
                review_required=True,
            )

    def test_validated_principle_requires_diverse_support_and_exception_review(self):
        with self.assertRaisesRegex(ModelError, "2 task families"):
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
                abstraction=PrincipleAbstraction(
                    common_core="preserve clearance",
                    preserved_variations=("path shape varies",),
                ),
                quality_policy=PrincipleQualityPolicy(
                    min_supporting_skills=3,
                    min_task_families=2,
                    max_exception_rate=0.3,
                    max_operational_fanout=12,
                ),
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
        self.assertFalse(report["ready"], "unbound labels cannot enter the golden gate")
        self.assertFalse(report["labels_hash_locked"])
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
        self.assertTrue(principle.abstraction.common_core)
        self.assertEqual(
            len(principle.abstraction.preserved_variations),
            len(skills),
        )
        self.assertEqual(principle.quality_policy.min_supporting_skills, 3)

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
                "abstraction": asdict(proposal.abstraction),
                "quality_policy": asdict(proposal.quality_policy),
                "exceptions": [
                    {
                        "id": "continuous-contact",
                        "when": {"fact": "task.continuous_contact", "op": "eq", "value": True},
                        "response": "hold contact",
                    }
                ],
                "counterexample_report": "reports/counterexamples.yaml",
                "counterexample_report_hash": "counterexample-report-hash",
                "counterexample_artifact_hash": "counterexample-artifact-hash",
                "leave_one_family_out_report": "reports/lofo.yaml",
                "leave_one_family_out_report_hash": "lofo-report-hash",
                "leave_one_family_out_artifact_hash": "lofo-artifact-hash",
                "compression_report": "reports/compression.yaml",
                "compression_report_hash": "compression-report-hash",
                "compression_artifact_hash": "compression-artifact-hash",
            },
            version="1.1.0",
        )
        self.assertEqual(candidate.status, "candidate")
        with self.assertRaisesRegex(
            ModelError,
            "exceptions require id, when, and response",
        ):
            replace(
                candidate,
                exceptions=(
                    {
                        "id": "continuous-contact",
                        "when": {
                            "fact": "task.continuous_contact",
                            "op": "eq",
                            "value": True,
                        },
                    },
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "exceptions require id, when, and response",
        ):
            validate_principle_review_content(
                {
                    "exceptions": [
                        {
                            "id": "continuous-contact",
                            "when": {
                                "fact": "task.continuous_contact",
                                "op": "eq",
                                "value": True,
                            },
                        }
                    ]
                }
            )
        self.assertEqual(
            candidate.abstraction.common_core,
            proposal.abstraction.common_core,
        )
        strict_candidate = replace(
            candidate,
            quality_policy=replace(
                candidate.quality_policy,
                min_supporting_skills=4,
            ),
        )
        with self.assertRaisesRegex(ValueError, "support policy"):
            promote_principle(strict_candidate, version="1.2.0")
        validated = promote_principle(candidate, version="1.2.0")
        self.assertEqual(validated.status, "validated")
        self.assertFalse(validated.review_required)

    def test_principle_review_cannot_weaken_quality_policy(self):
        skills = [make_skill(index) for index in range(1, 4)]
        proposal = propose_principle(
            skills,
            checkpoint_for_skills(*skills),
            ConsolidationPolicy(),
        )
        review = {
            "reviewer": "reviewer-a",
            "reviewed_at": "2026-01-02T00:00:00+00:00",
            "when": {"fact": "state.object_grasped", "op": "eq", "value": True},
            "decision": "preserve obstacle clearance",
            "invariant": "a grasped object needs a collision-free swept volume",
            "falsifiers": ["clearance does not change collision rate"],
            "exceptions": [
                {
                    "id": "continuous-contact",
                    "when": {
                        "fact": "task.continuous_contact",
                        "op": "eq",
                        "value": True,
                    },
                    "response": "hold contact",
                }
            ],
            "abstraction": asdict(proposal.abstraction),
            "quality_policy": {
                **asdict(proposal.quality_policy),
                "max_operational_fanout": 100,
            },
            "counterexample_report": "reports/counterexamples.yaml",
            "counterexample_report_hash": "counterexample-report-hash",
            "counterexample_artifact_hash": "counterexample-artifact-hash",
            "leave_one_family_out_report": "reports/lofo.yaml",
            "leave_one_family_out_report_hash": "lofo-report-hash",
            "leave_one_family_out_artifact_hash": "lofo-artifact-hash",
            "compression_report": "reports/compression.yaml",
            "compression_report_hash": "compression-report-hash",
            "compression_artifact_hash": "compression-artifact-hash",
        }
        with self.assertRaisesRegex(ValueError, "cannot weaken"):
            review_principle(proposal, review, version="1.1.0")

    def test_principle_compression_report_rejects_verbose_abstraction(self):
        skills = [make_skill(index) for index in range(1, 4)]
        proposal = propose_principle(
            skills,
            checkpoint_for_skills(*skills),
            ConsolidationPolicy(),
        )
        report = build_compression_report(
            proposal,
            {
                "title": "Verbose abstraction",
                "summary": "repeated filler " * 200,
                "when": {},
                "decision": "move safely",
                "invariant": "preserve clearance",
                "abstraction": {
                    "common_core": "preserve clearance",
                    "preserved_variations": ["path geometry"],
                },
            },
            skills,
        )
        self.assertFalse(report["passed"])
        self.assertGreater(report["principle_tokens"], report["direct_child_tokens"])

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

    def test_leave_family_out_report_requires_every_family_and_valid_hash(self):
        skills = [make_skill(index) for index in range(1, 4)]
        proposal = propose_principle(
            skills,
            checkpoint_for_skills(*skills),
            ConsolidationPolicy(),
        )
        with self.assertRaisesRegex(ValueError, "exactly the principle task families"):
            finalize_leave_family_out_report(
                proposal,
                {
                    "reviewer": "reviewer-a",
                    "reviewed_at": "2026-01-02T00:00:00+00:00",
                    "family_results": {
                        proposal.scope.task_families[0]: {
                            "passed": True,
                            "evaluated_task_ids": ["task-one"],
                            "supporting_skill_ids": [skills[0].id],
                        }
                    },
                },
            )
        report = finalize_leave_family_out_report(
            proposal,
            {
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-02T00:00:00+00:00",
                "family_results": {
                    family: {
                        "passed": True,
                        "evaluated_task_ids": [f"task-{family}"],
                        "supporting_skill_ids": [skill.id for skill in skills],
                    }
                    for family in proposal.scope.task_families
                },
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lofo.yaml"
            write_structured_atomic(path, report)
            self.assertEqual(
                validate_leave_family_out_report(path, proposal)["report_hash"],
                report["report_hash"],
            )


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
        proposal = self.make_principle_proposal(self.skills, version="0.8.0")
        self.principle = self.review_and_promote_principle(
            proposal,
            candidate_version="0.9.0",
            final_version="1.0.0",
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
        self.promote_tree(self.tree)

    def make_principle_proposal(
        self,
        skills: list[CanonicalSkill],
        *,
        version: str,
    ) -> Principle:
        checkpoint = self.repository.load_checkpoint("snapshot-n3")
        audit = audit_principle_repetition(
            skills,
            checkpoint,
            ConsolidationPolicy(),
        )
        self.assertTrue(audit.accepted, audit.rejection_reasons)
        return Principle(
            id="principle.transport.preserve-clearance",
            version=version,
            vertical_capability="transport",
            title="Draft transport invariant",
            summary="Repeated transport skills require contrastive review.",
            when={"review_required": True},
            decision_mode="prefer",
            decision="[review required]",
            invariant="[review required]",
            expected_effects=(),
            exceptions=(),
            falsifiers=(),
            child_ids=tuple(sorted(value.id for value in skills)),
            abstraction=PrincipleAbstraction(
                common_core="preserve safe transport state",
                preserved_variations=tuple(
                    f"{value.id} retains its operation-specific path"
                    for value in skills
                ),
                excluded_details=("task-specific target poses",),
            ),
            quality_policy=PrincipleQualityPolicy(
                min_supporting_skills=3,
                min_task_families=2,
                max_exception_rate=0.3,
                max_operational_fanout=12,
            ),
            scope=Scope(
                task_families=tuple(
                    sorted(
                        {
                            family
                            for skill in skills
                            for family in skill.scope.task_families
                        }
                    )
                )
            ),
            status="proposal",
            review_required=True,
            provenance={
                "checkpoint_id": "snapshot-n3",
                "proposal_method": "canonical-skill-repetition-audit",
                "canonical_repetition_audit": asdict(audit),
                "canonical_repetition_audit_hash": audit.content_hash,
                "canonical_skill_versions": audit.skill_versions,
            },
        )

    def review_and_promote_principle(
        self,
        proposal: Principle,
        *,
        candidate_version: str,
        final_version: str,
    ) -> Principle:
        self.repository.save_principle(proposal)
        counterexample = search_counterexamples(self.repository, proposal)
        counterexample_hash = content_hash(counterexample)
        self.repository.save_audit(
            "principle-counterexample",
            counterexample_hash,
            counterexample,
        )
        lofo = finalize_leave_family_out_report(
            proposal,
            {
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-01-02T00:00:00+00:00",
                "family_results": {
                    family: {
                        "passed": True,
                        "evaluated_task_ids": [
                            value.task
                            for value in self.instances
                            if value.task_family == family
                        ],
                        "supporting_skill_ids": list(proposal.child_ids),
                        "notes": "held-family behavior remained grounded",
                    }
                    for family in proposal.scope.task_families
                },
            },
        )
        lofo_hash = content_hash(lofo)
        self.repository.save_audit("principle-lofo", lofo_hash, lofo)
        review_payload = {
            "reviewer": "reviewer-a",
            "reviewed_at": "2026-01-02T00:00:00+00:00",
            "title": "Preserve clearance during transport",
            "summary": "Keep grasp and clearance.",
            "when": {
                "fact": "state.object_grasped",
                "op": "eq",
                "value": True,
            },
            "decision_mode": "require",
            "decision": "use a collision-safe path",
            "invariant": "grasped objects require clearance",
            "expected_effects": [],
            "exceptions": [
                {
                    "id": "continuous-contact",
                    "when": {
                        "fact": "task.continuous_contact",
                        "op": "eq",
                        "value": True,
                    },
                    "response": "hold contact",
                }
            ],
            "falsifiers": [
                "clearance-preserving patterns do not reduce collisions"
            ],
            "abstraction": {
                "common_core": "preserve grasp clearance",
                "preserved_variations": ["path geometry", "motion backend"],
                "excluded_details": ["target pose"],
            },
            "quality_policy": asdict(proposal.quality_policy),
            "counterexample_report": (
                "proposals/principle-counterexample/"
                f"{counterexample_hash}.yaml"
            ),
            "counterexample_report_hash": counterexample["report_hash"],
            "counterexample_artifact_hash": counterexample_hash,
            "counterexample_dispositions": validate_counterexample_dispositions(
                counterexample, {}
            ),
            "leave_one_family_out_report": (
                f"proposals/principle-lofo/{lofo_hash}.yaml"
            ),
            "leave_one_family_out_report_hash": lofo["report_hash"],
            "leave_one_family_out_artifact_hash": lofo_hash,
        }
        compression = build_compression_report(
            proposal,
            review_payload,
            supporting_skills(self.repository, proposal),
        )
        self.assertTrue(compression["passed"], compression)
        compression_hash = content_hash(compression)
        self.repository.save_audit(
            "principle-compression",
            compression_hash,
            compression,
        )
        review_payload.update(
            {
                "compression_report": (
                    f"proposals/principle-compression/{compression_hash}.yaml"
                ),
                "compression_report_hash": compression["report_hash"],
                "compression_artifact_hash": compression_hash,
            }
        )
        review = bind_principle_review(proposal, review_payload)
        candidate = review_principle(
            proposal,
            review,
            version=candidate_version,
        )
        self.repository.save_audit(
            "principle-review",
            str(candidate.provenance["review_artifact_hash"]),
            review,
        )
        self.repository.save_principle(candidate)
        principle = promote_principle(candidate, version=final_version)
        self.repository.save_principle(principle)
        self.repository.append_evidence(
            {
                "event": "knowledge.validated",
                "subject": principle.id,
                "version": principle.version,
                "principle_hash": content_hash(model_to_dict(principle)),
                "candidate_version": principle.provenance["candidate_version"],
                "candidate_hash": principle.provenance["candidate_hash"],
                "review_artifact_hash": principle.provenance[
                    "review_artifact_hash"
                ],
                "checkpoint_id": principle.provenance["checkpoint_id"],
                "at": "2026-01-02T00:00:00+00:00",
                "reviewer": "reviewer-a",
            },
            stream="lifecycle",
        )
        return principle

    def tearDown(self):
        self.temporary.cleanup()

    def promote_tree(self, tree: VerticalTree) -> None:
        nodes = set(tree.parent_by_child) | (
            set(tree.parent_by_child.values()) - {tree.structural_root}
        )
        skills = {
            value.id: value
            for value in self.repository.list_skills()
            if value.id in nodes
        }
        principles = {
            value.id: value
            for value in self.repository.list_principles()
            if value.id in nodes
        }
        base_manifest = KnowledgeManifest(
            id="tree-review-base",
            version=tree.version,
            checkpoint_id=tree.checkpoint_id,
            skill_versions={value.id: value.version for value in skills.values()},
            principle_versions={
                value.id: value.version for value in principles.values()
            },
            tree_versions={},
            edge_versions={},
            created_at="2026-01-02T00:00:00+00:00",
            source_partition="development",
        )
        self.repository.save_manifest(base_manifest)
        placement_paths = {}
        for principle in principles.values():
            report = analyze_placement(
                self.repository,
                principle,
                tree,
                tree.parent_by_child[principle.id],
            )
            path = Path(self.temporary.name) / (
                f"placement-{tree.version}-{principle.id}.yaml"
            )
            write_structured_atomic(path, report)
            placement_paths[principle.id] = str(path)
        raw_review = {
            "decision": "accept",
            "reviewer": "tree-reviewer-a",
            "reviewed_at": "2026-01-03T00:00:00+00:00",
            "rationale": "primary parents, coverage, and cycles were reviewed",
            "tree_hash": content_hash(asdict(tree)),
            "checkpoint_id": tree.checkpoint_id,
            "manifest_id": base_manifest.id,
            "manifest_version": base_manifest.version,
            "manifest_hash": content_hash(asdict(base_manifest)),
            "placement_reports": placement_paths,
        }
        review = prepare_tree_review(
            self.repository, tree, base_manifest, raw_review
        )
        review_hash = content_hash(review)
        self.repository.save_audit("tree-review", review_hash, review)
        reviewed_event = {
            "subject": tree.id,
            "version": tree.version,
            "tree_hash": content_hash(asdict(tree)),
            "checkpoint_id": tree.checkpoint_id,
            "manifest_id": base_manifest.id,
            "manifest_version": base_manifest.version,
            "manifest_hash": content_hash(asdict(base_manifest)),
            "review_artifact_hash": review_hash,
            "reviewer": review["reviewer"],
        }
        self.repository.append_evidence(
            {"event": "knowledge.tree-reviewed", **reviewed_event},
            stream="lifecycle",
        )
        validate_tree_review(self.repository, tree, review_hash)
        self.repository.append_evidence(
            {"event": "knowledge.tree-validated", **reviewed_event},
            stream="lifecycle",
        )

    def promote_edge(
        self, proposal: OverlayEdge, *, record_event: bool = True
    ) -> OverlayEdge:
        self.repository.save_edge(proposal)
        manifest = KnowledgeManifest(
            id="overlay-review-base",
            version="1.0.0",
            checkpoint_id="snapshot-n3",
            skill_versions={value.id: value.version for value in self.skills},
            principle_versions={self.principle.id: self.principle.version},
            tree_versions={self.tree.id: self.tree.version},
            edge_versions={},
            created_at="2026-01-02T00:00:00+00:00",
            source_partition="development",
        )
        self.repository.save_manifest(manifest)
        review = {
            "decision": "accept",
            "reviewer": "overlay-reviewer-a",
            "reviewed_at": "2026-01-03T00:00:00+00:00",
            "rationale": "endpoint revisions and guarded relation were reviewed",
            "proposal_hash": content_hash(asdict(proposal)),
            "checkpoint_id": "snapshot-n3",
            "manifest_id": manifest.id,
            "manifest_version": manifest.version,
            "manifest_hash": content_hash(asdict(manifest)),
            "kind": proposal.kind,
            "source_id": proposal.source_id,
            "source_version": proposal.source_version,
            "target_id": proposal.target_id,
            "target_version": proposal.target_version,
            "guard": proposal.guard,
        }
        candidate = review_overlay_edge(
            proposal, review, manifest, version="1.1.0"
        )
        self.repository.save_audit(
            "overlay-review",
            str(candidate.provenance["review_artifact_hash"]),
            review,
        )
        self.repository.save_edge(candidate)
        edge = promote_overlay_edge(candidate, version="1.2.0")
        self.repository.save_edge(edge)
        if record_event:
            self.repository.append_evidence(
                {
                    "event": "knowledge.edge-validated",
                    "subject": edge.id,
                    "version": edge.version,
                    "candidate_version": edge.provenance["candidate_version"],
                    "source_id": edge.source_id,
                    "source_version": edge.source_version,
                    "target_id": edge.target_id,
                    "target_version": edge.target_version,
                    "checkpoint_id": edge.provenance["checkpoint_id"],
                    "manifest_id": edge.provenance["manifest_id"],
                    "manifest_version": edge.provenance["manifest_version"],
                    "manifest_hash": edge.provenance["manifest_hash"],
                    "review_artifact_hash": edge.provenance[
                        "review_artifact_hash"
                    ],
                },
                stream="lifecycle",
            )
        return edge

    def test_forest_validation_and_descendants(self):
        report = validate_forest([self.tree], self.skills, [self.principle], [])
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(set(descendants(self.tree, self.principle.id)), {v.id for v in self.skills})

    def test_repository_integrity_covers_lineage_and_support(self):
        report = validate_repository(self.repository)
        self.assertTrue(report.ok, report.issues)

    def test_principle_promotion_event_rejects_same_version_content_tampering(self):
        tampered = replace(
            self.principle,
            title="Tampered principle content at the same semantic version",
        )
        path = (
            self.repository.root
            / "principles"
            / self.principle.id
            / f"{self.principle.version}.yaml"
        )
        write_structured_atomic(path, asdict(tampered))
        context = TaskContext(
            task_id="task-tamper-gate",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertTrue(portfolio.skill_ids)
        self.assertTrue(portfolio.fallback_used)
        issue_codes = {issue.code for issue in validate_repository(self.repository).issues}
        self.assertIn("unrecorded-principle-promotion", issue_codes)

    def test_principle_promotion_rejects_tampered_review_artifact(self):
        review_hash = str(self.principle.provenance["review_artifact_hash"])
        review = self.repository.load_audit("principle-review", review_hash)
        path = (
            self.repository.root
            / "proposals"
            / "principle-review"
            / f"{review_hash}.yaml"
        )
        write_structured_atomic(
            path,
            {**review, "decision": "tampered after review"},
        )
        context = TaskContext(
            task_id="task-review-tamper-gate",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertTrue(portfolio.skill_ids)
        self.assertTrue(portfolio.fallback_used)
        issue_codes = {issue.code for issue in validate_repository(self.repository).issues}
        self.assertIn("unrecorded-principle-promotion", issue_codes)

    def test_principle_promotion_rejects_tampered_compression_artifact(self):
        compression_hash = str(
            self.principle.provenance["compression_artifact_hash"]
        )
        compression = self.repository.load_audit(
            "principle-compression",
            compression_hash,
        )
        path = (
            self.repository.root
            / "proposals"
            / "principle-compression"
            / f"{compression_hash}.yaml"
        )
        write_structured_atomic(
            path,
            {**compression, "principle_tokens": 999999},
        )
        context = TaskContext(
            task_id="task-compression-tamper-gate",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertFalse(portfolio.principle_ids)
        self.assertTrue(portfolio.skill_ids)
        self.assertTrue(portfolio.fallback_used)

    def test_new_tree_proposal_does_not_shadow_active_revision(self):
        proposed_revision = replace(self.tree, version="2.0.0")
        self.repository.save_tree(proposed_revision)
        projection = vertical_forest(self.repository)
        self.assertEqual(projection["trees"][0]["tree_version"], self.tree.version)

    def test_new_principle_proposal_does_not_shadow_active_revision(self):
        proposal = self.make_principle_proposal(self.skills, version="2.0.0")
        self.repository.save_principle(proposal)
        context = TaskContext(
            task_id="task-principle-proposal-gate",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={"state": {"object_grasped": True}},
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertEqual(portfolio.principle_ids, (self.principle.id,))
        self.assertEqual(
            portfolio.node_versions[f"principle:{self.principle.id}"],
            "1.0.0",
        )

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
        self.assertTrue(portfolio.skill_ids)
        self.assertTrue(portfolio.fallback_used)
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

    def test_maintenance_simulation_compares_search_surfaces_without_mutation(self):
        scenarios = Path(self.temporary.name) / "maintenance-scenarios.yaml"
        write_structured_atomic(
            scenarios,
            {
                "scenarios": [
                    {
                        "id": "remove-first-transport-pattern",
                        "target_ref": self.skills[0].id,
                        "expected_skill_ids": [self.skills[0].id],
                        "expected_principle_ids": [self.principle.id],
                        "expected_task_ids": ["task-1", "task-2"],
                        "measured_review_minutes": {"B": 8.0, "E": 3.0},
                    }
                ]
            },
        )

        result = simulate_maintenance(self.repository, scenarios)

        comparison = result["scenarios"][0]["treatments"]
        self.assertEqual(comparison["B"]["nodes_reviewed"], 3)
        self.assertEqual(comparison["E"]["nodes_reviewed"], 2)
        self.assertEqual(comparison["E"]["invalidation_recall"], 1.0)
        self.assertEqual(comparison["E"]["false_affected_nodes"], 0)
        self.assertFalse(result["mutation_performed"])

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

    def test_tree_rejects_parent_node_without_its_own_primary_parent(self):
        tree = replace(
            self.tree,
            parent_by_child={self.skills[0].id: self.principle.id},
        )
        report = validate_forest([tree], self.skills, [self.principle], [])
        self.assertIn("missing-primary-parent", {issue.code for issue in report.issues})

    def test_topdown_limits_children_per_principle(self):
        extra = replace(
            self.skills[0],
            id="skill.transport.extra",
            title="Extra transport pattern",
        )
        self.repository.save_skill(extra)
        proposal = self.make_principle_proposal(
            [*self.skills, extra],
            version="1.0.1",
        )
        revised_principle = self.review_and_promote_principle(
            proposal,
            candidate_version="1.0.2",
            final_version="1.1.0",
        )
        revised_tree = replace(
            self.tree,
            version="1.1.0",
            parent_by_child={
                **self.tree.parent_by_child,
                extra.id: revised_principle.id,
            },
        )
        self.repository.save_tree(revised_tree)
        self.promote_tree(revised_tree)
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
            source_version=self.skills[0].version,
            target_id="skill.localization.missing",
            target_version="1.0.0",
            provenance={"checkpoint_id": "snapshot-n3"},
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
            source_version=self.skills[0].version,
            target_id=self.skills[1].id,
            target_version=self.skills[1].version,
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        edge = self.promote_edge(edge)
        projection = overlay_view(self.repository)
        self.assertEqual(
            projection["outgoing_by_node"][self.skills[0].id], [edge.id]
        )
        self.assertEqual(
            projection["incoming_by_node"][self.skills[1].id], [edge.id]
        )

    def test_new_overlay_proposal_does_not_shadow_active_revision(self):
        proposal = OverlayEdge(
            id="edge.transport.active-while-revising",
            version="1.0.0",
            kind="can-follow",
            source_id=self.skills[0].id,
            source_version=self.skills[0].version,
            target_id=self.skills[1].id,
            target_version=self.skills[1].version,
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        active_edge = self.promote_edge(proposal)
        next_proposal = replace(
            proposal,
            version="2.0.0",
            rationale="proposed change awaiting a fresh review",
        )
        self.repository.save_edge(next_proposal)
        projection = overlay_view(self.repository)
        self.assertEqual(
            [(edge["id"], edge["version"]) for edge in projection["edges"]],
            [(active_edge.id, active_edge.version)],
        )

    def test_overlay_proposal_is_not_actor_visible(self):
        edge = OverlayEdge(
            id="edge.transport.proposal-exception",
            version="1.0.0",
            kind="exception-to",
            source_id=self.skills[0].id,
            source_version=self.skills[0].version,
            target_id=self.principle.id,
            target_version=self.principle.version,
            guard={"fact": "task.cross_tree_exception", "op": "eq", "value": True},
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        self.repository.save_edge(edge)
        self.assertFalse(overlay_view(self.repository)["edges"])
        context = TaskContext(
            task_id="task-proposal-gate",
            suite="libero",
            task_language="transport with an unreviewed proposed exception",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={
                "state": {"object_grasped": True},
                "task": {
                    "continuous_contact": False,
                    "cross_tree_exception": True,
                },
            },
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertEqual(portfolio.principle_ids, (self.principle.id,))
        self.assertFalse(portfolio.overlay_edge_ids)
        database = Path(self.temporary.name) / "proposal-gate.sqlite3"
        rebuild_index(self.repository, database, checkpoint_id="snapshot-n3")
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM overlay_edges").fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_overlay_promotion_requires_an_exact_lifecycle_event(self):
        proposal = OverlayEdge(
            id="edge.transport.unrecorded-exception",
            version="1.0.0",
            kind="exception-to",
            source_id=self.skills[0].id,
            source_version=self.skills[0].version,
            target_id=self.principle.id,
            target_version=self.principle.version,
            guard={"fact": "task.cross_tree_exception", "op": "eq", "value": True},
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        edge = self.promote_edge(proposal, record_event=False)
        self.repository.append_evidence(
            {
                "event": "knowledge.edge-validated",
                "subject": edge.id,
                "version": edge.version,
                "candidate_version": edge.provenance["candidate_version"],
                "source_id": edge.source_id,
                "source_version": edge.source_version,
                "target_id": edge.target_id,
                "target_version": edge.target_version,
                "checkpoint_id": edge.provenance["checkpoint_id"],
                "manifest_id": edge.provenance["manifest_id"],
                "manifest_version": edge.provenance["manifest_version"],
                "manifest_hash": "wrong-manifest-hash",
                "review_artifact_hash": edge.provenance["review_artifact_hash"],
            },
            stream="lifecycle",
        )
        self.assertFalse(overlay_view(self.repository)["edges"])
        issue_codes = {issue.code for issue in validate_repository(self.repository).issues}
        self.assertIn("unrecorded-overlay-promotion", issue_codes)

    def test_counterexample_search_records_scope_conflicts_and_hash(self):
        edge = OverlayEdge(
            id="edge.transport.contradiction",
            version="1.0.0",
            kind="contradicts",
            source_id=self.skills[0].id,
            source_version=self.skills[0].version,
            target_id=self.skills[1].id,
            target_version=self.skills[1].version,
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        self.repository.save_edge(edge)
        report = search_counterexamples(self.repository, self.principle)
        self.assertEqual(report["high_severity_candidate_ids"], ["counterexample-0001"])
        self.assertEqual(report["candidates"][0]["kind"], "existing-contradiction")
        with self.assertRaisesRegex(ValueError, "lack disposition"):
            validate_counterexample_dispositions(report, {})
        self.assertIn(
            "counterexample-0001",
            validate_counterexample_dispositions(
                report,
                {
                    "counterexample-0001": {
                        "decision": "not-applicable",
                        "rationale": "the edge guard excludes this proposal scope",
                    }
                },
            ),
        )
        path = Path(self.temporary.name) / "counterexamples.yaml"
        write_structured_atomic(path, report)
        self.assertEqual(
            validate_counterexample_report(path, self.principle)["report_hash"],
            report["report_hash"],
        )
        write_structured_atomic(
            path,
            {**report, "no_result_boundary": "tampered"},
        )
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_counterexample_report(path, self.principle)

    def test_guarded_overlay_exception_blocks_target_branch(self):
        edge = OverlayEdge(
            id="edge.transport.contact-exception",
            version="1.0.0",
            kind="exception-to",
            source_id=self.skills[0].id,
            source_version=self.skills[0].version,
            target_id=self.principle.id,
            target_version=self.principle.version,
            guard={"fact": "task.cross_tree_exception", "op": "eq", "value": True},
            provenance={"checkpoint_id": "snapshot-n3"},
        )
        edge = self.promote_edge(edge)
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
        exclusion = next(
            item
            for item in portfolio.exclusions
            if item["reason"] == f"overlay-exception:{edge.id}"
        )
        self.assertEqual(exclusion["guidance"], edge.rationale)
        self.assertIn(f"Guidance: {edge.rationale}", portfolio.markdown)

    def test_guarded_overlay_contradiction_exposes_reviewed_guidance(self):
        edge = self.promote_edge(
            OverlayEdge(
                id="edge.transport.active-contradiction",
                version="1.0.0",
                kind="contradicts",
                source_id=self.skills[0].id,
                source_version=self.skills[0].version,
                target_id=self.skills[1].id,
                target_version=self.skills[1].version,
                guard={
                    "fact": "task.use_guarded_alternative",
                    "op": "eq",
                    "value": True,
                },
                provenance={"checkpoint_id": "snapshot-n3"},
            )
        )
        context = TaskContext(
            task_id="task-conflict",
            suite="libero",
            task_language="transport with a guarded alternative",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={
                "state": {"object_grasped": True},
                "task": {
                    "continuous_contact": False,
                    "use_guarded_alternative": True,
                },
            },
        )
        portfolio = compile_portfolio(self.repository, "snapshot-n3", context)
        self.assertIn(self.skills[0].id, portfolio.skill_ids)
        self.assertNotIn(self.skills[1].id, portfolio.skill_ids)
        exclusion = next(
            item
            for item in portfolio.exclusions
            if item["reason"] == f"overlay-conflict:{edge.id}"
        )
        self.assertEqual(exclusion["guidance"], edge.rationale)
        self.assertIn(f"Guidance: {edge.rationale}", portfolio.markdown)

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

    def test_portfolio_fails_closed_when_fixed_content_exceeds_budget(self):
        context = TaskContext(
            task_id="task-tiny-budget",
            suite="libero",
            task_language="transport the grasped object",
            task_family="pick-place",
            vertical_capabilities=("transport",),
            facts={
                "state": {"object_grasped": True},
                "task": {"continuous_contact": False},
            },
            token_budget=1,
        )
        with self.assertRaisesRegex(
            ValueError,
            "cannot fit governing principles and exclusions",
        ):
            compile_portfolio(self.repository, "snapshot-n3", context)
        for treatment in "AB":
            with self.subTest(treatment=treatment), self.assertRaisesRegex(
                ValueError,
                "cannot fit the token budget",
            ):
                compile_treatment(
                    self.repository,
                    "snapshot-n3",
                    context,
                    treatment,
                )

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
        exclusion = next(
            item
            for item in portfolio.exclusions
            if item["reason"] == "exception:continuous-contact"
        )
        self.assertEqual(
            exclusion["guidance"],
            "hold contact",
        )
        self.assertIn(
            "Guidance: hold contact",
            portfolio.markdown,
        )

    def test_golden_items_bind_manifest_children_and_two_reviewers(self):
        manifest = KnowledgeManifest(
            id="golden-manifest",
            version="1.0.0",
            checkpoint_id="snapshot-n3",
            skill_versions={value.id: value.version for value in self.skills},
            principle_versions={self.principle.id: self.principle.version},
            tree_versions={self.tree.id: self.tree.version},
            edge_versions={},
            created_at="2026-01-03T00:00:00+00:00",
        )
        self.repository.save_manifest(manifest)
        evidence = Path(self.temporary.name) / "golden-evidence.txt"
        evidence.write_text("reviewable execution evidence\n")
        labels = []
        cases = [
            (polarity, "principle-relevance", self.principle.id)
            for polarity in ("support", "hard-negative", "exception", "falsifier")
        ]
        cases.append(("support", "child-relation", self.skills[0].id))
        for polarity, subject_kind, subject_id in cases:
            for reviewer, score in (("reviewer-a", 0.9), ("reviewer-b", 0.8)):
                labels.append(
                    GoldenLabel(
                        principle_id=self.principle.id,
                        principle_version=self.principle.version,
                        case_id=f"{subject_kind}-{polarity}",
                        subject_kind=subject_kind,
                        subject_id=subject_id,
                        task_family="pick-place",
                        reviewer=reviewer,
                        dimension="faithfulness",
                        score=score,
                        polarity=polarity,
                        checkpoint_id="snapshot-n3",
                        manifest_id="golden-manifest@1.0.0",
                        evidence_path=str(evidence.resolve()),
                        evidence_hash=sha256_file(evidence),
                    )
                )
        label_path = Path(self.temporary.name) / "golden.jsonl"
        label_path.write_text(
            "\n".join(
                json.dumps(asdict(label)) for label in labels
            )
            + "\n"
        )

        report = evaluate_golden_file(
            label_path, self.repository, manifest, faithfulness_gate=0.75
        )

        self.assertTrue(report["independent_item_reviews_complete"])
        self.assertTrue(report["labels_hash_locked"])
        self.assertEqual(report["binding"]["manifest_id"], "golden-manifest@1.0.0")
        self.assertFalse(report["ready"], "one principle is below the 10-item gate")

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
        self.assertFalse(
            report["coverage"]["organic_and_synthetic_reported_separately"]
        )
        self.assertEqual(
            report["report_hash"],
            content_hash(
                {key: value for key, value in report.items() if key != "report_hash"}
            ),
        )
        self.assertGreater(report["results"]["organic:A"]["scale_slopes"]["context_tokens"], 0)

    def test_experiment_report_rejects_unbound_frozen_status(self):
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
                            unsupported_principle_escape=0.0,
                            exception_hard_violation_escape=0.0,
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
        self.assertEqual(report["claim_status"], "not-evaluable")
        self.assertTrue(report["heldout_success_noninferior_to_B"]["D"])
        self.assertTrue(report["runtime_gates"]["passed"])
        self.assertFalse(report["coverage"]["preregistration_frozen"])
        self.assertTrue(report["coverage"]["fairness_violations"])

    def test_stress_corpus_is_deterministic_and_never_evidence_eligible(self):
        first = build_stress_corpus(
            self.repository, "snapshot-n3", [1, 4], seed=11
        )
        second = build_stress_corpus(
            self.repository, "snapshot-n3", [1, 4], seed=11
        )
        self.assertEqual(first["corpus_hash"], second["corpus_hash"])
        self.assertEqual(first["snapshots"][1]["record_count"], 24)
        first_scale_ids = first["snapshots"][0]["record_ids"]
        self.assertEqual(
            first_scale_ids,
            first["snapshots"][1]["record_ids"][: len(first_scale_ids)],
        )
        self.assertEqual(
            set(first["snapshots"][1]["kind_counts"]), set(STRESS_KINDS)
        )
        self.assertTrue(
            all(
                record["synthetic"] and not record["evidence_eligible"]
                for snapshot in first["snapshots"]
                for record in snapshot["records"]
            )
        )
        stale = next(
            record
            for record in first["snapshots"][1]["records"]
            if record["kind"] == "stale-api-pattern"
        )
        self.assertTrue(any(value.startswith("legacy_") for value in stale["api_calls"]))
        different = next(
            record
            for record in first["snapshots"][1]["records"]
            if record["kind"] == "same-principle-different-implementation"
        )
        source = next(
            value
            for value in self.instances
            if value.id == different["source_instance_id"]
        )
        self.assertNotEqual(different["ast_fingerprint"], source.ast_fingerprint)

        audit = audit_stress_snapshot(first, 4, ConsolidationPolicy())
        self.assertFalse(audit["evidence_eligible"])
        self.assertFalse(audit["promotion_eligible"])
        self.assertEqual(audit["record_count"], 24)
        self.assertTrue(audit["classification_counts"])
        tampered = {
            **first,
            "snapshots": [
                first["snapshots"][0],
                {
                    **first["snapshots"][1],
                    "record_count": 23,
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "corpus hash mismatch"):
            audit_stress_snapshot(tampered, 4, ConsolidationPolicy())


if __name__ == "__main__":
    unittest.main()
