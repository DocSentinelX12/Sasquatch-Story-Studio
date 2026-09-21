"""Elastic capacity target management without fabricating verified capacity."""
from __future__ import annotations

from dataclasses import dataclass

from .compute_acquisition import ComputeAcquisitionManager, ProviderAdapter
from .compute_provider import ProviderResource, ProviderResourceState


@dataclass(frozen=True)
class CapacitySnapshot:
    target_nodes: int
    acquired_nodes: int
    verified_nodes: int

    @property
    def target_satisfied(self) -> bool:
        return self.verified_nodes >= self.target_nodes


class ComputeCapacityController:
    MINIMUM_VERIFIED_NODES = 12

    def __init__(self, adapters: tuple[ProviderAdapter, ...], *, target_nodes: int = MINIMUM_VERIFIED_NODES):
        if target_nodes < self.MINIMUM_VERIFIED_NODES:
            raise ValueError("target_nodes cannot be below the 12-node minimum")
        self.target_nodes = target_nodes
        self.acquisition = ComputeAcquisitionManager(adapters)

    def ensure_minimum(self, *, now: int) -> CapacitySnapshot:
        resources = self.acquisition.acquire_free_capacity(
            minimum_nodes=self.target_nodes,
            now=now,
        )
        return self.snapshot(resources, target_nodes=self.target_nodes)

    @staticmethod
    def snapshot(resources: tuple[ProviderResource, ...], *, target_nodes: int = MINIMUM_VERIFIED_NODES) -> CapacitySnapshot:
        verified = sum(
            1
            for resource in resources
            if resource.state is ProviderResourceState.AVAILABLE
            and resource.worker_id
            and resource.capability_digest
        )
        return CapacitySnapshot(
            target_nodes=target_nodes,
            acquired_nodes=len(resources),
            verified_nodes=verified,
        )
