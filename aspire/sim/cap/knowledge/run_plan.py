# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Materialize and execute immutable A--F experiment job matrices."""

from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from .experiment import Observation, TREATMENTS
from .preregistration import validate_frozen_preregistration
from .runtime import build_runtime_config
from .serialization import (
    canonical_json,
    content_hash,
    load_structured,
    write_structured_atomic,
)


def _load_fixed(preregistration: dict[str, Any]) -> tuple[dict, dict, dict]:
    errors = validate_frozen_preregistration(preregistration)
    if errors:
        raise ValueError(f"cannot plan from an invalid preregistration: {errors}")
    fixed = preregistration["fixed_artifacts"]
    task_split = load_structured(Path(str(fixed["task_split_path"])))
    checkpoint_map = load_structured(Path(str(fixed["checkpoint_map_path"])))
    execution = load_structured(Path(str(fixed["execution_config_path"])))
    return task_split, checkpoint_map, execution


def _portfolio_entries(catalog: dict[str, Any]) -> dict[tuple, dict[str, Any]]:
    raw_entries = catalog.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("portfolio catalog requires an entries list")
    entries: dict[tuple, dict[str, Any]] = {}
    fields = ("corpus_kind", "scale", "split", "task_id", "treatment")
    for value in raw_entries:
        if not isinstance(value, dict):
            raise ValueError("portfolio catalog entries must be objects")
        key = tuple(value.get(field) for field in fields)
        if key in entries:
            raise ValueError(f"duplicate portfolio catalog entry: {key}")
        entries[key] = value
    return entries


def _expected_portfolios(
    preregistration: dict[str, Any], task_split: dict[str, Any]
) -> set[tuple]:
    return {
        (corpus_kind, scale, split, str(task_id), treatment)
        for corpus_kind, partitions in preregistration["evaluation_partitions"].items()
        for scale in preregistration["library_scales"]
        for split in partitions
        for task_id in task_split[split]
        for treatment in TREATMENTS
    }


def _manifest_reference(checkpoint: dict[str, Any]) -> str:
    manifest_id = checkpoint.get("manifest_id")
    manifest_version = checkpoint.get("manifest_version")
    if not manifest_id or not manifest_version:
        raise ValueError("checkpoint map entries require manifest_id and manifest_version")
    return f"{manifest_id}@{manifest_version}"


