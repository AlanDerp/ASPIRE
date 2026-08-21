# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Static fingerprints for task-specific skill code."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass


WORD_RE = re.compile(r"[a-z0-9]+")


class _ShapeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.tokens.append(type(node).__name__)
        super().generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        self.tokens.append(f"Constant:{type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> None:
        self.tokens.append("Name")

    def visit_arg(self, node: ast.arg) -> None:
        self.tokens.append("arg")


def _call_name(node: ast.Call) -> str | None:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return None


@dataclass(frozen=True)
class CodeFingerprint:
    code_hash: str
    ast_fingerprint: str
    api_calls: tuple[str, ...]


def fingerprint_code(code: str) -> CodeFingerprint:
    normalized = code.strip() + "\n"
    code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    try:
        tree = ast.parse(normalized)
    except SyntaxError as error:
        raise ValueError(f"skill code is not valid Python: {error}") from error

    visitor = _ShapeVisitor()
    visitor.visit(tree)
    shape = " ".join(visitor.tokens)
    ast_fingerprint = hashlib.sha256(shape.encode("utf-8")).hexdigest()
    calls = tuple(
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _call_name(node)) is not None
    )
    return CodeFingerprint(code_hash, ast_fingerprint, calls)


def text_tokens(*values: str) -> set[str]:
    return {token for value in values for token in WORD_RE.findall(value.lower())}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
