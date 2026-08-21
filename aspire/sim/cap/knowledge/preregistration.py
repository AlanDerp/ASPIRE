# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Freeze exact experiment artifacts before any A--F execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .serialization import content_hash, load_structured, sha256_file


PARTITIONS = ("development", "held-out", "adversarial", "maintenance")
EXECUTION_FIELDS = (
    "model_id",
    "temperature",
    "simulator",
    "execution_api",
    "perception_backend",
    "task_seeds",
    "token_budget",
    "max_runs",
    "max_retries",
    "retrieval_lexical_normalization",
    "held_out_writeback",
)


def _validate_task_split(task_split: dict[str, Any]) -> None:
    for partition in PARTITIONS:
        values = task_split.get(partition)
        if not isinstance(values, list) or not values:
            raise ValueError(f"task split requires a nonempty {partition} list")
        if len({str(value) for value in values}) != len(values):
            raise ValueError(f"task split contains duplicate {partition} task ids")
    seen: dict[str, str] = {}
    overlaps: dict[str, list[str]] = {}
    for partition in PARTITIONS:
        for task_id in task_split[partition]:
            task_id = str(task_id)
            previous = seen.get(task_id)
            if previous is not None:
                overlaps.setdefault(task_id, [previous]).append(partition)
            else:
                seen[task_id] = partition
    if overlaps:
        raise ValueError(f"task split partitions overlap: {overlaps}")


def _validate_checkpoint_map(
    checkpoint_map: dict[str, Any],
    scales: list[int],
) -> None:
    expected = {str(value) for value in scales}
    for corpus_kind in ("organic", "synthetic"):
        values = checkpoint_map.get(corpus_kind)
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError(
                f"checkpoint map {corpus_kind} scales must equal {sorted(expected)}"
            )
        for scale, artifact in values.items():
            if not isinstance(artifact, dict):
                raise ValueError(f"checkpoint map entry must be an object: {scale}")
            required = ("checkpoint_id", "corpus_hash", "n_code")
            if any(artifact.get(key) in (None, "", 0) for key in required):
                raise ValueError(
                    f"checkpoint map entry lacks checkpoint_id/corpus_hash/n_code: {scale}"
                )
            if not isinstance(artifact["n_code"], int) or artifact["n_code"] < 1:
                raise ValueError(f"checkpoint n_code must be a positive integer: {scale}")
            expected_eligibility = corpus_kind == "organic"
            if artifact.get("evidence_eligible") is not expected_eligibility:
                raise ValueError(
                    f"{corpus_kind} checkpoint entries must set "
                    f"evidence_eligible={str(expected_eligibility).lower()}"
                )
        checkpoint_ids = [str(value["checkpoint_id"]) for value in values.values()]
        if len(set(checkpoint_ids)) != len(checkpoint_ids):
            raise ValueError(f"checkpoint map {corpus_kind} checkpoint ids must be unique")


def _validate_execution_config(
    execution_config: dict[str, Any],
    *,
    model_id: str,
    token_budget: int,
    seeds: list[int],
) -> None:
    missing = [
        field
        for field in EXECUTION_FIELDS
        if field not in execution_config or execution_config[field] in (None, "", [])
    ]
    if missing:
        raise ValueError(f"execution config lacks fixed fields: {missing}")
    if execution_config["model_id"] != model_id:
        raise ValueError("execution config model_id differs from the frozen model_id")
    if execution_config["token_budget"] != token_budget:
        raise ValueError("execution config token_budget differs from the preregistration")
    if execution_config["task_seeds"] != seeds:
        raise ValueError("execution config task_seeds differ from the preregistration")
    if execution_config["held_out_writeback"] is not False:
        raise ValueError("execution config must set held_out_writeback=false")
    if not isinstance(execution_config["temperature"], (int, float)):
        raise ValueError("execution config temperature must be numeric")
    for field in ("max_runs", "max_retries"):
        value = execution_config[field]
        minimum = 1 if field == "max_runs" else 0
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"execution config {field} must be an integer >= {minimum}")


