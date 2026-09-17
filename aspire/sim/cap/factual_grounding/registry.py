"""Typed allowlist of predicates and operators."""

from __future__ import annotations

from dataclasses import dataclass

from .targets import FGTarget


@dataclass(frozen=True)
class PredicateContract:
    name: str
    value_type: str
    requires_object: bool
    operators: tuple[str, ...]
    methods: tuple[str, ...]


class PredicateRegistry:
    def __init__(self) -> None:
        self._items: dict[str, PredicateContract] = {}

    def register(self, contract: PredicateContract) -> None:
        if contract.name in self._items:
            raise ValueError(f"duplicate predicate: {contract.name}")
        self._items[contract.name] = contract

    def validate(self, target: FGTarget) -> PredicateContract:
        contract = self._items.get(target.predicate)
        if contract is None:
            raise ValueError(f"unsupported predicate: {target.predicate}")
        if contract.value_type != target.value_type:
            raise ValueError("predicate value type mismatch")
        if contract.requires_object and target.object is None:
            raise ValueError("predicate requires an object")
        if target.operator not in contract.operators:
            raise ValueError("unsupported operator for predicate")
        return contract

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))


def default_registry() -> PredicateRegistry:
    registry = PredicateRegistry()
    registry.register(PredicateContract("held_by", "boolean", True, ("equals",), ("visual-held-by-v1",)))
    registry.register(PredicateContract("above", "number", True, ("gte", "gt"), ("depth-clearance-v1",)))
    registry.register(PredicateContract("contact", "boolean", True, ("equals",), ("multiview-contact-v1",)))
    return registry
