from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from clipsieve.config import REPO_ROOT

PINNED_COMMIT = "380b426000aac3d612837ed72c99808347dc94c9"


class XhsSettings(BaseSettings):
    # Relative paths are resolved against REPO_ROOT by MediaCrawlerRunner.mc_dir.
    # The CDP port is NOT here: core Settings.clipsieve_xhs_chrome_cdp_port owns it.
    clipsieve_xhs_mediacrawler_dir: Path = Path("../MediaCrawler")
    clipsieve_xhs_timeout_s: int = 900
    clipsieve_xhs_pinned_commit: str = PINNED_COMMIT
    # "video" asks the search API for videos only (api runner) and drops image notes before
    # anything is written (both runners).
    clipsieve_xhs_note_kinds: Literal["all", "video"] = "all"
    # Upper bound on search pages per query. One page is one API request plus one detail
    # request per note (api runner) or one full MediaCrawler crawl (mediacrawler runner).
    clipsieve_xhs_max_pages: int = Field(default=10, ge=1)
    # Which runner collects: the direct web API with the browser's cookies (default) or a
    # MediaCrawler checkout driven as a subprocess (fallback).
    clipsieve_xhs_runner: Literal["api", "mediacrawler"] = "api"
    # api runner only: fetch the first page of comments per note (one more request each).
    clipsieve_xhs_comments: bool = False
    # api runner only: seconds between requests (jittered 0.75x to 1.25x) and the backoff base.
    clipsieve_xhs_request_interval_s: float = Field(default=1.0, ge=0)
    # api runner only: notes per search request; the platform caps it at 20.
    clipsieve_xhs_page_size: int = Field(default=20, ge=1, le=20)

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )


@lru_cache
def get_xhs_settings() -> XhsSettings:
    return XhsSettings()
