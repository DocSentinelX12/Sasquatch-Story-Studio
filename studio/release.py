"""Fail-closed release gate."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseDecision:
    approved: bool
    reasons: tuple[str, ...]


def evaluate_release(*, qc_passed: bool, fidelity_passed: bool, human_approved: bool) -> ReleaseDecision:
    reasons: list[str] = []
    if not qc_passed:
        reasons.append("automated QC has not passed")
    if not fidelity_passed:
        reasons.append("story fidelity has not passed")
    if not human_approved:
        reasons.append("human approval has not been recorded")
    return ReleaseDecision(approved=not reasons, reasons=tuple(reasons))
