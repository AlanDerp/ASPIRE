"""Execute explicitly registered public probes under a fixed budget."""

from __future__ import annotations

from typing import Any, Callable


class ProbeRunner:
    def __init__(self, handlers: dict[str, Callable[[], Any]], max_runs: int) -> None:
        self.handlers = dict(handlers)
        self.max_runs = max_runs
        self.runs = 0

    def run(self, probe_id: str) -> Any:
        if probe_id not in self.handlers:
            raise ValueError(f"probe is not allowlisted: {probe_id}")
        if self.runs >= self.max_runs:
            raise RuntimeError("probe budget exhausted")
        self.runs += 1
        return self.handlers[probe_id]()
