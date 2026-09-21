from __future__ import annotations

from studio.gpu_capabilities import (
    GpuCapabilityName,
    GpuCapabilityState,
    admit_gpu_workload,
    derive_gpu_capabilities,
)
from studio.gpu_infrastructure import (
    GpuDeviceObservation,
    GpuHostObservation,
    GpuTelemetryEvidence,
    GpuTelemetryStatus,
    TelemetryValue,
)
from studio.gpu_topology import GpuTopologyEvidence
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.nccl_evidence import NCCLTestEvidence


NOW = 1_700_000_000
SHA = "a" * 64


def telemetry():
    return GpuTelemetryEvidence(
        source="nvml",
        collected_at=NOW,
        collector="pynvml",
        fields={
            "temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 61, "nvml", NOW),
        },
    )


def gpu(uuid: str, index: int = 0):
    return GpuDeviceObservation(
        index=index,
        uuid=uuid,
        name="NVIDIA Test GPU",
        memory_total_mib=81920,
        memory_used_mib=0,
        pci_bus_id=f"00000000:{17 + index:02x}:00.0",
        compute_capability="10.0",
        telemetry=telemetry(),
    )


def observation(*gpus, health=True, topology=None, nccl=None):
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=tuple(gpus),
        topology_text="topology" if topology else None,
        dcgm_available=health,
        dcgm_version="4.0" if health else None,
        health_json="Overall Health: Healthy" if health else None,
        topology_evidence=topology,
        nccl_evidence=nccl,
    )


def test_topology_evidence_is_bound_into_capability_digest():
    without_topology = derive_gpu_capabilities(observation(gpu("GPU-0")), now=NOW).digest()
    topology = GpuTopologyEvidence(
        gpu_uuids=("GPU-0",),
        gpu_matrix=(("X",),),
        cpu_affinity=(("GPU-0", "0-31"),),
        nic_paths=(),
        raw_text_sha256=SHA,
    )
    with_topology = derive_gpu_capabilities(
        observation(gpu("GPU-0"), topology=topology),
        now=NOW,
    ).digest()

    assert with_topology != without_topology


def test_observed_gpu_is_identified_but_not_production_eligible():
    record = derive_gpu_capabilities(observation(gpu("GPU-0"), health=False), now=NOW).get("GPU-0")

    assert record.state(GpuCapabilityName.BASE_GPU) is GpuCapabilityState.IDENTIFIED
    assert record.state(GpuCapabilityName.HEALTH) is GpuCapabilityState.UNAVAILABLE
    assert not record.production_eligible


def test_healthy_single_gpu_becomes_eligible_when_engine_runtime_is_verified():
    record = derive_gpu_capabilities(
        observation(gpu("GPU-0")),
        now=NOW,
        engine_verifications={"blender": NOW},
    ).get("GPU-0")

    requirements = HardwareRequirements(min_gpu_count=1)
    selected = admit_gpu_workload(
        requirements,
        derive_gpu_capabilities(
            observation(gpu("GPU-0")),
            now=NOW,
            engine_verifications={"blender": NOW},
        ),
        selected_gpu_uuids=("GPU-0",),
        now=NOW,
        required_engine_id="blender",
    )

    assert record.state(GpuCapabilityName.ENGINE_RUNTIME) is GpuCapabilityState.VERIFIED
    assert selected == ("GPU-0",)


def test_missing_health_cannot_produce_production_eligibility():
    capabilities = derive_gpu_capabilities(observation(gpu("GPU-0"), health=False), now=NOW)
    record = capabilities.get("GPU-0")

    assert record.state(GpuCapabilityName.HEALTH) is GpuCapabilityState.UNAVAILABLE
    assert not record.production_eligible


def test_missing_topology_cannot_satisfy_same_nvlink_requirement():
    capabilities = derive_gpu_capabilities(observation(gpu("GPU-0"), gpu("GPU-1", 1)), now=NOW, engine_verifications={"test": NOW})
    requirements = HardwareRequirements(
        min_gpu_count=2,
        placement=GpuPlacement.SAME_NVLINK_DOMAIN,
    )

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0", "GPU-1"),
        now=NOW,
    ) == ()


def test_missing_nccl_cannot_satisfy_multi_gpu_requirement():
    capabilities = derive_gpu_capabilities(observation(gpu("GPU-0"), gpu("GPU-1", 1)), now=NOW, engine_verifications={"test": NOW})
    requirements = HardwareRequirements(min_gpu_count=2, require_nccl=True)

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0", "GPU-1"),
        now=NOW,
    ) == ()


