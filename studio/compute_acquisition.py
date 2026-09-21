"""Legitimate multi-provider compute discovery and acquisition.

Provider adapters are explicit boundaries. They may only return resources that
the provider actually exposes through the configured authorization path.
"""
from __future__ import annotations

from typing import Protocol

from .compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass


class ProviderAdapter(Protocol):
    provider: ComputeProvider

    def discover(self) -> tuple[ProviderResource, ...]:
        ...

    def authorize(self, resource: ProviderResource) -> ProviderResource:
        ...

    def acquire(self, resource: ProviderResource, *, now: int) -> ProviderResource:
        ...

    def release(self, resource: ProviderResource) -> ProviderResource:
        ...


class ComputeAcquisitionManager:
    def __init__(self, adapters: tuple[ProviderAdapter, ...]):
        provider_ids = [adapter.provider.provider_id for adapter in adapters]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider IDs must be unique")
        self.adapters = tuple(adapters)
        self.provider_errors: dict[str, str] = {}

    def acquire_free_capacity(self, *, minimum_nodes: int, now: int) -> tuple[ProviderResource, ...]:
        if minimum_nodes < 0:
            raise ValueError("minimum_nodes cannot be negative")
        if now < 0:
            raise ValueError("now cannot be negative")

        acquired: list[ProviderResource] = []
        self.provider_errors.clear()

        for adapter in self.adapters:
            try:
                discovered = adapter.discover()
                for resource in discovered:
                    if resource.provider_id != adapter.provider.provider_id:
                        raise ValueError("provider resource identity does not match adapter")
                    if resource.cost_class is not ResourceCostClass.FREE:
                        continue
                    if resource.state is ProviderResourceState.DISCOVERED:
                        resource = adapter.authorize(resource)
                    if resource.state is ProviderResourceState.AUTHORIZED:
                        resource = adapter.acquire(resource, now=now)
                    if resource.state is ProviderResourceState.ACQUIRED:
                        acquired.append(resource)
            except Exception as exc:
                self.provider_errors[adapter.provider.provider_id] = str(exc)

        if len(acquired) < minimum_nodes:
            return tuple(acquired)
        return tuple(acquired)
