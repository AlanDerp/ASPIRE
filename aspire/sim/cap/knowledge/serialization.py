# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic serialization and append-only storage helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterator

def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_json_ready(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as error:
            raise ValueError(
                f"{path} is YAML rather than JSON-compatible YAML; install PyYAML to read it"
            ) from error
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"structured document must contain an object: {path}")
    return value


def write_structured_atomic(path: Path, value: Any) -> None:
    """Write JSON-compatible YAML atomically.

    JSON is a strict subset of YAML, so these files remain readable by YAML
    tooling while the core does not require PyYAML.
    """
    value = _json_ready(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    with temporary.open("r+") as destination:
        destination.flush()
        os.fsync(destination.fileno())
    temporary.replace(path)


def append_jsonl(path: Path, value: Any) -> None:
    value = _json_ready(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as destination:
        destination.write(canonical_json(value) + "\n")
        destination.flush()
        os.fsync(destination.fileno())


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"JSONL event must be an object at {path}:{line_number}")
        yield value
