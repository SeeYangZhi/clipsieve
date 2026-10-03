"""Application settings. The only place that reads environment variables."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from clipsieve.logging import get_logger

log = get_logger(__name__)

# backend/clipsieve/config.py -> repo root. Scripts `cd backend`, so nothing may depend on cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
CREATOR_SALT_FILE = "creator_salt"


class Settings(BaseSettings):
    typesafe_api_key: str = ""
    clipsieve_explain_backend: Literal["claude_cli", "claude_api", "fake"] = "claude_cli"
    clipsieve_claude_bin: str = "claude"
    clipsieve_claude_max_budget_usd: float = 3.0
    anthropic_api_key: str = ""
    youtube_api_key: str = ""
    clipsieve_data_dir: Path = Path("./data")
    clipsieve_creator_salt: str = ""
    clipsieve_xhs_chrome_cdp_port: int = 9222

    # Later files win: a cwd .env overrides the repo-root one.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("clipsieve_data_dir", mode="after")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        """A relative data dir is relative to the repo root; an absolute one is kept as given."""
        return v if v.is_absolute() else REPO_ROOT / v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def ensure_creator_salt(settings: Settings) -> str:
    """Return the per-install salt for `hash_creator`.

    Uses CLIPSIEVE_CREATOR_SALT when set; otherwise reads `<data_dir>/creator_salt`, creating it
    (32 hex chars, mode 0600) on first use. The salt value is never logged.
    """
    if settings.clipsieve_creator_salt:
        return settings.clipsieve_creator_salt
    path = settings.clipsieve_data_dir / CREATOR_SALT_FILE
    if path.exists():
        salt = path.read_text(encoding="utf-8").strip()
        if salt:
            return salt
    settings.clipsieve_data_dir.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(16)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fd, 0o600)  # also tightens a pre-existing empty file
        fh.write(salt)
    log.info("creator_salt_created", path=str(path))
    return salt
