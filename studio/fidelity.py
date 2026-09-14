"""Story fidelity checks that fail closed when required source facts are absent."""
from dataclasses import dataclass
from .models import EpisodePlan

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
    return FidelityReport(not missing and not extras, missing, extras)

def validate_episode_plan_fidelity(plan: EpisodePlan, approved_extra_event_ids: set[str] | None = None) -> FidelityReport:
    required = {event.id for scene in plan.scenes for event in scene.events if event.required}
    represented = {event_id for scene in plan.scenes for shot in scene.shots for event_id in shot.required_events}
    report = compare_required_events(required_event_ids=required, represented_event_ids=represented, approved_extra_event_ids=approved_extra_event_ids)
    if not report.passed:
        return report
    return FidelityReport(True, notes=("Every required canonical event is represented by at least one shot.",))
