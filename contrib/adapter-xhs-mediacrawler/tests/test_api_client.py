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
        self.x_rap = []

    def sign_headers_get(self, uri, cookies, params, x_rap=False):
        self.calls.append(("GET", uri, cookies, params))
        self.x_rap.append(x_rap)
        return {"x-s": "XS", "x-t": "1", "x-s-common": "XSC", "x-b3-traceid": "T"}

    def sign_headers_post(self, uri, cookies, payload, x_rap=False):
        self.calls.append(("POST", uri, cookies, payload))
        self.x_rap.append(x_rap)
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
    route = respx.post(API_HOST + SEARCH_URI).mock(
        return_value=ok({"items": [], "has_more": False})
    )
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
def test_requests_carry_the_browser_header_set_and_every_signed_header():
    """A tab sends x-mns, xy-direction and the sec-* fetch metadata with every request, and
    xhshow documents x-rap-param (x_rap=True) as required by the search and feed endpoints.
    (Task 6 live check: none of this changed the -104 the risk-controlled session returned; it
    is kept because it is what the browser sends.)"""
    route = respx.post(API_HOST + SEARCH_URI).mock(return_value=ok({"items": []}))
    client, signer, _ = make_client()
    seen = {}

    def sign_post(uri, cookies, payload, x_rap=False):
        seen["x_rap"] = x_rap
        return {
            "x-s": "XS",
            "x-t": "1",
            "x-s-common": "XSC",
            "x-b3-traceid": "T",
            "x-xray-traceid": "X",
            "x-mns": "unload",
            "xy-direction": "27",
            "x-rap-param": "RAP",
            "x-other": "dropped",
        }

    signer.sign_headers_post = sign_post
    client.search_notes("k", 1)
    assert seen == {"x_rap": True}
    h = route.calls.last.request.headers
    for name in ("x-s", "x-t", "x-s-common", "x-b3-traceid", "x-xray-traceid"):
        assert h[name]
    assert h["x-mns"] == "unload" and h["xy-direction"] == "27" and h["x-rap-param"] == "RAP"
    assert "x-other" not in h
    assert h["sec-fetch-site"] == "same-site" and h["sec-fetch-mode"] == "cors"
    assert h["sec-fetch-dest"] == "empty" and h["sec-ch-ua-mobile"] == "?0"
    assert h["sec-ch-ua-platform"] == '"macOS"' and "146" in h["sec-ch-ua"]
    assert h["accept-language"].startswith("zh-CN") and "146" in h["user-agent"]
    assert h["cookie"] == COOKIES


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
    # The wire query string must equal what xhshow signed: platform order, literal comma
    # (xhshow quotes with safe=","), empty values kept as `k=`.
    raw = route.calls.last.request.url.raw_path.decode()
    assert raw == (
        COMMENTS_URI
        + "?note_id=n1&cursor=c2&top_comment_id=&image_formats=jpg,webp,avif&xsec_token=TOKEN"
    )
    assert "image_formats=jpg,webp,avif" in raw and "cursor=c2&top_comment_id=&" in raw
    assert signer.calls == [
        (
            "GET",
            COMMENTS_URI,
            COOKIES,
            {
                "note_id": "n1",
                "cursor": "c2",
                "top_comment_id": "",
                "image_formats": "jpg,webp,avif",
                "xsec_token": "TOKEN",
            },
        )
    ]


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
        return_value=httpx.Response(200, json={"code": -100, "success": False, "msg": "登录已过期"})
    )
    client, _, _ = make_client()
    with pytest.raises(XhsLoginRequired, match="login expired .-100"):
        client.search_notes("k", 1)
    assert route.call_count == 1


