from studio.adapters import AdapterInfo, require_verified
from studio.fidelity import compare_required_events
from studio.release import evaluate_release


class Adapter:
    def __init__(self, verified):
        self.info = AdapterInfo("test", "1", "test", (), verified)


def test_unverified_adapter_is_blocked():
    try:
        require_verified(Adapter(False))
    except RuntimeError:
        return
    raise AssertionError("unverified adapter was accepted")


def test_fidelity_fails_on_missing_and_unapproved_events():
    report = compare_required_events(
        required_event_ids={"a", "b"},
        represented_event_ids={"a", "c"},
    )
    assert not report.passed
    assert report.missing_required_events == ("b",)
    assert report.unapproved_events == ("c",)


def test_release_requires_all_gates():
    decision = evaluate_release(qc_passed=True, fidelity_passed=True, human_approved=False)
    assert not decision.approved
    assert decision.reasons == ("human approval has not been recorded",)
