# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rebuildable SQLite/FTS index for the consolidation forest."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .checkpoints import instances_at_checkpoint
from .models import KnowledgeManifest
from .repository import KnowledgeRepository
from .retrieval import resolve_view
from .serialization import content_hash


SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE skill_code_instances (
  id TEXT PRIMARY KEY,
  vertical_capability TEXT NOT NULL,
  task TEXT NOT NULL,
  task_family TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  ast_fingerprint TEXT NOT NULL,
  api_calls TEXT NOT NULL,
  goal TEXT NOT NULL,
  trigger TEXT NOT NULL,
  observed_effect TEXT NOT NULL,
  positive_outcome INTEGER NOT NULL
);
CREATE TABLE nodes (
  id TEXT NOT NULL,
  version TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  vertical_capability TEXT NOT NULL,
  title TEXT NOT NULL,
  goal_or_summary TEXT NOT NULL,
  trigger_or_when TEXT NOT NULL,
  operation_or_decision TEXT NOT NULL,
  effect_or_invariant TEXT NOT NULL,
  scope TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  active INTEGER NOT NULL,
  token_estimate INTEGER NOT NULL,
  PRIMARY KEY (id, version)
);
CREATE TABLE tree_parents (
  tree_id TEXT NOT NULL,
  tree_version TEXT NOT NULL,
  child_id TEXT NOT NULL,
  parent_id TEXT NOT NULL,
  active INTEGER NOT NULL,
  PRIMARY KEY (tree_id, tree_version, child_id)
);
CREATE TABLE overlay_edges (
  id TEXT NOT NULL,
  version TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  guard TEXT NOT NULL,
  active INTEGER NOT NULL,
  PRIMARY KEY (id, version)
);
CREATE TABLE principle_metrics (
  principle_id TEXT NOT NULL,
  principle_version TEXT NOT NULL,
  support_count INTEGER NOT NULL,
  support_families INTEGER NOT NULL,
  support_diversity REAL NOT NULL,
  contradiction_count INTEGER NOT NULL,
  exception_rate REAL NOT NULL,
  operational_fanout INTEGER NOT NULL,
  compression_ratio REAL NOT NULL,
  support_sufficiency TEXT NOT NULL,
  PRIMARY KEY (principle_id, principle_version)
);
CREATE VIRTUAL TABLE principle_fts USING fts5(
  id UNINDEXED, version UNINDEXED, title, summary, decision, invariant, scope,
  tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE skill_fts USING fts5(
  id UNINDEXED, version UNINDEXED, title, goal, trigger, operation, effect, scope,
  tokenize='unicode61 remove_diacritics 2'
);
"""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rebuild_index(
    repository: KnowledgeRepository,
    output: Path,
    *,
    checkpoint_id: str,
    manifest: KnowledgeManifest | None = None,
) -> str:
    if manifest is not None and manifest.checkpoint_id != checkpoint_id:
        raise ValueError("index manifest and checkpoint do not match")
    checkpoint = repository.load_checkpoint(checkpoint_id)
    temporary = output.with_suffix(output.suffix + ".tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        instances = {value.id: value for value in instances_at_checkpoint(repository, checkpoint)}
        for instance_id in checkpoint.instance_ids:
            instance = instances[instance_id]
            connection.execute(
                "INSERT INTO skill_code_instances VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    instance.id,
                    instance.vertical_capability,
                    instance.task,
                    instance.task_family,
                    instance.code_hash,
                    instance.ast_fingerprint,
                    _json(instance.api_calls),
                    instance.goal,
                    instance.trigger,
                    instance.observed_effect,
                    int(instance.has_positive_outcome),
                ),
            )

        skills, principles, trees, edges = resolve_view(repository, manifest)
        for skill in sorted(skills.values(), key=lambda item: (item.id, item.version)):
            scope = _json(skill.scope.__dict__)
            digest = content_hash(skill)
            connection.execute(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    skill.id,
                    skill.version,
                    skill.KIND,
                    skill.status,
                    skill.vertical_capability,
                    skill.title,
                    skill.goal,
                    skill.trigger,
                    skill.operation_template,
                    skill.effect,
                    scope,
                    digest,
                    1,
                    max(1, len(skill.goal + skill.trigger + skill.operation_template + skill.effect) // 4),
                ),
            )
            connection.execute(
                "INSERT INTO skill_fts VALUES (?,?,?,?,?,?,?,?)",
                (
                    skill.id,
                    skill.version,
                    skill.title,
                    skill.goal,
                    skill.trigger,
                    skill.operation_template,
                    skill.effect,
                    scope,
                ),
            )

        for principle in sorted(principles.values(), key=lambda item: (item.id, item.version)):
            scope = _json(principle.scope.__dict__)
            when = _json(principle.when)
            digest = content_hash(principle)
            connection.execute(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    principle.id,
                    principle.version,
                    principle.KIND,
                    principle.status,
                    principle.vertical_capability,
                    principle.title,
                    principle.summary,
                    when,
                    principle.decision,
                    principle.invariant,
                    scope,
                    digest,
                    1,
                    max(1, len(principle.summary + principle.decision + principle.invariant) // 4),
                ),
            )
            connection.execute(
                "INSERT INTO principle_fts VALUES (?,?,?,?,?,?,?)",
                (
                    principle.id,
                    principle.version,
                    principle.title,
                    principle.summary + " " + when,
                    principle.decision,
                    principle.invariant,
                    scope,
                ),
            )

            from .lifecycle import principle_metrics

            metrics = principle_metrics(repository, principle)
            connection.execute(
                "INSERT INTO principle_metrics VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    principle.id,
                    principle.version,
                    metrics.support_count,
                    metrics.support_task_families,
                    metrics.support_diversity,
                    metrics.contradiction_count,
                    metrics.exception_rate,
                    metrics.operational_fanout,
                    metrics.compression_ratio,
                    metrics.support_sufficiency,
                ),
            )

        for tree in sorted(trees.values(), key=lambda item: (item.id, item.version)):
            for child, parent in sorted(tree.parent_by_child.items()):
                connection.execute(
                    "INSERT INTO tree_parents VALUES (?,?,?,?,?)",
                    (tree.id, tree.version, child, parent, 1),
                )
        for edge in sorted(edges.values(), key=lambda item: (item.id, item.version)):
            connection.execute(
                "INSERT INTO overlay_edges VALUES (?,?,?,?,?,?,?)",
                (edge.id, edge.version, edge.kind, edge.source_id, edge.target_id, _json(edge.guard), 1),
            )

        source_hash = content_hash(
            {
                "checkpoint": checkpoint,
                "manifest": manifest,
                "skills": list(skills.values()),
                "principles": list(principles.values()),
                "trees": list(trees.values()),
                "edges": list(edges.values()),
            }
        )
        connection.executemany(
            "INSERT INTO metadata VALUES (?,?)",
            (
                ("schema_version", "1"),
                ("checkpoint_id", checkpoint_id),
                ("manifest_id", f"{manifest.id}@{manifest.version}" if manifest else "latest"),
                ("source_hash", source_hash),
            ),
        )
        connection.commit()
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"SQLite integrity check failed: {result}")
    finally:
        connection.close()
    temporary.replace(output)
    return source_hash


def index_metadata(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    try:
        return dict(connection.execute("SELECT key, value FROM metadata"))
    finally:
        connection.close()
