import pytest

from studio.distributed_gpu import (
    DistributedGpuAllocationState,
    DistributedGpuAllocator,
    DistributedNCCLEvidence,
    SQLiteDistributedGpuAllocationStore,
    GpuDirectNetworkEvidence,
)
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryEvidence, GpuTelemetryStatus, TelemetryValue
from studio.gpu_topology import GpuTopologyEvidence
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.nccl_evidence import NCCLTestEvidence
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def telemetry():
    return GpuTelemetryEvidence(
        source="fixture",
        collected_at=100,
        collector="test",
        fields={
            "temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 60, "fixture", 100),
        },
    )


def host(worker_id: str, start: int) -> GpuHostObservation:
    gpus = tuple(
        GpuDeviceObservation(
            index=index,
            uuid=f"{worker_id}-GPU-{index}",
            name="NVIDIA Test GPU",
            memory_total_mib=80 * 1024,
            memory_used_mib=0,
            pci_bus_id=f"0000:{start + index:02x}:00.0",
            compute_capability="9.0",
            telemetry=telemetry(),
        )
        for index in range(4)
    )
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="test-driver",
        cuda_supported_version="12.9",
        gpus=gpus,
        topology_text="observed",
        dcgm_available=True,
        dcgm_version="test",
        health_json="Overall Health: Healthy",
    )



def topology(worker_id: str) -> GpuTopologyEvidence:
    uuids = tuple(f"{worker_id}-GPU-{index}" for index in range(4))
    return GpuTopologyEvidence(
        gpu_uuids=uuids,
        gpu_matrix=tuple(tuple("NV4" if left != right else "X" for right in uuids) for left in uuids),
        cpu_affinity=tuple((uuid, "0-63") for uuid in uuids),
        nic_paths=tuple((uuid, "mlx5_0", "PIX") for uuid in uuids),
        raw_text_sha256="c" * 64,
    )

def registry(*worker_ids: str) -> WorkerRegistry:
    records = []
    for offset, worker_id in enumerate(worker_ids):
        records.append(
            WorkerRecord(
                worker_id,
                ComputeResource(
                    worker_id,
                    64,
                    256 * 1024**3,
                    gpu_count=4,
                    vram_bytes=320 * 1024**3,
                    logical_slots=4,
                    scratch_bytes=1 * 1024**12,
                    power_budget_watts=2000,
                ),
                WorkerState.VERIFIED_AVAILABLE,
                observed_at=100,
                observation_source="test",
                hardware_observation=host(worker_id, offset * 4),
            )
        )
    return WorkerRegistry(tuple(records))


def requirement(count: int = 8, *, nccl: bool = False, direct: bool = False) -> HardwareRequirements:
    return HardwareRequirements(
        min_gpu_count=count,
        min_vram_per_gpu_bytes=80 * 1024**3,
        min_total_vram_bytes=count * 80 * 1024**3,
        placement=GpuPlacement.MULTI_NODE,
        require_nccl=nccl,
        allow_multi_node=True,
        require_gpu_direct_network=direct,
    )


def local_nccl(worker_id: str) -> NCCLTestEvidence:
    return NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("all_reduce_perf",),
        exit_code=0,
        output_sha256="b" * 64,
        gpu_uuids=tuple(f"{worker_id}-GPU-{index}" for index in range(4)),
        topology_digest="c" * 64,
    )


def distributed_nccl(worker_ids: tuple[str, ...], allocation_gpu_uuids: tuple[tuple[str, tuple[str, ...]], ...]) -> DistributedNCCLEvidence:
    return DistributedNCCLEvidence(
        worker_ids=worker_ids,
        gpu_uuids_by_worker=allocation_gpu_uuids,
        world_size=sum(len(gpus) for _, gpus in allocation_gpu_uuids),
        command=("all_reduce_perf_mpi",),
        exit_code=0,
        output_sha256="d" * 64,
        rendezvous_id="rdzv-test",
        topology_digests=tuple((worker_id, "c" * 64) for worker_id in worker_ids),
    )


def test_multi_node_reservation_is_atomic_and_builds_complete_rank_map():
    allocator = DistributedGpuAllocator(registry("A", "B"))

    allocation = allocator.reserve("task-1", requirement(), now=100, lease_seconds=60)

    assert allocation.state is DistributedGpuAllocationState.RESERVED
    assert allocation.worker_ids == ("A", "B")
    assert allocation.world_size == 8
    assert allocation.node_count == 2
    assert tuple(rank.global_rank for rank in allocation.ranks) == tuple(range(8))
    assert tuple(rank.node_rank for rank in allocation.ranks) == (0, 0, 0, 0, 1, 1, 1, 1)
    assert tuple(rank.local_rank for rank in allocation.ranks) == (0, 1, 2, 3, 0, 1, 2, 3)
    assert len({(rank.worker_id, rank.gpu_uuid) for rank in allocation.ranks}) == 8

    second = allocator.try_reserve("task-2", requirement(2), now=100, lease_seconds=60)
    assert second is None


