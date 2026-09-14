from studio.engine_registry import VERIFIED_ENGINES, engines_for, get_engine
from studio.production import ProductionRequest, ProductionRouter

def test_quality_registry_has_no_generic_engines():
    assert VERIFIED_ENGINES
    assert all(e.quality_tier != "generic" for e in VERIFIED_ENGINES)
    assert all(e.official_source.startswith("https://github.com/") for e in VERIFIED_ENGINES)

def test_video_generation_has_verified_choices():
    assert {"wan2.1", "ltx-video"}.issubset({e.id for e in engines_for("video_generation")})

def test_unknown_engine_rejected():
    try:
        get_engine("not-a-real-engine")
    except KeyError:
        return
    raise AssertionError("unknown engine accepted")

def test_unverified_adapter_never_executes():
    class Adapter:
        class Info:
            id, version, license = "test", "test", "unknown"
            capabilities, verified = ("animation",), False
        info = Info()
        def execute(self, request):
            raise AssertionError("unverified adapter executed")
    try:
        ProductionRouter([Adapter()]).execute(ProductionRequest("animate", {}, "hash"))
    except RuntimeError as exc:
        assert "verified" in str(exc).lower()
    else:
        raise AssertionError("unverified adapter accepted")
