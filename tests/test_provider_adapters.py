from studio.provider_adapters import ProviderAdapterRegistry
from studio.compute_provider import ComputeProvider

class Adapter:
    def __init__(self,pid):
        self.provider=ComputeProvider(pid,pid)
    def discover(self): return ()
    def authorize(self,r): return r
    def acquire(self,r,*,now): return r
    def release(self,r): return r

def test_registry_is_provider_scoped_and_deterministic():
    registry=ProviderAdapterRegistry((Adapter("z"),Adapter("a")))
    assert tuple(a.provider.provider_id for a in registry.snapshot()) == ("a","z")

def test_registry_rejects_duplicate_provider():
    registry=ProviderAdapterRegistry((Adapter("a"),))
    try: registry.register(Adapter("a"))
    except ValueError as exc: assert "already" in str(exc)
    else: raise AssertionError("duplicate provider accepted")
