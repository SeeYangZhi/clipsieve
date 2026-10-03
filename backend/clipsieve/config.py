"""Application settings. The only place that reads environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
