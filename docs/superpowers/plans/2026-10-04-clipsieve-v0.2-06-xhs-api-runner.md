# Xiaohongshu API Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect many more Xiaohongshu videos, much faster, by calling the platform's web API directly (video-only search, 20 notes per request) from the user's own logged-in browser session, instead of driving a MediaCrawler crawl per page.

**Architecture:** A second runner, `XhsApiRunner`, behind the contrib package's existing `RunnerProtocol`. It reads cookies from the user's Chromium (Brave) over the Chrome DevTools Protocol, signs each request with the MIT-licensed pure-Python `xhshow` library (the same signer MediaCrawler uses), calls search with `note_type=1`, fetches one detail per note for the video stream URL, and emits records with the keys MediaCrawler writes. Mapping, privacy stripping, the media-URL cache, `fetch_media` and the adapter's paging stay unchanged; MediaCrawler remains the fallback runner behind one setting.

**Tech Stack:** Python 3.12, httpx, `xhshow>=0.2.0`, `websockets` (sync client, CDP cookie read), respx for tests, uv. All inside `contrib/adapter-xhs-mediacrawler/` (package `clipsieve_xhs`).

**Spec:** `docs/superpowers/specs/2026-10-04-xhs-api-runner-design.md` (decision, prior art, risks). The v0.1 contracts still bind: `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md` Addenda B.1/B.2/B.10/B.11 and C.

## Global Constraints

- `uv` for everything Python; the contrib project is its own `uv` project; tests run with `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error`; ruff config extends the backend's (`ruff check . && ruff format --check .` clean).
- No network in tests: respx for httpx, injected fakes for the CDP socket and the signer. Never call xiaohongshu.com, never open Brave, never run MediaCrawler in a test.
- Core never imports the contrib package; the contrib package imports only `clipsieve.adapters.base`, `clipsieve.config`, `clipsieve.logging`, `clipsieve.models` (unchanged from v0.1).
- Privacy: raw creator ids and nicknames never leave the runner; `creator_hash` is `sha256(user_id)`; comment records carry only `comment_id`, `create_time`, `note_id`, `content`, `like_count`, `sub_comment_count`, `parent_comment_id`, `last_modify_ts`. No cookies, tokens or signed headers in logs.
- Pacing: one request at a time; jittered interval (`CLIPSIEVE_XHS_REQUEST_INTERVAL_S`, default `1.0`); at most 3 attempts on a rate-limit code with exponential backoff; verification (HTTP 461/471) and login-expired codes stop the page, never retry.
- Records emitted by the runner use exactly the MediaCrawler jsonl keys consumed by `clipsieve_xhs/mapping.py` `FIELD_MAP`: `note_id, type, title, desc, video_url, time, last_update_time, creator_hash, liked_count, collected_count, comment_count, share_count, image_list, tag_list, note_url, source_keyword, xsec_token` (lists comma-joined; `note_url` carries `xsec_token` and `xsec_source`).
- Wire format is the platform's, read from MediaCrawler as reference only (`media_platform/xhs/client.py:318-358`); no MediaCrawler code is copied. POST bodies are serialised exactly as `json.dumps(payload, separators=(",", ":"), ensure_ascii=False)` because the `x-s` signature covers the body.
- structlog via `clipsieve.logging.get_logger`; no `print()`.
- Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu`.
- DOX: `contrib/adapter-xhs-mediacrawler/AGENTS.md` and `README.md` updated in the task that changes the contract; root `README.md` adapter table and overview Addendum C in Task 5.

## Review Focus

1. **Login expired mid-page.** The platform answers `success: false` with code `-104` (or HTTP 461/471 verification) after some notes were fetched. Expected: the page returns the notes collected so far plus one error, `healthcheck` turns false with a "log in to xiaohongshu.com in the browser on port N" message, and no retry storm. Pinned in Task 4 `test_login_expired_mid_page_returns_partial_and_stops`.
2. **Rate limited.** Code `300012` ("访问频次异常"). Expected: back off `interval * 2^attempt` at most twice, then surface `XhsRateLimited`; the runner stops the page. Pinned in Task 3 `test_rate_limit_backs_off_then_raises` and Task 4 `test_rate_limit_during_details_stops_page`.
3. **A note whose detail has no stream** (deleted, private, or an image note slipped through). Expected: that note is skipped with an error naming it; the others on the page are unaffected. Pinned in Task 4 `test_note_without_stream_is_skipped_not_fatal`.
4. **Search exhausted.** `has_more: false` and later pages return no items. Expected: the runner returns an empty `RunnerOutput`, the adapter's "page added nothing new" rule stops paging, no error. Pinned in Task 4 `test_empty_page_returns_empty_output`.
5. **Non-note rows in search results** (`model_type` `rec_query` / `hot_query`, ads) and image notes under video mode. Expected: filtered out before any detail call, so no wasted requests. Pinned in Task 4 `test_only_note_rows_of_the_requested_kind_are_fetched`.

---

### Task 1: Settings and dependencies

**Files:**
- Modify: `contrib/adapter-xhs-mediacrawler/pyproject.toml` (add `xhshow>=0.2.0,<0.3`, `websockets>=13`)
- Modify: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/settings.py`
- Modify: `contrib/adapter-xhs-mediacrawler/tests/test_settings.py`
- Modify: `.env.example` (four lines after `CLIPSIEVE_XHS_MAX_PAGES`)

**Interfaces:**
- Consumes: `XhsSettings` (existing fields `clipsieve_xhs_mediacrawler_dir`, `clipsieve_xhs_timeout_s`, `clipsieve_xhs_pinned_commit`, `clipsieve_xhs_note_kinds: Literal["all","video"]`, `clipsieve_xhs_max_pages`).
- Produces: `XhsSettings.clipsieve_xhs_runner: Literal["api", "mediacrawler"] = "api"`, `clipsieve_xhs_comments: bool = False`, `clipsieve_xhs_request_interval_s: float = 1.0` (`ge=0`), `clipsieve_xhs_page_size: int = 20` (`ge=1, le=20`); `clipsieve_xhs_max_pages` default raised from 5 to 10.

- [x] **Step 1: Write the failing settings tests**

Append to `contrib/adapter-xhs-mediacrawler/tests/test_settings.py`:

```python


def test_api_runner_defaults(monkeypatch):
    for name in (
        "CLIPSIEVE_XHS_RUNNER",
        "CLIPSIEVE_XHS_COMMENTS",
        "CLIPSIEVE_XHS_REQUEST_INTERVAL_S",
        "CLIPSIEVE_XHS_PAGE_SIZE",
        "CLIPSIEVE_XHS_MAX_PAGES",
    ):
        monkeypatch.delenv(name, raising=False)
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_runner == "api"
    assert s.clipsieve_xhs_comments is False
    assert s.clipsieve_xhs_request_interval_s == 1.0
    assert s.clipsieve_xhs_page_size == 20
    assert s.clipsieve_xhs_max_pages == 10


def test_api_runner_settings_validate():
    import pytest

    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_runner="playwright")
    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_page_size=21)
    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_request_interval_s=-1)


def test_api_runner_settings_from_env(monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_XHS_RUNNER", "mediacrawler")
    monkeypatch.setenv("CLIPSIEVE_XHS_COMMENTS", "1")
    monkeypatch.setenv("CLIPSIEVE_XHS_REQUEST_INTERVAL_S", "0.5")
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_runner == "mediacrawler"
    assert s.clipsieve_xhs_comments is True
    assert s.clipsieve_xhs_request_interval_s == 0.5
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_settings.py`
Expected: 3 failed (`AttributeError: ... has no attribute 'clipsieve_xhs_runner'`, and the validation tests pass trivially only after the fields exist, so they fail on the first assertion).

- [x] **Step 3: Add the dependencies and the fields**

