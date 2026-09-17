"""Append-only public/private FG artifact store."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from aspire.sim.cap.knowledge.serialization import append_jsonl


class FGStore:
    def __init__(self, public_root: Path, private_root: Path | None = None) -> None:
        self.public_root = public_root
        self.private_root = private_root

    @staticmethod
    def _payload(value: Any) -> Any:
        return asdict(value) if is_dataclass(value) else value

    @staticmethod
    def _append(path: Path, value: Any) -> None:
        append_jsonl(path, FGStore._payload(value))

    def append_public(self, relative: str, value: Any) -> None:
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError("public artifact path escapes trial root")
        self._append(self.public_root / relative, value)

    def append_private(self, relative: str, value: Any) -> None:
        if self.private_root is None:
            raise ValueError("private artifact store is not configured")
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError("private artifact path escapes trial root")
        self._append(self.private_root / relative, value)

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
