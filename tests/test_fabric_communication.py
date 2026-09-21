from studio.fabric_communication import CommunicationCommandResult, FabricCommunicationVerifier


def test_successful_distributed_nccl_command_produces_bound_evidence():
    result = CommunicationCommandResult(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("/opt/nccl-tests/all_reduce_perf", "-g", "2"),
        exit_code=0,
        stdout="NCCL all_reduce succeeded across worker-a and worker-b",
        stderr="",
    )
    evidence = FabricCommunicationVerifier.distributed_nccl_evidence(
        result,
        worker_gpu_mapping=(("worker-a", ("GPU-a",)), ("worker-b", ("GPU-b",))),
        topology_digests=(("worker-a", "b" * 64), ("worker-b", "c" * 64)),
        rendezvous_id="rv-001",
    )
    assert evidence.worker_ids == ("worker-a", "worker-b")
    assert evidence.gpu_uuids_by_worker == (("worker-a", ("GPU-a",)), ("worker-b", ("GPU-b",)))
    assert evidence.world_size == 2
    assert evidence.exit_code == 0
    assert len(evidence.output_sha256) == 64


def test_failed_distributed_nccl_command_is_rejected():
    result = CommunicationCommandResult(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("/opt/nccl-tests/all_reduce_perf", "-g", "2"),
        exit_code=1,
        stdout="",
        stderr="NCCL failure",
    )
    try:
        FabricCommunicationVerifier.distributed_nccl_evidence(
            result,
            worker_gpu_mapping=(("worker-a", ("GPU-a",)), ("worker-b", ("GPU-b",))),
            topology_digests=(("worker-a", "b" * 64), ("worker-b", "c" * 64)),
            rendezvous_id="rv-001",
        )
    except RuntimeError:
        return
    raise AssertionError("failed communication must never become valid evidence")
