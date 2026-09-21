"""Evidence-backed inter-worker fabric topology and communication registry.

This registry describes only observed worker/GPU relationships. It does not
reserve capacity and it never infers communication capability from provider,
region, or network locality alone.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from .compute_provider import ProviderResource, ProviderResourceState
from .distributed_gpu import DistributedNCCLEvidence, GpuDirectNetworkEvidence
from .gpu_infrastructure import GpuHostObservation
from .gpu_topology import GpuTopologyEvidence


@dataclass(frozen=True)
class FabricTopologyRecord:
    provider_id: str
    resource_id: str
    region: str
    worker_id: str
    resource: ProviderResource
    hardware_observation: GpuHostObservation
    observed_at: int
    distributed_nccl: tuple[DistributedNCCLEvidence, ...] = ()
    gpu_direct_network: tuple[GpuDirectNetworkEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.resource_id.strip():
            raise ValueError("provider and resource identity are required")
        if not self.region.strip() or not self.worker_id.strip():
            raise ValueError("fabric worker locality and identity are required")
        if self.resource.provider_id != self.provider_id or self.resource.resource_id != self.resource_id:
            raise ValueError("provider resource identity does not match fabric record")
        if self.resource.worker_id != self.worker_id:
            raise ValueError("provider resource worker identity does not match fabric record")
        if self.hardware_observation.worker_id != self.worker_id:
            raise ValueError("hardware observation worker identity does not match fabric record")
        if self.observed_at < 0:
            raise ValueError("fabric observation timestamp cannot be negative")
        topology = self.hardware_observation.topology_evidence
        if topology is None:
            raise ValueError("fabric topology requires explicit GPU topology evidence")
        for evidence in self.distributed_nccl:
            if self.worker_id not in evidence.worker_ids:
                raise ValueError("distributed NCCL evidence does not reference this worker")
            if dict(evidence.topology_digests).get(self.worker_id) != self.topology_digest:
                raise ValueError("distributed NCCL evidence topology does not match this worker")
        for evidence in self.gpu_direct_network:
            if not any(self.worker_id in pair for pair in evidence.worker_pairs):
                raise ValueError("GPU-direct evidence does not reference this worker")

    @property
    def topology_evidence(self) -> GpuTopologyEvidence:
        evidence = self.hardware_observation.topology_evidence
        assert evidence is not None
        return evidence

    @property
    def topology_digest(self) -> str:
        payload = {
            "gpu_uuids": list(self.topology_evidence.gpu_uuids),
            "gpu_matrix": [list(row) for row in self.topology_evidence.gpu_matrix],
            "cpu_affinity": [list(item) for item in self.topology_evidence.cpu_affinity],
            "nic_paths": [list(item) for item in self.topology_evidence.nic_paths],
            "raw_text_sha256": self.topology_evidence.raw_text_sha256,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def with_distributed_nccl(self, evidence: DistributedNCCLEvidence) -> "FabricTopologyRecord":
        return replace(self, distributed_nccl=self.distributed_nccl + (evidence,))

    def with_gpu_direct_network(self, evidence: GpuDirectNetworkEvidence) -> "FabricTopologyRecord":
        return replace(self, gpu_direct_network=self.gpu_direct_network + (evidence,))


class FabricTopologyRegistry:
    """Deterministic topology/communication view above the worker registry."""

    def __init__(self, records: tuple[FabricTopologyRecord, ...] = ()):
        self._records: dict[str, FabricTopologyRecord] = {}
        for record in records:
            self.upsert(record)

    def upsert(self, record: FabricTopologyRecord) -> None:
        existing = self._records.get(record.worker_id)
        if existing is not None and (
            existing.provider_id != record.provider_id or existing.resource_id != record.resource_id
        ):
            raise ValueError("worker identity collision across provider resources")
        self._records[record.worker_id] = record

    def get(self, worker_id: str) -> FabricTopologyRecord:
        try:
            return self._records[worker_id]
        except KeyError as exc:
            raise KeyError(f"unknown fabric worker: {worker_id}") from exc

    def snapshot(self) -> tuple[FabricTopologyRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def can_form_group(
        self,
        worker_ids: tuple[str, ...],
        gpus_by_worker: tuple[tuple[str, tuple[str, ...]], ...],
        *,
        now: int,
        require_nccl: bool,
        require_gpu_direct: bool,
    ) -> bool:
        if now < 0 or len(worker_ids) < 2 or tuple(sorted(worker_ids)) != worker_ids:
            return False
        if len(set(worker_ids)) != len(worker_ids):
            return False
        mapping = dict(gpus_by_worker)
        if tuple(sorted(mapping)) != worker_ids or any(not gpus for gpus in mapping.values()):
            return False

        records = []
        for worker_id in worker_ids:
            try:
                record = self.get(worker_id)
            except KeyError:
                return False
            if record.resource.state is not ProviderResourceState.AVAILABLE:
                return False
            if record.resource.worker_id != worker_id:
                return False
            if now < record.observed_at or now - record.observed_at > 60:
                return False
            observed_gpus = {gpu.uuid for gpu in record.hardware_observation.gpus}
            if any(gpu_uuid not in observed_gpus for gpu_uuid in mapping[worker_id]):
                return False
            records.append(record)

        if require_nccl:
            if not self._has_exact_nccl_evidence(tuple(records), worker_ids, mapping):
                return False

        if require_gpu_direct:
            if not self._has_complete_gpu_direct_evidence(tuple(records), worker_ids, mapping):
                return False

        return True

    @staticmethod
    def _has_exact_nccl_evidence(
        records: tuple[FabricTopologyRecord, ...],
        worker_ids: tuple[str, ...],
        mapping: dict[str, tuple[str, ...]],
    ) -> bool:
        expected_mapping = tuple((worker_id, mapping[worker_id]) for worker_id in worker_ids)
        for record in records:
            for evidence in record.distributed_nccl:
                if evidence.worker_ids == worker_ids and evidence.gpu_uuids_by_worker == expected_mapping:
                    if evidence.world_size != sum(len(gpus) for gpus in mapping.values()):
                        continue
                    return all(dict(evidence.topology_digests).get(item.worker_id) == item.topology_digest for item in records)
        return False

    @staticmethod
    def _has_complete_gpu_direct_evidence(
        records: tuple[FabricTopologyRecord, ...],
        worker_ids: tuple[str, ...],
        mapping: dict[str, tuple[str, ...]],
    ) -> bool:
        expected_pairs = {
            (left, right)
            for index, left in enumerate(worker_ids)
            for right in worker_ids[index + 1 :]
        }
        observed_pairs: set[tuple[str, str]] = set()
        selected = {(worker_id, gpu_uuid) for worker_id in worker_ids for gpu_uuid in mapping[worker_id]}
        for record in records:
            for evidence in record.gpu_direct_network:
                for pair in evidence.worker_pairs:
                    if pair in expected_pairs:
                        for left_worker, left_gpu, right_worker, right_gpu in evidence.gpu_pairs:
                            if (left_worker, left_gpu) in selected and (right_worker, right_gpu) in selected:
                                observed_pairs.add(pair)
        return observed_pairs == expected_pairs
