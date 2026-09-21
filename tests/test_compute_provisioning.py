from studio.compute_provisioning import ProvisioningManager, ProvisioningOutcome
from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass

class Provisioner:
    def provision(self, resource, *, now):
        return resource.transition(ProviderResourceState.PROVISIONED)

def r():
    return ProviderResource("p","r1","test",ResourceCostClass.FREE,ProviderResourceState.ACQUIRED)

def test_provisioning_advances_only_acquired_resources():
    result=ProvisioningManager(Provisioner()).provision((r(),),now=10)
    assert result.resources[0].state is ProviderResourceState.PROVISIONED
    assert result.failed == ()

def test_provisioning_isolates_failed_resource():
    class Broken:
        def provision(self, resource, *, now): raise RuntimeError("boot failed")
    result=ProvisioningManager(Broken()).provision((r(),),now=10)
    assert result.resources == ()
    assert result.failed == (("p","r1","boot failed"),)
