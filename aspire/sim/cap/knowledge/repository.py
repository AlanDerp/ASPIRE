# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Git-friendly filesystem repository for knowledge revisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TypeVar

from .models import (
    CanonicalSkill,
    Checkpoint,
    KnowledgeManifest,
    OverlayEdge,
    Principle,
    SkillCodeInstance,
    VerticalTree,
    model_to_dict,
)
from .serialization import append_jsonl, content_hash, iter_jsonl, load_structured, write_structured_atomic


T = TypeVar("T")


class RepositoryConflict(ValueError):
    """Raised when an immutable revision would be overwritten."""


class KnowledgeRepository:
    """Persist immutable revisions and append-only evidence under one root."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def initialize(self) -> None:
        for relative in (
            "manifests",
            "skill-code-instances",
            "skills",
            "principles",
            "trees",
            "edges",
            "checkpoints",
            "evidence",
            "proposals",
            "projections",
            "experiment",
            "experiment/corpora",
            "experiment/task-contexts",
            "experiment/relevance-labels",
            "experiment/reports",
            "migrations",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def _safe(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"knowledge path escapes repository root: {path}") from error
        return path

    def _write_immutable(self, path: Path, value: Any) -> Path:
        payload = model_to_dict(value)
        if path.exists():
            existing = load_structured(path)
            if content_hash(existing) != content_hash(payload):
                raise RepositoryConflict(f"immutable revision already exists with different content: {path}")
            return path
        write_structured_atomic(path, payload)
        return path

    def save_instance(self, value: SkillCodeInstance) -> Path:
        path = self._safe("skill-code-instances", value.vertical_capability, f"{value.id}.yaml")
        return self._write_immutable(path, value)

    def save_skill(self, value: CanonicalSkill) -> Path:
        path = self._safe("skills", value.id, f"{value.version}.yaml")
        return self._write_immutable(path, value)

    def save_principle(self, value: Principle) -> Path:
        path = self._safe("principles", value.id, f"{value.version}.yaml")
        return self._write_immutable(path, value)

    def save_tree(self, value: VerticalTree) -> Path:
        path = self._safe("trees", value.vertical_capability, value.id, f"{value.version}.yaml")
        return self._write_immutable(path, value)

    def save_edge(self, value: OverlayEdge) -> Path:
        path = self._safe("edges", value.id, f"{value.version}.yaml")
        return self._write_immutable(path, value)

    def save_checkpoint(self, value: Checkpoint) -> Path:
        path = self._safe("checkpoints", f"{value.id}.yaml")
        return self._write_immutable(path, value)

    def save_manifest(self, value: KnowledgeManifest) -> Path:
        path = self._safe("manifests", value.id, f"{value.version}.yaml")
        return self._write_immutable(path, value)

    def append_evidence(self, event: dict[str, Any], stream: str = "events") -> None:
        if not stream.replace("-", "").isalnum():
            raise ValueError(f"invalid evidence stream: {stream!r}")
        append_jsonl(self._safe("evidence", f"{stream}.jsonl"), event)

    def iter_evidence(self, stream: str = "events"):
        yield from iter_jsonl(self._safe("evidence", f"{stream}.jsonl"))

    def _list(self, relative: str, factory: Callable[[dict[str, Any]], T]) -> list[T]:
        base = self._safe(relative)
        if not base.exists():
            return []
        return [factory(load_structured(path)) for path in sorted(base.rglob("*.yaml"))]

    def list_instances(self) -> list[SkillCodeInstance]:
        return self._list("skill-code-instances", SkillCodeInstance.from_dict)

    def list_skills(self) -> list[CanonicalSkill]:
        return self._list("skills", CanonicalSkill.from_dict)

    def list_principles(self) -> list[Principle]:
        return self._list("principles", Principle.from_dict)

    def list_trees(self) -> list[VerticalTree]:
        return self._list("trees", VerticalTree.from_dict)

    def list_edges(self) -> list[OverlayEdge]:
        return self._list("edges", OverlayEdge.from_dict)

    def list_manifests(self) -> list[KnowledgeManifest]:
        return self._list("manifests", KnowledgeManifest.from_dict)

    def load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        return Checkpoint.from_dict(load_structured(self._safe("checkpoints", f"{checkpoint_id}.yaml")))

    def load_manifest(self, manifest_id: str, version: str | None = None) -> KnowledgeManifest:
        matches = [value for value in self.list_manifests() if value.id == manifest_id]
        if version is not None:
            matches = [value for value in matches if value.version == version]
        if not matches:
            suffix = f"@{version}" if version else ""
            raise ValueError(f"knowledge manifest not found: {manifest_id}{suffix}")
        return max(matches, key=lambda value: tuple(int(part) for part in value.version.split(".")))

    def all_node_ids(self) -> set[str]:
        return {value.id for value in self.list_skills()} | {value.id for value in self.list_principles()}
