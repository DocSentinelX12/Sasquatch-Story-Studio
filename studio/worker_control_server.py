"""Control-plane HTTP service for authenticated GPU worker lifecycle.

The service is deliberately standard-library only. TLS termination is required
outside this handler, and the existing SecureWorkerClient refuses plain HTTP.
This module owns transport-level request parsing and authorization while
WorkerControlPlane remains the authoritative inventory and health boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .remote_worker import WorkerAccess
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


class WorkerControlServer:
    """HTTP-independent service implementation for worker lifecycle endpoints."""

    def __init__(self, control_plane: WorkerControlPlane):
        self.control_plane = control_plane

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

    def dispatch(self, method: str, path: str, body: bytes, authorization: str | None, *, now: int) -> ControlResponse:
        if method.upper() != "POST":
            return self._json(405, {"error": "method not allowed"})
        try:
            payload = self.decode_json_body(body)
            request = {"authorization": authorization, "payload": payload}
            if path == "/v1/worker/register":
                return self.register(request, now=now)
            if path == "/v1/worker/heartbeat":
                return self.heartbeat(request, now=now)
            return self._json(404, {"error": "worker endpoint not found"})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except (KeyError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})


class WorkerControlHTTPHandler:
    """Thin adapter for an HTTP server implementation.

    The handler delegates all lifecycle decisions to WorkerControlServer. A
    deployment must wrap the listener in TLS before exposing these endpoints.
    """

    service: WorkerControlServer
    clock: Any

    def handle(self, method: str, path: str, body: bytes, authorization: str | None) -> ControlResponse:
        return self.service.dispatch(method, path, body, authorization, now=int(self.clock()))
