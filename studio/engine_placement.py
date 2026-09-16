"""Explicit, evidence-backed placement contracts for production engines."""
from __future__ import annotations

from dataclasses import dataclass

from .hardware_requirements import HardwareRequirements


@dataclass(frozen=True)
class EnginePlacementContract:
    engine_id: str
    model_revision: str
    hardware: HardwareRequirements

    def __post_init__(self) -> None:
        if not self.engine_id.strip():
            raise ValueError("engine_id is required")
        if not self.model_revision.strip():
            raise ValueError("model_revision is required")


class EnginePlacementRegistry:
    """Registry deliberately has no guessed defaults for GPU placement."""

    def __init__(self, contracts: tuple[EnginePlacementContract, ...] = ()):
        self._contracts: dict[str, EnginePlacementContract] = {}
        for contract in contracts:
            self.register(contract)

    def register(self, contract: EnginePlacementContract) -> None:
        if contract.engine_id in self._contracts:
            raise ValueError(f"engine placement contract already exists: {contract.engine_id}")
        self._contracts[contract.engine_id] = contract

    def get(self, engine_id: str) -> EnginePlacementContract:
        try:
            return self._contracts[engine_id]
        except KeyError as exc:
            raise KeyError(f"no explicit hardware placement contract for engine: {engine_id}") from exc

    def snapshot(self) -> tuple[EnginePlacementContract, ...]:
        return tuple(self._contracts[key] for key in sorted(self._contracts))
