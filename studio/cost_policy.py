"""Hard policy for a zero-recurring-cost production studio.

The studio may use free/open-source software and locally owned compute, but it must
never require a paid hosted API, subscription, credit system, or metered generation
service to complete a production run.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostPolicy:
    allow_paid_services: bool = False
    allow_paid_apis: bool = False
    require_local_execution: bool = True


ZERO_COST_POLICY = CostPolicy()


def require_local_zero_cost(*, is_local: bool, uses_paid_service: bool = False, uses_paid_api: bool = False) -> None:
    """Reject a production path that would require recurring third-party spend."""
    policy = ZERO_COST_POLICY
    if policy.require_local_execution and not is_local:
        raise RuntimeError("Zero-cost policy requires local execution")
    if not policy.allow_paid_services and uses_paid_service:
        raise RuntimeError("Zero-cost policy prohibits paid hosted services")
    if not policy.allow_paid_apis and uses_paid_api:
        raise RuntimeError("Zero-cost policy prohibits paid APIs")
