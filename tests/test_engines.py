from studio.engine_registry import CATALOG_ENGINES, VERIFIED_ENGINES, catalog_engines_for, get_catalog_engine, get_engine, verified_engine
from studio.production import ProductionRequest, ProductionRouter


def test_catalog_contains_curated_quality_engines_without_claiming_verification():
    assert CATALOG_ENGINES
    assert all(e.quality_tier != "generic" for e in CATALOG_ENGINES)
    assert all(e.official_source.startswith("https://github.com/") for e in CATALOG_ENGINES)
    assert VERIFIED_ENGINES == ()


def test_video_generation_catalog_has_candidates_but_no_unearned_verified_choices():
    assert {"wan2.1", "ltx-video"}.issubset({e.id for e in catalog_engines_for("video_generation")})
    assert {e.id for e in VERIFIED_ENGINES}.isdisjoint({"wan2.1", "ltx-video"})


def test_catalog_lookup_does_not_imply_production_verification():
    assert get_catalog_engine("wan2.2").id == "wan2.2"
    try:
        get_engine("wan2.2")
    except KeyError as exc:
        assert "not runtime verified" in str(exc.value)
    else:
        raise AssertionError("unverified catalog engine accepted as production engine")


def test_verified_engine_requires_real_evidence_fields():
    engine = verified_engine(
        "wan2.2",
        runtime_evidence="runtime-check-001",
        license_evidence="license-check-001",
        checkpoint_evidence="checkpoint-sha256-001",
    )
    assert engine.runtime_verified and engine.license_verified and engine.checkpoint_verified
    assert engine.verification_evidence


def test_verified_engine_rejects_missing_evidence():
    try:
        verified_engine("wan2.2", runtime_evidence="", license_evidence="x", checkpoint_evidence="y")
    except ValueError:
        return
    raise AssertionError("missing verification evidence accepted")


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
