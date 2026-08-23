# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prefix-stable controlled-growth corpora that cannot become evidence."""

from __future__ import annotations

import ast
import random
from collections import Counter
from dataclasses import asdict
from typing import Any

from .checkpoints import instances_at_checkpoint
from .fingerprint import fingerprint_code
from .models import Checkpoint, ConsolidationPolicy, SkillCodeInstance
from .repetition import audit_repetition
from .repository import KnowledgeRepository
from .serialization import content_hash


STRESS_KINDS = (
    "paraphrase-duplicate",
    "same-principle-different-implementation",
    "narrow-scope-specialization",
    "contradictory-advice",
    "stale-api-pattern",
    "irrelevant-domain-distractor",
    "rare-safety-critical-exception",
    "over-broad-false-principle",
)

EXPECTED_RELATIONS = {
    "paraphrase-duplicate": "exact-duplicate",
    "same-principle-different-implementation": "same-principle-different-skill",
    "narrow-scope-specialization": "narrower-scope",
    "contradictory-advice": "possible-conflict",
    "stale-api-pattern": "stale-implementation",
    "irrelevant-domain-distractor": "unrelated",
    "rare-safety-critical-exception": "exception-to",
    "over-broad-false-principle": "unsafe-generalization",
}


class _StaleCalls(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name):
            node.func.id = f"legacy_{node.func.id}"
            self.changed = True
        elif isinstance(node.func, ast.Attribute):
            node.func.attr = f"legacy_{node.func.attr}"
            self.changed = True
        return node


def _implementation_variant(code: str, index: int) -> str:
    tree = ast.parse(code)
    tree.body.append(
        ast.Assign(
            targets=[ast.Name(id=f"_synthetic_variant_{index}", ctx=ast.Store())],
            value=ast.Constant(index),
        )
    )
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def _stale_variant(code: str) -> str:
    tree = ast.parse(code)
    transformer = _StaleCalls()
    tree = transformer.visit(tree)
    if not transformer.changed:
        tree.body.append(
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="legacy_unavailable_api", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            )
        )
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def _transform(
    source: SkillCodeInstance, kind: str, index: int
) -> tuple[str, str, str, str]:
    if kind == "paraphrase-duplicate":
        return (
            source.code,
            f"Equivalent wording for: {source.goal}",
            f"Equivalent condition: {source.trigger}",
            f"Equivalent effect: {source.observed_effect}",
        )
    if kind == "same-principle-different-implementation":
        return (
            _implementation_variant(source.code, index),
            source.goal,
            source.trigger,
            source.observed_effect,
        )
    if kind == "narrow-scope-specialization":
        return (
            source.code,
            f"Only in synthetic narrow scope {index}: {source.goal}",
            f"{source.trigger}; synthetic_scope_id equals {index}",
            source.observed_effect,
        )
    if kind == "contradictory-advice":
        return (
            (
                "def synthetic_conflict():\n"
                f"    raise RuntimeError('avoid source behavior {index}')\n"
            ),
            f"Avoid rather than perform: {source.goal}",
            source.trigger,
            f"Negates expected effect: {source.observed_effect}",
        )
    if kind == "stale-api-pattern":
        return (
            _stale_variant(source.code),
            source.goal,
            source.trigger,
            f"Legacy API claims: {source.observed_effect}",
        )
    if kind == "irrelevant-domain-distractor":
        return (
            (
                "def synthetic_unrelated_domain():\n"
                f"    return 'unrelated-domain-{index}'\n"
            ),
            f"Format an unrelated synthetic document {index}",
            "a non-robotics document is open",
            "the unrelated document is formatted",
        )
    if kind == "rare-safety-critical-exception":
        return (
            source.code,
            f"Safety exception to: {source.goal}",
            f"rare_hazard_{index} is true; {source.trigger}",
            f"Prevent harm before pursuing: {source.observed_effect}",
        )
    if kind == "over-broad-false-principle":
        return (
            source.code,
            f"Always, for every task and embodiment: {source.goal}",
            "unconditionally",
            f"Claims universal effect without evidence: {source.observed_effect}",
        )
    raise ValueError(f"unsupported stress kind: {kind}")


