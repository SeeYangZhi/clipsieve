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
    # "Connection: close": a pooled keep-alive socket to the browser would outlive the runner
    # (one per adapter build) and surface as an unclosed-socket ResourceWarning.
    version = http.get(
        f"http://127.0.0.1:{port}/json/version", timeout=5.0, headers={"Connection": "close"}
    )
    version.raise_for_status()
    ws_url = version.json()["webSocketDebuggerUrl"]
    with connect(ws_url) as ws:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                break
    if "error" in msg:
        raise XhsLoginRequired(
            f"CDP Storage.getCookies failed: {msg['error'].get('message', msg['error'])}"
        )
    return list(msg["result"]["cookies"])


def cookie_header(port: int, http: httpx.Client, connect: Connect = _default_connect) -> str:
    """`name=value; ...` for xiaohongshu.com, or `XhsLoginRequired` when the session is missing."""
    cookies = [
        c
        for c in fetch_cookies(port, http, connect)
        if str(c.get("domain", "")).endswith(COOKIE_DOMAIN)
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