def _inject_runtime_config(
    base_config: dict[str, Any], runtime_config: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(base_config)
    env = result.get("env")
    if not isinstance(env, dict):
        raise ValueError("ASPIRE environment config lacks env")
    cfg = env.get("cfg")
    if not isinstance(cfg, dict):
        raise ValueError("ASPIRE environment config lacks env.cfg")
    cfg["knowledge"] = runtime_config
    return result


def _render_command(template: list[str], values: dict[str, Any]) -> list[str]:
    try:
        return [argument.format_map(values) for argument in template]
    except KeyError as error:
        raise ValueError(f"unknown runner command placeholder: {error.args[0]}") from error


def materialize_experiment_plan(
    preregistration_path: Path,
    portfolio_catalog_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Build configs and immutable jobs without starting external evaluation."""
    preregistration = load_structured(preregistration_path)
    task_split, checkpoint_map, execution = _load_fixed(preregistration)
    fixed = preregistration["fixed_artifacts"]
    job_catalog = load_structured(Path(str(fixed["job_catalog_path"])))
    portfolio_catalog = load_structured(portfolio_catalog_path)
    entries = _portfolio_entries(portfolio_catalog)
    expected = _expected_portfolios(preregistration, task_split)
    if set(entries) != expected:
        missing = sorted(expected - set(entries))
        extra = sorted(set(entries) - expected)
        raise ValueError(
            f"portfolio catalog does not match the frozen matrix; missing={missing}, extra={extra}"
        )

    output_root = output_root.resolve()
    jobs = []
    for key in sorted(expected):
        corpus_kind, scale, split, task_id, treatment = key
        entry = entries[key]
        checkpoint = checkpoint_map[corpus_kind][str(scale)]
        task = job_catalog["tasks"][task_id]
        portfolio_path = Path(str(entry.get("path", "")))
        if not portfolio_path.is_absolute() or not portfolio_path.is_file():
            raise ValueError(f"portfolio path must be an existing absolute file: {key}")
        portfolio = load_structured(portfolio_path)
        portfolio_hash = content_hash(portfolio)
        expected_manifest = _manifest_reference(checkpoint)
        expected_values = {
            "treatment": treatment,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "manifest_id": expected_manifest,
            "context_hash": task["context_hash"],
        }
        mismatches = {
            field: {"expected": expected_value, "actual": portfolio.get(field)}
            for field, expected_value in expected_values.items()
            if portfolio.get(field) != expected_value
        }
        if entry.get("hash") != portfolio_hash:
            mismatches["portfolio_hash"] = {
                "expected": entry.get("hash"),
                "actual": portfolio_hash,
            }
        if int(portfolio.get("estimated_tokens", 0)) > int(
            preregistration["token_budget"]
        ):
            mismatches["token_budget"] = {
                "expected_max": preregistration["token_budget"],
                "actual": portfolio.get("estimated_tokens"),
            }
        if mismatches:
            raise ValueError(f"portfolio lock mismatch for {key}: {mismatches}")

        runtime_config = build_runtime_config(
            "experiment",
            {str(treatment): str(portfolio_path)},
            token_budget=int(preregistration["token_budget"]),
        )
        env_config = load_structured(Path(str(task["env_config_path"])))
        config_path = (
            output_root
            / "configs"
            / str(corpus_kind)
            / f"scale-{scale}"
            / str(split)
            / str(task_id)
            / f"{treatment}.yaml"
        )
        write_structured_atomic(
            config_path, _inject_runtime_config(env_config, runtime_config)
        )
        for seed in preregistration["seeds"]:
            identity = {
                "corpus_kind": corpus_kind,
                "scale": scale,
                "seed": seed,
                "split": split,
                "task_id": task_id,
                "treatment": treatment,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "manifest_id": expected_manifest,
                "corpus_hash": checkpoint["corpus_hash"],
                "n_code": checkpoint["n_code"],
                "context_hash": task["context_hash"],
                "portfolio_hash": portfolio_hash,
                "model_id": fixed["model_id"],
                "prompt_hash": fixed["prompt_hash"],
                "token_budget": preregistration["token_budget"],
            }
            job_id = content_hash(identity)[:20]
            observation_path = output_root / "raw-observations" / f"{job_id}.yaml"
            log_path = output_root / "logs" / f"{job_id}.log"
            command_values = {
                **identity,
                "config_path": str(config_path),
                "prompt_path": fixed["prompt_path"],
                "observation_path": str(observation_path),
                "output_dir": str(output_root / "runner-output" / job_id),
                "temperature": execution["temperature"],
                "max_runs": execution["max_runs"],
                "max_retries": execution["max_retries"],
            }
            jobs.append(
                {
                    "id": job_id,
                    "identity": identity,
                    "config_path": str(config_path),
                    "observation_path": str(observation_path),
                    "log_path": str(log_path),
                    "timeout_seconds": execution["runner_timeout_seconds"],
                    "max_retries": execution["max_retries"],
                    "command": _render_command(
                        execution["runner_command"], command_values
                    ),
                }
            )

    payload = {
        "schema_version": 1,
        "status": "planned-not-executed",
        "preregistration_hash": content_hash(preregistration),
        "portfolio_catalog_hash": content_hash(portfolio_catalog),
        "output_root": str(output_root),
        "job_count": len(jobs),
        "jobs": jobs,
    }
    return {**payload, "plan_hash": content_hash(payload)}


def _validate_observation(job: dict[str, Any], payload: dict[str, Any]) -> Observation:
    expected = job["identity"]
    mismatches = {
        field: {"expected": expected_value, "actual": payload.get(field)}
        for field, expected_value in expected.items()
        if payload.get(field) != expected_value
    }
    if mismatches:
        raise ValueError(f"runner observation lock mismatch: {mismatches}")
    if payload.get("run_job_id") != job["id"]:
        raise ValueError("runner observation run_job_id mismatch")
    return Observation.from_dict(payload)


def _rebuild_observation_ledger(
    plan: dict[str, Any], state: dict[str, Any], observations_path: Path
) -> None:
    jobs = {job["id"]: job for job in plan["jobs"]}
    completed_ids = set(state.get("completed", {}))
    if not completed_ids <= set(jobs):
        raise ValueError("experiment state contains unknown completed job ids")
    if completed_ids & set(state.get("failed", {})):
        raise ValueError("experiment state marks the same job completed and failed")
    rows = []
    for job in plan["jobs"]:
        job_id = job["id"]
        if job_id not in completed_ids:
            continue
        observation_path = Path(job["observation_path"])
        if not observation_path.is_file():
            raise ValueError(f"completed job observation is missing: {job_id}")
        observation = load_structured(observation_path)
        _validate_observation(job, observation)
        expected_hash = state["completed"][job_id].get("observation_hash")
        if expected_hash != content_hash(observation):
            raise ValueError(f"completed job observation hash mismatch: {job_id}")
        rows.append(canonical_json(observation))
    observations_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = observations_path.with_suffix(observations_path.suffix + ".tmp")
    temporary.write_text("\n".join(rows) + ("\n" if rows else ""))
    temporary.replace(observations_path)


def execute_experiment_plan(
    plan_path: Path,
    state_path: Path,
    observations_path: Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """Execute a fixed command matrix and accept only lock-matching observations."""
    plan = load_structured(plan_path)
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    if plan.get("plan_hash") != content_hash(payload):
        raise ValueError("experiment plan hash mismatch")
    if state_path.exists():
        if not resume:
            raise ValueError("experiment state exists; pass resume for the same plan")
        state = load_structured(state_path)
        if state.get("plan_hash") != plan["plan_hash"]:
            raise ValueError("experiment state belongs to another plan")
        _rebuild_observation_ledger(plan, state, observations_path)
    else:
        if observations_path.exists():
            raise ValueError("observations already exist without a matching run state")
        state = {
            "schema_version": 1,
            "plan_hash": plan["plan_hash"],
            "completed": {},
            "failed": {},
            "attempts": {},
        }
    state.setdefault("attempts", {})

    for job in plan["jobs"]:
        job_id = job["id"]
        if job_id in state["completed"]:
            continue
        log_path = Path(job["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        max_attempts = 1 + int(job.get("max_retries", 0))
        while int(state["attempts"].get(job_id, 0)) < max_attempts:
            state["attempts"][job_id] = int(state["attempts"].get(job_id, 0)) + 1
            returncode: int | None = None
            try:
                result = subprocess.run(
                    job["command"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=int(job["timeout_seconds"]),
                )
                returncode = result.returncode
                log_path.write_text(result.stdout + result.stderr)
                if result.returncode != 0:
                    raise ValueError(f"runner exited with code {result.returncode}")
                observation_path = Path(job["observation_path"])
                if not observation_path.is_file():
                    raise ValueError("runner did not produce its observation artifact")
                observation_payload = load_structured(observation_path)
                _validate_observation(job, observation_payload)
            except subprocess.TimeoutExpired as error:
                log_path.write_text(f"{error.stdout or ''}{error.stderr or ''}")
                failure = f"runner timed out after {job['timeout_seconds']} seconds"
            except ValueError as error:
                failure = str(error)
            else:
                state["completed"][job_id] = {
                    "observation_path": str(observation_path),
                    "observation_hash": content_hash(observation_payload),
                    "attempts": state["attempts"][job_id],
                }
                state["failed"].pop(job_id, None)
                write_structured_atomic(state_path, state)
                _rebuild_observation_ledger(plan, state, observations_path)
                break
            state["failed"][job_id] = {
                "returncode": returncode,
                "error": failure,
                "log_path": str(log_path),
                "attempts": state["attempts"][job_id],
            }
            write_structured_atomic(state_path, state)

    result_payload = {
        **state,
        "status": (
            "complete"
            if len(state["completed"]) == int(plan["job_count"])
            else "partial"
        ),
        "completed_count": len(state["completed"]),
        "failed_count": len(state["failed"]),
        "job_count": plan["job_count"],
    }
    write_structured_atomic(state_path, result_payload)
    return result_payload
