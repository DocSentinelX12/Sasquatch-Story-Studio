"""Application configuration for Sasquatch Story Studio.

All provider credentials are read from the process environment (optionally a
git-ignored `.env` file at the repository root). Credential VALUES are never
exposed through the API or the frontend -- only their presence/absence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real env vars."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


_DOTENV = _load_dotenv(REPO_ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable, falling back to the local .env file."""
    value = os.environ.get(name)
    if value is None:
        value = _DOTENV.get(name)
    return value if value is not None and value != "" else default


def env_is_set(name: str) -> bool:
    return env(name) is not None


@dataclass(frozen=True)
class Settings:
    repo_root: Path = REPO_ROOT
    database_path: Path = field(default_factory=lambda: Path(env("STUDIO_DB_PATH", ".data/studio.db")))
    upload_root: Path = field(default_factory=lambda: Path(env("STUDIO_UPLOAD_ROOT", "assets/studio-uploads")))
    app_name: str = "Sasquatch Story Studio"
    app_version: str = "0.1.0-phase1"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def database_absolute(self) -> Path:
        return self.database_path if self.database_path.is_absolute() else self.repo_root / self.database_path

    @property
    def upload_root_absolute(self) -> Path:
        return self.upload_root if self.upload_root.is_absolute() else self.repo_root / self.upload_root

    @property
    def web_root(self) -> Path:
        return self.repo_root / "web"


settings = Settings()
