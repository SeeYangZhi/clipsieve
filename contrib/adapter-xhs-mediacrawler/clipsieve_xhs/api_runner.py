# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_runner.py
"""Collect xiaohongshu notes through the web API and emit MediaCrawler-shaped records.

One `search()` call is one search page (up to 20 notes) plus one detail request per note; the
adapter keeps paging, dedupe, `limit` and `max_pages` exactly as with the MediaCrawler runner.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from clipsieve.adapters.base import AdapterHealth
from clipsieve.logging import get_logger
from clipsieve_xhs.api_client import WEB_ORIGIN, XhsApiClient
from clipsieve_xhs.cdp_cookies import cookie_header
from clipsieve_xhs.errors import XhsApiError, XhsLoginRequired, XhsRateLimited
from clipsieve_xhs.runner import RunnerOutput
from clipsieve_xhs.settings import XhsSettings

log = get_logger(__name__)

COMMENT_FIELDS = (
    "comment_id",
    "create_time",
    "note_id",
    "content",
    "like_count",
    "sub_comment_count",
    "parent_comment_id",
    "last_modify_ts",
)


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def video_stream_urls(card: dict) -> list[str]:
    """Every `master_url` under video.media.stream, best (height, bitrate) first, deduped.

    Bucket names (h264/h265/av1 or newer tiers) are not assumed: all buckets are flattened.
    """
    stream = _as_dict(_as_dict(_as_dict(card.get("video")).get("media")).get("stream"))
    items = [
        it
        for bucket in stream.values()
        if isinstance(bucket, list)
        for it in bucket
        if isinstance(it, dict) and it.get("master_url")
    ]
    items.sort(
        key=lambda it: (_as_int(it.get("height")), _as_int(it.get("avg_bitrate"))), reverse=True
    )
    urls: list[str] = []
    for it in items:
        url = str(it["master_url"])
        if url not in urls:
            urls.append(url)
    return urls


def image_urls_from_card(card: dict) -> list[str]:
    return [
        str(img["url_default"])
        for img in card.get("image_list") or []
        if _as_dict(img).get("url_default")
    ]


def build_note_record(item: dict, card: dict, keyword: str, now_ms: int) -> dict:
    """The MediaCrawler jsonl shape `mapping.FIELD_MAP` reads: creator id hashed, no nickname."""
    note_id = str(item.get("id") or card.get("note_id") or "")
    token = str(item.get("xsec_token") or "")
    source = str(item.get("xsec_source") or "pc_search")
    user = _as_dict(card.get("user"))
    inter = _as_dict(card.get("interact_info"))
    user_id = str(user.get("user_id") or "")
    desc = str(card.get("desc") or "")
    return {
        "note_id": note_id,
        "type": card.get("type") or _as_dict(item.get("note_card")).get("type"),
        "title": card.get("title") or desc[:255],
        "desc": desc,
        "video_url": ",".join(video_stream_urls(card)),
        "time": card.get("time"),
        "last_update_time": card.get("last_update_time", 0),
        "creator_hash": hashlib.sha256(user_id.encode("utf-8")).hexdigest() if user_id else "",
        "liked_count": inter.get("liked_count"),
        "collected_count": inter.get("collected_count"),
        "comment_count": inter.get("comment_count"),
        "share_count": inter.get("share_count"),
        "image_list": ",".join(image_urls_from_card(card)),
        "tag_list": ",".join(
            str(t.get("name") or "")
            for t in card.get("tag_list") or []
            if _as_dict(t).get("type") == "topic"
        ),
        "last_modify_ts": now_ms,
        "note_url": f"{WEB_ORIGIN}/explore/{note_id}?xsec_token={token}&xsec_source={source}",
        "source_keyword": keyword,
        "xsec_token": token,
    }


def build_comment_records(note_id: str, data: dict, now_ms: int) -> list[dict]:
    out: list[dict] = []
    for raw in data.get("comments") or []:
        c = _as_dict(raw)
        out.append(
            {
                "comment_id": str(c.get("id") or ""),
                "create_time": c.get("create_time"),
                "note_id": note_id,
                "content": str(c.get("content") or ""),
                "like_count": c.get("like_count", 0),
                "sub_comment_count": c.get("sub_comment_count", 0),
                "parent_comment_id": "",
                "last_modify_ts": now_ms,
            }
        )
    return out


class XhsApiRunner:
    """`RunnerProtocol` over the web API: cookies from the browser, requests signed with xhshow."""

    def __init__(
        self,
        settings: XhsSettings,
        cdp_port: int,
        http: httpx.Client | None = None,
        *,
        cookies_provider: Callable[[], str] | None = None,
        client_factory: Callable[[str], XhsApiClient] | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self.settings = settings
        self.cdp_port = cdp_port
        self.http = http or httpx.Client(timeout=15.0)
        self._cookies_provider = cookies_provider or (
            lambda: cookie_header(self.cdp_port, self.http)
        )
        self._client_factory = client_factory or (
            lambda cookies: XhsApiClient(
                cookies, self.http, interval_s=self.settings.clipsieve_xhs_request_interval_s
            )
        )
        self._now_ms = now_ms
        self._client: XhsApiClient | None = None

    # -- RunnerProtocol -------------------------------------------------------------------

    def healthcheck(self) -> AdapterHealth:
        port = self.cdp_port
        try:
            self._cookies_provider()
        except XhsLoginRequired as e:
            return AdapterHealth(
                False,
                f"api runner: {e}; log in to xiaohongshu.com in the browser on port {port}, "
                "then retry",
            )
        except httpx.HTTPError as e:
            return AdapterHealth(
                False, f"api runner: Chrome remote debugging not reachable on port {port}: {e}"
            )
        return AdapterHealth(
            True, f"api runner: xiaohongshu web session from the browser on port {port}"
        )

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        notes: list[dict] = []
        comments: list[dict] = []
        errors: list[str] = []
        try:
            client = self._get_client()
        except (XhsLoginRequired, httpx.HTTPError) as e:
            return RunnerOutput(
                notes=[], comments=[], errors=[str(e)], returncode=1, stderr_tail=""
            )
        kind = self.settings.clipsieve_xhs_note_kinds
        try:
            data = client.search_notes(
                keyword, start_page, note_type=kind, page_size=self.settings.clipsieve_xhs_page_size
            )
        except XhsApiError as e:
            self._drop_client_if_dead(e)
            return RunnerOutput(
                notes=[], comments=[], errors=[str(e)], returncode=1, stderr_tail=""
            )

        items = [it for it in data.get("items") or [] if _as_dict(it).get("model_type") == "note"]
        returncode = 0
        for item in items:
            if kind == "video" and _as_dict(item.get("note_card")).get("type") not in (
                None,
                "video",
            ):
                continue  # image note: no detail request
            note_id = str(item.get("id") or "")
            try:
                card = client.note_detail(
                    note_id,
                    str(item.get("xsec_token") or ""),
                    str(item.get("xsec_source") or "pc_search"),
                )
            except (XhsLoginRequired, XhsRateLimited) as e:
                errors.append(f"{note_id}: {e}")
                self._drop_client_if_dead(e)
                returncode = 1
                break  # the session is dead or throttled: stop this page, keep what we have
            except XhsApiError as e:
                errors.append(f"{note_id}: {e}")
                continue
            record = build_note_record(item, card, keyword, self._now_ms())
            if kind == "video" and not record["video_url"]:
                errors.append(f"{note_id}: no video stream in the note detail")
                continue
            notes.append(record)
            if self.settings.clipsieve_xhs_comments:
                try:
                    data_c = client.comments(note_id, record["xsec_token"])
                    comments.extend(build_comment_records(note_id, data_c, self._now_ms()))
                except XhsApiError as e:
                    errors.append(f"{note_id} comments: {e}")
        log.info(
            "xhs.api.page",
            keyword=keyword,
            page=start_page,
            items=len(items),
            notes=len(notes),
            comments=len(comments),
            errors=len(errors),
            has_more=bool(data.get("has_more")),
        )
        return RunnerOutput(
            notes=notes, comments=comments, errors=errors, returncode=returncode, stderr_tail=""
        )

    # -- helpers --------------------------------------------------------------------------

    def _get_client(self) -> XhsApiClient:
        if self._client is None:
            self._client = self._client_factory(self._cookies_provider())
        return self._client

    def _drop_client_if_dead(self, error: XhsApiError) -> None:
        if isinstance(error, XhsLoginRequired):
            self._client = None  # the next page re-reads cookies from the browser
