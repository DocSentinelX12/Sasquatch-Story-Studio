"""Hard policy for a zero-recurring-cost production studio.

The studio may use free/open-source software, locally owned compute, and
legitimate free remote compute. It must never require a paid hosted API,
subscription, credit system, paid GPU rental, or metered generation service.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostPolicy:
    allow_paid_services: bool = False
    allow_paid_apis: bool = False
    require_local_execution: bool = False


ZERO_COST_POLICY = CostPolicy()


def require_zero_cost(
    *,
    is_local: bool,
    uses_paid_service: bool = False,
    uses_paid_api: bool = False,
) -> None:
    """Reject production paths that require recurring third-party spend.

    ``is_local`` is recorded for provenance and routing, but zero recurring
    cost does not imply local execution. Legitimate free remote workers are
    allowed when their own quota, availability, and provider policy permit it.
    """
    policy = ZERO_COST_POLICY
    if policy.require_local_execution and not is_local:
        raise RuntimeError("Zero-cost policy requires local execution")
    if not policy.allow_paid_services and uses_paid_service:
        raise RuntimeError("Zero-cost policy prohibits paid hosted services")
    if not policy.allow_paid_apis and uses_paid_api:
        raise RuntimeError("Zero-cost policy prohibits paid APIs")


def require_local_zero_cost(
    *,
    is_local: bool,
    uses_paid_service: bool = False,
    uses_paid_api: bool = False,
) -> None:
    """Backward-compatible strict helper for paths that explicitly require local execution."""
    if not is_local:
        raise RuntimeError("This execution path requires local execution")
    require_zero_cost(
        is_local=True,
        uses_paid_service=uses_paid_service,
        uses_paid_api=uses_paid_api,
    )
