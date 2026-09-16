"""Local GPU worker agent lifecycle, enrollment, and heartbeat."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .gpu_infrastructure import GpuHostObservation, probe_nvidia_host
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

    def registration_payload(self) -> dict[str, Any]:
        observation = self.observe()
        return {
            "worker_id": self.worker_id,
            "hardware_observation_digest": observation.digest(),
            "driver_version": observation.driver_version,
            "cuda_supported_version": observation.cuda_supported_version,
            "gpu_count": observation.gpu_count,
            "gpu_uuids": tuple(gpu.uuid for gpu in observation.gpus),
            "gpu_models": tuple(gpu.name for gpu in observation.gpus),
            "dcgm_available": observation.dcgm_available,
        }

    def heartbeat_payload(self) -> dict[str, Any]:
        observation = self.observe()
        return {
            "worker_id": self.worker_id,
            "hardware_observation_digest": observation.digest(),
            "gpu_count": observation.gpu_count,
            "health_evidence": "dcgm_health_check" if observation.health_json else "nvidia_smi_inventory_only",
            "dcgm_available": observation.dcgm_available,
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
