"""Prompt fragments for AgentTurn v2."""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_INSTRUCTION = """Return exactly one JSON object using protocol_version agent-turn-v2.
Your first turn must include a versioned plan, an FG patch with required task anchors,
and an action. Later actions use turn_kind action.
Do not wrap JSON in Markdown."""


def planning_instruction(
    requirements_text: str,
    capability_manifest: tuple[dict[str, Any], ...],
    allowed_probes: tuple[str, ...],
    *,
    feedback_visible: bool = True,
) -> str:
    """Build the public, versioned planning contract shown to the Actor."""
    return (
        PROTOCOL_INSTRUCTION
        + "\nTask requirements:\n"
        + requirements_text
        + "\nAllowed verification capabilities:\n"
        + json.dumps(capability_manifest, ensure_ascii=False, sort_keys=True)
        + "\nAllowed public probes: "
        + json.dumps(allowed_probes, ensure_ascii=False)
        + (
            "\nUse finish_request only after the public FG projection shows all "
            "required completion anchors satisfied. Every later control turn must "
            "set based_on_snapshot to that projection's latest snapshot hash."
            if feedback_visible
            else "\nFG runs in shadow mode. Request finish from public task evidence; "
            "shadow verdicts are recorded but do not gate control."
        )
    )


def protocol_error_prompt(code: str, message: str, repairs_left: int) -> str:
    return (
        f"AgentTurn rejected: {code}: {message}. No action was executed. "
        f"Return one corrected AgentTurn JSON object; repair attempts remaining: {repairs_left}."
    )
