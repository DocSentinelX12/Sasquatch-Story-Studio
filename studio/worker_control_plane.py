"""Authoritative control-plane lifecycle for authenticated GPU workers.

This layer owns worker identity, observed hardware, health state, and admission
state. Production episode, scene, and shot state remains outside the worker
fabric. Credentials are supplied out of band and are never persisted here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Mapping

from .gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, classify_dcgm_health
from .gpu_topology import GpuTopologyEvidence
from .nccl_evidence import NCCLTestEvidence
from .remote_worker import WorkerAccess, WorkerLifecycleAuthority
from .worker_registry import WorkerRecord, WorkerRegistry, WorkerState


class WorkerControlPlane:
    """Bind authenticated worker reports to the authoritative worker registry."""

    def __init__(self, registry: WorkerRegistry, authority: WorkerLifecycleAuthority):
        self.registry = registry
        self.authority = authority

    @staticmethod
    def _observation(payload: Mapping[str, Any]) -> GpuHostObservation:
        raw = payload.get("hardware_observation")
        if not isinstance(raw, Mapping):
            raise ValueError("worker hardware observation is required")
        gpus = raw.get("gpus")
        if not isinstance(gpus, (list, tuple)):
            raise ValueError("worker GPU inventory is required")

        topology_payload = raw.get("topology_evidence")
        topology_evidence = None
        if topology_payload is not None:
            if not isinstance(topology_payload, Mapping):
                raise ValueError("worker topology evidence must be an object")
            topology_evidence = GpuTopologyEvidence(
                gpu_uuids=tuple(topology_payload["gpu_uuids"]),
                gpu_matrix=tuple(tuple(row) for row in topology_payload["gpu_matrix"]),
                cpu_affinity=tuple(tuple(item) for item in topology_payload["cpu_affinity"]),
                nic_paths=tuple(tuple(item) for item in topology_payload["nic_paths"]),
                raw_text_sha256=topology_payload["raw_text_sha256"],
            )

        nccl_payload = raw.get("nccl_evidence")
        nccl_evidence = None
        if nccl_payload is not None:
            if not isinstance(nccl_payload, Mapping):
                raise ValueError("worker NCCL evidence must be an object")
            nccl_evidence = NCCLTestEvidence(
                executable=str(nccl_payload["executable"]),
                executable_sha256=str(nccl_payload["executable_sha256"]),
                command=tuple(nccl_payload["command"]),
                exit_code=int(nccl_payload["exit_code"]),
                output_sha256=str(nccl_payload["output_sha256"]),
                gpu_uuids=tuple(nccl_payload["gpu_uuids"]),
                topology_digest=str(nccl_payload["topology_digest"]),
            )

        observation = GpuHostObservation(
            worker_id=str(raw["worker_id"]),
            driver_version=str(raw["driver_version"]),
            cuda_supported_version=str(raw["cuda_supported_version"]),
            gpus=tuple(GpuDeviceObservation(**dict(item)) for item in gpus),
            topology_text=raw.get("topology_text"),
            dcgm_available=bool(raw["dcgm_available"]),
            dcgm_version=raw.get("dcgm_version"),
            health_json=raw.get("health_json"),
            nccl_evidence=nccl_evidence,
            topology_evidence=topology_evidence,
        )
        if observation.digest() != payload.get("hardware_observation_digest"):
            raise PermissionError("worker hardware observation digest does not match payload")
        return observation

    @staticmethod
    def _identity_digest(observation: GpuHostObservation) -> str:
        identity = {
            "worker_id": observation.worker_id,
            "driver_version": observation.driver_version,
            "cuda_supported_version": observation.cuda_supported_version,
            "gpus": [
                {
                    "uuid": gpu.uuid,
                    "name": gpu.name,
                    "pci_bus_id": gpu.pci_bus_id,
                    "compute_capability": gpu.compute_capability,
                    "memory_total_mib": gpu.memory_total_mib,
                }
                for gpu in observation.gpus
            ],
            "topology_text": observation.topology_text,
            "dcgm_available": observation.dcgm_available,
            "dcgm_version": observation.dcgm_version,
            "topology_evidence": None if observation.topology_evidence is None else {
                "gpu_uuids": observation.topology_evidence.gpu_uuids,
                "gpu_matrix": observation.topology_evidence.gpu_matrix,
                "cpu_affinity": observation.topology_evidence.cpu_affinity,
                "nic_paths": observation.topology_evidence.nic_paths,
                "raw_text_sha256": observation.topology_evidence.raw_text_sha256,
            },
            "nccl_evidence": None if observation.nccl_evidence is None else {
                "executable": observation.nccl_evidence.executable,
                "executable_sha256": observation.nccl_evidence.executable_sha256,
                "command": observation.nccl_evidence.command,
                "exit_code": observation.nccl_evidence.exit_code,
                "output_sha256": observation.nccl_evidence.output_sha256,
                "gpu_uuids": observation.nccl_evidence.gpu_uuids,
                "topology_digest": observation.nccl_evidence.topology_digest,
            },
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _state(observation: GpuHostObservation) -> WorkerState:
        health = classify_dcgm_health(observation.health_json)
        if health == "failure":
            return WorkerState.TEMPORARILY_UNAVAILABLE
        if health == "warning" or not observation.dcgm_available:
            return WorkerState.VERIFIED_LIMITED
        if health == "healthy":
            return WorkerState.VERIFIED_AVAILABLE
        return WorkerState.VERIFIED_LIMITED

    def _apply(self, worker_id: str, observation: GpuHostObservation, now: int) -> WorkerRecord:
        record = self.registry.get(worker_id)
        if observation.worker_id != worker_id:
            raise PermissionError("worker identity does not match registry identity")
        state = self._state(observation)
        resource = replace(
            record.resource,
            gpu_count=observation.gpu_count,
            gpu_models=tuple(gpu.name for gpu in observation.gpus),
            vram_bytes=sum(gpu.memory_total_mib for gpu in observation.gpus) * 1024 * 1024,
            healthy=state in {WorkerState.VERIFIED_AVAILABLE, WorkerState.VERIFIED_LIMITED},
        )
        updated = replace(
            record,
            resource=resource,
            state=state,
            observed_at=now,
            observation_source="authenticated_gpu_worker_agent",
            quota_note="" if state != WorkerState.TEMPORARILY_UNAVAILABLE else "DCGM health failure",
            hardware_observation=observation,
        )
        self.registry.update(updated)
        return updated

    def register(self, payload: Mapping[str, Any], enrollment_token: str, now: int) -> WorkerAccess:
        worker_id = payload.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        observation = self._observation(payload)
        identity_digest = payload.get("hardware_identity_digest")
        if identity_digest != self._identity_digest(observation):
            raise PermissionError("worker hardware identity digest does not match observed inventory")
        access = self.authority.register(worker_id, enrollment_token, now, hardware_identity_digest=identity_digest)
        self._apply(worker_id, observation, now)
        return access

    def heartbeat(self, payload: Mapping[str, Any], access: WorkerAccess, now: int) -> WorkerRecord:
        worker_id = payload.get("worker_id")
        if worker_id != access.worker_id:
            raise PermissionError("heartbeat worker identity does not match authenticated worker")
        observation = self._observation(payload)
        identity_digest = payload.get("hardware_identity_digest")
        if identity_digest != self._identity_digest(observation):
            raise PermissionError("worker hardware identity digest does not match observed inventory")
        self.authority.heartbeat(access, now, hardware_identity_digest=identity_digest)
        return self._apply(worker_id, observation, now)

    def revoke(self, worker_id: str) -> None:
        self.authority.revoke(worker_id)
        record = self.registry.get(worker_id)
        self.registry.update(replace(record, state=WorkerState.OFFLINE, observed_at=None, observation_source="revoked"))