def validate_frozen_preregistration(document: dict[str, Any]) -> list[str]:
    """Return fail-closed integrity errors for a frozen preregistration."""
    errors: list[str] = []
    if document.get("status") != "frozen":
        errors.append("status is not frozen")
        return errors

    payload = {key: value for key, value in document.items() if key != "frozen_document_hash"}
    if document.get("frozen_document_hash") != content_hash(payload):
        errors.append("frozen document hash mismatch")

    fixed = document.get("fixed_artifacts")
    if not isinstance(fixed, dict):
        return [*errors, "fixed_artifacts is not an object"]
    path_hashes = {
        "prompt_path": ("prompt_hash", sha256_file),
        "task_split_path": (
            "task_split_hash",
            lambda path: content_hash(load_structured(path)),
        ),
        "checkpoint_map_path": (
            "checkpoint_map_hash",
            lambda path: content_hash(load_structured(path)),
        ),
        "execution_config_path": (
            "execution_config_hash",
            lambda path: content_hash(load_structured(path)),
        ),
    }
    loaded: dict[str, dict[str, Any]] = {}
    for path_field, (hash_field, hash_function) in path_hashes.items():
        raw_path = fixed.get(path_field)
        expected_hash = fixed.get(hash_field)
        if not raw_path or not expected_hash:
            errors.append(f"missing {path_field} or {hash_field}")
            continue
        path = Path(str(raw_path))
        if not path.is_file():
            errors.append(f"fixed artifact is missing: {path}")
            continue
        try:
            actual_hash = hash_function(path)
            if path_field != "prompt_path":
                loaded[path_field] = load_structured(path)
        except (OSError, ValueError) as error:
            errors.append(f"cannot read fixed artifact {path}: {error}")
            continue
        if actual_hash != expected_hash:
            errors.append(f"fixed artifact hash mismatch: {path}")

    try:
        scales = [int(value) for value in document.get("library_scales", [])]
        seeds = [int(value) for value in document.get("seeds", [])]
        token_budget = int(document.get("token_budget", 0))
        if "task_split_path" in loaded:
            _validate_task_split(loaded["task_split_path"])
        if "checkpoint_map_path" in loaded:
            _validate_checkpoint_map(loaded["checkpoint_map_path"], scales)
        if "execution_config_path" in loaded:
            _validate_execution_config(
                loaded["execution_config_path"],
                model_id=str(fixed.get("model_id", "")),
                token_budget=token_budget,
                seeds=seeds,
            )
    except (TypeError, ValueError) as error:
        errors.append(str(error))
    return errors


def freeze_preregistration(
    draft_path: Path,
    *,
    model_id: str,
    prompt_path: Path,
    task_split_path: Path,
    checkpoint_map_path: Path,
    execution_config_path: Path,
    frozen_at: str,
) -> dict[str, Any]:
    """Return a frozen document containing semantic hashes for every fixed input."""
    draft = load_structured(draft_path)
    if draft.get("status") != "preregistered-engineering-draft":
        raise ValueError("only a preregistered-engineering-draft can be frozen")
    if not model_id.strip() or not frozen_at.strip():
        raise ValueError("freezing requires exact model_id and frozen_at values")
    hypotheses = draft.get("hypotheses", {})
    if not isinstance(hypotheses, dict) or set(hypotheses) != {
        f"H{index}" for index in range(1, 7)
    }:
        raise ValueError("preregistration must contain exactly H1--H6")
    if any(
        not isinstance(value, dict)
        or not value.get("claim")
        or not value.get("refutation")
        for value in hypotheses.values()
    ):
        raise ValueError("every hypothesis requires claim and refutation text")
    if set(draft.get("treatments", {})) != set("ABCDEF"):
        raise ValueError("preregistration must contain exactly treatments A--F")
    scales = [int(value) for value in draft.get("library_scales", [])]
    seeds = [int(value) for value in draft.get("seeds", [])]
    token_budget = int(draft.get("token_budget", 0))
    if not scales or not seeds or token_budget < 1:
        raise ValueError("scales, seeds, and token budget must be nonempty")

    task_split = load_structured(task_split_path)
    checkpoint_map = load_structured(checkpoint_map_path)
    execution_config = load_structured(execution_config_path)
    _validate_task_split(task_split)
    _validate_checkpoint_map(checkpoint_map, scales)
    _validate_execution_config(
        execution_config,
        model_id=model_id.strip(),
        token_budget=token_budget,
        seeds=seeds,
    )

    payload: dict[str, Any] = {
        **draft,
        "status": "frozen",
        "frozen_at": frozen_at.strip(),
        "draft_hash": content_hash(draft),
        "fixed_artifacts": {
            "model_id": model_id.strip(),
            "prompt_hash": sha256_file(prompt_path),
            "task_split_hash": content_hash(task_split),
            "checkpoint_map_hash": content_hash(checkpoint_map),
            "execution_config_hash": content_hash(execution_config),
            "prompt_path": str(prompt_path.resolve()),
            "task_split_path": str(task_split_path.resolve()),
            "checkpoint_map_path": str(checkpoint_map_path.resolve()),
            "execution_config_path": str(execution_config_path.resolve()),
        },
    }
    frozen: dict[str, Any] = {
        **payload,
        "frozen_document_hash": content_hash(payload),
    }
    errors = validate_frozen_preregistration(frozen)
    if errors:
        raise ValueError(f"generated preregistration failed validation: {errors}")
    return frozen
