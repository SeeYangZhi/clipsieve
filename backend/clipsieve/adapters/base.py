from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from clipsieve.models import Post, Query


class MediaDownloadError(Exception):
    """yt-dlp finished without leaving a media file (over max_filesize, or unavailable)."""


@dataclass
class AdapterHealth:
    ok: bool
    message: str


@runtime_checkable
class Adapter(Protocol):
    platform: str

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]: ...

    def fetch_media(self, post: Post, dest: Path) -> Post: ...

    def healthcheck(self) -> AdapterHealth: ...


def hash_creator(platform_creator_id: str, salt: str) -> str:
    """Stable, salted, one-way creator identifier.

    Never put the raw id in a Post; raw payloads keep platform ids as local provenance.
    """
    return hashlib.sha256(f"{salt}:{platform_creator_id}".encode()).hexdigest()


def incoming_dir(data_dir: Path, platform: str) -> Path:
    """Where adapters park raw payloads before the Runner relocates them into the run."""
    d = data_dir / "incoming" / platform
    d.mkdir(parents=True, exist_ok=True)
    return d
