from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from clipsieve.adapters.base import hash_creator
from clipsieve.models import Comment, Media, Metrics, Post, PostText

# Our field -> MediaCrawler record key. Verified against store/xhs/__init__.py at the pinned commit.
# Override entries here if a MediaCrawler bump renames a key; logic below never hardcodes record
# keys.
FIELD_MAP: dict[str, str] = {
    "note_id": "note_id",
    "type": "type",
    "title": "title",
    "caption": "desc",
    "video_url": "video_url",
    "time": "time",
    "creator_hash": "creator_hash",
    "nickname": "nickname",
    "liked_count": "liked_count",
    "collected_count": "collected_count",
    "comment_count": "comment_count",
    "share_count": "share_count",
    "image_list": "image_list",
    "tag_list": "tag_list",
    "note_url": "note_url",
    # comments
    "c_note_id": "note_id",
    "c_content": "content",
    "c_like_count": "like_count",
    "c_parent": "parent_comment_id",
}
LIST_DELIMITER = (
    ","  # image_list is ",".join(urls) in MediaCrawler; tag_list assumed the same (unverified)
)
TIME_UNIT = (
    "ms"  # Xiaohongshu web API uses epoch milliseconds (unverified against MediaCrawler output)
)
MAX_COMMENTS = 50
TOP_LEVEL_PARENT_VALUES = {"", "0", 0, None}
PLATFORM = "xiaohongshu"

_CJK = re.compile(r"[一-鿿㐀-䶿]")
_NUM = re.compile(r"^\s*([\d.,]+)\s*([万wW]?)\s*$")


def _g(rec: dict, key: str):
    return rec.get(FIELD_MAP[key])


def note_id(note: dict) -> str:
    """The note's id via FIELD_MAP, or "" when absent."""
    return str(_g(note, "note_id") or "")


def note_type(note: dict) -> str:
    """The note's type via FIELD_MAP, "normal" when absent."""
    return str(_g(note, "type") or "normal")


def parse_count(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    m = _NUM.match(str(value))
    if not m:
        return None
    num, unit = m.group(1).replace(",", ""), m.group(2)
    try:
        f = float(num)
    except ValueError:
        return None
    if unit:
        f *= 10_000
    return round(f)


def split_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(LIST_DELIMITER) if s.strip()]


def _clean_url(url: str) -> str:
    """Drop only the fragment. The query stays: Xiaohongshu refuses to open a note page
    without the `xsec_token` MediaCrawler puts in `note_url`, so a token-free `Post.url`
    is a dead link for the person reviewing the post."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def image_urls(note: dict) -> list[str]:
    return split_list(_g(note, "image_list"))


def video_urls(note: dict) -> list[str]:
    return split_list(_g(note, "video_url"))


def _posted_at(note: dict) -> datetime | None:
    raw = _g(note, "time")
    n = parse_count(raw) if not isinstance(raw, (int, float)) else int(raw)
    if n is None or n <= 0:
        return None
    seconds = n / 1000 if TIME_UNIT == "ms" else n
    return datetime.fromtimestamp(seconds, tz=UTC)


def _lang(title: str, caption: str) -> str | None:
    text = f"{title} {caption}"
    if not text.strip():
        return None
    cjk = len(_CJK.findall(text))
    letters = sum(ch.isalpha() for ch in text)
    if letters == 0:
        return None
    return "zh" if cjk / letters >= 0.3 else "en"


def group_comments(comments: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for c in comments:
        if _g(c, "c_parent") not in TOP_LEVEL_PARENT_VALUES:
            continue
        nid = str(_g(c, "c_note_id") or "")
        grouped.setdefault(nid, []).append(c)
    for lst in grouped.values():
        lst.sort(key=lambda c: parse_count(_g(c, "c_like_count")) or 0, reverse=True)
    return grouped


def map_note(
    note: dict, comments: list[dict], salt: str, raw_ref: str, collected_at: datetime
) -> Post:
    nid = note_id(note)
    ntype = note_type(note)
    title = str(_g(note, "title") or "")
    caption = str(_g(note, "caption") or "")
    kind = "video" if ntype == "video" else "image_note"
    media: list[Media] = []
    if kind == "video":
        urls = video_urls(note)
        if urls:
            media.append(Media(type="video", local_path=None, index=0))
    else:
        media = [
            Media(type="image", local_path=None, index=i) for i, _ in enumerate(image_urls(note))
        ]
    top = comments[:MAX_COMMENTS]
    return Post(
        id=f"{PLATFORM}:{nid}",
        platform=PLATFORM,
        url=_clean_url(str(_g(note, "note_url") or f"https://www.xiaohongshu.com/explore/{nid}")),
        creator_hash=hash_creator(str(_g(note, "creator_hash") or "unknown"), salt),
        creator_display=(str(_g(note, "nickname")) if _g(note, "nickname") else None),
        posted_at=_posted_at(note),
        kind=kind,
        text=PostText(
            title=title or None, caption=caption or None, hashtags=split_list(_g(note, "tag_list"))
        ),
        media=media,
        metrics=Metrics(
            views=None,
            likes=parse_count(_g(note, "liked_count")),
            comments=parse_count(_g(note, "comment_count")),
            shares=parse_count(_g(note, "share_count")),
            saves=parse_count(_g(note, "collected_count")),
        ),
        comments=[
            Comment(text=str(_g(c, "c_content") or ""), likes=parse_count(_g(c, "c_like_count")))
            for c in top
        ],
        lang=_lang(title, caption),
        raw_ref=raw_ref,
        collected_at=collected_at,
    )
