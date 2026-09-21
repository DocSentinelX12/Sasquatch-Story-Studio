"""Provider-agnostic provisioning boundary.

Provisioning is intentionally separate from acquisition. It never asserts
hardware capability. Worker verification must advance a provisioned resource
to verified through the existing capability authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .compute_provider import ProviderResource, ProviderResourceState

class ResourceProvisioner(Protocol):
    def provision(self, resource: ProviderResource, *, now: int) -> ProviderResource: ...

@dataclass(frozen=True)
class ProvisioningOutcome:
    resources: tuple[ProviderResource, ...]
    failed: tuple[tuple[str,str,str], ...]

class ProvisioningManager:
    def __init__(self, provisioner: ResourceProvisioner):
        self.provisioner=provisioner

    def provision(self, resources: tuple[ProviderResource, ...], *, now: int) -> ProvisioningOutcome:
        if now < 0: raise ValueError("now cannot be negative")
        ready=[]
        failed=[]
        for resource in resources:
            if resource.state is not ProviderResourceState.ACQUIRED:
                failed.append((resource.provider_id,resource.resource_id,"resource is not acquired"))
                continue
            try:
                updated=self.provisioner.provision(resource,now=now)
                if updated.state is not ProviderResourceState.PROVISIONED:
                    raise ValueError("provisioner must return a provisioned resource")
                ready.append(updated)
            except Exception as exc:
                failed.append((resource.provider_id,resource.resource_id,str(exc)))
        return ProvisioningOutcome(tuple(ready),tuple(failed))
