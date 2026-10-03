"""yt-dlp behind a small interface. `RealYtDlpClient` is the only network path."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from clipsieve.logging import get_logger

log = get_logger(__name__)

MAX_FILESIZE_BYTES = 200 * 1024 * 1024


class YtDlpClient(Protocol):
    def search(self, query: str, n: int) -> list[dict[str, Any]]: ...

    def info(self, url: str) -> dict[str, Any]: ...

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]:
        """Download into `dest/video.<ext>`. An empty `subtitle_langs` writes no captions."""
        ...


class RealYtDlpClient:
    """Thin wrapper over yt_dlp.YoutubeDL. Only this class imports yt_dlp."""

    def _ydl(self, **opts: Any):
        import yt_dlp  # lazy: keep adapters importable without yt_dlp for tooling

        base = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YtLogger()}
        base.update(opts)
        return yt_dlp.YoutubeDL(base)

    def search(self, query: str, n: int) -> list[dict[str, Any]]:
        with self._ydl(extract_flat="in_playlist", skip_download=True) as ydl:
            result = ydl.extract_info(f"ytsearch{n}:{query}", download=False) or {}
        return list(result.get("entries") or [])

    def info(self, url: str) -> dict[str, Any]:
        with self._ydl(
            skip_download=True,
            getcomments=True,
            extractor_args={"youtube": {"max_comments": ["50", "all", "0", "0"]}},
        ) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]:
        dest.mkdir(parents=True, exist_ok=True)
        captions = bool(subtitle_langs)
        opts: dict[str, Any] = {
            "outtmpl": str(dest / "video.%(ext)s"),
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "merge_output_format": "mp4",
            "max_filesize": MAX_FILESIZE_BYTES,
            "writeautomaticsub": captions,
            "writesubtitles": captions,
        }
        if captions:
            opts["subtitleslangs"] = subtitle_langs
            opts["subtitlesformat"] = "vtt"
        with self._ydl(**opts) as ydl:
            return ydl.extract_info(url, download=True) or {}


class _YtLogger:
    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        log.debug("ytdlp", msg=msg)

    def info(self, msg: str) -> None:
        log.debug("ytdlp", msg=msg)

    def warning(self, msg: str) -> None:
        log.warning("ytdlp", msg=msg)

    def error(self, msg: str) -> None:
        log.error("ytdlp", msg=msg)


class FakeYtDlpClient:
    """Replays recorded info dicts from tests/fixtures/youtube. No network."""

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = fixture_dir
        self.download_calls = 0

    def search(self, query: str, n: int) -> list[dict[str, Any]]:
        entries = json.loads((self._dir / "search.json").read_text(encoding="utf-8"))
        return entries[:n]

    def info(self, url: str) -> dict[str, Any]:
        video_id = url.rsplit("v=", 1)[-1].split("&")[0]
        path = self._dir / f"{video_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"no recorded info for {video_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]:
        self.download_calls += 1
        meta = self.info(url)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "video.mp4").write_bytes(b"\x00" * 1024)
        # Like yt-dlp, write only the requested caption tracks.
        for vtt in self._dir.glob(f"{meta['id']}.*.vtt"):
            if vtt.name.split(".")[-2] in subtitle_langs:
                shutil.copy(vtt, dest / vtt.name.replace(meta["id"], "video"))
        meta = dict(meta)
        meta["requested_downloads"] = [{"filepath": str(dest / "video.mp4")}]
        return meta