def test_multi_node_requires_two_workers_and_never_fabricates_capacity():
    allocator = DistributedGpuAllocator(registry("A"))

    with pytest.raises(RuntimeError, match="at least two"):
        allocator.reserve("task-1", requirement(4), now=100, lease_seconds=60)


def test_nccl_requirement_requires_exact_distributed_collective_evidence():
    registry_value = registry("A", "B")
    registry_value.update(
        WorkerRecord(
            "A",
            registry_value.get("A").resource,
            WorkerState.VERIFIED_AVAILABLE,
            observed_at=100,
            observation_source="test",
            hardware_observation=GpuHostObservation(
                worker_id="A",
                driver_version="test-driver",
                cuda_supported_version="12.9",
                gpus=registry_value.get("A").hardware_observation.gpus,
                topology_text="observed",
                dcgm_available=True,
                dcgm_version="test",
                health_json="Overall Health: Healthy",
                nccl_evidence=local_nccl("A"),
                topology_evidence=topology("A"),
            ),
        )
    )
    registry_value.update(
        WorkerRecord(
            "B",
            registry_value.get("B").resource,
            WorkerState.VERIFIED_AVAILABLE,
            observed_at=100,
            observation_source="test",
            hardware_observation=GpuHostObservation(
                worker_id="B",
                driver_version="test-driver",
                cuda_supported_version="12.9",
                gpus=registry_value.get("B").hardware_observation.gpus,
                topology_text="observed",
                dcgm_available=True,
                dcgm_version="test",
                health_json="Overall Health: Healthy",
                nccl_evidence=local_nccl("B"),
                topology_evidence=topology("B"),
            ),
        )
    )
    allocator = DistributedGpuAllocator(registry_value)
    with pytest.raises(RuntimeError, match="distributed NCCL evidence"):
        allocator.reserve("task-1", requirement(nccl=True), now=100, lease_seconds=60)

    planned = allocator.plan("task-1", requirement(nccl=True), now=100, lease_seconds=60)
    evidence = distributed_nccl(
        planned.worker_ids,
        tuple((worker_id, planned.gpus_by_worker_map[worker_id]) for worker_id in planned.worker_ids),
    )
    allocation = allocator.reserve("task-1", requirement(nccl=True), now=100, lease_seconds=60, distributed_nccl=evidence)
    assert allocation.state is DistributedGpuAllocationState.RESERVED


def test_gpu_direct_requirement_requires_explicit_peer_evidence_for_every_worker_pair():
    allocator = DistributedGpuAllocator(registry("A", "B"))
    with pytest.raises(RuntimeError, match="GPU-direct"):
        allocator.reserve("task-1", requirement(direct=True), now=100, lease_seconds=60)

    planned = allocator.plan("task-1", requirement(direct=True), now=100, lease_seconds=60)
    evidence = GpuDirectNetworkEvidence(
        worker_pairs=(("A", "B"),),
        gpu_pairs=(("A", planned.gpus_by_worker_map["A"][0], "B", planned.gpus_by_worker_map["B"][0]),),
        transport="RDMA",
        command=("peer-memory-test",),
        exit_code=0,
        output_sha256="e" * 64,
    )
    allocation = allocator.reserve("task-1", requirement(direct=True), now=100, lease_seconds=60, gpu_direct_network=evidence)
    assert allocation.state is DistributedGpuAllocationState.RESERVED
    assert allocation.gpu_direct_network == evidence


def test_expiry_releases_exact_gpu_reservations():
    allocator = DistributedGpuAllocator(registry("A", "B"))
    allocation = allocator.reserve("task-1", requirement(), now=100, lease_seconds=10)

    assert allocator.expire(110) == (allocation.allocation_id,)
    assert allocator.get(allocation.allocation_id).state is DistributedGpuAllocationState.EXPIRED
    assert allocator.try_reserve("task-2", requirement(), now=111, lease_seconds=10) is not None


def test_completion_requires_fencing_epoch():
    allocator = DistributedGpuAllocator(registry("A", "B"))
    allocation = allocator.reserve("task-1", requirement(), now=100, lease_seconds=60)

    with pytest.raises(PermissionError, match="fencing"):
        allocator.complete(allocation.allocation_id, allocation.fencing_epoch + 1, now=101)

    allocator.complete(allocation.allocation_id, allocation.fencing_epoch, now=101)
    assert allocator.get(allocation.allocation_id).state is DistributedGpuAllocationState.COMPLETED


