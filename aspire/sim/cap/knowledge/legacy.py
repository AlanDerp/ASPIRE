# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read-only audit of pre-forest Markdown skills.

Legacy recipes lack execution provenance, outcomes, and frozen checkpoint
membership. The audit therefore inventories migration candidates but never
creates knowledge nodes.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .serialization import sha256_file


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"```(?P<language>[A-Za-z0-9_+-]*)\s*\n(?P<body>.*?)```", re.DOTALL)


@dataclass(frozen=True)
class LegacySkillAudit:
    path: str
    sha256: str
    headings: tuple[str, ...]
    code_blocks: int
    python_blocks: int
    parseable_python_blocks: int
    disposition: str = "requires-instance-provenance"


def audit_markdown(path: Path, *, relative_to: Path | None = None) -> LegacySkillAudit:
    text = path.read_text(errors="replace")
    fences = list(FENCE_RE.finditer(text))
    headings = tuple(
        match.group(2).strip() for match in HEADING_RE.finditer(FENCE_RE.sub("", text))
    )
    python_blocks = [
        match.group("body")
        for match in fences
        if match.group("language").lower() in {"py", "python"}
    ]
    parseable = 0
    for block in python_blocks:
        try:
            ast.parse(block)
        except SyntaxError:
            continue
        parseable += 1
    display_path = path
    if relative_to is not None:
        try:
            display_path = path.resolve().relative_to(relative_to.resolve())
        except ValueError:
            pass
    return LegacySkillAudit(
        path=str(display_path),
        sha256=sha256_file(path),
        headings=headings,
        code_blocks=len(fences),
        python_blocks=len(python_blocks),
        parseable_python_blocks=parseable,
    )


def audit_legacy_library(root: Path, *, relative_to: Path | None = None) -> dict:
    files = sorted(path for path in root.glob("*.md") if path.is_file())
    audits = [audit_markdown(path, relative_to=relative_to) for path in files]
    return {
        "schema_version": 1,
        "source": str(root.resolve().relative_to(relative_to.resolve())) if relative_to else str(root),
        "files": [audit.__dict__ for audit in audits],
        "summary": {
            "markdown_files": len(audits),
            "code_blocks": sum(audit.code_blocks for audit in audits),
            "python_blocks": sum(audit.python_blocks for audit in audits),
            "parseable_python_blocks": sum(audit.parseable_python_blocks for audit in audits),
            "knowledge_nodes_created": 0,
        },
        "migration_rule": (
            "A legacy recipe becomes evidence only after its concrete code is executed, "
            "recorded with task/outcome provenance, and included in a frozen checkpoint."
        ),
    }
