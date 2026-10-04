# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/adapter.py
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from clipsieve.adapters.base import Adapter, AdapterHealth, MediaDownloadError, incoming_dir
from clipsieve.config import Settings, ensure_creator_salt, get_settings
from clipsieve.logging import get_logger
from clipsieve.models import Media, Post, Query
from clipsieve.store.paths import safe_post_filename
from clipsieve_xhs.mapping import (
    PLATFORM,
    group_comments,
    image_urls,
    map_note,
    note_id,
    note_type,
    video_urls,
)
from clipsieve_xhs.runner import MediaCrawlerRunner, RunnerProtocol
from clipsieve_xhs.settings import XhsSettings, get_xhs_settings

log = get_logger(__name__)

REFERER = "https://www.xiaohongshu.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
CACHE_SUBDIR = "adapter-cache"
DOWNLOAD_TIMEOUT_S = 30.0
# Dropped before the raw payload is written (backend/AGENTS.md: author identifiers are not stored).
RAW_NOTE_DROP = frozenset({"xsec_token"})
RAW_COMMENT_DROP = frozenset({"creator_hash", "nickname", "pictures"})


def _strip(record: dict, drop: frozenset[str]) -> dict:
    return {k: v for k, v in record.items() if k not in drop}


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


class XhsMediaCrawlerAdapter(Adapter):
    """Xiaohongshu via a local MediaCrawler checkout. Media is downloaded here with httpx."""

    platform = PLATFORM

    def __init__(
        self,
        settings: Settings | None = None,
        xhs_settings: XhsSettings | None = None,
        runner: RunnerProtocol | None = None,
        http: httpx.Client | None = None,
        raw_dir: Path | None = None,
        cache_dir: Path | None = None,
        now: Callable[[], datetime] = _now_utc,
    ) -> None:
        self.settings = settings or get_settings()
        self.xhs = xhs_settings or get_xhs_settings()
        self.http = http or httpx.Client(
            timeout=DOWNLOAD_TIMEOUT_S,
            follow_redirects=True,
            headers={"Referer": REFERER, "User-Agent": USER_AGENT},
        )
        self.runner = runner or self._runner_from_settings()
        self.raw_dir = raw_dir or incoming_dir(self.settings.clipsieve_data_dir, self.platform)
        self.cache_dir = cache_dir or (
            self.settings.clipsieve_data_dir / CACHE_SUBDIR / self.platform
        )
        self._now = now
        self._media_cache: dict[str, list[str]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> XhsMediaCrawlerAdapter:
        return cls(settings=settings)

    # ---- Adapter protocol -------------------------------------------------

    def healthcheck(self) -> AdapterHealth:
        return self.runner.healthcheck()

    def _runner_from_settings(self) -> RunnerProtocol:
        port = self.settings.clipsieve_xhs_chrome_cdp_port
        if self.xhs.clipsieve_xhs_runner == "api":
            from clipsieve_xhs.api_runner import (
                XhsApiRunner,
            )  # keeps MediaCrawler-only installs importable

            return XhsApiRunner(self.xhs, cdp_port=port, http=self.http)
        return MediaCrawlerRunner(self.xhs, cdp_port=port)

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        """One MediaCrawler run per page, from page 1, until `limit` posts are yielded, a page
        adds no unseen note, or `clipsieve_xhs_max_pages` is reached. Notes are deduped by id
        across pages and queries; with `clipsieve_xhs_note_kinds == "video"` image notes are
        dropped before any raw payload or media cache is written."""
        seen: set[str] = set()
        yielded = 0
        video_only = self.xhs.clipsieve_xhs_note_kinds == "video"
        max_pages = self.xhs.clipsieve_xhs_max_pages
        salt = ensure_creator_salt(self.settings)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        for q in queries:
            if q.platform != self.platform:
                continue
            page = 1
            while yielded < limit:
                new_notes = new_posts = skipped = 0
                for note, comments in self._run_page(q.query, page):
                    nid = note_id(note)
                    if not nid or nid in seen:
                        continue
                    seen.add(nid)
                    new_notes += 1
                    if video_only and note_type(note) != "video":
                        skipped += 1
                        continue
                    new_posts += 1
                    yield self._collect(note, comments, q.query, salt)
                    yielded += 1
                    if yielded >= limit:
                        break
                log.info(
                    "xhs.page",
                    query=q.query,
                    page=page,
                    new_notes=new_notes,
                    new_posts=new_posts,
                    skipped=skipped,
                    total=yielded,
                )
                if new_notes == 0:
                    break
                if page >= max_pages:
                    if yielded < limit:
                        log.warning(
                            "xhs.page_cap",
                            query=q.query,
                            pages=page,
                            total=yielded,
                            limit=limit,
                        )
                    break
                page += 1

    def media_urls_for(self, post_id: str) -> list[str]:
        """Memory first, then the on-disk cache `search` wrote. Never reads the raw payload:
        the Runner relocates it before `fetch_media` runs (overview B.10)."""
        if post_id in self._media_cache:
            return self._media_cache[post_id]
        path = self._cache_path(post_id)
        try:
            urls = [str(u) for u in json.loads(path.read_text(encoding="utf-8"))["urls"]]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise MediaDownloadError(
                f"{post_id}: no cached media URLs ({e}); run search first"
            ) from e
        self._media_cache[post_id] = urls
        return urls

    def fetch_media(self, post: Post, dest: Path) -> Post:
        """Download into `dest`; `local_path` is relative to `dest` (Addendum B2). Idempotent."""
        urls = self.media_urls_for(post.id)  # raises MediaDownloadError when nothing is cached
        if not urls:
            return post
        dest.mkdir(parents=True, exist_ok=True)
        if post.kind == "video":
            name = "video.mp4"
            self._download(urls[0], dest / name)  # first URL is the main stream, the rest are low
            media = [m.model_copy(update={"local_path": name}) for m in post.media] or [
                Media(type="video", local_path=name, index=0)
            ]
        else:
            media = []
            for i, url in enumerate(urls):
                name = f"img_{i:02d}.jpg"  # fixed extension (B2), whatever the URL says
                self._download(url, dest / name)
                existing = post.media[i] if i < len(post.media) else Media(type="image", index=i)
                media.append(existing.model_copy(update={"local_path": name}))
        return post.model_copy(update={"media": media})

    # ---- helpers ----------------------------------------------------------

    def _run_page(self, keyword: str, page: int) -> Iterator[tuple[dict, list[dict]]]:
        with tempfile.TemporaryDirectory(prefix="clipsieve-xhs-") as tmp:
            out = self.runner.search(keyword, start_page=page, workdir=Path(tmp))
        for err in out.errors:
            log.warning("xhs.runner.error", query=keyword, page=page, error=err)
        grouped = group_comments(out.comments)
        for note in out.notes:
            yield note, grouped.get(note_id(note), [])

    def _collect(self, note: dict, comments: list[dict], query: str, salt: str) -> Post:
        post_id = f"{PLATFORM}:{note_id(note)}"
        raw_path = self.raw_dir / f"{safe_post_filename(post_id)}.json"
        payload = {
            "note": _strip(note, RAW_NOTE_DROP),
            "comments": [_strip(c, RAW_COMMENT_DROP) for c in comments],
            "query": query,
        }
        raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._remember_media_urls(post_id, note)
        return map_note(note, comments, salt, raw_ref=str(raw_path), collected_at=self._now())

    def _cache_path(self, post_id: str) -> Path:
        return self.cache_dir / f"{safe_post_filename(post_id)}.media.json"

    def _remember_media_urls(self, post_id: str, note: dict) -> None:
        urls = video_urls(note) if note_type(note) == "video" else image_urls(note)
        self._media_cache[post_id] = urls
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(post_id).write_text(
            json.dumps({"urls": urls}, ensure_ascii=False), encoding="utf-8"
        )

    def _download(self, url: str, target: Path) -> None:
        if target.exists() and target.stat().st_size > 0:
            return
        part = target.with_name(target.name + ".part")
        try:
            with self.http.stream("GET", url) as resp:
                resp.raise_for_status()
                with part.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            part.replace(target)
        except httpx.HTTPError as e:
            part.unlink(missing_ok=True)
            log.warning("xhs.media_download_failed", target=target.name, error=str(e))
            raise MediaDownloadError(f"{url}: {e}") from e