@respx.mock
def test_no_permission_code_names_the_risk_control_without_retry():
    """-104 is the platform holding the account back (seen live, Task 6), not an expired login:
    the message must tell the user to check the browser and retry later. No retry, no backoff."""
    route = respx.post(API_HOST + SEARCH_URI).mock(
        return_value=httpx.Response(
            200, json={"code": -104, "success": False, "msg": "您当前登录的账号没有权限访问"}
        )
    )
    client, _, sleeps = make_client()
    with pytest.raises(XhsLoginRequired, match="no permission .-104 .*retry later") as e:
        client.search_notes("k", 1)
    assert e.value.code == -104
    assert route.call_count == 1 and sleeps == []


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
        return_value=httpx.Response(
            200, json={"code": 300012, "success": False, "msg": "访问频次异常"}
        )
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


@respx.mock
def test_non_json_200_is_an_api_error_without_echoing_the_body():
    respx.post(API_HOST + SEARCH_URI).mock(
        return_value=httpx.Response(200, text="<html><body>secret challenge page</body></html>")
    )
    client, _, _ = make_client()
    with pytest.raises(XhsApiError, match="non-JSON") as info:
        client.search_notes("k", 1)
    assert info.value.status == 200
    assert "secret" not in str(info.value)


@respx.mock
def test_network_error_is_an_api_error_without_retry():
    """A timeout or connection failure must reach the runner as `XhsApiError` (so a page ends
    with a recoverable error) and must not be retried; the message names the type only."""
    route = respx.post(API_HOST + SEARCH_URI).mock(side_effect=httpx.ReadTimeout("t"))
    client, _, _ = make_client()
    with pytest.raises(XhsApiError, match=r"network error \(ReadTimeout\)") as info:
        client.search_notes("k", 1)
    assert route.call_count == 1
    assert info.value.status is None and info.value.code is None
    assert SEARCH_URI in str(info.value)


class RaisingSigner(FakeSigner):
    def __init__(self, exc: Exception):
        super().__init__()
        self.exc = exc

    def sign_headers_post(self, uri, cookies, payload, x_rap=False):
        raise self.exc

    def sign_headers_get(self, uri, cookies, params, x_rap=False):
        raise self.exc


@respx.mock
def test_signer_value_error_is_an_api_error_with_a_truncated_message():
    route = respx.post(API_HOST + SEARCH_URI).mock(return_value=ok({"items": []}))
    client = XhsApiClient(
        COOKIES,
        httpx.Client(),
        signer=RaisingSigner(ValueError("Missing 'a1' in cookies")),
        sleep=lambda _s: None,
    )
    with pytest.raises(XhsApiError, match="ValueError: Missing 'a1'"):
        client.search_notes("k", 1)
    assert route.call_count == 0  # nothing was sent
    # A long signer message is cut so it cannot carry a whole cookie string.
    long = RaisingSigner(ValueError("x" * 300))
    client2 = XhsApiClient(COOKIES, httpx.Client(), signer=long, sleep=lambda _s: None)
    with pytest.raises(XhsApiError) as info:
        client2.comments("n1", "TOK")
    assert len(str(info.value)) < 120 + len(COMMENTS_URI) + 20


@respx.mock
def test_non_integer_code_is_an_api_error():
    respx.post(API_HOST + SEARCH_URI).mock(
        return_value=httpx.Response(200, json={"code": "weird", "success": False, "msg": "m"})
    )
    client, _, _ = make_client()
    with pytest.raises(XhsApiError, match="ValueError"):
        client.search_notes("k", 1)


def test_search_id_is_base36_and_fresh():
    a, b = search_id(), search_id()
    assert a != b
    assert all(ch in "0123456789abcdefghijklmnopqrstuvwxyz" for ch in a)


def test_real_signer_produces_the_required_headers():
    """xhshow is pure Python; one offline call proves the dependency and the key names."""
    from xhshow import Xhshow

    headers = Xhshow().sign_headers_post(
        uri=SEARCH_URI, cookies=COOKIES, payload={"keyword": "k"}, x_rap=True
    )
    assert {"x-s", "x-t", "x-s-common", "x-rap-param"} <= set(headers)
