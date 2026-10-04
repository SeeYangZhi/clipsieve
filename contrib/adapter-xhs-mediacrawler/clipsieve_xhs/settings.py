from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from clipsieve.config import REPO_ROOT

PINNED_COMMIT = "380b426000aac3d612837ed72c99808347dc94c9"


class XhsSettings(BaseSettings):
    # Relative paths are resolved against REPO_ROOT by MediaCrawlerRunner.mc_dir.
    # The CDP port is NOT here: core Settings.clipsieve_xhs_chrome_cdp_port owns it.
    clipsieve_xhs_mediacrawler_dir: Path = Path("../MediaCrawler")
    clipsieve_xhs_timeout_s: int = 900
    clipsieve_xhs_pinned_commit: str = PINNED_COMMIT

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )


@lru_cache
def get_xhs_settings() -> XhsSettings:
    return XhsSettings()
