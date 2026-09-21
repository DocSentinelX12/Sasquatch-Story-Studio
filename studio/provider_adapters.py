"""Provider adapter boundary.

Adapters are intentionally abstract. Concrete implementations must use
legitimate configured provider APIs and must never manufacture capacity.
"""
from __future__ import annotations
from typing import Protocol
from .compute_provider import ComputeProvider, ProviderResource

class ProviderAdapter(Protocol):
    provider: ComputeProvider
    def discover(self) -> tuple[ProviderResource, ...]: ...
    def authorize(self, resource: ProviderResource) -> ProviderResource: ...
    def acquire(self, resource: ProviderResource, *, now: int) -> ProviderResource: ...
    def release(self, resource: ProviderResource) -> ProviderResource: ...

class ProviderAdapterRegistry:
    def __init__(self, adapters: tuple[ProviderAdapter, ...] = ()):
        self._adapters: dict[str, ProviderAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ProviderAdapter) -> None:
        provider_id=adapter.provider.provider_id
        if provider_id in self._adapters:
            raise ValueError(f"provider adapter already registered: {provider_id}")
        self._adapters[provider_id]=adapter

    def snapshot(self) -> tuple[ProviderAdapter, ...]:
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    def get(self, provider_id: str) -> ProviderAdapter:
        return self._adapters[provider_id]