def test_sqlite_store_reloads_active_allocation_and_preserves_gpu_fencing(tmp_path):
    store = SQLiteDistributedGpuAllocationStore(tmp_path / "gpu-allocations.sqlite3")
    allocator = DistributedGpuAllocator(registry("A", "B"), store)
    allocation = allocator.reserve("task-1", requirement(), now=100, lease_seconds=60)

    reloaded = DistributedGpuAllocator(registry("A", "B"), store)
    persisted = reloaded.get(allocation.allocation_id)
    assert persisted == allocation
    assert reloaded.try_reserve("task-2", requirement(2), now=101, lease_seconds=60) is None

    reloaded.complete(allocation.allocation_id, allocation.fencing_epoch, now=101)
    reloaded_again = DistributedGpuAllocator(registry("A", "B"), store)
    assert reloaded_again.get(allocation.allocation_id).state is DistributedGpuAllocationState.COMPLETED
    assert reloaded_again.try_reserve("task-2", requirement(2), now=102, lease_seconds=60) is not None


def test_gpu_direct_evidence_must_cover_each_selected_worker_pair_with_bound_gpu_endpoints():
    allocator = DistributedGpuAllocator(registry("A", "B", "C"))
    planned = allocator.plan("task-1", requirement(9, direct=True), now=100, lease_seconds=60)
    evidence = GpuDirectNetworkEvidence(
        worker_pairs=(("A", "B"), ("A", "C"), ("B", "C")),
        gpu_pairs=(
            ("A", planned.gpus_by_worker_map["A"][0], "B", planned.gpus_by_worker_map["B"][0]),
            ("A", planned.gpus_by_worker_map["A"][0], "C", planned.gpus_by_worker_map["C"][0]),
        ),
        transport="RDMA",
        command=("peer-memory-test",),
        exit_code=0,
        output_sha256="f" * 64,
    )
    with pytest.raises(RuntimeError, match="every selected worker pair"):
        allocator.reserve("task-1", requirement(9, direct=True), now=100, lease_seconds=60, gpu_direct_network=evidence)


def test_required_distributed_evidence_survives_sqlite_reload(tmp_path):
    store = SQLiteDistributedGpuAllocationStore(tmp_path / "gpu-allocations.sqlite3")
    registry_value = registry("A", "B")
    registry_value.update(
        WorkerRecord(
            "A",
            registry_value.get("A").resource,
            WorkerState.VERIFIED_AVAILABLE,
            observed_at=100,
            observation_source="test",
            hardware_observation=GpuHostObservation(
                worker_id="A",
                driver_version="test-driver",
                cuda_supported_version="12.9",
                gpus=registry_value.get("A").hardware_observation.gpus,
                topology_text="observed",
                dcgm_available=True,
                dcgm_version="test",
                health_json="Overall Health: Healthy",
                nccl_evidence=local_nccl("A"),
                topology_evidence=topology("A"),
            ),
        )
    )
    registry_value.update(
        WorkerRecord(
            "B",
            registry_value.get("B").resource,
            WorkerState.VERIFIED_AVAILABLE,
            observed_at=100,
            observation_source="test",
            hardware_observation=GpuHostObservation(
                worker_id="B",
                driver_version="test-driver",
                cuda_supported_version="12.9",
                gpus=registry_value.get("B").hardware_observation.gpus,
                topology_text="observed",
                dcgm_available=True,
                dcgm_version="test",
                health_json="Overall Health: Healthy",
                nccl_evidence=local_nccl("B"),
                topology_evidence=topology("B"),
            ),
        )
    )
    allocator = DistributedGpuAllocator(registry_value, store)
    planned = allocator.plan("task-1", requirement(nccl=True, direct=True), now=100, lease_seconds=60)
    direct = GpuDirectNetworkEvidence(
        worker_pairs=(("A", "B"),),
        gpu_pairs=(("A", planned.gpus_by_worker_map["A"][0], "B", planned.gpus_by_worker_map["B"][0]),),
        transport="RDMA",
        command=("peer-memory-test",),
        exit_code=0,
        output_sha256="e" * 64,
    )
    nccl = distributed_nccl(planned.worker_ids, planned.gpus_by_worker)
    allocation = allocator.reserve("task-1", requirement(nccl=True, direct=True), now=100, lease_seconds=60, distributed_nccl=nccl, gpu_direct_network=direct)

    reloaded = DistributedGpuAllocator(registry_value, store)
    persisted = reloaded.get(allocation.allocation_id)
    assert persisted.distributed_nccl == nccl
    assert persisted.gpu_direct_network == direct
