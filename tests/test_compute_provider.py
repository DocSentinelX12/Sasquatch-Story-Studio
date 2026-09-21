from __future__ import annotations

import pytest

from studio.compute_provider import (
    ComputeProvider,
    ProviderResource,
    ProviderResourceState,
    ResourceCostClass,
)


def test_provider_resource_requires_authorization_before_acquisition():
    provider = ComputeProvider(provider_id="provider-a", display_name="Provider A")
    resource = ProviderResource(
        provider_id=provider.provider_id,
        resource_id="gpu-a-1",
        region="test-region",
        cost_class=ResourceCostClass.FREE,
    )

    assert resource.state is ProviderResourceState.DISCOVERED

    with pytest.raises(ValueError, match="authorized"):
        resource.transition(ProviderResourceState.ACQUIRED)


def test_provider_resource_can_progress_to_available_only_after_provisioning_and_verification():
    provider = ComputeProvider(provider_id="provider-a", display_name="Provider A")
    resource = ProviderResource(
        provider_id=provider.provider_id,
        resource_id="gpu-a-1",
        region="test-region",
        cost_class=ResourceCostClass.FREE,
    )

    resource = resource.transition(ProviderResourceState.AUTHORIZED)
    resource = resource.transition(ProviderResourceState.ACQUIRED)
    resource = resource.transition(ProviderResourceState.PROVISIONED)
    resource = resource.transition(ProviderResourceState.VERIFIED)
    resource = resource.transition(ProviderResourceState.AVAILABLE)

    assert resource.state is ProviderResourceState.AVAILABLE


def test_resource_expiry_cannot_be_available():
    provider = ComputeProvider(provider_id="provider-a", display_name="Provider A")
    resource = ProviderResource(
        provider_id=provider.provider_id,
        resource_id="gpu-a-1",
        region="test-region",
        cost_class=ResourceCostClass.FREE,
        expires_at=100,
    ).transition(ProviderResourceState.AUTHORIZED).transition(ProviderResourceState.ACQUIRED)

    with pytest.raises(ValueError, match="expiry"):
        resource.transition(ProviderResourceState.PROVISIONED, now=101)


def test_free_resource_must_be_explicitly_classified():
    with pytest.raises(ValueError, match="cost"):
        ProviderResource(
            provider_id="provider-a",
            resource_id="gpu-a-1",
            region="test-region",
            cost_class=None,
        )
