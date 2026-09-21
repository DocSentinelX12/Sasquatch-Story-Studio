"""Provider-scoped compute resource inventory.

The inventory is a control-plane registry, not a hardware verifier. Physical
capability remains authoritative in the existing GPU capability layer.
"""
from __future__ import annotations
from .compute_provider import ProviderResource, ProviderResourceState

class ComputeResourceInventory:
    def __init__(self, resources: tuple[ProviderResource, ...] = ()):
        self._resources: dict[tuple[str,str], ProviderResource] = {}
        self._resource_ids: dict[str,str] = {}
        for resource in resources:
            self.upsert(resource)

    def upsert(self, resource: ProviderResource) -> None:
        key=(resource.provider_id, resource.resource_id)
        existing_provider=self._resource_ids.get(resource.resource_id)
        if existing_provider is not None and existing_provider != resource.provider_id:
            raise ValueError("resource identity collision across providers")
        self._resources[key]=resource
        self._resource_ids[resource.resource_id]=resource.provider_id

    def get(self, provider_id: str, resource_id: str) -> ProviderResource:
        return self._resources[(provider_id, resource_id)]

    def snapshot(self) -> tuple[ProviderResource, ...]:
        return tuple(self._resources[key] for key in sorted(self._resources))

    def verified_resources(self) -> tuple[ProviderResource, ...]:
        return tuple(
            resource for resource in self.snapshot()
            if resource.state is ProviderResourceState.AVAILABLE
            and resource.worker_id
            and resource.capability_digest
        )
