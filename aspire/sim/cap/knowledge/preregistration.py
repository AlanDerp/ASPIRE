# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Freeze exact experiment artifacts before any A--F execution."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .models import TaskContext
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
    "runner_command",
    "runner_executable_hash",
    "runner_timeout_seconds",
)
DECISION_FIELDS = (
    "task_noninferiority_margin",
    "principle_recall_at_8_min",
    "operational_skill_recall_margin",
    "unsupported_principle_escape_max",
    "exception_hard_violation_escape_max",
    "shadow_fallback_rate_max",
    "compile_latency_p95_ms_max",
    "claim_min_independent_tasks",
    "claim_min_task_families",
    "claim_min_advantage_scales",
    "claim_requires_slope_comparison",
    "total_cost_weights",
)


def _validate_task_split(task_split: dict[str, Any]) -> None:
    for partition in PARTITIONS:
        values = task_split.get(partition)
        if not isinstance(values, list) or not values:
            raise ValueError(f"task split requires a nonempty {partition} list")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"task split {partition} ids must be nonempty strings")
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


def _validate_evaluation_partitions(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"organic", "synthetic"}:
        raise ValueError("evaluation_partitions requires exact organic and synthetic keys")
    for corpus_kind, partitions in value.items():
        if not isinstance(partitions, list) or not partitions:
            raise ValueError(f"evaluation_partitions {corpus_kind} must be nonempty")
        if len(set(partitions)) != len(partitions) or not set(partitions) <= set(PARTITIONS):
            raise ValueError(
                f"evaluation_partitions {corpus_kind} contains duplicates or unknown partitions"
            )


