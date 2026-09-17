"""Private audit adapter protocol and explicit allowlist registry."""

from __future__ import annotations

from typing import Protocol

from aspire.sim.cap.perception.observation_broker import SensorBundle
from .observations import FGObservation
from .targets import FGTarget


class AuditAdapter(Protocol):
    def observe(self, target: FGTarget, bundle: SensorBundle) -> FGObservation: ...


_BUILDERS = {}


def register_audit_adapter(name: str, builder) -> None:
    if name in _BUILDERS:
        raise ValueError(f"duplicate audit adapter: {name}")
    _BUILDERS[name] = builder


def build_audit_adapter(name: str | None, source):
    if name is None:
        return None
    if name == "franka-semantic-v1" and name not in _BUILDERS:
        import aspire.sim.cap.integrations.franka.fg_audit_adapter  # noqa: F401
    if name == "franka-semantic-v1" and name not in _BUILDERS:
        from aspire.sim.cap.integrations.franka import fg_audit_adapter  # noqa: F401
    if name not in _BUILDERS:
        raise ValueError(f"audit adapter is not registered: {name}")
    return _BUILDERS[name](source)
