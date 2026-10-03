"""YouTube Shorts. Search via yt-dlp, or the Data API when a key is set; media via yt-dlp."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import httpx

from clipsieve.adapters.base import AdapterHealth, hash_creator, incoming_dir
from clipsieve.adapters.vtt import parse_vtt, vtt_lang_from_filename
from clipsieve.adapters.ytdlp_client import FakeYtDlpClient, RealYtDlpClient, YtDlpClient
from clipsieve.config import Settings, ensure_creator_salt
from clipsieve.logging import get_logger
from clipsieve.models import Comment, Media, Metrics, Post, PostText, Query, TranscriptSegment
from clipsieve.store.paths import safe_post_filename

log = get_logger(__name__)

HASHTAG = re.compile(r"#([\w一-鿿]+)")
DATA_API_SEARCH = "https://www.googleapis.com/youtube/v3/search"
MAX_COMMENTS = 50
DEFAULT_MAX_DURATION_S = 180
CAPTION_LANGS = ("en", "zh-Hans", "zh-Hant", "zh")
# The Data API wants zh-Hans / zh-Hant as given; every other language as its primary subtag.
_DATA_API_FULL_LANGS = {"zh-Hans", "zh-Hant"}
# Comment keys kept in the persisted raw payload. author, author_id, author_url, ... are dropped:
# comments carry no author identifiers.
RAW_COMMENT_KEYS = frozenset({"id", "parent", "text", "like_count", "timestamp", "is_pinned"})
# yt-dlp writes `video.<ext>` (outtmpl `video.%(ext)s`); these siblings are not the media file.
_NOT_MEDIA_SUFFIXES = {".vtt", ".part", ".ytdl", ".json"}


class MediaDownloadError(RuntimeError):
    """yt-dlp finished without leaving a media file (over max_filesize, or unavailable)."""


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _posted_at(info: dict[str, Any]) -> datetime | None:
    if info.get("timestamp"):
        return datetime.fromtimestamp(int(info["timestamp"]), tz=UTC)
    if info.get("upload_date"):
        return datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=UTC)
    return None


def _strip_comment_authors(info: dict[str, Any]) -> dict[str, Any]:
    """Copy of `info` whose comments keep no author fields. Persist this, never `info`."""
    if not info.get("comments"):
        return info
    clean = dict(info)
    clean["comments"] = [
        {k: v for k, v in c.items() if k in RAW_COMMENT_KEYS} for c in info["comments"]
    ]
    return clean


def map_info_to_post(info: dict[str, Any], salt: str, raw_ref: str) -> Post:
    video_id = info["id"]
    description = info.get("description") or ""
    tags = {t.strip().replace(" ", "") for t in (info.get("tags") or []) if t.strip()}
    hashtags = sorted(tags | set(HASHTAG.findall(description)))
    comments = sorted(
        (c for c in (info.get("comments") or []) if (c.get("text") or "").strip()),
        key=lambda c: int(c.get("like_count") or 0),
        reverse=True,
    )[:MAX_COMMENTS]
    return Post(
        id=f"youtube:{video_id}",
        platform="youtube",
        url=f"https://www.youtube.com/shorts/{video_id}",
        creator_hash=hash_creator(
            info.get("channel_id") or info.get("uploader_id") or video_id, salt
        ),
        creator_display=info.get("uploader") or info.get("channel"),
        posted_at=_posted_at(info),
        kind="video",
        text=PostText(title=info.get("title"), caption=description or None, hashtags=hashtags),
        media=[
            Media(
                type="video",
                duration_s=info.get("duration"),
                width=info.get("width"),
                height=info.get("height"),
            )
        ],
        metrics=Metrics(
            views=info.get("view_count"),
            likes=info.get("like_count"),
            comments=info.get("comment_count"),
        ),
        comments=[Comment(text=c["text"], likes=c.get("like_count")) for c in comments],
        lang=info.get("language"),
        raw_ref=raw_ref,
        collected_at=datetime.now(UTC),
    )


def write_transcript_sidecar(
    media_path: Path, lang: str | None, segments: list[TranscriptSegment]
) -> Path:
    """Write `<media>.transcript.json` = {"lang", "segments"}. `lang` is omitted when unknown."""
    sidecar = media_path.with_name(media_path.name + ".transcript.json")
    payload: dict[str, Any] = {"lang": lang} if lang else {}
    payload["segments"] = [s.model_dump(mode="json") for s in segments]
    part = sidecar.with_name(sidecar.name + ".part")
    part.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(part, sidecar)
    return sidecar


def _caption_langs(post_lang: str | None) -> list[str]:
    """Caption languages in preference order: the post's own language first, then the defaults."""
    head = [post_lang] if post_lang else []
    return head + [lang for lang in CAPTION_LANGS if lang != post_lang]


