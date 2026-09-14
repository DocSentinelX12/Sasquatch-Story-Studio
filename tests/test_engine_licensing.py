import pytest

from studio.engine_registry import license_record
from studio.licensing import CommercialStatus


def test_verified_engine_license_records_are_explicit():
    record = license_record("wan2.2")
    assert record.license_name == "Apache-2.0"
    assert record.commercial_status == CommercialStatus.ALLOWED
    assert record.official_source == "https://github.com/Wan-Video/Wan2.2"


def test_ltx_checkpoint_requires_commercial_review():
    record = license_record("ltx-video")
    assert record.commercial_status == CommercialStatus.REVIEW_REQUIRED
    with pytest.raises(RuntimeError):
        from studio.licensing import LicenseRegistry
        LicenseRegistry((record,)).require_commercial("ltx-video")
