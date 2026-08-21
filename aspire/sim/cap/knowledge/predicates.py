# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small, non-executable predicate language for applicability and guards."""

from __future__ import annotations

import re
from typing import Any


UNKNOWN = None
MAX_REGEX_LENGTH = 256


def _fact(facts: dict[str, Any], name: str) -> tuple[bool, Any]:
    if name in facts:
        return True, facts[name]
    current: Any = facts
    for part in name.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def evaluate(predicate: dict[str, Any] | None, facts: dict[str, Any]) -> bool | None:
    """Evaluate a predicate with three-valued logic.

    ``None`` means the predicate cannot be decided from the supplied facts.
    Unknown hard preconditions are rejected by callers; they are never treated
    as true implicitly.
    """
    if not predicate:
        return True
    if "all" in predicate:
        values = [evaluate(value, facts) for value in predicate["all"]]
        if False in values:
            return False
        return None if None in values else True
    if "any" in predicate:
        values = [evaluate(value, facts) for value in predicate["any"]]
        if True in values:
            return True
        return None if None in values else False
    if "not" in predicate:
        value = evaluate(predicate["not"], facts)
        return None if value is None else not value
    if "fact" not in predicate:
        raise ValueError(f"invalid predicate: {predicate}")

    exists, actual = _fact(facts, str(predicate["fact"]))
    op = predicate.get("op", "eq")
    expected = predicate.get("value")
    if op == "exists":
        return exists == bool(expected if "value" in predicate else True)
    if not exists:
        return None
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        if not isinstance(expected, (list, tuple, set, frozenset, str, dict)):
            raise ValueError("predicate 'in' requires a container value")
        return actual in expected
    if op == "contains":
        if not isinstance(actual, (list, tuple, set, frozenset, str, dict)):
            raise ValueError("predicate 'contains' requires a container fact")
        return expected in actual
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "regex":
        pattern = str(expected)
        if len(pattern) > MAX_REGEX_LENGTH:
            raise ValueError("predicate regex is too long")
        return re.search(pattern, str(actual)) is not None
    raise ValueError(f"unsupported predicate operator: {op}")
