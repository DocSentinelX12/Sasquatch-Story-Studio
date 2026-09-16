"""Authenticated TLS transport contracts for remote GPU workers.

The transport does not generate certificates or secrets. Credentials must be
provisioned outside source control and referenced by filesystem paths or the
runtime environment.
"""
from __future__ import annotations

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
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"worker transport failed: {exc}") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("worker transport returned non-JSON data") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("worker transport response must be a JSON object")
        return decoded