Run: `cd contrib/adapter-xhs-mediacrawler && uv add "xhshow>=0.2.0,<0.3" "websockets>=13"`

Expected: `pyproject.toml` `dependencies` gains both lines and `uv.lock` updates.

Replace the field block in `clipsieve_xhs/settings.py` so the class reads:

```python
class XhsSettings(BaseSettings):
    # Relative paths are resolved against REPO_ROOT by MediaCrawlerRunner.mc_dir.
    # The CDP port is NOT here: core Settings.clipsieve_xhs_chrome_cdp_port owns it.
    clipsieve_xhs_mediacrawler_dir: Path = Path("../MediaCrawler")
    clipsieve_xhs_timeout_s: int = 900
    clipsieve_xhs_pinned_commit: str = PINNED_COMMIT
    # "video" asks the search API for videos only (api runner) and drops image notes before
    # anything is written (both runners).
    clipsieve_xhs_note_kinds: Literal["all", "video"] = "all"
    # Upper bound on search pages per query. One page is one API request plus one detail
    # request per note (api runner) or one full MediaCrawler crawl (mediacrawler runner).
    clipsieve_xhs_max_pages: int = Field(default=10, ge=1)
    # Which runner collects: the direct web API with the browser's cookies (default) or a
    # MediaCrawler checkout driven as a subprocess (fallback).
    clipsieve_xhs_runner: Literal["api", "mediacrawler"] = "api"
    # api runner only: fetch the first page of comments per note (one more request each).
    clipsieve_xhs_comments: bool = False
    # api runner only: seconds between requests (jittered 0.75x to 1.25x) and the backoff base.
    clipsieve_xhs_request_interval_s: float = Field(default=1.0, ge=0)
    # api runner only: notes per search request; the platform caps it at 20.
    clipsieve_xhs_page_size: int = Field(default=20, ge=1, le=20)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_settings.py && uv run ruff check . && uv run ruff format --check .`
Expected: all settings tests pass; ruff clean. (The adapter test `test_max_pages_caps_paging_short_of_limit` sets its own `clipsieve_xhs_max_pages=2`, so the default change does not break it; confirm with the full suite.)

- [x] **Step 5: Document the variables**

Append to `.env.example` after the `CLIPSIEVE_XHS_MAX_PAGES=5` line, and change that default to `10`:

```text
CLIPSIEVE_XHS_MAX_PAGES=10
# api | mediacrawler. "api" calls the web API with your browser's cookies (fast, video-only
# search); "mediacrawler" drives the MediaCrawler checkout below (fallback).
CLIPSIEVE_XHS_RUNNER=api
# api runner: also fetch the first page of comments per note (one extra request each).
CLIPSIEVE_XHS_COMMENTS=0
# api runner: seconds between requests; raise it if runs hit "访问频次异常" (300012).
CLIPSIEVE_XHS_REQUEST_INTERVAL_S=1.0
# api runner: notes per search request (platform maximum 20).
CLIPSIEVE_XHS_PAGE_SIZE=20
```

- [x] **Step 6: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/pyproject.toml contrib/adapter-xhs-mediacrawler/uv.lock contrib/adapter-xhs-mediacrawler/clipsieve_xhs/settings.py contrib/adapter-xhs-mediacrawler/tests/test_settings.py .env.example
git commit -m "feat(contrib-xhs): settings for the api runner; add xhshow and websockets

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 2: Errors and the CDP cookie reader

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/errors.py`
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/cdp_cookies.py`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_cdp_cookies.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `errors.XhsApiError(message, code: int | None = None, status: int | None = None)`, `errors.XhsLoginRequired(XhsApiError)`, `errors.XhsRateLimited(XhsApiError)`.
  - `cdp_cookies.fetch_cookies(port: int, http: httpx.Client, connect: Connect = _default_connect) -> list[dict]`
  - `cdp_cookies.cookie_header(port: int, http: httpx.Client, connect: Connect = _default_connect) -> str` (`"a1=...; web_session=...; ..."`, xiaohongshu.com cookies only; raises `XhsLoginRequired` when `a1` or `web_session` is missing).
  - `cdp_cookies.Connect = Callable[[str], AbstractContextManager[Any]]` where the context manager exposes `send(str)` and `recv() -> str`.

- [x] **Step 1: Write the failing tests**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_cdp_cookies.py
import json
from contextlib import contextmanager

import httpx
import pytest

from clipsieve_xhs.cdp_cookies import cookie_header, fetch_cookies
from clipsieve_xhs.errors import XhsLoginRequired

