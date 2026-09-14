import pytest

from studio.cost_policy import ZERO_COST_POLICY, require_local_zero_cost, require_zero_cost


def test_zero_cost_policy_disallows_paid_paths_without_forcing_local_execution():
    assert ZERO_COST_POLICY.allow_paid_services is False
    assert ZERO_COST_POLICY.allow_paid_apis is False
    assert ZERO_COST_POLICY.require_local_execution is False


def test_zero_cost_policy_allows_legitimate_free_remote_execution():
    require_zero_cost(is_local=False)


def test_strict_local_helper_rejects_remote_execution():
    with pytest.raises(RuntimeError, match="local execution"):
        require_local_zero_cost(is_local=False)


def test_zero_cost_policy_rejects_paid_service():
    with pytest.raises(RuntimeError, match="paid hosted services"):
        require_zero_cost(is_local=False, uses_paid_service=True)


def test_zero_cost_policy_rejects_paid_api():
    with pytest.raises(RuntimeError, match="paid APIs"):
        require_zero_cost(is_local=False, uses_paid_api=True)
