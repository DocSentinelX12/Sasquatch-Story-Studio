"""Story fidelity checks that fail closed when required source facts are absent."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FidelityReport:
    passed: bool
    missing_required_events: tuple[str, ...] = ()
    unapproved_events: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def compare_required_events(*, required_event_ids: set[str], represented_event_ids: set[str], approved_extra_event_ids: set[str] | None = None) -> FidelityReport:
    approved = approved_extra_event_ids or set()
    missing = tuple(sorted(required_event_ids - represented_event_ids))
    extras = tuple(sorted(represented_event_ids - required_event_ids - approved))
    return FidelityReport(
        passed=not missing and not extras,
        missing_required_events=missing,
        unapproved_events=extras,
    )
