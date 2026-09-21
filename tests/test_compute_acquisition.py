from studio.compute_acquisition import ComputeAcquisitionManager, ProviderAdapter
from studio.compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass


class FakeProvider(ProviderAdapter):
    def __init__(self, provider_id, resources):
        self.provider = ComputeProvider(provider_id, provider_id.title())
        self.resources = list(resources)
        self.authorized = False

    def discover(self):
        return tuple(self.resources)

    def authorize(self, resource):
        self.authorized = True
        return resource.transition(ProviderResourceState.AUTHORIZED)

    def acquire(self, resource, *, now):
        return resource.transition(ProviderResourceState.ACQUIRED, now=now)

    def release(self, resource):
        return resource.transition(ProviderResourceState.RELEASED)


def make_resources(provider_id, count):
    return tuple(
        ProviderResource(provider_id, f"{provider_id}-{i}", "test", ResourceCostClass.FREE)
        for i in range(count)
    )


def test_acquisition_combines_multiple_providers_to_reach_twelve_verified_capacity():
    a = FakeProvider("a", make_resources("a", 7))
    b = FakeProvider("b", make_resources("b", 5))
    manager = ComputeAcquisitionManager((a, b))

    acquired = manager.acquire_free_capacity(minimum_nodes=12, now=10)

    assert len(acquired) == 12
    assert {item.provider_id for item in acquired} == {"a", "b"}
    assert all(item.state is ProviderResourceState.ACQUIRED for item in acquired)


def test_acquisition_has_no_software_maximum():
    a = FakeProvider("a", make_resources("a", 125))
    manager = ComputeAcquisitionManager((a,))

    acquired = manager.acquire_free_capacity(minimum_nodes=100, now=10)

    assert len(acquired) == 125


def test_one_provider_failure_does_not_remove_other_provider_capacity():
    class BrokenProvider(FakeProvider):
        def discover(self):
            raise RuntimeError("provider unavailable")

    broken = BrokenProvider("broken", make_resources("broken", 20))
    healthy = FakeProvider("healthy", make_resources("healthy", 3))
    manager = ComputeAcquisitionManager((broken, healthy))

    acquired = manager.acquire_free_capacity(minimum_nodes=3, now=10)

    assert len(acquired) == 3
    assert {item.provider_id for item in acquired} == {"healthy"}
    assert manager.provider_errors["broken"] == "provider unavailable"
