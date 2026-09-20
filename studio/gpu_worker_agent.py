"""Local GPU worker agent lifecycle, enrollment, and heartbeat."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol

from .gpu_infrastructure import GpuHostObservation, classify_dcgm_health, probe_nvidia_host
from .remote_worker import WorkerAccess


class WorkerControlTransport(Protocol):
    def post_json(self, path: str, payload: dict[str, Any], *, bearer_token: str) -> dict[str, Any]:
        ...


class GpuWorkerAgent:
    """Observe, register, and heartbeat one physical GPU worker."""

    def __init__(self, worker_id: str, observer: Callable[[], GpuHostObservation] | None = None):
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self.worker_id = worker_id
        self._observer = observer or (lambda: probe_nvidia_host(worker_id))

    def observe(self) -> GpuHostObservation:
        observation = self._observer()
        if observation.worker_id != self.worker_id:
            raise RuntimeError("hardware observation identity does not match worker identity")
        return observation

    @staticmethod
    def _topology_digest(observation: GpuHostObservation) -> str | None:
        if not observation.topology_text:
            return None
        return hashlib.sha256(observation.topology_text.encode("utf-8")).hexdigest()

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
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _observation_payload(observation: GpuHostObservation) -> dict[str, Any]:
        return json.loads(observation.canonical_json())

    def registration_payload(self) -> dict[str, Any]:
        observation = self.observe()
        return {
            "worker_id": self.worker_id,
            "hardware_observation_digest": observation.digest(),
            "hardware_identity_digest": self._identity_digest(observation),
            "driver_version": observation.driver_version,
            "cuda_supported_version": observation.cuda_supported_version,
            "gpu_count": observation.gpu_count,
            "gpu_uuids": tuple(gpu.uuid for gpu in observation.gpus),
            "gpu_models": tuple(gpu.name for gpu in observation.gpus),
            "topology_digest": self._topology_digest(observation),
            "dcgm_available": observation.dcgm_available,
            "dcgm_version": observation.dcgm_version,
            "health_evidence_present": observation.health_json is not None,
            "health_state": classify_dcgm_health(observation.health_json),
            "hardware_observation": self._observation_payload(observation),
        }

    def heartbeat_payload(self) -> dict[str, Any]:
        observation = self.observe()
        return {
            "worker_id": self.worker_id,
            "hardware_observation_digest": observation.digest(),
            "hardware_identity_digest": self._identity_digest(observation),
            "gpu_count": observation.gpu_count,
            "gpu_uuids": tuple(gpu.uuid for gpu in observation.gpus),
            "topology_digest": self._topology_digest(observation),
            "health_evidence": "dcgm_health_check" if observation.health_json else "nvidia_smi_inventory_only",
            "health_state": classify_dcgm_health(observation.health_json),
            "dcgm_available": observation.dcgm_available,
            "dcgm_version": observation.dcgm_version,
            "hardware_observation": self._observation_payload(observation),
        }

    def register_remote(self, transport: WorkerControlTransport, enrollment_token: str) -> WorkerAccess:
        if not enrollment_token.strip():
            raise ValueError("enrollment token is required")
        response = transport.post_json(
            "/v1/worker/register",
            self.registration_payload(),
            bearer_token=enrollment_token,
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("worker registration did not return an access token")
        worker_id = response.get("worker_id", self.worker_id)
        if worker_id != self.worker_id:
            raise RuntimeError("worker registration returned a mismatched worker identity")
        return WorkerAccess(self.worker_id, access_token)

    def heartbeat_remote(self, transport: WorkerControlTransport, access: WorkerAccess) -> None:
        if access.worker_id != self.worker_id:
            raise ValueError("worker access identity does not match agent")
        response = transport.post_json(
            "/v1/worker/heartbeat",
            self.heartbeat_payload(),
            bearer_token=access.access_token,
        )
        if response.get("worker_id", self.worker_id) != self.worker_id:
            raise RuntimeError("worker heartbeat returned a mismatched worker identity")
