# contrib/adapter-xhs-mediacrawler/tests/test_cdp_cookies.py
import json
from contextlib import contextmanager

import httpx
import pytest

from clipsieve_xhs.cdp_cookies import cookie_header, fetch_cookies
from clipsieve_xhs.errors import XhsLoginRequired

VERSION = {
    "Browser": "Chrome/146.0",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc",
}


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
