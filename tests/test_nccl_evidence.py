from studio.nccl_evidence import NCCLTestEvidence, validate_nccl_evidence


def test_nccl_evidence_is_explicit_and_not_implied_by_gpu_count():
    evidence = NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("/opt/nccl-tests/all_reduce_perf", "-g", "8"),
        exit_code=0,
        output_sha256="b" * 64,
        gpu_uuids=("GPU-0", "GPU-1"),
        topology_digest="c" * 64,
    )
    validate_nccl_evidence(evidence)
    assert evidence.exit_code == 0


def test_nonzero_nccl_result_is_not_valid_evidence():
    evidence = NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("/opt/nccl-tests/all_reduce_perf", "-g", "2"),
        exit_code=1,
        output_sha256="b" * 64,
        gpu_uuids=("GPU-0", "GPU-1"),
        topology_digest="c" * 64,
    )
    try:
        validate_nccl_evidence(evidence)
    except RuntimeError:
        return
    raise AssertionError("failed NCCL evidence must be rejected")
