"""Explicit license and provenance gates for production assets and engines."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommercialStatus(StrEnum):
    ALLOWED = "allowed"
    REVIEW_REQUIRED = "review_required"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LicenseRecord:
    subject_id: str
    subject_version: str
    official_source: str
    license_name: str
    commercial_status: CommercialStatus
    territory_restriction: str | None = None
    attribution_required: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        for name, value in (("subject_id", self.subject_id), ("subject_version", self.subject_version), ("official_source", self.official_source), ("license_name", self.license_name)):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if not self.official_source.startswith(("https://", "http://")):
            raise ValueError("official_source must be an explicit URL")

    def permits_commercial_use(self, territory: str | None = None) -> bool:
        if self.commercial_status != CommercialStatus.ALLOWED:
            return False
        if self.territory_restriction and territory:
            return territory not in {item.strip() for item in self.territory_restriction.split(",") if item.strip()}
        return self.territory_restriction is None


class LicenseRegistry:
    """Require explicit records before an engine, model, voice, or asset enters production."""

    def __init__(self, records: tuple[LicenseRecord, ...] = ()):
        self._records = {record.subject_id: record for record in records}

    def register(self, record: LicenseRecord) -> None:
        if record.subject_id in self._records:
            raise ValueError(f"license record already exists: {record.subject_id}")
        self._records[record.subject_id] = record

    def get(self, subject_id: str) -> LicenseRecord:
        try:
            return self._records[subject_id]
        except KeyError as exc:
            raise KeyError(f"no license record for production subject: {subject_id}") from exc

    def require_commercial(self, subject_id: str, territory: str | None = None) -> LicenseRecord:
        record = self.get(subject_id)
        if not record.permits_commercial_use(territory):
            raise RuntimeError(f"commercial-use license gate failed for {subject_id}")
        return record

    def snapshot(self) -> tuple[LicenseRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))
