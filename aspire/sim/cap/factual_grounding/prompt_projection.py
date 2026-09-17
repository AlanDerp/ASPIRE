"""Bounded public projection for the next Actor turn."""

from __future__ import annotations

from .observations import FGSnapshot
from .targets import FGSpec


def project_public(spec: FGSpec, snapshot: FGSnapshot, *, max_chars: int = 8000) -> str:
    by_id = {item.target_id: item for item in snapshot.public_verdicts}
    required = [item for item in spec.active.values() if item.criticality == "required"]
    others = [item for item in spec.active.values() if item.criticality != "required"]
    lines = [f"FG SPEC r{spec.revision} / snapshot {snapshot.public_hash}"]
    if snapshot.vdm_description:
        lines.extend([
            "[VDM EXECUTION DESCRIPTION]",
            snapshot.vdm_description,
            "[AGENT-DEFINED FG VERIFICATION]",
        ])
    lines.append("Required anchors:")
    for target in sorted(required, key=lambda item: item.id):
        verdict = by_id.get(target.id)
        state = verdict.state.upper() if verdict else "UNKNOWN"
        suffix = f", reason={verdict.reason_code}" if verdict and verdict.reason_code else ""
        if verdict and verdict.progress:
            suffix += f", progress={verdict.progress}"
        if verdict and verdict.confidence is not None:
            suffix += f", confidence={verdict.confidence:.3f}"
        if verdict and verdict.based_on:
            suffix += f", evidence={','.join(verdict.based_on)}"
        if verdict and verdict.next_probe_options:
            suffix += f", probes={','.join(verdict.next_probe_options)}"
        lines.append(f"- {target.id}: {state}{suffix}")
    optional_lines = []
    for target in sorted(others, key=lambda item: item.id):
        verdict = by_id.get(target.id)
        detail = ""
        if verdict and verdict.reason_code:
            detail += f", reason={verdict.reason_code}"
        if verdict and verdict.next_probe_options:
            detail += f", probes={','.join(verdict.next_probe_options)}"
        optional_lines.append(
            f"- {target.id}: {(verdict.state if verdict else 'unknown').upper()}{detail}"
        )
    base = "\n".join(lines)
    if optional_lines and len(base) + len("\nOther anchors:\n") + sum(map(len, optional_lines)) < max_chars:
        base += "\nOther anchors:\n" + "\n".join(optional_lines)
    blocked = [target.id for target in required if by_id.get(target.id) is None or by_id[target.id].state != "satisfied"]
    base += "\nHarness decision:\n- " + (f"FINISH is not admissible; unresolved: {', '.join(blocked)}" if blocked else "FINISH is admissible")
    if len(base) > max_chars:
        raise ValueError("required FG projection exceeds prompt budget")
    return base
