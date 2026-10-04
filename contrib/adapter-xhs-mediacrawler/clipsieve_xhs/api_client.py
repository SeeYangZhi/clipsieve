# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_client.py
"""Direct calls to the xiaohongshu web API, signed per request with xhshow.

The wire format (paths, body fields, body serialisation) is the platform's; MediaCrawler's
client (media_platform/xhs/client.py) was the reference. Nothing here talks to a browser:
the cookies come from `cdp_cookies.cookie_header`.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from clipsieve.logging import get_logger
from clipsieve_xhs.errors import XhsApiError, XhsLoginRequired, XhsRateLimited

log = get_logger(__name__)

API_HOST = "https://edith.xiaohongshu.com"
WEB_ORIGIN = "https://www.xiaohongshu.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
SEARCH_URI = "/api/sns/web/v1/search/notes"
FEED_URI = "/api/sns/web/v1/feed"
COMMENTS_URI = "/api/sns/web/v2/comment/page"
NOTE_TYPE = {"all": 0, "video": 1, "image": 2}
LOGIN_CODES = {-100, -101, -104}
RATE_LIMIT_CODES = {300011, 300012, 300013}
VERIFY_STATUSES = {461, 471}
MAX_ATTEMPTS = 3
SIGNED_HEADER_NAMES = ("x-s", "x-t", "x-s-common", "x-b3-traceid", "x-xray-traceid")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


class Signer(Protocol):
    def sign_headers_get(self, uri: str, cookies: str, params: dict) -> dict[str, str]: ...

    def sign_headers_post(self, uri: str, cookies: str, payload: dict) -> dict[str, str]: ...


def _default_signer() -> Signer:
    from xhshow import Xhshow  # pure Python, MIT; imported lazily so tests can inject a fake

    return Xhshow()


def search_id() -> str:
    """The platform's search_id shape: (ms timestamp << 64) + random, base36."""
    n = (int(time.time() * 1000) << 64) + random.randint(0, 2147483646)  # not security
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out or "0"


class XhsApiClient:
    def __init__(
        self,
        cookies: str,
        http: httpx.Client,
        *,
        signer: Signer | None = None,
        interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.cookies = cookies
        self.http = http
        self.signer = signer or _default_signer()
        self.interval_s = interval_s
        self.sleep = sleep
        self.jitter = jitter
        self._last_request_at: float | None = None

    # -- public endpoints --------------------------------------------------------------

    def search_notes(
        self,
        keyword: str,
        page: int,
        *,
        note_type: str = "all",
        page_size: int = 20,
        sort: str = "general",
        sid: str | None = None,
    ) -> dict:
        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": sid or search_id(),
            "sort": sort,
            "note_type": NOTE_TYPE[note_type],
        }
        return self._request("POST", SEARCH_URI, payload=payload)

    def note_detail(self, note_id: str, xsec_token: str, xsec_source: str = "pc_search") -> dict:
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source or "pc_search",
            "xsec_token": xsec_token,
        }
        data = self._request("POST", FEED_URI, payload=payload)
        items = data.get("items") or []
        if not items:
            raise XhsApiError(
                f"{FEED_URI}: no note card for {note_id} (deleted, private or blocked)"
            )
        return items[0].get("note_card") or {}

    def comments(self, note_id: str, xsec_token: str, cursor: str = "") -> dict:
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return self._request("GET", COMMENTS_URI, params=params)

    # -- transport ---------------------------------------------------------------------

    def _pace(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            target = self._last_request_at + self.interval_s * (0.75 + 0.5 * self.jitter())
            if target > now:
                self.sleep(target - now)
        self._last_request_at = time.monotonic()

    def _headers(self, signed: dict[str, str]) -> dict[str, str]:
        base = {
            "Cookie": self.cookies,
            "Origin": WEB_ORIGIN,
            "Referer": WEB_ORIGIN + "/",
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
        }
        base.update({k: v for k, v in signed.items() if k in SIGNED_HEADER_NAMES and v})
        return base

    def _send(
        self, method: str, uri: str, params: dict | None, payload: dict | None
    ) -> httpx.Response:
        if method == "GET":
            signed = self.signer.sign_headers_get(
                uri=uri, cookies=self.cookies, params=params or {}
            )
            return self.http.get(
                API_HOST + uri, params=params, headers=self._headers(signed), timeout=15.0
            )
        signed = self.signer.sign_headers_post(uri=uri, cookies=self.cookies, payload=payload or {})
        # The signer saw `payload`; send exactly its compact, non-ASCII-escaped serialisation.
        body = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self.http.post(
            API_HOST + uri, content=body, headers=self._headers(signed), timeout=15.0
        )

    def _request(
        self, method: str, uri: str, *, params: dict | None = None, payload: dict | None = None
    ) -> dict:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace()
            resp = self._send(method, uri, params, payload)
            if resp.status_code in VERIFY_STATUSES:
                raise XhsLoginRequired(
                    f"{uri}: verification required (HTTP {resp.status_code}); open "
                    "xiaohongshu.com in the browser, complete the check, then resume",
                    status=resp.status_code,
                )
            if resp.status_code >= 400:
                raise XhsApiError(f"{uri}: HTTP {resp.status_code}", status=resp.status_code)
            body: dict[str, Any] = resp.json()
            if body.get("success") or body.get("code") == 0:
                return body.get("data") or {}
            code = int(body.get("code") or 0)
            msg = str(body.get("msg") or body.get("message") or "")
            if code in LOGIN_CODES:
                raise XhsLoginRequired(f"{uri}: login expired ({code} {msg})", code=code)
            if code in RATE_LIMIT_CODES:
                if attempt < MAX_ATTEMPTS:
                    backoff = self.interval_s * (2**attempt)
                    log.warning(
                        "xhs.rate_limited", uri=uri, code=code, attempt=attempt, backoff_s=backoff
                    )
                    self.sleep(backoff)
                    continue
                raise XhsRateLimited(
                    f"{uri}: rate limited after {MAX_ATTEMPTS} attempts ({code} {msg}); "
                    "raise CLIPSIEVE_XHS_REQUEST_INTERVAL_S",
                    code=code,
                )
            raise XhsApiError(f"{uri}: {code} {msg}", code=code)
        raise XhsApiError(f"{uri}: gave up")  # pragma: no cover - loop always returns or raises
