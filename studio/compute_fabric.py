"""Unified provider-to-worker GPU admission boundary.

This module is the integration seam between provider lifecycle, authenticated
worker verification, canonical GPU capability authority, resource inventory,
and fabric topology. It never fabricates hardware or provider capacity.
"""
from __future__ import annotations

from dataclasses import replace

from .compute_provider import ProviderResource, ProviderResourceState
from .compute_resources import ComputeResourceInventory
from .fabric_topology import FabricTopologyRecord, FabricTopologyRegistry
from .gpu_capabilities import derive_gpu_capabilities
from .worker_registry import WorkerRecord, WorkerState


class ComputeFabricAdmission:
    """Promote one provider resource only after canonical worker verification."""

    _ACTIVE_WORKER_STATES = {
        WorkerState.VERIFIED_AVAILABLE,
        WorkerState.VERIFIED_LIMITED,
    }

    def __init__(
        self,
        inventory: ComputeResourceInventory,
        topology_registry: FabricTopologyRegistry | None = None,
    ) -> None:
        self.inventory = inventory
        self.topology_registry = topology_registry

    def admit(
        self,
        resource: ProviderResource,
        worker: WorkerRecord,
        *,
        now: int,
    ) -> ProviderResource:
        if now < 0:
            raise ValueError("now cannot be negative")
        if resource.state is not ProviderResourceState.PROVISIONED:
            raise ValueError("provider resource must be provisioned before worker admission")
        if resource.expires_at is not None and now > resource.expires_at:
            raise ValueError("expired provider resource cannot be admitted")
        if resource.worker_id != worker.id:
            raise ValueError("provider resource worker identity does not match worker record")
        if worker.state not in self._ACTIVE_WORKER_STATES:
            raise ValueError("worker is not in an active verified state")
        observation = worker.hardware_observation
        if observation is None:
            raise ValueError("worker admission requires an authenticated hardware observation")
        if observation.worker_id != worker.id:
            raise ValueError("worker hardware observation identity does not match worker")
        capabilities = derive_gpu_capabilities(observation, now=now)
        capability_digest = capabilities.digest()
        if worker.gpu_capability_digest != capability_digest:
            raise ValueError("worker GPU capability digest does not match canonical derivation")
        if resource.capability_digest is not None and resource.capability_digest != capability_digest:
            raise ValueError("provider resource capability digest does not match worker evidence")
        if not all(capabilities.get(gpu.uuid).production_eligible for gpu in observation.gpus):
            raise ValueError("worker GPUs are not production eligible")

        admitted = replace(
            resource,
            worker_id=worker.id,
            capability_digest=capability_digest,
        ).transition(ProviderResourceState.VERIFIED, now=now).transition(
            ProviderResourceState.AVAILABLE,
            now=now,
        )
        self.inventory.upsert(admitted)

        if self.topology_registry is not None and observation.topology_evidence is not None:
            self.topology_registry.upsert(
                FabricTopologyRecord(
                    provider_id=admitted.provider_id,
                    resource_id=admitted.resource_id,
                    region=admitted.region,
                    worker_id=worker.id,
                    resource=admitted,
                    hardware_observation=observation,
                    observed_at=now,
                )
            )
        return admitted
