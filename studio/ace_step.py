"""ACE-Step 1.5 service adapter.

The adapter talks only to an explicitly configured ACE-Step REST service. It
does not start a server, download models, or silently substitute another
provider. Runtime production verification is supplied separately by the
engine registry after real execution and license/checkpoint evidence exists.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .adapters import AdapterInfo
from .engine_registry import get_catalog_engine
from .production import ProductionRequest, ProductionResponse


@dataclass(frozen=True)
class AceStepServiceAdapter:
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 3600
    poll_interval_seconds: float = 1.0

    @property
    def info(self) -> AdapterInfo:
        engine = get_catalog_engine("ace-step-1.5")
        return AdapterInfo(engine.id, engine.version_family, engine.license, engine.capabilities, False)

    @property
    def is_local(self) -> bool:
        parsed = urlparse(self.base_url)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    @property
    def uses_paid_service(self) -> bool:
        return False

    @property
    def uses_paid_api(self) -> bool:
        return False

    def _url(self, path: str) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ACE-Step service URL must be an explicit HTTP(S) URL")
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self._url(path), data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"ACE-Step service request failed: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ACE-Step service returned non-JSON response") from exc
        if not isinstance(data, dict):
            raise RuntimeError("ACE-Step service returned an invalid response")
        return data

    def health(self) -> bool:
        data = self._request("GET", "/health")
        return data.get("code") == 200 or data.get("status") in {"ok", "healthy"}

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        if not request.stage == "sound_music":
            raise RuntimeError("ACE-Step 1.5 adapter only executes the sound_music stage")
        payload = request.payload
        output_dir = Path(str(payload.get("output_dir", ""))).expanduser().resolve()
        if not output_dir.is_dir():
            raise RuntimeError(f"ACE-Step output directory does not exist: {output_dir}")
        prompt = payload.get("prompt", "")
        lyrics = payload.get("lyrics", "[inst]")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("ACE-Step requires a non-empty prompt")
        if not isinstance(lyrics, str):
            raise ValueError("ACE-Step lyrics must be text")
        params = dict(payload.get("param_obj", {}))
        if not isinstance(params, dict):
            raise ValueError("ACE-Step param_obj must be an object")
        params.update({"prompt": prompt, "lyrics": lyrics})
        if request.seed is not None:
            params["seed"] = request.seed
        body = {"param_obj": params, "batch_size": int(payload.get("batch_size", 1))}
        if body["batch_size"] < 1:
            raise ValueError("ACE-Step batch_size must be positive")
        submitted = self._request("POST", "/release_task", body)
        task_ids = submitted.get("data")
        if not isinstance(task_ids, list) or not task_ids:
            raise RuntimeError("ACE-Step release_task returned no task IDs")
        task_ids = [str(item) for item in task_ids]
        deadline = time.monotonic() + self.timeout_seconds
        results: list[str] = []
        while time.monotonic() < deadline:
            queried = self._request("POST", "/query_result", {"task_id_list": task_ids})
            data = queried.get("data")
            if not isinstance(data, list):
                raise RuntimeError("ACE-Step query_result returned invalid data")
            statuses = {str(item.get("task_id")): item for item in data if isinstance(item, dict)}
            if any(statuses.get(task_id, {}).get("status") == 2 for task_id in task_ids):
                raise RuntimeError("ACE-Step generation task failed")
            if all(statuses.get(task_id, {}).get("status") == 1 for task_id in task_ids):
                for task_id in task_ids:
                    raw_result = statuses[task_id].get("result")
                    if not isinstance(raw_result, str):
                        raise RuntimeError("ACE-Step completed task has no result")
                    parsed = json.loads(raw_result)
                    if not isinstance(parsed, list):
                        raise RuntimeError("ACE-Step task result is not a list")
                    for item in parsed:
                        if isinstance(item, dict) and isinstance(item.get("file"), str):
                            results.append(self._download_audio(item["file"], output_dir))
                if not results:
                    raise RuntimeError("ACE-Step completed task returned no audio files")
                return ProductionResponse(
                    self.info.id,
                    tuple(results),
                    {
                        "engine_id": self.info.id,
                        "engine_version_family": self.info.version,
                        "official_source": get_catalog_engine(self.info.id).official_source,
                        "license": self.info.license,
                        "canonical_source_hash": request.canonical_source_hash,
                        "task_ids": task_ids,
                        "endpoint": "/release_task",
                        "runtime_verification": "adapter execution evidence must be recorded separately before production promotion",
                    },
                )
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError("ACE-Step generation timed out")

    def _download_audio(self, file_url: str, output_dir: Path) -> str:
        parsed = urlparse(file_url)
        if parsed.scheme or parsed.netloc:
            target = urlparse(self._url(file_url))
            base = urlparse(self.base_url)
            if target.scheme != base.scheme or target.netloc != base.netloc:
                raise RuntimeError("ACE-Step audio URL leaves the configured service")
            url = target.geturl()
        else:
            url = self._url(file_url)
        suffix = Path(parsed.path).suffix or ".audio"
        digest = hashlib.sha256(file_url.encode("utf-8")).hexdigest()[:24]
        destination = output_dir / f"acestep-{digest}{suffix}"
        request = Request(url, method="GET", headers={"Accept": "audio/*"})
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urlopen(request, timeout=60) as response, destination.open("wb") as target:
                target.write(response.read())
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"ACE-Step audio download failed: {exc}") from exc
        if destination.stat().st_size == 0:
            raise RuntimeError("ACE-Step audio output is empty")
        return str(destination)