def _record(
    source: SkillCodeInstance, kind: str, index: int, seed: int
) -> dict[str, Any]:
    code, goal, trigger, effect = _transform(source, kind, index)
    fingerprint = fingerprint_code(code)
    instance_id = f"stress.s{seed}.{index:06d}"
    instance = SkillCodeInstance(
        id=instance_id,
        vertical_capability=source.vertical_capability,
        task=f"synthetic-stress-task-{index:06d}",
        task_family=(
            "synthetic-distractor"
            if kind == "irrelevant-domain-distractor"
            else source.task_family
        ),
        source_code_path=f"synthetic://{source.id}/{kind}/{index}",
        source_code_sha256=fingerprint.code_hash,
        code=code,
        goal=goal,
        trigger=trigger,
        observed_effect=effect,
        code_hash=fingerprint.code_hash,
        ast_fingerprint=fingerprint.ast_fingerprint,
        api_calls=fingerprint.api_calls,
        development_outcomes=source.development_outcomes,
        provenance={
            "partition": "synthetic-stress",
            "source_instance_id": source.id,
            "source_instance_hash": content_hash(source),
            "stress_kind": kind,
            "transformation_version": "v2",
            "outcome_semantics": "inherited-control-label-not-new-execution",
            "evidence_eligible": False,
        },
    )
    payload = {
        **asdict(instance),
        "source_instance_id": source.id,
        "source_instance_hash": content_hash(source),
        "kind": kind,
        "expected_relation": EXPECTED_RELATIONS[kind],
        "synthetic": True,
        "execution_status": "not-executed-synthetic",
        "evidence_eligible": False,
        "success_outcome_eligible": False,
    }
    return {**payload, "content_hash": content_hash(payload)}


def _snapshot(
    records: list[dict[str, Any]], checkpoint_id: str, scale: int, seed: int
) -> dict[str, Any]:
    checkpoint_ref = f"stress.{checkpoint_id}.s{seed}.x{scale}"
    unsigned = {
        "scale": scale,
        "checkpoint_id": checkpoint_ref,
        "record_count": len(records),
        "record_ids": [str(value["id"]) for value in records],
        "kind_counts": dict(sorted(Counter(value["kind"] for value in records).items())),
        "records": records,
    }
    return {**unsigned, "snapshot_hash": content_hash(unsigned)}


def build_stress_corpus(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    scales: list[int],
    *,
    seed: int,
) -> dict[str, Any]:
    """Build cumulative scale snapshots with identical shared prefixes."""
    if (
        not scales
        or any(
            not isinstance(scale, int)
            or isinstance(scale, bool)
            or scale < 1
            for scale in scales
        )
        or not isinstance(seed, int)
        or isinstance(seed, bool)
        or seed < 0
    ):
        raise ValueError(
            "stress scales must be positive integers and seed a non-negative integer"
        )
    checkpoint = repository.load_checkpoint(checkpoint_id)
    instances = sorted(
        instances_at_checkpoint(repository, checkpoint), key=lambda value: value.id
    )
    if not instances:
        raise ValueError("stress corpus requires at least one source instance")
    nondevelopment = [
        value.id
        for value in instances
        if value.provenance.get("partition", "development") != "development"
    ]
    if nondevelopment:
        raise ValueError(
            f"stress corpus sources must be real development instances: {nondevelopment}"
        )

    randomizer = random.Random(seed)
    randomizer.shuffle(instances)
    kinds = list(STRESS_KINDS)
    randomizer.shuffle(kinds)
    unique_scales = sorted(set(scales))
    maximum = len(instances) * unique_scales[-1]
    if maximum < len(STRESS_KINDS):
        raise ValueError(
            f"largest stress snapshot must cover all {len(STRESS_KINDS)} stress kinds"
        )
    records = [
        _record(
            instances[(index - 1) % len(instances)],
            kinds[(index - 1) % len(kinds)],
            index,
            seed,
        )
        for index in range(1, maximum + 1)
    ]
    snapshots = [
        _snapshot(
            records[: len(instances) * scale],
            checkpoint_id,
            scale,
            seed,
        )
        for scale in unique_scales
    ]
    payload = {
        "schema_version": 2,
        "corpus_kind": "synthetic",
        "checkpoint_id": checkpoint_id,
        "checkpoint_hash": content_hash(checkpoint),
        "seed": seed,
        "stress_kinds": list(STRESS_KINDS),
        "source_instance_count": len(instances),
        "prefix_stable_across_scales": True,
        "snapshots": snapshots,
        "partition_guard": (
            "This corpus is retrieval/maintenance stress only and must not be used for "
            "success evidence, canonicalization, principle support, or promotion."
        ),
    }
    return {**payload, "corpus_hash": content_hash(payload)}


