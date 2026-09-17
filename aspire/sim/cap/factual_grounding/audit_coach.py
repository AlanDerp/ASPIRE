"""Development-only conversion of mismatches into reviewable probe proposals."""

from __future__ import annotations

from dataclasses import asdict

from aspire.sim.cap.perception.probe_planner import ProbeOption, select_probe
from .config import FactualGroundingConfig
from .diagnostics import diagnose
from .observations import FGComparison


def propose_probe(
    config: FactualGroundingConfig,
    comparison: FGComparison,
    options: tuple[ProbeOption, ...],
    *,
    remaining_budget: float,
) -> dict | None:
    if config.runtime_mode != "development_compare":
        raise PermissionError("Audit Coach is development_compare only")
    hypotheses = diagnose(comparison)
    if not hypotheses:
        return None
    selected = select_probe(options, remaining_budget=remaining_budget)
    if selected is None:
        return None
    return {
        "target_id": comparison.target_id,
        "probe": asdict(selected),
        "hypotheses": [asdict(item) for item in hypotheses],
        "audit_influenced": True,
        "status": "candidate",
    }
