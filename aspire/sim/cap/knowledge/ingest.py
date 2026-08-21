# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Create immutable skill-code instances from executed task programs."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .fingerprint import fingerprint_code
from .models import SkillCodeInstance
from .serialization import sha256_file


def extract_code(code: str, symbol: str | None, line_range: str | None) -> str:
    if symbol and line_range:
        raise ValueError("choose either a symbol or a line range, not both")
    if line_range:
        try:
            start_text, end_text = line_range.split(":", 1)
            start, end = int(start_text), int(end_text)
        except (TypeError, ValueError) as error:
            raise ValueError("line range must use 1-based START:END syntax") from error
        lines = code.splitlines()
        if start < 1 or end < start or end > len(lines):
            raise ValueError(
                f"line range {line_range} is outside source lines 1:{len(lines)}"
            )
        return "\n".join(lines[start - 1 : end]).strip()
    if symbol is None:
        return code.strip()
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            segment = ast.get_source_segment(code, node)
            if segment:
                return segment.strip()
    raise ValueError(f"symbol not found in source code: {symbol}")


def build_instance(
    *,
    instance_id: str,
    vertical_capability: str,
    task: str,
    task_family: str,
    source_path: Path,
    goal: str,
    trigger: str = "",
    observed_effect: str = "",
    symbol: str | None = None,
    line_range: str | None = None,
    development_outcomes: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_partition: str = "development",
) -> SkillCodeInstance:
    if source_partition != "development":
        raise ValueError("held-out outcomes cannot be ingested as consolidation evidence")
    source = source_path.read_text()
    code = extract_code(source, symbol, line_range)
    fingerprint = fingerprint_code(code)
    return SkillCodeInstance(
        id=instance_id,
        vertical_capability=vertical_capability,
        task=task,
        task_family=task_family,
        source_code_path=str(source_path),
        source_code_sha256=sha256_file(source_path),
        code=code,
        goal=goal,
        trigger=trigger,
        observed_effect=observed_effect,
        code_hash=fingerprint.code_hash,
        ast_fingerprint=fingerprint.ast_fingerprint,
        api_calls=fingerprint.api_calls,
        development_outcomes=development_outcomes or {},
        provenance={**(provenance or {}), "partition": source_partition},
    )