def _existing_video(dest: Path) -> Path | None:
    """The finished `video.<ext>` in `dest`, if any. mp4 wins when several exist."""
    found = [
        p
        for p in dest.glob("video.*")
        if p.stem == "video" and p.suffix.lower() not in _NOT_MEDIA_SUFFIXES and p.is_file()
    ]
    return min(found, key=lambda p: (p.suffix.lower() != ".mp4", p.name), default=None)


class YouTubeAdapter:
    platform = "youtube"

    def __init__(
        self,
        client: YtDlpClient,
        data_dir: Path,
        salt: str,
        api_key: str = "",
        http: httpx.Client | None = None,
        max_duration_s: int = DEFAULT_MAX_DURATION_S,
    ) -> None:
        self._client = client
        self._raw_dir = incoming_dir(data_dir, self.platform)
        self._salt = salt
        self._api_key = api_key
        self._http = http
        self._max_duration_s = max_duration_s

    @classmethod
    def from_settings(cls, settings: Settings) -> YouTubeAdapter:
        return cls(
            client=RealYtDlpClient(),
            data_dir=settings.clipsieve_data_dir,
            salt=ensure_creator_salt(settings),
            api_key=settings.youtube_api_key,
        )

    # -- search ---------------------------------------------------------------

    def _is_short(self, duration: float | None) -> bool:
        return duration is None or duration < self._max_duration_s

    def _candidate_ids(self, query: Query, n: int) -> list[str]:
        if self._api_key:
            try:
                return self._data_api_ids(query, n)
            except (httpx.HTTPError, ValueError) as exc:
                # Log the type and status only: an httpx error message embeds the request URL.
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                log.warning("youtube_data_api_failed", error_type=type(exc).__name__, status=status)
        entries = self._client.search(query.query, n)
        return [e["id"] for e in entries if e.get("id") and self._is_short(e.get("duration"))]

    def _data_api_ids(self, query: Query, n: int) -> list[str]:
        if self._http is None:
            self._http = httpx.Client(timeout=20.0)
        # The key goes in a header, never the URL, so it cannot reach logs or error messages.
        headers = {"x-goog-api-key": self._api_key}
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < n:
            params: dict[str, str | int] = {
                "part": "id",
                "type": "video",
                "videoDuration": "short",
                "q": query.query,
                "maxResults": min(50, n - len(ids)),
            }
            if query.lang:
                lang = query.lang
                params["relevanceLanguage"] = (
                    lang if lang in _DATA_API_FULL_LANGS else lang.split("-")[0]
                )
            if page_token:
                params["pageToken"] = page_token
            resp = self._http.get(DATA_API_SEARCH, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            ids.extend(
                item["id"]["videoId"]
                for item in body.get("items", [])
                if (item.get("id") or {}).get("videoId")
            )
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return ids[:n]

    def _collect(self, video_id: str) -> Post | None:
        try:
            info = self._client.info(_watch_url(video_id))
        except Exception as exc:  # noqa: BLE001 - one bad video must not stop the search
            log.warning("youtube_info_failed", video_id=video_id, error=str(exc))
            return None
        if not info.get("id"):
            log.warning("youtube_info_empty", video_id=video_id)
            return None
        if not self._is_short(info.get("duration")):
            return None
        raw = _strip_comment_authors(info)
        post_id = f"youtube:{raw['id']}"
        # Persist the raw payload before normalising it. default=str: yt-dlp info dicts can hold
        # values json cannot encode.
        raw_path = self._raw_dir / f"{safe_post_filename(post_id)}.json"
        raw_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        try:
            return map_info_to_post(raw, self._salt, str(raw_path))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("youtube_mapping_failed", post_id=post_id, error=str(exc))
            return None

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        seen: set[str] = set()
        yielded = 0
        for q in queries:
            if yielded >= limit:
                return
            for video_id in self._candidate_ids(q, limit - yielded):
                # Stop before fetching the next info, so no raw payload is written for it.
                if yielded >= limit:
                    return
                if video_id in seen:
                    continue
                seen.add(video_id)
                post = self._collect(video_id)
                if post is not None:
                    yield post
                    yielded += 1

    # -- media ----------------------------------------------------------------

    def fetch_media(self, post: Post, dest: Path) -> Post:
        """Download once into `dest`; `local_path` is relative to `dest`. Idempotent."""
        dest.mkdir(parents=True, exist_ok=True)
        video = _existing_video(dest) or self._download(post, dest)
        if not video.with_name(video.name + ".transcript.json").exists():
            self._write_sidecar_from_vtt(dest, video, post.lang)
        media = [m.model_copy(update={"local_path": video.name}) for m in post.media] or [
            Media(type="video", local_path=video.name)
        ]
        return post.model_copy(update={"media": media})

    def _download(self, post: Post, dest: Path) -> Path:
        video_id = post.id.partition(":")[2]
        result = self._client.download(
            _watch_url(video_id), dest, subtitle_langs=_caption_langs(post.lang)
        )
        # The format fallback may yield another container than mp4: trust what yt-dlp reports.
        downloads = result.get("requested_downloads") or []
        reported = downloads[0].get("filepath") if downloads else None
        video = dest / Path(reported).name if reported else _existing_video(dest)
        # yt-dlp skips a file over max_filesize without raising, so check the file is there.
        if video is None or not video.is_file():
            log.warning("youtube_media_missing", post_id=post.id)
            raise MediaDownloadError(
                f"yt-dlp left no media file for {post.id} (over max_filesize or unavailable)"
            )
        return video

    def _write_sidecar_from_vtt(self, dest: Path, video: Path, post_lang: str | None) -> None:
        preferred = _caption_langs(post_lang)

        def rank(path: Path) -> tuple[int, str]:
            lang = vtt_lang_from_filename(path)
            return (preferred.index(lang) if lang in preferred else len(preferred), path.name)

        for vtt in sorted(dest.glob("video.*.vtt"), key=rank):
            try:
                segments = parse_vtt(vtt.read_text(encoding="utf-8"))
            except ValueError as exc:  # bad timestamp, or not UTF-8
                log.warning("youtube_captions_unparseable", file=vtt.name, error=str(exc))
                continue
            if segments:
                write_transcript_sidecar(video, vtt_lang_from_filename(vtt), segments)
                return

    def healthcheck(self) -> AdapterHealth:
        # find_spec, not import: only RealYtDlpClient imports yt_dlp.
        if find_spec("yt_dlp") is None:
            return AdapterHealth(ok=False, message="yt-dlp not installed; run uv sync")
        search = "Data API search" if self._api_key else "yt-dlp search"
        return AdapterHealth(ok=True, message=f"yt-dlp available; {search}")


__all__ = [
    "FakeYtDlpClient",
    "MediaDownloadError",
    "YouTubeAdapter",
    "map_info_to_post",
    "write_transcript_sidecar",
]
