"""Provider health state: cached connection validation results.

'connected' is only ever set by a REAL successful validation call — never by
credential presence alone. Overrides reset on server restart.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_status_overrides: dict[str, dict] = {}   # key -> {"status": ..., "checked_at": ..., "detail": ...}


def record_validation(key: str, status: str, detail: str = "") -> None:
    with _lock:
        _status_overrides[key] = {
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": detail[:300],
        }


def get_status_override(key: str) -> str | None:
    with _lock:
        entry = _status_overrides.get(key)
        return entry["status"] if entry else None


def get_last_validation(key: str) -> dict | None:
    with _lock:
        return _status_overrides.get(key)
