from __future__ import annotations

import hashlib

import pytest

from studio.distributed_gpu_scheduler import DistributedGpuScheduler, DistributedWorker
from studio.gpu_aware_scheduler import GpuAwareScheduler
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryEvidence, GpuTelemetryStatus, TelemetryValue
from studio.gpu_scheduler import select_gpus
from studio.gpu_topology import GpuTopologyEvidence
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.network_evidence import NetworkFabricObservation
from studio.resources import ComputeResource
from studio.scheduler import Job, JobRequirements, Scheduler
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


NOW = 1_700_000_000


def healthy_telemetry():
    return GpuTelemetryEvidence(
        source="nvml",
        collected_at=NOW,
        collector="pynvml",
        fields={
            "temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 60, "nvml", NOW),
        },
    )


def host_with_topology() -> GpuHostObservation:
    raw = """        GPU0 GPU1 GPU2 CPU Affinity NUMA Affinity
GPU0      X  NV2  SYS  0-31       0
GPU1    NV2    X  NV2  0-31       0
GPU2    SYS  NV2    X  0-31       0
"""
    gpus = tuple(
        GpuDeviceObservation(
            i,
            f"GPU-{i}",
            "NVIDIA Test GPU",
            81920,
            0,
            f"00000000:{17+i:02x}:00.0",
            "10.0",
            telemetry=healthy_telemetry(),
        )
        for i in range(3)
    )
    topology = GpuTopologyEvidence(
        gpu_uuids=("GPU-0", "GPU-1", "GPU-2"),
        gpu_matrix=(("X", "NV2", "SYS"), ("NV2", "X", "NV2"), ("SYS", "NV2", "X")),
        cpu_affinity=(("GPU-0", "0-31"), ("GPU-1", "0-31"), ("GPU-2", "0-31")),
        nic_paths=(),
        raw_text_sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=gpus,
        topology_text=raw,
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Healthy",
        topology_evidence=topology,
    )


def test_scheduler_filters_ineligible_gpu_before_selection():
    observation = host_with_topology()
    unhealthy = GpuHostObservation(
        worker_id=observation.worker_id,
        driver_version=observation.driver_version,
        cuda_supported_version=observation.cuda_supported_version,
        gpus=observation.gpus,
        topology_text=observation.topology_text,
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Failure",
        topology_evidence=observation.topology_evidence,
    )

    with pytest.raises(RuntimeError, match="free GPUs"):
        select_gpus(unhealthy, HardwareRequirements(min_gpu_count=1))


def test_scheduler_uses_canonical_topology_capability_not_raw_topology_text():
    observation = host_with_topology()
    misleading = GpuHostObservation(
        worker_id=observation.worker_id,
        driver_version=observation.driver_version,
        cuda_supported_version=observation.cuda_supported_version,
        gpus=observation.gpus,
        topology_text=observation.topology_text.replace("SYS", "NV2"),
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Healthy",
        topology_evidence=observation.topology_evidence,
    )

    with pytest.raises(RuntimeError, match="qualifying"):
        select_gpus(
            misleading,
            HardwareRequirements(min_gpu_count=3, placement=GpuPlacement.SAME_NVLINK_DOMAIN),
        )


def test_gpu_aware_scheduler_binds_selected_gpu_uuids_into_scheduler_lease():
    observation = host_with_topology()
    resource = ComputeResource(
        "resource-a",
        16,
        64 * 1024**3,
        gpu_count=3,
        vram_bytes=240 * 1024**3,
        logical_slots=3,
    )
    registry = WorkerRegistry((
        WorkerRecord("worker-a", resource, WorkerState.VERIFIED_AVAILABLE, hardware_observation=observation),
    ))
    scheduler = Scheduler((
        Job("job-a", JobRequirements(slots=2, hardware=HardwareRequirements(min_gpu_count=2))),
        Job("job-b", JobRequirements(slots=1, hardware=HardwareRequirements(min_gpu_count=1))),
    ))
    aware = GpuAwareScheduler(scheduler, registry)

    first = aware.choose_on_worker("worker-a", now=NOW)
    assert first is not None
    assert first.allocated_gpu_uuids == ("GPU-0", "GPU-1")

    second = aware.choose_on_worker("worker-a", now=NOW)
    assert second is not None
    assert second.allocated_gpu_uuids == ("GPU-2",)


def test_gpu_aware_scheduler_never_selects_busy_gpu_when_lower_lease_layer_knows_it_is_reserved():
    observation = host_with_topology()
    resource = ComputeResource(
        "resource-a",
        16,
        64 * 1024**3,
        gpu_count=3,
        vram_bytes=240 * 1024**3,
        logical_slots=3,
    )
    registry = WorkerRegistry((
        WorkerRecord("worker-a", resource, WorkerState.VERIFIED_AVAILABLE, hardware_observation=observation),
    ))
    scheduler = Scheduler((
        Job("job-a", JobRequirements(slots=1, hardware=HardwareRequirements(min_gpu_count=1))),
        Job("job-b", JobRequirements(slots=1, hardware=HardwareRequirements(min_gpu_count=1))),
    ))
    aware = GpuAwareScheduler(scheduler, registry)

    assert aware.choose_on_worker("worker-a", now=NOW) is not None
    assert aware.choose_on_worker("worker-a", now=NOW) is not None
    leased = scheduler.snapshot()
    assert {job.allocated_gpu_uuids for job in leased if job.state.value == "leased"} == {("GPU-0",), ("GPU-1",)}


def test_distributed_scheduler_preserves_distinct_worker_mapping_through_capability_gate():
    workers = []
    for suffix in ("a", "b"):
        host = host_with_topology()
        host = GpuHostObservation(
            worker_id=f"worker-{suffix}",
            driver_version=host.driver_version,
            cuda_supported_version=host.cuda_supported_version,
            gpus=(host.gpus[0],),
            topology_text=None,
            dcgm_available=True,
            dcgm_version="4.0",
            health_json="Overall Health: Healthy",
        )
        workers.append(
            DistributedWorker(
                worker_id=f"worker-{suffix}",
                hardware=host,
                network=NetworkFabricObservation("ib0", "rdma", 200, True, False),
            )
        )

    allocation = DistributedGpuScheduler(tuple(workers)).allocate(
        HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)
    )
    assert allocation.world_size == 2
    assert tuple(worker for worker, _ in allocation.gpus_by_worker) == ("worker-a", "worker-b")
