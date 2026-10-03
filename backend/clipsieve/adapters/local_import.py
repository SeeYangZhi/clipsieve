"""Local import: a folder of media files, or a CSV export of posts. No network."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from clipsieve.adapters.base import AdapterHealth, hash_creator, incoming_dir
from clipsieve.config import Settings, ensure_creator_salt
from clipsieve.logging import get_logger
from clipsieve.models import Media, Metrics, Post, PostText, Query
from clipsieve.store.paths import safe_post_filename

log = get_logger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
CSV_COLUMNS = ("url", "title", "caption", "views", "likes", "comments")


def _int_or_none(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


class LocalImportAdapter:
    """Source is `Query.query`: a folder path (one post per media file) or a `.csv` path."""

    platform = "local"

    def __init__(self, data_dir: Path, salt: str) -> None:
        self._raw_dir = incoming_dir(data_dir, self.platform)
        self._salt = salt

    @classmethod
    def from_settings(cls, settings: Settings) -> LocalImportAdapter:
        return cls(data_dir=settings.clipsieve_data_dir, salt=ensure_creator_salt(settings))

    # -- search -------------------------------------------------------------

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        yielded = 0
        for q in queries:
            if yielded >= limit:
                return
            source = Path(q.query).expanduser()
            if not source.exists():
                log.warning("local_source_missing", source=str(source))
                continue
            if source.is_file() and source.suffix.lower() == ".csv":
                producer = self._from_csv(source, q.lang)
            elif source.is_dir():
                producer = self._from_folder(source, q.lang)
            else:
                log.warning("local_source_unsupported", source=str(source))
                continue
            for post in producer:
                yield post
                yielded += 1
                # Stop before pulling the next item so no raw payload is written for it.
                if yielded >= limit:
                    return

    def _post_id(self, source: Path) -> str:
        digest = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"local:{digest}"

    def _write_raw(self, post_id: str, payload: dict) -> str:
        path = self._raw_dir / f"{safe_post_filename(post_id)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _from_folder(self, folder: Path, lang: str) -> Iterator[Post]:
        creator = hash_creator(str(folder.resolve()), self._salt)
        for file in sorted(folder.iterdir()):
            # Hidden files include macOS AppleDouble `._a.mp4` companions, which are not media.
            if file.name.startswith(".") or not file.is_file():
                continue
            ext = file.suffix.lower()
            if ext in VIDEO_EXT:
                kind, media_type = "video", "video"
            elif ext in IMAGE_EXT:
                kind, media_type = "image_note", "image"
            else:
                continue
            post_id = self._post_id(file)
            payload = {"source": str(file.resolve()), "size": file.stat().st_size, "kind": kind}
            raw_ref = self._write_raw(post_id, payload)
            yield Post(
                id=post_id,
                platform="local",
                url=file.resolve().as_uri(),
                creator_hash=creator,
                creator_display=folder.name,
                kind=kind,
                text=PostText(title=file.stem, caption=None, hashtags=[]),
                media=[Media(type=media_type, index=0)],
                metrics=Metrics(),
                comments=[],
                lang=lang or None,
                raw_ref=raw_ref,
                collected_at=datetime.now(UTC),
            )

    def _from_csv(self, csv_path: Path, lang: str) -> Iterator[Post]:
        creator = hash_creator(str(csv_path.resolve()), self._salt)
        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in ("url",) if c not in (reader.fieldnames or [])]
            if missing:
                log.warning("local_csv_missing_columns", csv=str(csv_path), missing=missing)
                return
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                post_id = f"local:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"
                payload = {k: row.get(k) for k in row}
                raw_ref = self._write_raw(post_id, payload)
                caption = row.get("caption") or None
                hashtags = [w.lstrip("#") for w in (caption or "").split() if w.startswith("#")]
                yield Post(
                    id=post_id,
                    platform="local",
                    url=url,
                    creator_hash=creator,
                    creator_display=csv_path.stem,
                    kind="video",
                    text=PostText(
                        title=row.get("title") or None, caption=caption, hashtags=hashtags
                    ),
                    media=[],
                    metrics=Metrics(
                        views=_int_or_none(row.get("views")),
                        likes=_int_or_none(row.get("likes")),
                        comments=_int_or_none(row.get("comments")),
                    ),
                    comments=[],
                    lang=(row.get("lang") or lang or None),
                    raw_ref=raw_ref,
                    collected_at=datetime.now(UTC),
                )

    # -- media ----------------------------------------------------------------

    def fetch_media(self, post: Post, dest: Path) -> Post:
        """Copy the source file into `dest`; `local_path` is relative to `dest`. Idempotent."""
        if not post.media:
            return post
        raw = json.loads(Path(post.raw_ref).read_text(encoding="utf-8"))
        source = Path(raw["source"])
        dest.mkdir(parents=True, exist_ok=True)
        media = []
        for m in post.media:
            name = (
                "video.mp4"
                if m.type == "video"
                else f"img_{(m.index or 0):02d}{source.suffix.lower()}"
            )
            target = dest / name
            if not target.exists():
                # Copy then rename, so an interrupted copy never looks like a finished one.
                part = target.with_name(f"{name}.part")
                shutil.copy2(source, part)
                os.replace(part, target)
            media.append(m.model_copy(update={"local_path": name}))
        return post.model_copy(update={"media": media})

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(ok=True, message="local import ready")
