"""Control-plane HTTP service for authenticated GPU worker lifecycle.

The service is standard-library only and deliberately keeps production state
above the worker fabric. TLS termination remains an explicit deployment
requirement because SecureWorkerClient refuses plain HTTP.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .distributed_execution import DistributedLaunchSpec, DistributedProcessExecutor, _parse_lease as _parse_distributed_lease
from .remote_worker import RemoteLease, WorkerAccess
from .worker_control_plane import WorkerControlPlane


@dataclass(frozen=True)
class ControlResponse:
    status: int
    body: str
    content_type: str = "application/json"


def _bearer(value: str | None) -> str:
    if not isinstance(value, str):
        raise PermissionError("Bearer authorization is required")
    scheme, separator, token = value.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise PermissionError("Bearer authorization is required")
    return token.strip()


def _lease(payload: Mapping[str, Any]) -> RemoteLease:
    raw = payload.get("lease")
    if not isinstance(raw, Mapping):
        raise ValueError("lease is required")
    try:
        return RemoteLease(
            lease_id=str(raw["lease_id"]),
            task_id=str(raw["task_id"]),
            worker_id=str(raw["worker_id"]),
            expires_at=int(raw["expires_at"]),
            gpu_uuids=tuple(str(value) for value in raw.get("gpu_uuids", ())),
            execution_nonce=str(raw["execution_nonce"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid remote lease") from exc


class WorkerControlServer:
    """HTTP-independent control service for worker lifecycle and execution."""

    def __init__(
        self,
        control_plane: WorkerControlPlane,
        execute: Callable[[Mapping[str, Any], RemoteLease, WorkerAccess, int], Mapping[str, Any]] | None = None,
        distributed_allocation: Callable[[str], Any] | None = None,
        execute_distributed: Callable[[Mapping[str, Any], Any, WorkerAccess, int], Mapping[str, Any]] | None = None,
    ):
        self.control_plane = control_plane
        self._execute = execute
        self._distributed_allocation = distributed_allocation
        self._execute_distributed = execute_distributed

    @staticmethod
    def decode_json_body(body: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must contain valid UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("request body must be a JSON object")
        return decoded

    @staticmethod
    def _json(status: int, payload: Mapping[str, Any]) -> ControlResponse:
        return ControlResponse(status, json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def register(self, request: Mapping[str, Any], *, now: int) -> ControlResponse:
        token = _bearer(request.get("authorization"))
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("worker registration payload must be an object")
        access = self.control_plane.register(payload, token, now)
        return self._json(200, {"worker_id": access.worker_id, "access_token": access.access_token})

    def heartbeat(self, request: Mapping[str, Any], *, now: int) -> ControlResponse:
        token = _bearer(request.get("authorization"))
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("worker heartbeat payload must be an object")
        worker_id = payload.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id is required")
        record = self.control_plane.heartbeat(payload, WorkerAccess(worker_id, token), now)
        return self._json(200, {"worker_id": record.id, "state": record.state.value, "observed_at": record.observed_at})

    def execute(self, request: Mapping[str, Any], *, now: int) -> ControlResponse:
        if self._execute is None:
            return self._json(503, {"error": "remote execution service is not configured"})
        token = _bearer(request.get("authorization"))
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("worker execution payload must be an object")
        lease = _lease(payload)
        access = WorkerAccess(lease.worker_id, token)
        self.control_plane.authority.authorize_execution(access, lease, now)
        result = self._execute(payload, lease, access, now)
        if not isinstance(result, Mapping):
            raise ValueError("worker execution callback must return an object")
        self.control_plane.authority.complete_lease(access, lease, now)
        return self._json(200, result)

    def execute_distributed(self, request: Mapping[str, Any], *, now: int) -> ControlResponse:
        token = _bearer(request.get("authorization"))
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("distributed worker execution payload must be an object")
        raw_lease = payload.get("lease")
        if not isinstance(raw_lease, Mapping):
            raise ValueError("distributed lease is required")
        lease = _parse_distributed_lease(raw_lease)
        access = WorkerAccess(lease.worker_id, token)
        if self._distributed_allocation is None:
            return self._json(503, {"error": "distributed allocation authority is not configured"})
        allocation = self._distributed_allocation(lease.allocation_id)
        self.control_plane.authority.authorize_distributed_execution(access, lease, allocation, now)
        if self._execute_distributed is not None:
            result = self._execute_distributed(payload, lease, access, now)
        else:
            raw_launch = payload.get("launch")
            if not isinstance(raw_launch, Mapping):
                return self._json(503, {"error": "distributed execution service is not configured"})
            try:
                spec = DistributedLaunchSpec(
                    executable=str(raw_launch["executable"]),
                    command=tuple(str(item) for item in raw_launch["command"]),
                    rendezvous_id=str(raw_launch["rendezvous_id"]),
                    rendezvous_host=str(raw_launch["rendezvous_host"]),
                    rendezvous_port=int(raw_launch["rendezvous_port"]),
                    timeout_seconds=int(raw_launch.get("timeout_seconds", 3600)),
                    max_restarts=int(raw_launch.get("max_restarts", 0)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("invalid distributed launch specification") from exc
            result = DistributedProcessExecutor(spec).execute(payload, lease, access, now)
        if not isinstance(result, Mapping):
            raise ValueError("distributed worker execution callback must return an object")
        return self._json(200, result)

    def dispatch(self, method: str, path: str, body: bytes, authorization: str | None, *, now: int | None = None) -> ControlResponse:
        if method.upper() != "POST":
            return self._json(405, {"error": "method not allowed"})
        current = int(time.time()) if now is None else now
        try:
            payload = self.decode_json_body(body)
            request = {"authorization": authorization, "payload": payload}
            if path == "/v1/worker/register":
                return self.register(request, now=current)
            if path == "/v1/worker/heartbeat":
                return self.heartbeat(request, now=current)
            if path == "/v1/worker/execute":
                return self.execute(request, now=current)
            if path == "/v1/worker/execute-distributed":
                return self.execute_distributed(request, now=current)
            return self._json(404, {"error": "worker endpoint not found"})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except (KeyError, ValueError, TypeError) as exc:
            return self._json(400, {"error": str(exc)})


class WorkerControlHTTPHandler:
    """Thin adapter for an HTTP server implementation.

    Deployments must provide TLS before exposing these endpoints. The handler
    never creates certificates, credentials, or worker identities itself.
    """

    service: WorkerControlServer
    clock: Any

    def handle(self, method: str, path: str, body: bytes, authorization: str | None) -> ControlResponse:
        return self.service.dispatch(method, path, body, authorization, now=int(self.clock()))
