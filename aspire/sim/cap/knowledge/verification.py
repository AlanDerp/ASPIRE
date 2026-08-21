# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic rebuild verification for forest, index, and portfolios."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, cast

from .experiment import Treatment, compile_treatment
from .index import rebuild_index
from .integrity import validate_repository
from .models import KnowledgeManifest, TaskContext, model_to_dict
from .projection import overlay_view, vertical_forest
from .repository import KnowledgeRepository
from .serialization import content_hash, load_structured


INDEX_TABLES = (
    "metadata",
    "skill_code_instances",
    "nodes",
    "tree_parents",
    "overlay_edges",
    "principle_metrics",
    "principle_fts",
    "skill_fts",
)


def _logical_index_hash(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        payload = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in INDEX_TABLES
        }
    finally:
        connection.close()
    return content_hash(payload)


def _build_once(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    manifest: KnowledgeManifest,
    contexts: list[TaskContext],
    index_path: Path,
) -> dict[str, Any]:
    forest = vertical_forest(repository, manifest=manifest)
    overlay = overlay_view(repository, manifest=manifest)
    index_source_hash = rebuild_index(
        repository,
        index_path,
        checkpoint_id=checkpoint_id,
        manifest=manifest,
    )
    portfolios = {
        f"{context.task_id}:{treatment}": content_hash(
            model_to_dict(
                compile_treatment(
                    repository,
                    checkpoint_id,
                    context,
                    cast(Treatment, treatment),
                    manifest=manifest,
                )
            )
        )
        for context in contexts
        for treatment in "ABCDEF"
    }
    return {
        "forest_hash": forest["projection_hash"],
        "overlay_hash": overlay["projection_hash"],
        "index_source_hash": index_source_hash,
        "index_logical_hash": _logical_index_hash(index_path),
        "portfolio_hashes": portfolios,
    }


def verify_deterministic_rebuild(
    repository: KnowledgeRepository,
    checkpoint_id: str,
    manifest: KnowledgeManifest,
    context_paths: list[Path],
) -> dict[str, Any]:
    """Build all derived views twice and compare their semantic hashes."""
    if not context_paths:
        raise ValueError("determinism verification requires at least one task context")
    validate_repository(repository).require_ok()
    contexts = [TaskContext.from_dict(load_structured(path)) for path in context_paths]
    if len({context.task_id for context in contexts}) != len(contexts):
        raise ValueError("determinism contexts require unique task_id values")
    with tempfile.TemporaryDirectory(prefix="aspire-knowledge-determinism-") as directory:
        root = Path(directory)
        first = _build_once(
            repository,
            checkpoint_id,
            manifest,
            contexts,
            root / "first.sqlite3",
        )
        second = _build_once(
            repository,
            checkpoint_id,
            manifest,
            contexts,
            root / "second.sqlite3",
        )
    payload = {
        "schema_version": 1,
        "checkpoint_id": checkpoint_id,
        "manifest_id": f"{manifest.id}@{manifest.version}",
        "context_ids": [context.task_id for context in contexts],
        "context_hashes": {
            context.task_id: content_hash(model_to_dict(context)) for context in contexts
        },
        "first": first,
        "second": second,
        "tree_index_portfolio_deterministic": first == second,
    }
    return {**payload, "verification_hash": content_hash(payload)}
