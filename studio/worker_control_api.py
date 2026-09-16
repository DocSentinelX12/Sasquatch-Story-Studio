"""Framework-neutral authenticated control API for the remote worker fabric.

The API is deliberately transport-agnostic: HTTPS/TLS is provided by
WorkerTransportSecurity/SecureWorkerClient, while this module owns endpoint
authorization, request validation, lease lifecycle, and worker identity.
Production episode/scene/shot state remains outside this API.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .remote_worker import RemoteLease, WorkerAccess, WorkerLifecycleAuthority
from .worker import WorkerResult, WorkerResultState, WorkerTask
from .worker_control_plane import WorkerControlPlane


@dataclass(frozen=True)
class ControlResponse:
    status: int
    body: dict[str, Any]


class WorkerControlApi:
    """Authenticated endpoint dispatcher suitable for an HTTPS server adapter."""

    def __init__(
        self,
        control_plane: WorkerControlPlane,
        authority: WorkerLifecycleAuthority,
        *,
        clock: Callable[[], int] | None = None,
        execute: Callable[[WorkerTask, RemoteLease], WorkerResult] | None = None,
    ) -> None:
        self.control_plane = control_plane
        self.authority = authority
        self.clock = clock or (lambda: int(time.time()))
        self.execute = execute

    @staticmethod
    def _token(headers: Mapping[str, str]) -> str:
        value = headers.get("Authorization", "")
        prefix = "Bearer "
        if not value.startswith(prefix) or not value[len(prefix):].strip():
            raise PermissionError("Bearer authorization is required")
        return value[len(prefix):].strip()

    @staticmethod
    def _access(worker_id: str, token: str) -> WorkerAccess:
        return WorkerAccess(worker_id, token)

    @staticmethod
    def _lease(payload: Mapping[str, Any]) -> RemoteLease:
        raw = payload.get("lease")
        if not isinstance(raw, Mapping):
            raise ValueError("lease object is required")
        return RemoteLease(
            str(raw["lease_id"]),
            str(raw["task_id"]),
            str(raw["worker_id"]),
            int(raw["expires_at"]),
            tuple(str(value) for value in raw.get("gpu_uuids", ())),
            str(raw["execution_nonce"]),
        )

    @staticmethod
    def _result(result: WorkerResult) -> dict[str, Any]:
        return {
            "task_id": result.task_id,
            "state": result.state.value,
            "output_refs": list(result.output_refs),
            "error": result.error,
        }

    def register(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> ControlResponse:
        try:
            token = self._token(headers)
            access = self.control_plane.register(payload, token, self.clock())
            return ControlResponse(200, {"worker_id": access.worker_id, "access_token": access.access_token})
        except (PermissionError, ValueError, KeyError) as exc:
            return ControlResponse(403 if isinstance(exc, PermissionError) else 400, {"error": str(exc)})

    def heartbeat(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> ControlResponse:
        try:
            worker_id = payload.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id.strip():
                raise ValueError("worker_id is required")
            token = self._token(headers)
            access = self._access(worker_id, token)
            record = self.control_plane.heartbeat(payload, access, self.clock())
            return ControlResponse(200, {"worker_id": record.id, "state": record.state.value, "observed_at": record.observed_at})
        except (PermissionError, ValueError, KeyError) as exc:
            return ControlResponse(403 if isinstance(exc, PermissionError) else 400, {"error": str(exc)})

    def execute_lease(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> ControlResponse:
        if self.execute is None:
            return ControlResponse(503, {"error": "worker execution service is not configured"})
        try:
            worker_id = payload.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id.strip():
                raise ValueError("worker_id is required")
            access = self._access(worker_id, self._token(headers))
            lease = self._lease(payload)
            self.authority.authorize_execution(access, lease, self.clock())
            task = payload.get("task")
            if not isinstance(task, Mapping):
                raise ValueError("task object is required")
            if str(task.get("task_id")) != lease.task_id:
                raise PermissionError("lease and task identities do not match")
            if tuple(str(value) for value in task.get("gpu_uuids", ())) != lease.gpu_uuids:
                raise PermissionError("lease and task GPU allocations do not match")
            result = self.execute(self._task(task), lease)
            self.authority.complete_lease(access, lease, self.clock())
            return ControlResponse(200, self._result(result))
        except PermissionError as exc:
            return ControlResponse(403, {"error": str(exc)})
        except (ValueError, KeyError) as exc:
            return ControlResponse(400, {"error": str(exc)})

    @staticmethod
    def _task(payload: Mapping[str, Any]) -> WorkerTask:
        from .hardware_requirements import GpuPlacement, HardwareRequirements
        from .scheduler import JobRequirements

        raw = payload.get("requirements")
        if not isinstance(raw, Mapping):
            raise ValueError("task requirements are required")
        hardware = raw.get("hardware")
        hw = None
        if isinstance(hardware, Mapping):
            hw = HardwareRequirements(
                min_gpu_count=int(hardware.get("min_gpu_count", 1)),
                min_vram_per_gpu_bytes=int(hardware.get("min_vram_per_gpu_bytes", 0)),
                min_total_vram_bytes=int(hardware.get("min_total_vram_bytes", 0)),
                min_compute_capability=hardware.get("min_compute_capability"),
                required_gpu_models=tuple(hardware.get("required_gpu_models", ())),
                placement=GpuPlacement(str(hardware.get("placement", "any"))),
                require_nccl=bool(hardware.get("require_nccl", False)),
                allow_multi_node=bool(hardware.get("allow_multi_node", False)),
                require_gpu_direct_network=bool(hardware.get("require_gpu_direct_network", False)),
            )
        requirements = JobRequirements(
            slots=int(raw.get("slots", 1)),
            memory_bytes=int(raw.get("memory_bytes", 0)),
            vram_bytes=int(raw.get("vram_bytes", 0)),
            scratch_bytes=int(raw.get("scratch_bytes", 0)),
            power_watts=int(raw.get("power_watts", 0)),
            capabilities=tuple(raw.get("capabilities", ())),
            engines=tuple(raw.get("engines", ())),
            hardware=hw,
        )
        return WorkerTask(
            task_id=str(payload["task_id"]),
            episode_id=str(payload["episode_id"]),
            stage=str(payload["stage"]),
            shot_id=str(payload["shot_id"]),
            input_refs=tuple(str(value) for value in payload.get("input_refs", ())),
            input_hashes=tuple(str(value) for value in payload.get("input_hashes", ())),
            requirements=requirements,
            provenance_context=tuple((str(k), str(v)) for k, v in payload.get("provenance_context", ())),
            canonical_source_hash=str(payload.get("canonical_source_hash", "")),
            payload_json=str(payload.get("payload_json", "")),
            gpu_uuids=tuple(str(value) for value in payload.get("gpu_uuids", ())),
        )

    def dispatch(self, path: str, payload: Mapping[str, Any], headers: Mapping[str, str]) -> ControlResponse:
        if path == "/v1/worker/register":
            return self.register(payload, headers)
        if path == "/v1/worker/heartbeat":
            return self.heartbeat(payload, headers)
        if path == "/v1/worker/execute":
            return self.execute_lease(payload, headers)
        return ControlResponse(404, {"error": "unknown worker endpoint"})
