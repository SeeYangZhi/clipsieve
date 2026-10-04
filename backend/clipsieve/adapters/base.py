"""Adapter protocol and shared helpers.

Required methods (the `Adapter` Protocol): `platform`, `search(queries, limit)`,
`fetch_media(post, dest)`, `healthcheck()`, plus the `from_settings(settings)` classmethod.

Optional method, NOT part of the Protocol so adapters without it keep working:

    def fetch_cover(self, post: Post, dest: Path) -> Path | None

Downloads a small cover image for `post` into `dest / COVER_NAME` (`thumb.jpg`), creating
`dest`, and returns that path; returns `None` when the adapter has no cover for the post. An
existing `dest / COVER_NAME` is kept and returned. It must never raise for ordinary failures
(network, 404, bad image): return `None` and log at info with `post_id` only, never the URL.
Core calls it through `cover_fetcher(adapter)` after storing a post and before emitting its
`post_collected`, and once more on resume for stored posts without a cover, so a cover exists
for every collected post, including those pass one drops before any `fetch_media`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from clipsieve.models import Post, Query

# The cover file inside a post's media dir; `evidence/extract.py` writes the same name from the
# first keyframe and keeps an existing one, so a collection-time cover is never overwritten.
COVER_NAME = "thumb.jpg"


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


def cover_fetcher(adapter: Adapter) -> Callable[[Post, Path], Path | None] | None:
    """The adapter's optional `fetch_cover` bound method, or None when it has none."""
    fetch = getattr(adapter, "fetch_cover", None)
    return fetch if callable(fetch) else None


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
