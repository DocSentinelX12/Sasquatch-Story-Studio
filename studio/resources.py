"""Self-hosted resource models for elastic, zero-recurring-cost production.

These models describe observed capacity. They do not pretend to create hardware,
power, or storage that does not actually exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class ResourceKind(StrEnum):
    COMPUTE = "compute"
    STORAGE = "storage"
    POWER = "power"


class PowerSourceKind(StrEnum):
    GRID = "grid"
    SOLAR = "solar"
    BATTERY = "battery"
    GENERATOR = "generator"
    OTHER = "other"


@dataclass(frozen=True)
class ComputeResource:
    id: str
    cpu_cores: int
    memory_bytes: int
    gpu_count: int = 0
    gpu_models: tuple[str, ...] = ()
    vram_bytes: int = 0
    capabilities: tuple[str, ...] = ()
    installed_engines: tuple[str, ...] = ()
    logical_slots: int = 1
    healthy: bool = True
    power_budget_watts: int | None = None
    scratch_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("compute resource id is required")
        if self.cpu_cores < 1 or self.memory_bytes < 1:
            raise ValueError("compute resources require positive CPU and memory")
        if self.gpu_count < 0 or self.vram_bytes < 0 or self.logical_slots < 1:
            raise ValueError("compute resource quantities cannot be negative")
        if self.power_budget_watts is not None and self.power_budget_watts < 0:
            raise ValueError("power budget cannot be negative")


@dataclass(frozen=True)
class StorageResource:
    id: str
    capacity_bytes: int
    free_bytes: int
    tier: str
    durable: bool = True
    healthy: bool = True
    read_bytes_per_second: int | None = None
    write_bytes_per_second: int | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.tier.strip():
            raise ValueError("storage id and tier are required")
        if self.capacity_bytes < 1 or self.free_bytes < 0 or self.free_bytes > self.capacity_bytes:
            raise ValueError("storage capacity/free space is invalid")


@dataclass(frozen=True)
class PowerResource:
    id: str
    kind: PowerSourceKind
    available_watts: int
    sustained_watts: int
    minimum_reserve_percent: float = 0.0
    state_of_charge_percent: float | None = None
    healthy: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("power source id is required")
        if self.available_watts < 0 or self.sustained_watts < 0:
            raise ValueError("power values cannot be negative")
        if not 0 <= self.minimum_reserve_percent <= 100:
            raise ValueError("minimum reserve must be 0..100 percent")
        if self.state_of_charge_percent is not None and not 0 <= self.state_of_charge_percent <= 100:
            raise ValueError("state of charge must be 0..100 percent")


@dataclass(frozen=True)
class ResourceSnapshot:
    compute: tuple[ComputeResource, ...] = ()
    storage: tuple[StorageResource, ...] = ()
    power: tuple[PowerResource, ...] = ()

    @property
    def healthy_compute_slots(self) -> int:
        return sum(r.logical_slots for r in self.compute if r.healthy)

    @property
    def healthy_power_watts(self) -> int:
        return sum(r.sustained_watts for r in self.power if r.healthy)

    @property
    def free_storage_bytes(self) -> int:
        return sum(r.free_bytes for r in self.storage if r.healthy)

    def capacity(self) -> Mapping[ResourceKind, int]:
        return {
            ResourceKind.COMPUTE: self.healthy_compute_slots,
            ResourceKind.STORAGE: self.free_storage_bytes,
            ResourceKind.POWER: self.healthy_power_watts,
        }