def audit_stress_snapshot(
    corpus: dict[str, Any],
    scale: int,
    policy: ConsolidationPolicy,
) -> dict[str, Any]:
    """Run a synthetic-only repetition audit for one exact scale snapshot."""
    unsigned_corpus = {key: value for key, value in corpus.items() if key != "corpus_hash"}
    if corpus.get("corpus_hash") != content_hash(unsigned_corpus):
        raise ValueError("stress corpus hash mismatch")
    snapshots = [
        value for value in corpus.get("snapshots", []) if int(value.get("scale", -1)) == scale
    ]
    if len(snapshots) != 1:
        raise ValueError(f"stress corpus requires exactly one scale {scale} snapshot")
    snapshot = snapshots[0]
    unsigned_snapshot = {
        key: value for key, value in snapshot.items() if key != "snapshot_hash"
    }
    if snapshot.get("snapshot_hash") != content_hash(unsigned_snapshot):
        raise ValueError("stress snapshot hash mismatch")

    records = snapshot["records"]
    if snapshot.get("record_ids") != [record.get("id") for record in records]:
        raise ValueError("stress snapshot record ids do not match its records")
    if int(snapshot.get("record_count", -1)) != len(records):
        raise ValueError("stress snapshot record count mismatch")
    instances: list[SkillCodeInstance] = []
    for record in records:
        unsigned_record = {
            key: value for key, value in record.items() if key != "content_hash"
        }
        if record.get("content_hash") != content_hash(unsigned_record):
            raise ValueError(f"stress record hash mismatch: {record.get('id')}")
        if (
            record.get("synthetic") is not True
            or record.get("evidence_eligible") is not False
            or record.get("success_outcome_eligible") is not False
        ):
            raise ValueError("stress audit accepts only evidence-ineligible records")
        instances.append(SkillCodeInstance.from_dict(record))

    checkpoint = Checkpoint(
        id=str(snapshot["checkpoint_id"]),
        instance_ids=tuple(value.id for value in instances),
        instance_hashes={value.id: content_hash(value) for value in instances},
        created_at="1970-01-01T00:00:00+00:00",
    )
    report = audit_repetition(instances, checkpoint, policy)
    report_payload = asdict(report)
    payload = {
        "schema_version": 1,
        "corpus_kind": "synthetic",
        "corpus_hash": corpus["corpus_hash"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "scale": scale,
        "checkpoint_id": checkpoint.id,
        "record_count": len(instances),
        "evidence_eligible": False,
        "promotion_eligible": False,
        "policy": asdict(policy),
        "classification_counts": dict(
            sorted(Counter(value.classification for value in report.pairs).items())
        ),
        "repetition_report": report_payload,
        "repetition_report_hash": report.content_hash,
    }
    return {**payload, "audit_hash": content_hash(payload)}