VERSION = {"Browser": "Chrome/146.0", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc"}


def http_with_version(port_ok=True):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/json/version" and port_ok:
            return httpx.Response(200, json=VERSION)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


class FakeSocket:
    def __init__(self, cookies, error=None):
        self.sent: list[dict] = []
        self.cookies = cookies
        self.error = error

    def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def recv(self) -> str:
        req = self.sent[-1]
        if self.error:
            return json.dumps({"id": req["id"], "error": self.error})
        # An unrelated event first, then the reply: the reader must match on id.
        if not getattr(self, "_event_sent", False):
            self._event_sent = True
            return json.dumps({"method": "Target.targetCreated", "params": {}})
        return json.dumps({"id": req["id"], "result": {"cookies": self.cookies}})


def fake_connect(sock: FakeSocket):
    seen: list[str] = []

    @contextmanager
    def connect(url: str):
        seen.append(url)
        yield sock

    connect.seen = seen  # type: ignore[attr-defined]
    return connect


COOKIES = [
    {"name": "a1", "value": "A1", "domain": ".xiaohongshu.com"},
    {"name": "web_session", "value": "WS", "domain": ".xiaohongshu.com"},
    {"name": "webId", "value": "W", "domain": "www.xiaohongshu.com"},
    {"name": "sid", "value": "OTHER", "domain": ".google.com"},
]


def test_fetch_cookies_uses_the_browser_socket_and_matches_reply_by_id():
    sock = FakeSocket(COOKIES)
    connect = fake_connect(sock)
    cookies = fetch_cookies(9222, http_with_version(), connect=connect)
    assert connect.seen == [VERSION["webSocketDebuggerUrl"]]
    assert sock.sent[0]["method"] == "Storage.getCookies"
    assert [c["name"] for c in cookies] == ["a1", "web_session", "webId", "sid"]


def test_cookie_header_keeps_only_xiaohongshu_cookies():
    header = cookie_header(9222, http_with_version(), connect=fake_connect(FakeSocket(COOKIES)))
    assert header == "a1=A1; web_session=WS; webId=W"


def test_cookie_header_requires_login_cookies():
    not_logged_in = [c for c in COOKIES if c["name"] != "web_session"]
    with pytest.raises(XhsLoginRequired, match="web_session"):
        cookie_header(9222, http_with_version(), connect=fake_connect(FakeSocket(not_logged_in)))


def test_cdp_error_is_a_login_problem_with_the_message():
    sock = FakeSocket([], error={"code": -32000, "message": "no browser"})
    with pytest.raises(XhsLoginRequired, match="no browser"):
        fetch_cookies(9222, http_with_version(), connect=fake_connect(sock))


def test_unreachable_port_raises_httpx_error():
    with pytest.raises(httpx.HTTPStatusError):
        fetch_cookies(9222, http_with_version(port_ok=False), connect=fake_connect(FakeSocket([])))
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_cdp_cookies.py`
Expected: `ModuleNotFoundError: No module named 'clipsieve_xhs.cdp_cookies'`

- [x] **Step 3: Write the errors module**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/errors.py
"""Failure classes shared by the api runner; the adapter turns them into per-page errors."""

from __future__ import annotations


class XhsApiError(Exception):
    """The platform refused or failed a request; `code` is its body code, `status` the HTTP status."""

    def __init__(self, message: str, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class XhsLoginRequired(XhsApiError):
    """No usable web session: cookies missing, login expired, or a verification challenge."""


class XhsRateLimited(XhsApiError):
    """The platform throttled us (访问频次异常); retried with backoff before this was raised."""
```

- [x] **Step 4: Write the cookie reader**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/cdp_cookies.py
"""Read the user's xiaohongshu.com cookies from their own Chromium over the DevTools Protocol.

Nothing is stored: the cookie header lives in memory for one runner and is never logged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import httpx

from clipsieve.logging import get_logger
from clipsieve_xhs.errors import XhsLoginRequired

log = get_logger(__name__)

COOKIE_DOMAIN = "xiaohongshu.com"
REQUIRED_COOKIES = ("a1", "web_session")
Connect = Callable[[str], AbstractContextManager[Any]]


def _default_connect(url: str) -> AbstractContextManager[Any]:
    from websockets.sync.client import connect  # imported lazily: tests inject a fake

    return connect(url, max_size=None, open_timeout=5, close_timeout=1)


def fetch_cookies(port: int, http: httpx.Client, connect: Connect = _default_connect) -> list[dict]:
    """All cookies the browser on `port` holds, via `Storage.getCookies`."""
    version = http.get(f"http://127.0.0.1:{port}/json/version", timeout=5.0)
    version.raise_for_status()
    ws_url = version.json()["webSocketDebuggerUrl"]
    with connect(ws_url) as ws:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                break
    if "error" in msg:
        raise XhsLoginRequired(f"CDP Storage.getCookies failed: {msg['error'].get('message', msg['error'])}")
    return list(msg["result"]["cookies"])


def cookie_header(port: int, http: httpx.Client, connect: Connect = _default_connect) -> str:
    """`name=value; ...` for xiaohongshu.com, or `XhsLoginRequired` when the session is missing."""
    cookies = [
        c for c in fetch_cookies(port, http, connect) if str(c.get("domain", "")).endswith(COOKIE_DOMAIN)
    ]
    names = {c["name"] for c in cookies}
    missing = [n for n in REQUIRED_COOKIES if n not in names]
    if missing:
        raise XhsLoginRequired(
            f"not logged in to xiaohongshu.com in the browser on port {port}: "
            f"missing cookie(s) {', '.join(missing)}; open xiaohongshu.com there and log in"
        )
    log.info("xhs.cookies", count=len(cookies))  # names and values are never logged
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_cdp_cookies.py && uv run ruff check . && uv run ruff format --check .`
Expected: 5 passed; ruff clean.

- [x] **Step 6: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/clipsieve_xhs/errors.py contrib/adapter-xhs-mediacrawler/clipsieve_xhs/cdp_cookies.py contrib/adapter-xhs-mediacrawler/tests/test_cdp_cookies.py
git commit -m "feat(contrib-xhs): read the xiaohongshu web session from the browser over CDP

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 3: Signed API client

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_client.py`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_api_client.py`

**Interfaces:**
- Consumes: `errors.XhsApiError/XhsLoginRequired/XhsRateLimited`.
- Produces:
  - `api_client.Signer` Protocol: `sign_headers_get(uri, cookies, params) -> dict`, `sign_headers_post(uri, cookies, payload) -> dict`.
  - `api_client.XhsApiClient(cookies: str, http: httpx.Client, *, signer: Signer | None = None, interval_s: float = 1.0, sleep: Callable[[float], None] = time.sleep, jitter: Callable[[], float] = random.random)`
  - `.search_notes(keyword: str, page: int, *, note_type: str = "all", page_size: int = 20, sort: str = "general", sid: str | None = None) -> dict` (the response `data`: `items`, `has_more`)
  - `.note_detail(note_id: str, xsec_token: str, xsec_source: str = "pc_search") -> dict` (the `note_card`)
  - `.comments(note_id: str, xsec_token: str, cursor: str = "") -> dict` (the response `data`: `comments`, `cursor`, `has_more`)
  - constants `API_HOST`, `WEB_ORIGIN`, `SEARCH_URI`, `FEED_URI`, `COMMENTS_URI`, `NOTE_TYPE = {"all": 0, "video": 1, "image": 2}`, `MAX_ATTEMPTS = 3`; `search_id() -> str`.

- [x] **Step 1: Write the failing tests**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_api_client.py
import json

import httpx
import pytest
import respx

from clipsieve_xhs.api_client import (
    API_HOST,
    COMMENTS_URI,
    FEED_URI,
    SEARCH_URI,
    XhsApiClient,
    search_id,
)
from clipsieve_xhs.errors import XhsApiError, XhsLoginRequired, XhsRateLimited

COOKIES = "a1=A1; web_session=WS"


class FakeSigner:
    def __init__(self):
        self.calls = []

    def sign_headers_get(self, uri, cookies, params):
        self.calls.append(("GET", uri, cookies, params))
        return {"x-s": "XS", "x-t": "1", "x-s-common": "XSC", "x-b3-traceid": "T"}

    def sign_headers_post(self, uri, cookies, payload):
        self.calls.append(("POST", uri, cookies, payload))
        return {"x-s": "XS", "x-t": "1", "x-s-common": "XSC", "x-b3-traceid": "T"}


def make_client(interval_s=1.0):
    sleeps: list[float] = []
    signer = FakeSigner()
    client = XhsApiClient(
        COOKIES,
        httpx.Client(),
        signer=signer,
        interval_s=interval_s,
        sleep=sleeps.append,
        jitter=lambda: 0.5,  # exactly interval_s between requests
    )
    return client, signer, sleeps


def ok(data):
    return httpx.Response(200, json={"code": 0, "success": True, "msg": "成功", "data": data})


@respx.mock
def test_search_posts_the_platform_body_and_signed_headers():
    route = respx.post(API_HOST + SEARCH_URI).mock(return_value=ok({"items": [], "has_more": False}))
    client, signer, _ = make_client()
    data = client.search_notes("新加坡 上海 vlog", 2, note_type="video", page_size=20, sid="SID")
    assert data == {"items": [], "has_more": False}
    req = route.calls.last.request
    body = json.loads(req.content)
    assert body == {
        "keyword": "新加坡 上海 vlog",
        "page": 2,
        "page_size": 20,
        "search_id": "SID",
        "sort": "general",
        "note_type": 1,
    }
    # Signed over the exact bytes sent: compact separators, CJK unescaped.
    assert req.content == json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    assert signer.calls == [("POST", SEARCH_URI, COOKIES, body)]
    assert req.headers["x-s"] == "XS" and req.headers["x-s-common"] == "XSC"
    assert req.headers["cookie"] == COOKIES
    assert req.headers["origin"] == "https://www.xiaohongshu.com"
    assert req.headers["referer"] == "https://www.xiaohongshu.com/"
    assert req.headers["content-type"].startswith("application/json")


@respx.mock
def test_note_detail_returns_the_note_card():
    card = {"note_id": "n1", "type": "video", "title": "t"}
    route = respx.post(API_HOST + FEED_URI).mock(return_value=ok({"items": [{"note_card": card}]}))
    client, _, _ = make_client()
    assert client.note_detail("n1", "TOKEN") == card
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "source_note_id": "n1",
        "image_formats": ["jpg", "webp", "avif"],
        "extra": {"need_body_topic": 1},
        "xsec_source": "pc_search",
        "xsec_token": "TOKEN",
    }


@respx.mock
def test_note_detail_without_items_is_an_api_error():
    respx.post(API_HOST + FEED_URI).mock(return_value=ok({"items": []}))
    client, _, _ = make_client()
    with pytest.raises(XhsApiError, match="n1"):
        client.note_detail("n1", "TOKEN")


@respx.mock
def test_comments_is_a_signed_get_with_the_platform_params():
    route = respx.get(API_HOST + COMMENTS_URI).mock(
        return_value=ok({"comments": [], "cursor": "", "has_more": False})
    )
    client, signer, _ = make_client()
    client.comments("n1", "TOKEN", cursor="c2")
    params = dict(route.calls.last.request.url.params)
    assert params == {
        "note_id": "n1",
        "cursor": "c2",
        "top_comment_id": "",
        "image_formats": "jpg,webp,avif",
        "xsec_token": "TOKEN",
    }
    assert signer.calls[0][:2] == ("GET", COMMENTS_URI)


@respx.mock
def test_requests_are_paced_by_the_interval():
    respx.post(API_HOST + SEARCH_URI).mock(return_value=ok({"items": [], "has_more": False}))
    client, _, sleeps = make_client(interval_s=2.0)
    client.search_notes("k", 1)
    client.search_notes("k", 2)
    # No wait before the first request; about one interval before the second.
    assert len(sleeps) == 1 and 1.9 <= sleeps[0] <= 2.0


@respx.mock
def test_login_expired_code_raises_login_required_without_retry():
    route = respx.post(API_HOST + SEARCH_URI).mock(
        return_value=httpx.Response(200, json={"code": -104, "success": False, "msg": "登录已过期"})
    )
    client, _, _ = make_client()
    with pytest.raises(XhsLoginRequired, match="-104"):
        client.search_notes("k", 1)
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("status", [461, 471])
def test_verification_status_raises_login_required(status):
    respx.post(API_HOST + SEARCH_URI).mock(return_value=httpx.Response(status, text="verify"))
    client, _, _ = make_client()
    with pytest.raises(XhsLoginRequired, match=str(status)):
        client.search_notes("k", 1)


@respx.mock
def test_rate_limit_backs_off_then_raises():
    route = respx.post(API_HOST + SEARCH_URI).mock(
        return_value=httpx.Response(200, json={"code": 300012, "success": False, "msg": "访问频次异常"})
    )
    client, _, sleeps = make_client(interval_s=1.0)
    with pytest.raises(XhsRateLimited, match="300012"):
        client.search_notes("k", 1)
    assert route.call_count == 3
    # pacing sleeps between attempts plus the two backoffs 2^1 and 2^2 seconds
    assert [s for s in sleeps if s in (2.0, 4.0)] == [2.0, 4.0]


@respx.mock
def test_rate_limit_then_success_recovers():
    route = respx.post(API_HOST + SEARCH_URI)
    route.side_effect = [
        httpx.Response(200, json={"code": 300012, "success": False, "msg": "访问频次异常"}),
        ok({"items": [{"id": "n1"}], "has_more": True}),
    ]
    client, _, _ = make_client()
    assert client.search_notes("k", 1)["items"] == [{"id": "n1"}]


@respx.mock
def test_http_error_is_an_api_error_with_status():
    respx.post(API_HOST + SEARCH_URI).mock(return_value=httpx.Response(403))
    client, _, _ = make_client()
    with pytest.raises(XhsApiError) as info:
        client.search_notes("k", 1)
    assert info.value.status == 403


def test_search_id_is_base36_and_fresh():
    a, b = search_id(), search_id()
    assert a != b
    assert all(ch in "0123456789abcdefghijklmnopqrstuvwxyz" for ch in a)


def test_real_signer_produces_the_required_headers():
    """xhshow is pure Python; one offline call proves the dependency and the key names."""
    from xhshow import Xhshow

    headers = Xhshow().sign_headers_post(uri=SEARCH_URI, cookies=COOKIES, payload={"keyword": "k"})
    assert {"x-s", "x-t", "x-s-common"} <= set(headers)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_api_client.py`
Expected: `ModuleNotFoundError: No module named 'clipsieve_xhs.api_client'`

- [x] **Step 3: Write the client**

```python
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
    n = (int(time.time() * 1000) << 64) + random.randint(0, 2147483646)  # noqa: S311 - not security
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
            raise XhsApiError(f"{FEED_URI}: no note card for {note_id} (deleted, private or blocked)")
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

    def _send(self, method: str, uri: str, params: dict | None, payload: dict | None) -> httpx.Response:
        if method == "GET":
            signed = self.signer.sign_headers_get(uri=uri, cookies=self.cookies, params=params or {})
            return self.http.get(API_HOST + uri, params=params, headers=self._headers(signed), timeout=15.0)
        signed = self.signer.sign_headers_post(uri=uri, cookies=self.cookies, payload=payload or {})
        body = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self.http.post(API_HOST + uri, content=body, headers=self._headers(signed), timeout=15.0)

    def _request(self, method: str, uri: str, *, params: dict | None = None, payload: dict | None = None) -> dict:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace()
            resp = self._send(method, uri, params, payload)
            if resp.status_code in VERIFY_STATUSES:
                raise XhsLoginRequired(
                    f"{uri}: verification required (HTTP {resp.status_code}); open xiaohongshu.com "
                    "in the browser, complete the check, then resume",
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
                    log.warning("xhs.rate_limited", uri=uri, code=code, attempt=attempt, backoff_s=backoff)
                    self.sleep(backoff)
                    continue
                raise XhsRateLimited(
                    f"{uri}: rate limited after {MAX_ATTEMPTS} attempts ({code} {msg}); "
                    "raise CLIPSIEVE_XHS_REQUEST_INTERVAL_S",
                    code=code,
                )
            raise XhsApiError(f"{uri}: {code} {msg}", code=code)
        raise XhsApiError(f"{uri}: gave up")  # pragma: no cover - loop always returns or raises
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_api_client.py && uv run ruff check . && uv run ruff format --check .`
Expected: 12 passed; ruff clean. If ruff flags `S311` as unknown (the backend config may not enable `S`), drop that `noqa`.

- [x] **Step 5: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_client.py contrib/adapter-xhs-mediacrawler/tests/test_api_client.py
git commit -m "feat(contrib-xhs): signed web API client for search, note detail and comments

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 4: Records and the api runner

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_runner.py`
- Create: `contrib/adapter-xhs-mediacrawler/tests/fixtures/xhs-api/search.json`
- Create: `contrib/adapter-xhs-mediacrawler/tests/fixtures/xhs-api/feed.json`
- Create: `contrib/adapter-xhs-mediacrawler/tests/fixtures/xhs-api/comments.json`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_api_runner.py`

**Interfaces:**
- Consumes: `XhsApiClient` (Task 3), `cookie_header` (Task 2), `RunnerOutput`, `RunnerProtocol`, `AdapterHealth`, `XhsSettings` fields from Task 1.
- Produces:
  - `api_runner.video_stream_urls(card: dict) -> list[str]` (best quality first, deduped)
  - `api_runner.image_urls_from_card(card: dict) -> list[str]`
  - `api_runner.build_note_record(item: dict, card: dict, keyword: str, now_ms: int) -> dict`
  - `api_runner.build_comment_records(note_id: str, data: dict, now_ms: int) -> list[dict]`
  - `api_runner.XhsApiRunner(settings: XhsSettings, cdp_port: int, http: httpx.Client | None = None, *, cookies_provider: Callable[[], str] | None = None, client_factory: Callable[[str], XhsApiClient] | None = None, now_ms: Callable[[], int] = ...)` implementing `RunnerProtocol` (`search(keyword, start_page, workdir) -> RunnerOutput`, `healthcheck() -> AdapterHealth`).

- [x] **Step 1: Write the synthetic fixtures**

Synthetic data only (ids, tokens and URLs are made up; no real creators). Note `n1` is a video, `n2` is an image note, `n3` is a video whose detail is missing; the search also carries a `rec_query` row.

`tests/fixtures/xhs-api/search.json`:

```json
{
  "has_more": true,
  "items": [
    { "id": "66f1a2b3c4d5e6f700000101", "model_type": "note", "xsec_token": "TOK1", "xsec_source": "pc_search",
      "note_card": { "type": "video", "display_title": "搬来上海第一周", "user": { "user_id": "u-1", "nickname": "小*" },
                     "interact_info": { "liked_count": "1.2万" }, "cover": { "url_default": "https://sns-img.example/c1.jpg" } } },
    { "id": "66f1a2b3c4d5e6f700000102", "model_type": "note", "xsec_token": "TOK2", "xsec_source": "pc_search",
      "note_card": { "type": "normal", "display_title": "租房避坑", "user": { "user_id": "u-2", "nickname": "阿*" },
                     "interact_info": { "liked_count": "88" } } },
    { "id": "rec-1", "model_type": "rec_query", "rec_query": { "queries": [] } },
    { "id": "66f1a2b3c4d5e6f700000103", "model_type": "note", "xsec_token": "TOK3", "xsec_source": "pc_search",
      "note_card": { "type": "video", "display_title": "已删除的视频", "user": { "user_id": "u-3", "nickname": "被*" },
                     "interact_info": { "liked_count": "3" } } }
  ]
}
```

`tests/fixtures/xhs-api/feed.json` (the detail for `n1`; the runner's fake client maps ids to this or to an empty item list):

```json
{
  "note_id": "66f1a2b3c4d5e6f700000101",
  "type": "video",
  "title": "搬来上海第一周｜新加坡人的真实感受",
  "desc": "从新加坡搬到上海的第一周，租房踩了三个坑。#上海生活 #新加坡人在上海",
  "time": 1727000000000,
  "last_update_time": 1727000500000,
  "user": { "user_id": "u-1", "nickname": "小*" },
  "interact_info": { "liked_count": "1.2万", "collected_count": "3,210", "comment_count": "15", "share_count": "7" },
  "image_list": [ { "url_default": "https://sns-img.example/n1-cover.jpg", "info_list": [] } ],
  "tag_list": [ { "name": "上海生活", "type": "topic" }, { "name": "@someone", "type": "mention" } ],
  "video": { "media": { "stream": {
    "h264": [ { "master_url": "https://sns-video.example/n1-720.mp4", "height": 720, "avg_bitrate": 900 } ],
    "h265": [ { "master_url": "https://sns-video.example/n1-1080.mp4", "height": 1080, "avg_bitrate": 1500 },
              { "master_url": "https://sns-video.example/n1-720.mp4", "height": 720, "avg_bitrate": 800 } ],
    "av1": []
  } } }
}
```

`tests/fixtures/xhs-api/comments.json`:

```json
{
  "has_more": false,
  "cursor": "",
  "comments": [
    { "id": "c1", "content": "太真实了", "like_count": "12", "create_time": 1727001000000, "sub_comment_count": "2",
      "user_info": { "user_id": "u-9", "nickname": "路*" }, "pictures": [] },
    { "id": "c2", "content": "求房源", "like_count": "3", "create_time": 1727002000000, "sub_comment_count": "0",
      "user_info": { "user_id": "u-8", "nickname": "甲*" } }
  ]
}
```

Run from the repo root after writing them: `bunx ultracite fix contrib/adapter-xhs-mediacrawler/tests/fixtures/xhs-api` (Biome formats JSON).

- [x] **Step 2: Write the failing tests**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_api_runner.py
import json
from pathlib import Path

import httpx
import pytest

from clipsieve.adapters.base import AdapterHealth
from clipsieve_xhs.api_runner import (
    XhsApiRunner,
    build_comment_records,
    build_note_record,
    image_urls_from_card,
    video_stream_urls,
)
from clipsieve_xhs.errors import XhsApiError, XhsLoginRequired, XhsRateLimited
from clipsieve_xhs.mapping import map_note
from clipsieve_xhs.runner import RunnerOutput
from clipsieve_xhs.settings import XhsSettings

FIX = Path(__file__).parent / "fixtures" / "xhs-api"
SEARCH = json.loads((FIX / "search.json").read_text(encoding="utf-8"))
FEED = json.loads((FIX / "feed.json").read_text(encoding="utf-8"))
COMMENTS = json.loads((FIX / "comments.json").read_text(encoding="utf-8"))
N1, N2, N3 = (SEARCH["items"][i]["id"] for i in (0, 1, 3))
NOW = 1_727_100_000_000


def settings(**over):
    return XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=Path("/nonexistent"), **over)


class FakeClient:
    """Scripted responses; records every call so tests can count requests."""

    def __init__(self, search=SEARCH, detail=None, comments=COMMENTS, fail=None):
        self.search = search
        self.detail = detail if detail is not None else {N1: FEED}
        self.comment_data = comments
        self.fail = fail or {}  # method name -> exception to raise
        self.calls: list[tuple] = []

    def search_notes(self, keyword, page, **kw):
        self.calls.append(("search", keyword, page, kw.get("note_type"), kw.get("page_size")))
        if "search" in self.fail:
            raise self.fail["search"]
        return self.search if page == 1 else {"items": [], "has_more": False}

    def note_detail(self, note_id, xsec_token, xsec_source="pc_search"):
        self.calls.append(("detail", note_id, xsec_token))
        if note_id in self.fail:
            raise self.fail[note_id]
        if note_id not in self.detail:
            raise XhsApiError(f"/api/sns/web/v1/feed: no note card for {note_id}")
        return self.detail[note_id]

    def comments(self, note_id, xsec_token, cursor=""):
        self.calls.append(("comments", note_id))
        if "comments" in self.fail:
            raise self.fail["comments"]
        return self.comment_data


def make_runner(client: FakeClient, cookies="a1=A; web_session=W", **over) -> XhsApiRunner:
    provider = cookies if callable(cookies) else (lambda: cookies)
    return XhsApiRunner(
        settings(**over),
        cdp_port=9222,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
        cookies_provider=provider,
        client_factory=lambda _cookies: client,
        now_ms=lambda: NOW,
    )


# -- record builders -------------------------------------------------------------------


def test_video_stream_urls_best_quality_first_and_deduped():
    assert video_stream_urls(FEED) == [
        "https://sns-video.example/n1-1080.mp4",
        "https://sns-video.example/n1-720.mp4",
    ]
    assert video_stream_urls({"video": {"media": {"stream": {"h264": []}}}}) == []
    assert video_stream_urls({}) == []


def test_image_urls_from_card_uses_url_default():
    assert image_urls_from_card(FEED) == ["https://sns-img.example/n1-cover.jpg"]
    assert image_urls_from_card({}) == []


def test_note_record_has_the_mediacrawler_keys_and_no_identifiers():
    rec = build_note_record(SEARCH["items"][0], FEED, "新加坡 上海 vlog", NOW)
    assert rec["note_id"] == N1
    assert rec["type"] == "video"
    assert rec["title"] == FEED["title"] and rec["desc"] == FEED["desc"]
    assert rec["video_url"].split(",")[0] == "https://sns-video.example/n1-1080.mp4"
    assert rec["time"] == FEED["time"] and rec["last_update_time"] == FEED["last_update_time"]
    assert rec["liked_count"] == "1.2万" and rec["collected_count"] == "3,210"
    assert rec["image_list"] == "https://sns-img.example/n1-cover.jpg"
    assert rec["tag_list"] == "上海生活"  # mentions are not topics
    assert rec["note_url"] == f"https://www.xiaohongshu.com/explore/{N1}?xsec_token=TOK1&xsec_source=pc_search"
    assert rec["source_keyword"] == "新加坡 上海 vlog" and rec["xsec_token"] == "TOK1"
    assert rec["last_modify_ts"] == NOW
    assert len(rec["creator_hash"]) == 64 and "u-1" not in json.dumps(rec)
    assert "nickname" not in rec and "user_id" not in json.dumps(rec)


def test_note_record_feeds_map_note_unchanged():
    rec = build_note_record(SEARCH["items"][0], FEED, "k", NOW)
    post = map_note(rec, [], "salt", "/tmp/raw.json", __import__("datetime").datetime.now(__import__("datetime").UTC))
    assert post.kind.value == "video"
    assert post.text.title == FEED["title"]
    assert post.url.endswith("xsec_token=TOK1&xsec_source=pc_search")


def test_comment_records_keep_only_the_allowed_fields():
    recs = build_comment_records(N1, COMMENTS, NOW)
    assert [r["comment_id"] for r in recs] == ["c1", "c2"]
    assert set(recs[0]) == {
        "comment_id", "create_time", "note_id", "content", "like_count",
        "sub_comment_count", "parent_comment_id", "last_modify_ts",
    }
    assert recs[0]["note_id"] == N1 and recs[0]["parent_comment_id"] == ""
    assert "u-9" not in json.dumps(recs) and "路" not in json.dumps(recs)


# -- runner ---------------------------------------------------------------------------


def test_only_note_rows_of_the_requested_kind_are_fetched(tmp_path):
    client = FakeClient()
    out = make_runner(client, clipsieve_xhs_note_kinds="video").search("k", 1, tmp_path)
    assert isinstance(out, RunnerOutput)
    assert out.returncode == 0
    assert [n["note_id"] for n in out.notes] == [N1]
    detail_calls = [c for c in client.calls if c[0] == "detail"]
    # n2 is an image note, rec-1 is not a note: neither costs a detail request
    assert [c[1] for c in detail_calls] == [N1, N3]
    assert client.calls[0] == ("search", "k", 1, "video", 20)


def test_all_kinds_fetches_image_notes_too(tmp_path):
    client = FakeClient(detail={N1: FEED, N2: {**FEED, "note_id": N2, "type": "normal", "video": None}})
    out = make_runner(client, clipsieve_xhs_note_kinds="all").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1, N2]
    assert client.calls[0][3] == "all"


def test_note_without_stream_is_skipped_not_fatal(tmp_path):
    out = make_runner(FakeClient(), clipsieve_xhs_note_kinds="video").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert any(N3 in e for e in out.errors)
    assert out.returncode == 0


def test_comments_are_fetched_only_when_enabled(tmp_path):
    off = FakeClient()
    make_runner(off).search("k", 1, tmp_path)
    assert not [c for c in off.calls if c[0] == "comments"]
    on = FakeClient()
    out = make_runner(on, clipsieve_xhs_comments=True).search("k", 1, tmp_path)
    assert [c for c in on.calls if c[0] == "comments"] == [("comments", N1)]
    assert [c["comment_id"] for c in out.comments] == ["c1", "c2"]


def test_empty_page_returns_empty_output(tmp_path):
    out = make_runner(FakeClient()).search("k", 2, tmp_path)
    assert out.notes == [] and out.comments == [] and out.errors == [] and out.returncode == 0


def test_login_expired_mid_page_returns_partial_and_stops(tmp_path):
    client = FakeClient(fail={N3: XhsLoginRequired("/feed: login expired (-104)", code=-104)})
    runner = make_runner(client, clipsieve_xhs_note_kinds="video")
    out = runner.search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert out.returncode == 1 and any("login expired" in e for e in out.errors)
    # the next page must not reuse the dead session: the client is rebuilt from fresh cookies
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        raise XhsLoginRequired("missing cookie(s) web_session")

    runner2 = make_runner(client, cookies=provider)
    out2 = runner2.search("k", 1, tmp_path)
    assert out2.notes == [] and out2.returncode == 1 and "web_session" in out2.errors[0]
    assert calls["n"] == 1


def test_rate_limit_during_details_stops_page(tmp_path):
    client = FakeClient(fail={N3: XhsRateLimited("/feed: rate limited after 3 attempts (300012)", code=300012)})
    out = make_runner(client, clipsieve_xhs_note_kinds="video").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert out.returncode == 1 and any("300012" in e for e in out.errors)


def test_search_failure_is_a_page_error_not_an_exception(tmp_path):
    client = FakeClient(fail={"search": XhsApiError("/search: HTTP 403", status=403)})
    out = make_runner(client).search("k", 1, tmp_path)
    assert out.notes == [] and out.returncode == 1 and "403" in out.errors[0]


def test_healthcheck_reports_the_session_or_the_login_problem():
    ok = make_runner(FakeClient()).healthcheck()
    assert isinstance(ok, AdapterHealth) and ok.ok is True
    assert "api" in ok.message and "9222" in ok.message

    def no_login():
        raise XhsLoginRequired("not logged in to xiaohongshu.com in the browser on port 9222")

    bad = make_runner(FakeClient(), cookies=no_login).healthcheck()
    assert bad.ok is False and "log in" in bad.message

    def no_browser():
        raise httpx.ConnectError("refused")

    down = make_runner(FakeClient(), cookies=no_browser).healthcheck()
    assert down.ok is False and "9222" in down.message
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_api_runner.py`
Expected: `ModuleNotFoundError: No module named 'clipsieve_xhs.api_runner'`

- [x] **Step 4: Write the records and the runner**

```python
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
    items.sort(key=lambda it: (_as_int(it.get("height")), _as_int(it.get("avg_bitrate"))), reverse=True)
    urls: list[str] = []
    for it in items:
        url = str(it["master_url"])
        if url not in urls:
            urls.append(url)
    return urls


def image_urls_from_card(card: dict) -> list[str]:
    return [str(img["url_default"]) for img in card.get("image_list") or [] if _as_dict(img).get("url_default")]


def build_note_record(item: dict, card: dict, keyword: str, now_ms: int) -> dict:
    """The MediaCrawler jsonl shape `mapping.FIELD_MAP` reads; creator id hashed, nickname dropped."""
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
            str(t.get("name") or "") for t in card.get("tag_list") or [] if _as_dict(t).get("type") == "topic"
        ),
        "last_modify_ts": now_ms,
        "note_url": f"{WEB_ORIGIN}/explore/{note_id}?xsec_token={token}&xsec_source={source}",
        "source_keyword": keyword,
        "xsec_token": token,
    }


def build_comment_records(note_id: str, data: dict, now_ms: int) -> list[dict]:
    out: list[dict] = []
    for c in data.get("comments") or []:
        c = _as_dict(c)
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
        self._cookies_provider = cookies_provider or (lambda: cookie_header(self.cdp_port, self.http))
        self._client_factory = client_factory or (
            lambda cookies: XhsApiClient(cookies, self.http, interval_s=self.settings.clipsieve_xhs_request_interval_s)
        )
        self._now_ms = now_ms
        self._client: XhsApiClient | None = None

    # -- RunnerProtocol -------------------------------------------------------------------

    def healthcheck(self) -> AdapterHealth:
        try:
            self._cookies_provider()
        except XhsLoginRequired as e:
            return AdapterHealth(False, f"api runner: {e}")
        except httpx.HTTPError as e:
            return AdapterHealth(False, f"api runner: Chrome remote debugging not reachable on port {self.cdp_port}: {e}")
        return AdapterHealth(True, f"api runner: xiaohongshu web session from the browser on port {self.cdp_port}")

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        notes: list[dict] = []
        comments: list[dict] = []
        errors: list[str] = []
        try:
            client = self._get_client()
        except (XhsLoginRequired, httpx.HTTPError) as e:
            return RunnerOutput(notes=[], comments=[], errors=[str(e)], returncode=1, stderr_tail="")
        kind = self.settings.clipsieve_xhs_note_kinds
        try:
            data = client.search_notes(
                keyword, start_page, note_type=kind, page_size=self.settings.clipsieve_xhs_page_size
            )
        except XhsApiError as e:
            self._drop_client_if_dead(e)
            return RunnerOutput(notes=[], comments=[], errors=[str(e)], returncode=1, stderr_tail="")

        items = [it for it in data.get("items") or [] if _as_dict(it).get("model_type") == "note"]
        returncode = 0
        for item in items:
            if kind == "video" and _as_dict(item.get("note_card")).get("type") not in (None, "video"):
                continue  # image note: no detail request
            note_id = str(item.get("id") or "")
            try:
                card = client.note_detail(note_id, str(item.get("xsec_token") or ""), str(item.get("xsec_source") or "pc_search"))
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
                    comments.extend(build_comment_records(note_id, client.comments(note_id, record["xsec_token"]), self._now_ms()))
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
        return RunnerOutput(notes=notes, comments=comments, errors=errors, returncode=returncode, stderr_tail="")

    # -- helpers --------------------------------------------------------------------------

    def _get_client(self) -> XhsApiClient:
        if self._client is None:
            self._client = self._client_factory(self._cookies_provider())
        return self._client

    def _drop_client_if_dead(self, error: XhsApiError) -> None:
        if isinstance(error, XhsLoginRequired):
            self._client = None  # the next page re-reads cookies from the browser
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error && uv run ruff check . && uv run ruff format --check .`
Expected: all tests pass (54 before this plan + 3 settings + 5 cookies + 12 client + 15 runner = 89); ruff clean. From the repo root `bun run check` exit 0 (Biome lints the new fixture JSON; ruff covers `contrib/`).

- [x] **Step 6: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/clipsieve_xhs/api_runner.py contrib/adapter-xhs-mediacrawler/tests/test_api_runner.py contrib/adapter-xhs-mediacrawler/tests/fixtures/xhs-api
git commit -m "feat(contrib-xhs): api runner emitting MediaCrawler-shaped records

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 5: Adapter wiring, docs and the overview addendum

**Files:**
- Modify: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/adapter.py` (runner selection)
- Modify: `contrib/adapter-xhs-mediacrawler/tests/test_adapter.py` (two tests)
- Modify: `contrib/adapter-xhs-mediacrawler/AGENTS.md`, `contrib/adapter-xhs-mediacrawler/README.md`
- Modify: `README.md` (root; Community adapters table row)
- Modify: `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md` (Addendum C.19)

**Interfaces:**
- Consumes: `XhsApiRunner` (Task 4), `MediaCrawlerRunner`, `XhsSettings.clipsieve_xhs_runner`.
- Produces: `XhsMediaCrawlerAdapter.__init__` picks the runner from settings when none is injected; `from_settings` unchanged; `healthcheck` unchanged (delegates).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adapter.py`:

```python


def test_default_runner_follows_the_setting(tmp_path):
    from clipsieve.config import Settings
    from clipsieve_xhs.api_runner import XhsApiRunner
    from clipsieve_xhs.runner import MediaCrawlerRunner

    core = Settings(_env_file=None, clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")
    api = XhsMediaCrawlerAdapter(core, XhsSettings(_env_file=None, clipsieve_xhs_runner="api"))
    assert isinstance(api.runner, XhsApiRunner)
    assert api.runner.cdp_port == core.clipsieve_xhs_chrome_cdp_port
    mc = XhsMediaCrawlerAdapter(core, XhsSettings(_env_file=None, clipsieve_xhs_runner="mediacrawler"))
    assert isinstance(mc.runner, MediaCrawlerRunner)


def test_from_settings_builds_the_api_runner_by_default(tmp_path):
    from clipsieve.config import Settings
    from clipsieve_xhs.api_runner import XhsApiRunner

    core = Settings(_env_file=None, clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")
    adapter = XhsMediaCrawlerAdapter.from_settings(core)
    assert isinstance(adapter.runner, XhsApiRunner)
```

If the adapter stores the runner under another attribute name than `runner`, read `adapter.py` and use that name in both tests; do not add a second attribute.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error tests/test_adapter.py -k "default_runner or from_settings_builds"`
Expected: 2 failed (`MediaCrawlerRunner` is built regardless of the setting).

- [ ] **Step 3: Select the runner from settings**

In `clipsieve_xhs/adapter.py`, where `__init__` currently does `runner or MediaCrawlerRunner(self.xhs, cdp_port=...)` (see the line after `self.xhs = xhs_settings or get_xhs_settings()`), replace the runner construction with:

```python
        self.runner = runner or self._runner_from_settings()
```

and add the method to the class (next to `healthcheck`):

```python
    def _runner_from_settings(self) -> RunnerProtocol:
        port = self.settings.clipsieve_xhs_chrome_cdp_port
        if self.xhs.clipsieve_xhs_runner == "api":
            from clipsieve_xhs.api_runner import XhsApiRunner  # keeps MediaCrawler-only installs importable

            return XhsApiRunner(self.xhs, cdp_port=port, http=self.http)
        return MediaCrawlerRunner(self.xhs, cdp_port=port)
```

`RunnerProtocol` is already imported from `clipsieve_xhs.runner`; if the adapter's httpx client attribute is named differently from `self.http`, use that name.

- [ ] **Step 4: Run the whole contrib suite and the repo check**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest -q -W error && uv run ruff check . && uv run ruff format --check . && cd ../.. && bun run check`
Expected: 91 passed; ruff clean; `bun run check` exit 0.

- [ ] **Step 5: Update the contrib docs**

`contrib/adapter-xhs-mediacrawler/AGENTS.md`: in the contract list replace the bullet that begins "Never vendor MediaCrawler files." with two bullets:

```markdown
- Two runners behind `RunnerProtocol`, chosen by `CLIPSIEVE_XHS_RUNNER`. `api` (default, `api_runner.py`): the user's xiaohongshu.com cookies are read from their own Chromium over CDP (`cdp_cookies.py`, `Storage.getCookies`, never stored or logged), every request is signed with `xhshow` (`api_client.py`), search uses `note_type=1` when `CLIPSIEVE_XHS_NOTE_KINDS=video`, one detail request per note supplies the video stream URL, comments are opt-in (`CLIPSIEVE_XHS_COMMENTS`). Requests are serial with a jittered interval (`CLIPSIEVE_XHS_REQUEST_INTERVAL_S`); rate-limit codes back off at most twice; login-expired and verification responses end the page with a recoverable error and the next page re-reads cookies.
- `mediacrawler` (fallback, `runner.py`): never vendor MediaCrawler files; drive the checkout at `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` as a subprocess with cwd = the checkout and `--save_data_path <workdir>`, and parse `<workdir>/xhs/jsonl/`.
```

Add under Layout: `clipsieve_xhs/errors.py`, `cdp_cookies.py`, `api_client.py`, `api_runner.py`, `tests/fixtures/xhs-api/` (synthetic search/feed/comments responses). Keep the paging bullet; change "Each page is a full MediaCrawler run" to "Each page is one full MediaCrawler run (mediacrawler) or one search request plus one detail request per note (api)".

`contrib/adapter-xhs-mediacrawler/README.md`: in Setup, make step 1 (the MediaCrawler clone) conditional: "Only for `CLIPSIEVE_XHS_RUNNER=mediacrawler`"; step 2 (browser with remote debugging, logged in) is required for both runners; add a "How the api runner works" section with the five bullets from the design note's Decision section, and a "Performance" section with the table from the design note marked "measured in Task 6".

- [ ] **Step 6: Root README and the overview addendum**

Root `README.md`, Community adapters table: change the "How it works" cell to "Calls the web search API from your own logged-in browser session (video-only search, 20 notes per request), signed with `xhshow`; a MediaCrawler checkout is the optional fallback runner".

`docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`, append to Addendum C:

```markdown
19. **XHS api runner (plan 06).** `CLIPSIEVE_XHS_RUNNER=api` (default) collects through `https://edith.xiaohongshu.com` with cookies read from the user's browser over CDP and `xhshow` signatures; `note_type=1` when `CLIPSIEVE_XHS_NOTE_KINDS=video`; one `/feed` detail request per note for the stream URL; comments opt-in. Records keep the MediaCrawler jsonl keys, so `mapping.py`, raw-payload stripping (C.17), the media-URL cache (C.15) and `fetch_media` are unchanged. `mediacrawler` keeps C.2's invocation as the fallback.
```

- [ ] **Step 7: Lint the docs and commit**

Run from the repo root: `bunx ultracite check contrib/adapter-xhs-mediacrawler/AGENTS.md contrib/adapter-xhs-mediacrawler/README.md README.md docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`
Expected: exit 0.

```bash
git add contrib/adapter-xhs-mediacrawler README.md docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md
git commit -m "feat(contrib-xhs): api runner is the default; MediaCrawler becomes the fallback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 6: Live verification and calibration (needs the user's browser session)

This task talks to xiaohongshu.com through the user's own logged-in Brave on port 9222. It is not a test and never runs in CI. Nothing it fetches is committed.

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/scripts/probe_api_runner.py`
- Modify: `contrib/adapter-xhs-mediacrawler/README.md` (Performance table filled with measured numbers)
- Modify: `.env.example` only if the default interval had to change

**Interfaces:**
- Consumes: `XhsApiRunner`, `get_settings`, `get_xhs_settings`.
- Produces: measured throughput numbers; a go/no-go on the `1.0` s default interval.

- [ ] **Step 1: Write the probe script**

```python
# contrib/adapter-xhs-mediacrawler/scripts/probe_api_runner.py
"""One video-only search page through the api runner against the user's browser session.

Run from contrib/adapter-xhs-mediacrawler:
    uv run python scripts/probe_api_runner.py "新加坡搬到上海" [pages]
Prints counts and timing only; writes nothing. Not a test; needs Brave on the CDP port, logged in.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from clipsieve.config import get_settings
from clipsieve_xhs.api_runner import XhsApiRunner
from clipsieve_xhs.settings import get_xhs_settings


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "新加坡搬到上海"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    core = get_settings()
    xhs = get_xhs_settings().model_copy(update={"clipsieve_xhs_note_kinds": "video"})
    runner = XhsApiRunner(xhs, cdp_port=core.clipsieve_xhs_chrome_cdp_port)
    health = runner.healthcheck()
    sys.stdout.write(f"health: {health.ok} {health.message}\n")
    if not health.ok:
        return 2
    workdir = Path(tempfile.mkdtemp(prefix="xhs-api-probe-"))
    total_notes = 0
    started = time.monotonic()
    for page in range(1, pages + 1):
        t0 = time.monotonic()
        out = runner.search(keyword, page, workdir)
        videos = sum(1 for n in out.notes if n.get("video_url"))
        sys.stdout.write(
            f"page {page}: notes={len(out.notes)} videos={videos} comments={len(out.comments)} "
            f"errors={len(out.errors)} rc={out.returncode} in {time.monotonic() - t0:.1f}s\n"
        )
        for err in out.errors[:3]:
            sys.stdout.write(f"  error: {err[:160]}\n")
        total_notes += len(out.notes)
        if out.returncode != 0 or not out.notes:
            break
    elapsed = time.monotonic() - started
    sys.stdout.write(f"total: {total_notes} video notes in {elapsed:.0f}s ({60 * total_notes / max(elapsed, 1):.0f}/min)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(`sys.stdout.write` keeps the repo's no-`print()` rule; the script is outside the package and is not imported by anything.)

- [ ] **Step 2: Confirm the browser session**

Run: `curl -s localhost:9222/json/version | head -c 120`
Expected: a JSON object with `webSocketDebuggerUrl`. If not, start Brave: `open -na "Brave Browser" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.clipsieve-chrome" "https://www.xiaohongshu.com"` and log in there.

- [ ] **Step 3: Probe one page, then three**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run python scripts/probe_api_runner.py "新加坡搬到上海" 1`
Expected: `health: True api runner: ...`, then `page 1: notes=<15..20> videos=<same> ... rc=0 in <20..40>s`. Every note must be a video (the server-side filter), and `errors` should be 0 to 2 (deleted notes).

Run: `uv run python scripts/probe_api_runner.py "新加坡人 上海 vlog" 3`
Expected: three pages, 40 to 60 video notes, total under 2 minutes, no `300012`. If a page reports `rate limited`, set `CLIPSIEVE_XHS_REQUEST_INTERVAL_S=1.5` in `.env`, rerun, and if that is what it takes, change the default in `settings.py` and `.env.example` to `1.5` and say so in the README.

If the first page returns `HTTP 403`/`406` or `success: false` with an unfamiliar code, the signature or body shape is off: compare the request against MediaCrawler's `client.py:318-330` and `playwright_sign.py` (body bytes, header names, `x-s-common`), fix `api_client.py`, add a unit test for the difference, and rerun.

- [ ] **Step 4: End-to-end run from the dashboard**

With `.env` holding `CLIPSIEVE_XHS_RUNNER=api`, `CLIPSIEVE_XHS_NOTE_KINDS=video`, restart `bun run dev`, confirm `curl -s localhost:8000/api/adapters` shows `xiaohongshu` healthy with the "api runner" message, then start a run with platform `xiaohongshu`, quantity 30, brief `新加坡人搬到上海的生活 vlog`. Expected: `collecting` finishes in under 5 minutes with 30 video posts; `post_collected` events carry `kind: video`; `fetch_media` downloads `video.mp4` for every kept post (the stream URLs need the `Referer` header the adapter already sends); the run proceeds through extraction and judging as before.

Record in `contrib/adapter-xhs-mediacrawler/README.md` Performance: notes per page, seconds per page, videos per minute, and the interval that worked.

- [ ] **Step 5: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/scripts/probe_api_runner.py contrib/adapter-xhs-mediacrawler/README.md
git commit -m "docs(contrib-xhs): api runner probe script and measured throughput

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

If `.env.example` or `settings.py` changed in Step 3, add them to the same commit.

---

## Self-review

**Spec coverage.** Design note Decision bullets: cookies over CDP (Task 2); direct signed requests with browser headers (Task 3); `note_type=1` and `page_size=20`, one page per `search()` (Tasks 3, 4); one detail per note, comments opt-in (Task 4); MediaCrawler-shaped records with hashed creator ids and no nicknames (Task 4); pacing and backoff (Task 3); runner switch with `api` default (Tasks 1, 5). Expected-effect table measured in Task 6. Risks: fallback kept (Task 5), verification/rate-limit surfaced not retried (Tasks 3, 4), disclaimer covers both runners (Task 5 README).

**Placeholder scan.** None. Every step has full code or an exact command; Task 6 is manual by nature and says exactly what to run and what to expect.

**Type consistency.** `RunnerOutput(notes, comments, errors, returncode, stderr_tail)` as in `runner.py`; `XhsApiClient.search_notes(keyword, page, *, note_type, page_size, sort, sid)` used identically in Tasks 3 and 4; `cookie_header(port, http, connect)` used by `XhsApiRunner` with the default `connect`; `build_note_record(item, card, keyword, now_ms)` matches its tests; `AdapterHealth(ok, message)` positional as in `base.py`; settings field names identical across Tasks 1, 4, 5 and `.env.example`.

**Review Focus.** Items 1 to 5 are pinned by the named tests in Tasks 3 and 4.

## Sources

- MediaCrawler (NanmiCoder): https://github.com/NanmiCoder/MediaCrawler
- xhshow (Cloxl), MIT, pure-Python signing: https://github.com/cloxl/xhshow and https://pypi.org/project/xhshow/
- xhs (ReaJason), MIT, endpoint reference: https://github.com/ReaJason/xhs
- Spider_XHS (cv-cat): https://github.com/cv-cat/Spider_XHS
- XHS-Downloader (JoeanAmier): https://github.com/JoeanAmier/XHS-Downloader
