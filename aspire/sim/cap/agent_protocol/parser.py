"""Fail-closed JSON parser for AgentTurn v2."""

from __future__ import annotations

import json
from typing import Any

from .models import AgentTurn, ProtocolError


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_agent_turn(raw: str, *, max_bytes: int = 64_000) -> AgentTurn | ProtocolError:
    if len(raw.encode("utf-8")) > max_bytes:
        return ProtocolError("response-too-large", "AgentTurn exceeds the response budget")
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicates, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"invalid constant: {x}")))
        if not isinstance(value, dict):
            raise ValueError("AgentTurn must be a JSON object")
        return AgentTurn.from_dict(value)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return ProtocolError("invalid-agent-turn", str(error))
