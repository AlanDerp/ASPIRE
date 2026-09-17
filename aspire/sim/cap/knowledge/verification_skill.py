"""Frozen, publicly-triggered factual-grounding verification methods."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .serialization import content_hash, load_structured, write_structured_atomic


@dataclass(frozen=True)
class VerificationSkill:
    id: str
    version: str
    supported_predicates: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    public_trigger: dict[str, Any]
    observation_plan: tuple[dict[str, Any], ...]
    verifier_id: str
    thresholds: dict[str, Any]
    uncertainty_policy: dict[str, Any]
    contraindications: tuple[str, ...]
    development_evidence_refs: tuple[str, ...]
    audit_metrics_ref: str
    checkpoint_id: str
    status: str = "candidate"
    reviewed_by: str | None = None
    candidate_content_hash: str | None = None
    evaluation_content_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.id.startswith("verification-skill."):
            raise ValueError("verification skill id must use verification-skill.*")
        if not self.public_trigger:
            raise ValueError("verification skill requires a public trigger")
        if self.status not in {"candidate", "reviewed", "frozen"}:
            raise ValueError("unsupported verification skill lifecycle status")
        if self.status == "frozen" and not all((
            self.reviewed_by, self.candidate_content_hash,
            self.evaluation_content_hash, self.development_evidence_refs,
        )):
            raise ValueError("frozen verification skill requires review lineage")
        forbidden = str(asdict(self)).lower()
        for token in ("sim.data", "body_xpos", "_eval_predicate", "audit_mismatch"):
            if token in forbidden:
                raise ValueError(f"verification skill contains forbidden dependency: {token}")

    @property
    def content_hash(self) -> str:
        return content_hash(asdict(self))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationSkill":
        unknown = sorted(set(value) - {item.name for item in fields(cls)})
        if unknown:
            raise ValueError(f"unknown VerificationSkill fields: {unknown}")
        payload = dict(value)
        for name in ("supported_predicates", "required_capabilities", "observation_plan", "contraindications", "development_evidence_refs"):
            payload[name] = tuple(payload.get(name, ()))
        return cls(**payload)


def save_verification_skill(root: Path, skill: VerificationSkill) -> Path:
    path = root / "verification-skills" / skill.id / f"{skill.version}.yaml"
    write_structured_atomic(path, asdict(skill))
    return path


def load_verification_skill(path: Path) -> VerificationSkill:
    return VerificationSkill.from_dict(load_structured(path))