def test_missing_gpu_direct_evidence_cannot_satisfy_gpu_direct_requirement():
    capabilities = derive_gpu_capabilities(observation(gpu("GPU-0")), now=NOW, engine_verifications={"test": NOW})
    requirements = HardwareRequirements(require_gpu_direct_network=True)

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0",),
        now=NOW,
    ) == ()


def test_stale_health_evidence_cannot_satisfy_current_admission():
    capabilities = derive_gpu_capabilities(
        observation(gpu("GPU-0")),
        now=NOW + 61,
        freshness_window_seconds=60,
    )

    assert capabilities.get("GPU-0").state(GpuCapabilityName.HEALTH) is GpuCapabilityState.STALE


def test_failed_health_invalidates_only_health_and_preserves_identity():
    capabilities = derive_gpu_capabilities(
        observation(gpu("GPU-0"), health=False),
        now=NOW,
    )
    record = capabilities.get("GPU-0")

    assert record.state(GpuCapabilityName.BASE_GPU) is GpuCapabilityState.IDENTIFIED
    assert record.state(GpuCapabilityName.HEALTH) is GpuCapabilityState.UNAVAILABLE


def test_multi_gpu_nccl_evidence_must_cover_exact_selected_gpu_set():
    nccl = NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256=SHA,
        command=("all_reduce_perf",),
        exit_code=0,
        output_sha256=SHA,
        gpu_uuids=("GPU-0",),
        topology_digest=SHA,
    )
    capabilities = derive_gpu_capabilities(
        observation(gpu("GPU-0"), gpu("GPU-1", 1), nccl=nccl),
        now=NOW,
        engine_verifications={"test": NOW},
    )
    requirements = HardwareRequirements(min_gpu_count=2, require_nccl=True)

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0", "GPU-1"),
        now=NOW,
    ) == ()


def test_single_gpu_workload_does_not_require_nccL_without_explicit_requirement():
    capabilities = derive_gpu_capabilities(observation(gpu("GPU-0")), now=NOW, engine_verifications={"blender": NOW})
    requirements = HardwareRequirements(min_gpu_count=1)

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0",),
        now=NOW,
        required_engine_id="blender",
    ) == ("GPU-0",)


def test_failed_nccl_evidence_invalidates_only_nccl_capability():
    failed_nccl = NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256=SHA,
        command=("all_reduce_perf",),
        exit_code=1,
        output_sha256=SHA,
        gpu_uuids=("GPU-0", "GPU-1"),
        topology_digest=SHA,
    )
    capabilities = derive_gpu_capabilities(
        observation(gpu("GPU-0"), gpu("GPU-1", 1), nccl=failed_nccl),
        now=NOW,
        engine_verifications={"test": NOW},
    )

    assert capabilities.get("GPU-0").state(GpuCapabilityName.NCCL) is GpuCapabilityState.FAILED
    assert capabilities.get("GPU-0").state(GpuCapabilityName.HEALTH) is GpuCapabilityState.VERIFIED


def test_gpu_direct_capability_requires_exact_verified_gpu_set():
    capabilities = derive_gpu_capabilities(
        observation(gpu("GPU-0"), gpu("GPU-1", 1)),
        now=NOW,
        engine_verifications={"test": NOW},
        gpu_direct_gpu_sets=(("GPU-0", "GPU-1"),),
    )
    requirements = HardwareRequirements(
        min_gpu_count=2,
        require_gpu_direct_network=True,
    )

    assert admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=("GPU-0", "GPU-1"),
        now=NOW,
    ) == ("GPU-0", "GPU-1")



def test_non_multi_node_admission_rejects_cross_worker_gpu_selection():
    first = derive_gpu_capabilities(observation(gpu("GPU-0")), now=NOW)
    second_obs = GpuHostObservation(
        worker_id="worker-b",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(gpu("GPU-1"),),
        topology_text=None,
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Healthy",
    )
    second = derive_gpu_capabilities(second_obs, now=NOW)
    from studio.gpu_capabilities import GpuCapabilitySet
    combined = GpuCapabilitySet(first.records + second.records)

    assert admit_gpu_workload(
        HardwareRequirements(min_gpu_count=2),
        combined,
        selected_gpu_uuids=("GPU-0", "GPU-1"),
        now=NOW,
    ) == ()
