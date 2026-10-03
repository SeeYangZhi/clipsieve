"""Adapter that serves the five fixture posts as the `local` platform.

Used by tests, `CLIPSIEVE_EXPLAIN_BACKEND=fake` and the Playwright flow. Registered only when
`CLIPSIEVE_FIXTURE_DIR` is set. Fixture layout under that dir: `posts/<safe_id>.json` (Post),
`raw/<safe_id>.json` (raw payload), `evidence/<safe_id>/` (media files plus sidecars).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from clipsieve.adapters.base import Adapter, AdapterHealth, incoming_dir
from clipsieve.config import Settings
from clipsieve.logging import get_logger
from clipsieve.models import Media, Post, Query
from clipsieve.store.paths import safe_post_filename

log = get_logger(__name__)


def _media_name(index: int, media: Media) -> str:
    return "video.mp4" if media.type == "video" else f"img_{index:02d}.jpg"


class FixtureAdapter(Adapter):
    platform = "local"

    def __init__(self, fixture_dir: Path, data_dir: Path) -> None:
        self._fixtures = Path(fixture_dir)
        self._data_dir = Path(data_dir)

    @classmethod
    def from_settings(cls, settings: Settings) -> FixtureAdapter:
        if settings.clipsieve_fixture_dir is None:
            raise ValueError("CLIPSIEVE_FIXTURE_DIR is not set")
        return cls(settings.clipsieve_fixture_dir, settings.clipsieve_data_dir)

    def healthcheck(self) -> AdapterHealth:
        posts = self._fixtures / "posts"
        ok = posts.is_dir()
        return AdapterHealth(ok=ok, message="fixture posts present" if ok else f"missing {posts}")

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        """The fixture posts in id order, whatever the queries. Raw payloads go to incoming/."""
        incoming = incoming_dir(self._data_dir, self.platform)
        for path in sorted((self._fixtures / "posts").glob("*.json"))[: max(limit, 0)]:
            post = Post.model_validate_json(path.read_text(encoding="utf-8"))
            safe = safe_post_filename(post.id)
            raw_dst = incoming / f"{safe}.json"
            shutil.copyfile(self._fixtures / "raw" / f"{safe}.json", raw_dst)
            yield post.model_copy(
                update={
                    "raw_ref": str(raw_dst),
                    "media": [m.model_copy(update={"local_path": None}) for m in post.media],
                }
            )

    def fetch_media(self, post: Post, dest: Path) -> Post:
        """Copy `evidence/<safe_id>/` (media, sidecars, frames/ OCR sidecars) into dest.

        Existing files are kept (idempotent). A media item whose file is not in the fixture keeps
        `local_path = None`, so extraction skips it.
        """
        dest.mkdir(parents=True, exist_ok=True)
        src = self._fixtures / "evidence" / safe_post_filename(post.id)
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                target = dest / f.relative_to(src)
                if f.is_file() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, target)
        media: list[Media] = []
        for i, m in enumerate(post.media):
            name = _media_name(i, m)
            if not (dest / name).is_file():
                log.warning("fixture_media_missing", post_id=post.id, name=name)
                name = None
            media.append(m.model_copy(update={"local_path": name}))
        return post.model_copy(update={"media": media})
