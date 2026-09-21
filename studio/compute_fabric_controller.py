"""Unified control-plane reconciliation for provider resources and verified workers.

This is the orchestration seam that keeps acquisition/provisioning, worker
verification, canonical GPU capability admission, and fabric inventory in one
pipeline. It does not fabricate or infer capacity.
"""
from __future__ import annotations

from dataclasses import dataclass

from .compute_fabric import ComputeFabricAdmission
from .compute_provider import ProviderResource
from .compute_provisioning import ProvisioningManager
from .compute_resources import ComputeResourceInventory
from .fabric_topology import FabricTopologyRegistry
from .worker_registry import WorkerRegistry


@dataclass(frozen=True)
class ComputeFabricReconciliation:
    available: int
    failed: tuple[tuple[str, str, str], ...]


class ComputeFabricController:
    """Reconcile acquired provider resources through the verified fabric boundary."""

    def __init__(
        self,
        *,
        provisioning: ProvisioningManager,
        workers: WorkerRegistry,
        inventory: ComputeResourceInventory,
        topology_registry: FabricTopologyRegistry | None = None,
    ) -> None:
        self.provisioning = provisioning
        self.workers = workers
        self.inventory = inventory
        self.admission = ComputeFabricAdmission(inventory, topology_registry)

    def reconcile(
        self,
        resources: tuple[ProviderResource, ...],
        *,
        now: int,
    ) -> ComputeFabricReconciliation:
        outcome = self.provisioning.provision(resources, now=now)
        failures = list(outcome.failed)
        available = 0

        for resource in outcome.resources:
            try:
                worker_id = resource.worker_id
                if not worker_id:
                    raise ValueError("provisioned resource is not bound to a worker")
                worker = self.workers.get(worker_id)
                self.admission.admit(resource, worker, now=now)
                available += 1
            except Exception as exc:
                failures.append((resource.provider_id, resource.resource_id, str(exc)))

        return ComputeFabricReconciliation(
            available=available,
            failed=tuple(sorted(failures)),
        )
