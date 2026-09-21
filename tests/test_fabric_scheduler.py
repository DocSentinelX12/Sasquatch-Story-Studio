from studio.compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass
from studio.distributed_gpu import DistributedNCCLEvidence
from studio.nccl_evidence import NCCLTestEvidence
from studio.fabric_topology import FabricTopologyRecord, FabricTopologyRegistry
from studio.gpu_topology import GpuTopologyEvidence
from studio.fabric_scheduler import FabricScheduler, FabricWorker
from studio.gpu_capabilities import derive_gpu_capabilities
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.worker_registry import WorkerState
from studio.resources import ComputeResource


def obs(worker_id, uuid, model="NVIDIA A100"):
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="550.1",
        cuda_supported_version="12.4",
        gpus=(GpuDeviceObservation(0, uuid, model, 80_000, 0, "0000:00:00.0", "8.0"),),
        topology_text="",
        dcgm_available=True,
        dcgm_version="3",
        health_json="Overall Health: Healthy",
        topology_evidence=GpuTopologyEvidence(
            gpu_uuids=(uuid,),
            gpu_matrix=(("X",),),
            cpu_affinity=((uuid, "0-63"),),
            nic_paths=((uuid, "mlx5_0", "PIX"),),
            raw_text_sha256="a" * 64,
        ),
        nccl_evidence=NCCLTestEvidence(
            executable="all_reduce_perf",
            executable_sha256="b" * 64,
            command=("all_reduce_perf",),
            exit_code=0,
            output_sha256="c" * 64,
            gpu_uuids=(uuid,),
            topology_digest="a" * 64,
        ),
    )


def worker(provider_id, worker_id, uuid):
    resource = ProviderResource(
        provider_id=provider_id,
        resource_id=worker_id,
        region="test",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.AVAILABLE,
        worker_id=worker_id,
    )
    return FabricWorker(
        provider_id=provider_id,
        resource=resource,
        hardware=obs(worker_id, uuid),
        worker_state=WorkerState.VERIFIED_AVAILABLE,
    )


def test_scheduler_can_combine_multiple_providers_for_non_distributed_work():
    workers = tuple(worker("a", f"a-{i}", f"GPU-A-{i}") for i in range(6)) + tuple(
        worker("b", f"b-{i}", f"GPU-B-{i}") for i in range(6)
    )
    placement = FabricScheduler(workers).plan(
        HardwareRequirements(min_gpu_count=12, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True),
        now=10,
    )
    assert placement.node_count == 12
    assert {item.provider_id for item in placement.workers} == {"a", "b"}


def test_scheduler_rejects_cross_provider_nccl_without_distributed_fabric_evidence():
    workers = (worker("a", "a-1", "GPU-A"), worker("b", "b-1", "GPU-B"))
    requirements = HardwareRequirements(
        min_gpu_count=2,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
        require_nccl=True,
    )
    try:
        FabricScheduler(workers).plan(requirements, now=10)
    except RuntimeError as exc:
        assert "cross-provider" in str(exc)
    else:
        raise AssertionError("cross-provider NCCL allocation was not rejected")


def test_scheduler_has_no_twelve_node_ceiling():
    workers = tuple(worker("a", f"a-{i}", f"GPU-{i}") for i in range(20))
    requirements = HardwareRequirements(min_gpu_count=20, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)
    placement = FabricScheduler(workers).plan(requirements, now=10)
    assert placement.node_count == 20

def test_scheduler_allows_cross_provider_nccl_when_exact_fabric_evidence_exists():
    left = worker("a", "a-1", "GPU-A")
    right = worker("b", "b-1", "GPU-B")
    records = tuple(
        FabricTopologyRecord(
            provider_id=item.provider_id,
            resource_id=item.resource.resource_id,
            region=item.resource.region,
            worker_id=item.hardware.worker_id,
            resource=item.resource,
            hardware_observation=item.hardware,
            observed_at=10,
        )
        for item in (left, right)
    )
    evidence = DistributedNCCLEvidence(
        worker_ids=("a-1", "b-1"),
        gpu_uuids_by_worker=(("a-1", ("GPU-A",)), ("b-1", ("GPU-B",))),
        world_size=2,
        command=("all_reduce_perf_mpi",),
        exit_code=0,
        output_sha256="b" * 64,
        rendezvous_id="rdzv-test",
        topology_digests=tuple((item.worker_id, item.topology_digest) for item in records),
    )
    registry = FabricTopologyRegistry(tuple(item.with_distributed_nccl(evidence) for item in records))
    requirements = HardwareRequirements(
        min_gpu_count=2,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
        require_nccl=True,
    )

    placement = FabricScheduler((left, right), registry).plan(requirements, now=20)

    assert placement.node_count == 2
    assert {item.provider_id for item in placement.workers} == {"a", "b"}
