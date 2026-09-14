"""Observed power telemetry and admission policy for local production."""
from __future__ import annotations

from dataclasses import dataclass

from .resources import PowerResource


@dataclass(frozen=True)
class PowerTelemetry:
    source_id: str
    observed_at: int
    available_watts: int
    sustained_watts: int
    state_of_charge_percent: float | None = None
    healthy: bool = True

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("power source id is required")
        if self.observed_at < 0:
            raise ValueError("telemetry timestamp cannot be negative")
        if self.available_watts < 0 or self.sustained_watts < 0:
            raise ValueError("power telemetry cannot be negative")
        if self.state_of_charge_percent is not None and not 0 <= self.state_of_charge_percent <= 100:
            raise ValueError("state of charge must be 0..100 percent")

    def apply(self, source: PowerResource) -> PowerResource:
        if source.id != self.source_id:
            raise ValueError("telemetry source does not match power resource")
        return PowerResource(
            id=source.id,
            kind=source.kind,
            available_watts=self.available_watts,
            sustained_watts=self.sustained_watts,
            minimum_reserve_percent=source.minimum_reserve_percent,
            state_of_charge_percent=self.state_of_charge_percent,
            healthy=self.healthy,
        )


@dataclass(frozen=True)
class PowerAdmission:
    allowed: bool
    available_sustained_watts: int
    requested_watts: int
    reason: str


def admit_power(resources: tuple[PowerResource, ...], requested_watts: int) -> PowerAdmission:
    if requested_watts < 0:
        raise ValueError("requested power cannot be negative")
    sustained = sum(source.sustained_watts for source in resources if source.healthy)
    allowed = sustained >= requested_watts
    return PowerAdmission(
        allowed=allowed,
        available_sustained_watts=sustained,
        requested_watts=requested_watts,
        reason="sufficient observed sustained power" if allowed else "insufficient observed sustained power",
    )
