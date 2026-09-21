from studio.compute_resources import ComputeResourceInventory
from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass

def resource(provider, rid, state=ProviderResourceState.DISCOVERED, worker=None, digest=None):
    return ProviderResource(provider, rid, "test", ResourceCostClass.FREE, state, worker_id=worker, capability_digest=digest)

def test_inventory_reconciles_provider_resources_without_overwriting_other_providers():
    inv=ComputeResourceInventory()
    inv.upsert(resource("a","a1"))
    inv.upsert(resource("b","b1"))
    assert {r.provider_id for r in inv.snapshot()} == {"a","b"}
    inv.upsert(resource("a","a1",ProviderResourceState.ACQUIRED))
    assert inv.get("a","a1").state is ProviderResourceState.ACQUIRED

def test_only_available_worker_bound_resources_with_capability_digest_count_as_verified():
    inv=ComputeResourceInventory((
        resource("a","a1",ProviderResourceState.AVAILABLE,"w1","d"),
        resource("a","a2",ProviderResourceState.AVAILABLE,"w2"),
        resource("a","a3",ProviderResourceState.VERIFIED,"w3","d"),
    ))
    assert inv.verified_resources()==(inv.get("a","a1"),)

def test_inventory_rejects_cross_provider_identity_collision():
    inv=ComputeResourceInventory()
    inv.upsert(resource("a","same"))
    try:
        inv.upsert(resource("b","same"))
    except ValueError as exc:
        assert "provider" in str(exc)
    else:
        raise AssertionError("provider identity collision was accepted")
