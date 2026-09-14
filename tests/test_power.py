from studio.power import PowerTelemetry, admit_power
from studio.resources import PowerResource, PowerSourceKind


def test_power_telemetry_updates_only_the_observed_source():
    source = PowerResource("battery-1", PowerSourceKind.BATTERY, 1200, 900, minimum_reserve_percent=20, state_of_charge_percent=80)
    telemetry = PowerTelemetry("battery-1", 100, 700, 600, state_of_charge_percent=65)
    updated = telemetry.apply(source)
    assert updated.available_watts == 700
    assert updated.sustained_watts == 600
    assert updated.minimum_reserve_percent == 20
    assert updated.state_of_charge_percent == 65


def test_power_admission_uses_only_healthy_observed_sources():
    sources = (
        PowerResource("grid", PowerSourceKind.GRID, 3000, 2500),
        PowerResource("solar", PowerSourceKind.SOLAR, 1200, 800),
        PowerResource("offline", PowerSourceKind.OTHER, 9999, 9999, healthy=False),
    )
    assert admit_power(sources, 3300).allowed
    denied = admit_power(sources, 3400)
    assert not denied.allowed
    assert denied.available_sustained_watts == 3300


def test_power_admission_rejects_negative_requests():
    try:
        admit_power((), -1)
    except ValueError as exc:
        assert "negative" in str(exc)
    else:
        raise AssertionError("negative power request must be rejected")
