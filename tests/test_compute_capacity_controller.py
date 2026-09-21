from studio.compute_capacity_controller import ComputeCapacityController
from studio.compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass


class Adapter:
    def __init__(self, provider_id, count):
        self.provider = ComputeProvider(provider_id, provider_id)
        self.resources = tuple(
            ProviderResource(provider_id, f"{provider_id}-{i}", "test", ResourceCostClass.FREE)
            for i in range(count)
        )

    def discover(self):
        return self.resources

    def authorize(self, resource):
        return resource.transition(ProviderResourceState.AUTHORIZED)

    def acquire(self, resource, *, now):
        return resource.transition(ProviderResourceState.ACQUIRED, now=now)

    def release(self, resource):
        return resource.transition(ProviderResourceState.RELEASED)


def test_capacity_controller_does_not_treat_acquired_capacity_as_verified():
    controller = ComputeCapacityController((Adapter("a", 20),))

    result = controller.ensure_minimum(now=10)

    assert result.target_nodes == 12
    assert result.acquired_nodes == 20
    assert result.target_satisfied is False


def test_capacity_controller_distinguishes_acquired_from_verified_capacity():
    controller = ComputeCapacityController((Adapter("a", 12),))

    result = controller.ensure_minimum(now=10)

    assert result.acquired_nodes == 12
    assert result.verified_nodes == 0
    assert result.target_satisfied is False
