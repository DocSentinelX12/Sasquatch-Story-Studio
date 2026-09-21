import pytest

from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass
from studio.fabric_topology import FabricTopologyRecord, FabricTopologyRegistry
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_topology import GpuTopologyEvidence


def topology(worker_id: str, gpu_uuid: str) -> GpuTopologyEvidence:
    return GpuTopologyEvidence(
        gpu_uuids=(gpu_uuid,),
        gpu_matrix=(("X",),),
        cpu_affinity=((gpu_uuid, "0-63"),),
        nic_paths=((gpu_uuid, "mlx5_0", "PIX"),),
        raw_text_sha256="a" * 64,
    )


def observation(worker_id: str, gpu_uuid: str) -> GpuHostObservation:
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="550.1",
        cuda_supported_version="12.4",
        gpus=(GpuDeviceObservation(0, gpu_uuid, "NVIDIA A100", 80_000, 0, "0000:00:00.0", "8.0"),),
        topology_text="observed",
        dcgm_available=True,
        dcgm_version="3",
        health_json="Overall Health: Healthy",
        topology_evidence=topology(worker_id, gpu_uuid),
    )


def resource(provider_id: str, worker_id: str, resource_id: str | None = None) -> ProviderResource:
    return ProviderResource(
        provider_id=provider_id,
        resource_id=resource_id or worker_id,
        region="test-region",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.AVAILABLE,
        worker_id=worker_id,
        capability_digest="b" * 64,
    )


def record(provider_id: str, worker_id: str, gpu_uuid: str, *, observed_at: int = 100) -> FabricTopologyRecord:
    return FabricTopologyRecord(
        provider_id=provider_id,
        resource_id=worker_id,
        region="test-region",
        worker_id=worker_id,
        resource=resource(provider_id, worker_id),
        hardware_observation=observation(worker_id, gpu_uuid),
        observed_at=observed_at,
    )


def test_registry_keeps_provider_scoped_worker_identity_and_snapshot_deterministic():
    registry = FabricTopologyRegistry((record("provider-b", "worker-b", "GPU-B"), record("provider-a", "worker-a", "GPU-A")))

    assert tuple(item.worker_id for item in registry.snapshot()) == ("worker-a", "worker-b")
    assert registry.get("worker-a").provider_id == "provider-a"


def test_registry_rejects_worker_identity_mismatch_between_resource_and_observation():
    with pytest.raises(ValueError, match="worker identity"):
        FabricTopologyRecord(
            provider_id="provider-a",
            resource_id="resource-a",
            region="test-region",
            worker_id="worker-a",
            resource=resource("provider-a", "worker-a", "resource-a"),
            hardware_observation=observation("worker-b", "GPU-B"),
            observed_at=100,
        )

def test_registry_requires_fresh_topology_evidence_for_distributed_groups():
    registry = FabricTopologyRegistry((record("provider-a", "worker-a", "GPU-A", observed_at=100), record("provider-b", "worker-b", "GPU-B", observed_at=100)))

    assert registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=120,
        require_nccl=False,
        require_gpu_direct=False,
    )

    assert not registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=161,
        require_nccl=False,
        require_gpu_direct=False,
    )


def test_registry_does_not_infer_cross_provider_communication_without_explicit_evidence():
    registry = FabricTopologyRegistry((record("provider-a", "worker-a", "GPU-A"), record("provider-b", "worker-b", "GPU-B")))

    assert not registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=110,
        require_nccl=True,
        require_gpu_direct=False,
    )


def test_registry_accepts_explicit_distributed_nccl_evidence_only_when_identity_and_topology_bind():
    records = (
        record("provider-a", "worker-a", "GPU-A"),
        record("provider-b", "worker-b", "GPU-B"),
    )
    topology_digests = tuple((item.worker_id, item.topology_digest) for item in records)
    evidence = __import__("studio.distributed_gpu", fromlist=["DistributedNCCLEvidence"]).DistributedNCCLEvidence(
        worker_ids=("worker-a", "worker-b"),
        gpu_uuids_by_worker=(("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        world_size=2,
        command=("all_reduce_perf_mpi",),
        exit_code=0,
        output_sha256="c" * 64,
        rendezvous_id="rdzv-test",
        topology_digests=topology_digests,
    )
    registry = FabricTopologyRegistry(tuple(item.with_distributed_nccl(evidence) for item in records))

    assert registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=110,
        require_nccl=True,
        require_gpu_direct=False,
    )


def test_registry_rejects_nccl_evidence_bound_to_different_worker_or_gpu_mapping():
    record_a = record("provider-a", "worker-a", "GPU-A")
    record_b = record("provider-b", "worker-b", "GPU-B")
    from studio.distributed_gpu import DistributedNCCLEvidence
    evidence = DistributedNCCLEvidence(
        worker_ids=("worker-a", "worker-b"),
        gpu_uuids_by_worker=(("worker-a", ("GPU-WRONG",)), ("worker-b", ("GPU-B",))),
        world_size=2,
        command=("all_reduce_perf_mpi",),
        exit_code=0,
        output_sha256="d" * 64,
        rendezvous_id="rdzv-test",
        topology_digests=(("worker-a", record_a.topology_digest), ("worker-b", record_b.topology_digest)),
    )
    registry = FabricTopologyRegistry((record_a.with_distributed_nccl(evidence), record_b.with_distributed_nccl(evidence)))

    assert not registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=110,
        require_nccl=True,
        require_gpu_direct=False,
    )

def test_registry_accepts_explicit_gpu_direct_evidence_for_every_selected_worker_pair():
    from studio.distributed_gpu import GpuDirectNetworkEvidence

    record_a = record("provider-a", "worker-a", "GPU-A")
    record_b = record("provider-b", "worker-b", "GPU-B")
    evidence = GpuDirectNetworkEvidence(
        worker_pairs=(("worker-a", "worker-b"),),
        gpu_pairs=(("worker-a", "GPU-A", "worker-b", "GPU-B"),),
        transport="RDMA",
        command=("peer-memory-test",),
        exit_code=0,
        output_sha256="e" * 64,
    )
    registry = FabricTopologyRegistry((
        record_a.with_gpu_direct_network(evidence),
        record_b.with_gpu_direct_network(evidence),
    ))

    assert registry.can_form_group(
        ("worker-a", "worker-b"),
        (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",))),
        now=110,
        require_nccl=False,
        require_gpu_direct=True,
    )
