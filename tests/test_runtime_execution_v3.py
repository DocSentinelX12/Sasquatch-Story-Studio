from studio.runtime_execution import RuntimeExecutionCoordinator


def test_runtime_execution_coordinator_exposes_evidence_gated_execute():
    assert callable(RuntimeExecutionCoordinator.execute)
