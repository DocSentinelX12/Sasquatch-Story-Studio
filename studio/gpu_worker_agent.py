"""Local GPU worker agent lifecycle, without assuming a network is present."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .gpu_infrastructure import GpuHostObservation, probe_nvidia_host


class GpuWorkerAgent:
    """Observe, describe, and heartbeat one physical GPU worker.

    Transport and lease execution are deliberately separate. This keeps local
    hardware truth testable before a remote protocol is allowed to schedule
    production work on the worker.
    """

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
