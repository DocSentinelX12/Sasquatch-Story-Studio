"""Authenticated TLS transport for remote GPU workers and artifacts.

The transport does not generate certificates or secrets. Credentials must be
provisioned outside source control and referenced by filesystem paths or the
runtime environment.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class WorkerTransportSecurity:
    base_url: str
    ca_certificate_path: str | None = None
    client_certificate_path: str | None = None
    client_key_path: str | None = None

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https":
            raise ValueError("worker transport requires HTTPS")
        if not parsed.netloc:
            raise ValueError("worker transport requires an HTTPS authority")
        if self.client_certificate_path and not self.client_key_path:
            raise ValueError("client certificate requires a client key")
        if self.client_key_path and not self.client_certificate_path:
            raise ValueError("client key requires a client certificate")
        for path in (self.ca_certificate_path, self.client_certificate_path, self.client_key_path):
            if path is not None and not Path(path).is_file():
                raise ValueError(f"configured TLS credential does not exist: {path}")

    def ssl_context(self) -> ssl.SSLContext:
        self.validate()
        context = ssl.create_default_context(cafile=self.ca_certificate_path)
        if self.client_certificate_path:
            context.load_cert_chain(self.client_certificate_path, self.client_key_path)
        return context


@dataclass(frozen=True)
class WorkerRegistration:
    worker_id: str
    enrollment_token: str

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or not self.enrollment_token.strip():
            raise ValueError("worker registration requires worker_id and enrollment_token")


class SecureWorkerClient:
    def __init__(self, security: WorkerTransportSecurity, *, opener: urllib.request.OpenerDirector | None = None):
        security.validate()
        self.security = security
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=security.ssl_context()))

    def _open(self, request: urllib.request.Request):
        try:
            return self._opener.open(request, timeout=30)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"worker transport failed: {exc}") from exc

    def post_json(self, path: str, payload: Mapping[str, Any], *, bearer_token: str) -> dict[str, Any]:
        if not bearer_token.strip():
            raise ValueError("bearer_token is required")
        if not path.startswith("/"):
            raise ValueError("worker endpoint path must start with /")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.security.base_url.rstrip("/") + path,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer_token}",
            },
        )
        with self._open(request) as response:
            raw = response.read()
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("worker transport returned non-JSON data") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("worker transport response must be a JSON object")
        return decoded

    def get_bytes(
        self,
        path: str,
        *,
        bearer_token: str,
        expected_digest: str,
        offset: int,
        size_bytes: int,
    ) -> bytes:
        if not bearer_token.strip():
            raise ValueError("bearer_token is required")
        if not path.startswith("/"):
            raise ValueError("worker endpoint path must start with /")
        if offset < 0 or size_bytes < 0:
            raise ValueError("artifact offset and size must be non-negative")
        if len(expected_digest) != 64 or any(c not in "0123456789abcdef" for c in expected_digest):
            raise ValueError("expected artifact digest must be a lowercase SHA-256 digest")
        request = urllib.request.Request(
            self.security.base_url.rstrip("/") + path,
            method="GET",
            headers={
                "Accept": "application/octet-stream",
                "Authorization": f"Bearer {bearer_token}",
                "Range": f"bytes={offset}-{offset + size_bytes - 1}" if size_bytes else f"bytes={offset}-{offset}",
            },
        )
        with self._open(request) as response:
            data = response.read()
        if len(data) != size_bytes:
            raise IOError("remote artifact chunk size does not match the requested range")
        if hashlib.sha256(data).hexdigest() != expected_digest:
            raise IOError("remote artifact chunk failed SHA-256 verification")
        return data
