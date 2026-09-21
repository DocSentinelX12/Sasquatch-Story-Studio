"""Provider identity and verified compute resource lifecycle contracts.

Provider adapters may discover and acquire resources, but a resource cannot
become usable capacity until authorization, provisioning, and hardware
capability verification have completed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ResourceCostClass(StrEnum):
    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


class ProviderResourceState(StrEnum):
    DISCOVERED = "discovered"
    AUTHORIZED = "authorized"
    ACQUIRED = "acquired"
    PROVISIONED = "provisioned"
    VERIFIED = "verified"
    AVAILABLE = "available"
    LEASED = "leased"
    EXECUTING = "executing"
    RESULT_VERIFIED = "result_verified"
    RELEASED = "released"
    UNAVAILABLE = "unavailable"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class ComputeProvider:
    provider_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.display_name.strip():
            raise ValueError("display_name is required")


@dataclass(frozen=True)
class ProviderResource:
    provider_id: str
    resource_id: str
    region: str
    cost_class: ResourceCostClass
    state: ProviderResourceState = ProviderResourceState.DISCOVERED
    discovered_at: int | None = None
    acquired_at: int | None = None
    expires_at: int | None = None
    worker_id: str | None = None
    capability_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.resource_id.strip():
            raise ValueError("provider and resource identity are required")
        if not self.region.strip():
            raise ValueError("resource region is required")
        if self.cost_class is None:
            raise ValueError("resource cost classification is required")
        if self.expires_at is not None and self.expires_at < 0:
            raise ValueError("resource expiry cannot be negative")
        if self.acquired_at is not None and self.acquired_at < 0:
            raise ValueError("resource acquisition time cannot be negative")

    def transition(self, target: ProviderResourceState, *, now: int | None = None) -> "ProviderResource":
        if now is not None and now < 0:
            raise ValueError("resource transition time cannot be negative")
        if self.expires_at is not None and now is not None and now > self.expires_at:
            if target not in {ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED, ProviderResourceState.RELEASED}:
                raise ValueError("resource expiry prevents transition to active capacity")

        allowed = {
            ProviderResourceState.DISCOVERED: {ProviderResourceState.AUTHORIZED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.AUTHORIZED: {ProviderResourceState.ACQUIRED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.ACQUIRED: {ProviderResourceState.PROVISIONED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.PROVISIONED: {ProviderResourceState.VERIFIED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.VERIFIED: {ProviderResourceState.AVAILABLE, ProviderResourceState.QUARANTINED, ProviderResourceState.UNAVAILABLE},
            ProviderResourceState.AVAILABLE: {ProviderResourceState.LEASED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED, ProviderResourceState.RELEASED},
            ProviderResourceState.LEASED: {ProviderResourceState.EXECUTING, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.EXECUTING: {ProviderResourceState.RESULT_VERIFIED, ProviderResourceState.UNAVAILABLE, ProviderResourceState.QUARANTINED},
            ProviderResourceState.RESULT_VERIFIED: {ProviderResourceState.RELEASED, ProviderResourceState.AVAILABLE},
            ProviderResourceState.RELEASED: {ProviderResourceState.AUTHORIZED, ProviderResourceState.ACQUIRED, ProviderResourceState.UNAVAILABLE},
            ProviderResourceState.UNAVAILABLE: {ProviderResourceState.AUTHORIZED, ProviderResourceState.ACQUIRED, ProviderResourceState.QUARANTINED},
            ProviderResourceState.QUARANTINED: {ProviderResourceState.AUTHORIZED, ProviderResourceState.RELEASED},
        }
        if target not in allowed[self.state]:
            raise ValueError(f"resource must transition through authorized/provisioned/verified before {target.value}")
        if target is ProviderResourceState.ACQUIRED and self.state is not ProviderResourceState.AUTHORIZED:
            raise ValueError("resource must be authorized before acquisition")
        if target is ProviderResourceState.PROVISIONED and self.state is not ProviderResourceState.ACQUIRED:
            raise ValueError("resource must be acquired before provisioning")
        if target is ProviderResourceState.VERIFIED and self.state is not ProviderResourceState.PROVISIONED:
            raise ValueError("resource must be provisioned before verification")
        if target is ProviderResourceState.AVAILABLE and self.state is not ProviderResourceState.VERIFIED:
            raise ValueError("resource must be verified before becoming available")
        if target is ProviderResourceState.ACQUIRED and self.cost_class is ResourceCostClass.UNKNOWN:
            raise ValueError("resource cost classification must be known before acquisition")

        updates: dict[str, object] = {"state": target}
        if target is ProviderResourceState.ACQUIRED:
            updates["acquired_at"] = now
        return replace(self, **updates)
