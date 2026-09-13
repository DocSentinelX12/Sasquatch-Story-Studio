"""Stable interfaces for optional AI production engines."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterInfo:
    id: str
    version: str
    license: str
    capabilities: tuple[str, ...]
    verified: bool = False


class ProductionAdapter(Protocol):
    info: AdapterInfo

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute a production request and return output references plus provenance."""
        ...


def require_verified(adapter: ProductionAdapter) -> None:
    if not adapter.info.verified:
        raise RuntimeError(f"Adapter {adapter.info.id} is not license/capability verified")
