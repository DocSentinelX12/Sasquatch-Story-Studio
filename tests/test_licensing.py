import pytest

from studio.licensing import CommercialStatus, LicenseRecord, LicenseRegistry


def record(subject_id="engine", status=CommercialStatus.ALLOWED, territory=None):
    return LicenseRecord(subject_id, "1.0", "https://example.com/official", "MIT", status, territory)


def test_license_registry_requires_explicit_record():
    registry = LicenseRegistry()
    with pytest.raises(KeyError):
        registry.require_commercial("missing")


def test_license_registry_allows_explicit_commercial_record():
    registry = LicenseRegistry((record(),))
    assert registry.require_commercial("engine").license_name == "MIT"


def test_review_required_is_not_treated_as_allowed():
    registry = LicenseRegistry((record(status=CommercialStatus.REVIEW_REQUIRED),))
    with pytest.raises(RuntimeError):
        registry.require_commercial("engine")


def test_territory_restriction_blocks_only_listed_territory():
    registry = LicenseRegistry((record(territory="EU,UK"),))
    assert not registry.get("engine").permits_commercial_use("EU")
    assert not registry.get("engine").permits_commercial_use("UK")
    assert registry.get("engine").permits_commercial_use("US")


def test_duplicate_license_subject_is_rejected():
    registry = LicenseRegistry((record(),))
    with pytest.raises(ValueError):
        registry.register(record())