def _validate_decision_rules(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("decision_rules must be an object")
    missing = [field for field in DECISION_FIELDS if field not in value]
    if missing:
        raise ValueError(f"decision_rules lacks fixed fields: {missing}")
    if value["claim_requires_slope_comparison"] is not True:
        raise ValueError("claim_requires_slope_comparison must be true")
    for field in (
        "claim_min_independent_tasks",
        "claim_min_task_families",
        "claim_min_advantage_scales",
    ):
        if not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 2:
            raise ValueError(f"decision_rules {field} must be an integer >= 2")
    for field in (
        "task_noninferiority_margin",
        "principle_recall_at_8_min",
        "operational_skill_recall_margin",
        "unsupported_principle_escape_max",
        "exception_hard_violation_escape_max",
        "shadow_fallback_rate_max",
    ):
        number = value[field]
        if not isinstance(number, (int, float)) or isinstance(number, bool) or not 0 <= number <= 1:
            raise ValueError(f"decision_rules {field} must be numeric in [0, 1]")
    latency = value["compile_latency_p95_ms_max"]
    if not isinstance(latency, (int, float)) or isinstance(latency, bool) or latency <= 0:
        raise ValueError("compile_latency_p95_ms_max must be positive")
    weights = value["total_cost_weights"]
    expected_weights = {"compute_minute", "model_1k_tokens", "monetary_unit"}
    if not isinstance(weights, dict) or set(weights) != expected_weights:
        raise ValueError(f"total_cost_weights requires exact keys: {sorted(expected_weights)}")
    if any(
        not isinstance(weight, (int, float))
        or isinstance(weight, bool)
        or weight < 0
        for weight in weights.values()
    ):
        raise ValueError("total_cost_weights values must be non-negative")


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
    command = execution_config["runner_command"]
    if not isinstance(command, list) or not command or any(
        not isinstance(value, str) or not value for value in command
    ):
        raise ValueError("execution config runner_command must be a nonempty string list")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("runner_command executable must be an existing absolute file")
    if sha256_file(executable) != execution_config["runner_executable_hash"]:
        raise ValueError("runner executable hash mismatch")
    rendered = "\n".join(command)
    required_placeholders = {
        "{config_path}",
        "{model_id}",
        "{prompt_path}",
        "{seed}",
        "{observation_path}",
    }
    missing_placeholders = sorted(
        placeholder for placeholder in required_placeholders if placeholder not in rendered
    )
    if missing_placeholders:
        raise ValueError(
            f"execution config runner_command lacks placeholders: {missing_placeholders}"
        )
    if not isinstance(execution_config["temperature"], (int, float)):
        raise ValueError("execution config temperature must be numeric")
    for field in ("max_runs", "max_retries"):
        value = execution_config[field]
        minimum = 1 if field == "max_runs" else 0
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"execution config {field} must be an integer >= {minimum}")
    timeout = execution_config["runner_timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise ValueError("execution config runner_timeout_seconds must be positive")


def _validate_job_catalog(
    catalog: dict[str, Any],
    task_split: dict[str, Any],
    *,
    token_budget: int,
) -> None:
    tasks = catalog.get("tasks")
    expected_ids = {
        str(task_id)
        for partition in PARTITIONS
        for task_id in task_split[partition]
    }
    if not isinstance(tasks, dict) or set(tasks) != expected_ids:
        raise ValueError("job catalog tasks must exactly match the frozen task split")
    for task_id, artifact in tasks.items():
        if not isinstance(artifact, dict):
            raise ValueError(f"job catalog task must be an object: {task_id}")
        required = (
            "context_path",
            "context_hash",
            "env_config_path",
            "env_config_hash",
        )
        if any(not artifact.get(field) for field in required):
            raise ValueError(f"job catalog task lacks paths or hashes: {task_id}")
        context_path = Path(str(artifact["context_path"]))
        env_config_path = Path(str(artifact["env_config_path"]))
        if not context_path.is_absolute() or not env_config_path.is_absolute():
            raise ValueError("job catalog paths must be absolute")
        context_payload = load_structured(context_path)
        env_config = load_structured(env_config_path)
        if content_hash(context_payload) != artifact["context_hash"]:
            raise ValueError(f"job catalog context hash mismatch: {task_id}")
        if content_hash(env_config) != artifact["env_config_hash"]:
            raise ValueError(f"job catalog environment hash mismatch: {task_id}")
        context = TaskContext.from_dict(context_payload)
        if context.task_id != task_id:
            raise ValueError(f"job catalog context task id mismatch: {task_id}")
        if context.token_budget != token_budget:
            raise ValueError(f"job catalog context token budget mismatch: {task_id}")
        env = env_config.get("env")
        if not isinstance(env, dict) or not isinstance(env.get("cfg"), dict):
            raise ValueError(f"job catalog environment lacks env.cfg: {task_id}")


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
        "job_catalog_path": (
            "job_catalog_hash",
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
        _validate_evaluation_partitions(document.get("evaluation_partitions"))
        _validate_decision_rules(document.get("decision_rules"))
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
        if "job_catalog_path" in loaded and "task_split_path" in loaded:
            _validate_job_catalog(
                loaded["job_catalog_path"],
                loaded["task_split_path"],
                token_budget=token_budget,
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
    job_catalog_path: Path,
    frozen_at: str,
) -> dict[str, Any]:
    """Return a frozen document containing semantic hashes for every fixed input."""
    draft = load_structured(draft_path)
    if draft.get("status") != "preregistered-engineering-draft":
        raise ValueError("only a preregistered-engineering-draft can be frozen")
    if not model_id.strip() or not frozen_at.strip():
        raise ValueError("freezing requires exact model_id and frozen_at values")
    try:
        frozen_time = datetime.fromisoformat(frozen_at.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("frozen_at must be an RFC3339 timestamp") from error
    if frozen_time.tzinfo is None:
        raise ValueError("frozen_at must include a timezone")
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
    _validate_evaluation_partitions(draft.get("evaluation_partitions"))
    _validate_decision_rules(draft.get("decision_rules"))
    raw_scales = draft.get("library_scales", [])
    raw_seeds = draft.get("seeds", [])
    if any(not isinstance(value, int) or isinstance(value, bool) for value in raw_scales):
        raise ValueError("library scales must be integers")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in raw_seeds):
        raise ValueError("seeds must be integers")
    scales = [int(value) for value in raw_scales]
    seeds = [int(value) for value in raw_seeds]
    token_budget = int(draft.get("token_budget", 0))
    if (
        not scales
        or not seeds
        or token_budget < 1
        or len(scales) != len(set(scales))
        or len(seeds) != len(set(seeds))
        or any(value < 1 for value in scales)
        or any(value < 0 for value in seeds)
    ):
        raise ValueError("scales, seeds, and token budget must be nonempty")

    task_split = load_structured(task_split_path)
    checkpoint_map = load_structured(checkpoint_map_path)
    execution_config = load_structured(execution_config_path)
    job_catalog = load_structured(job_catalog_path)
    _validate_task_split(task_split)
    _validate_checkpoint_map(checkpoint_map, scales)
    _validate_execution_config(
        execution_config,
        model_id=model_id.strip(),
        token_budget=token_budget,
        seeds=seeds,
    )
    _validate_job_catalog(job_catalog, task_split, token_budget=token_budget)

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
            "job_catalog_hash": content_hash(job_catalog),
            "prompt_path": str(prompt_path.resolve()),
            "task_split_path": str(task_split_path.resolve()),
            "checkpoint_map_path": str(checkpoint_map_path.resolve()),
            "execution_config_path": str(execution_config_path.resolve()),
            "job_catalog_path": str(job_catalog_path.resolve()),
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
