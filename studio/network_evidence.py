"""Observed network capabilities used for distributed GPU placement."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkFabricObservation:
    interface: str
    transport: str
    link_speed_gbps: int
    rdma: bool
    gpu_direct_rdma: bool

    def __post_init__(self) -> None:
        if not self.interface.strip() or not self.transport.strip():
            raise ValueError("network interface and transport are required")
        if self.link_speed_gbps <= 0:
            raise ValueError("network link speed must be positive")
