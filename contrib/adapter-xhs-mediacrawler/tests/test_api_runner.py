# contrib/adapter-xhs-mediacrawler/tests/test_api_runner.py
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from clipsieve.adapters.base import AdapterHealth
from clipsieve_xhs.api_runner import (
    COMMENT_FIELDS,
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
    assert (
        rec["note_url"]
        == f"https://www.xiaohongshu.com/explore/{N1}?xsec_token=TOK1&xsec_source=pc_search"
    )
    assert rec["source_keyword"] == "新加坡 上海 vlog" and rec["xsec_token"] == "TOK1"
    assert rec["last_modify_ts"] == NOW
    assert len(rec["creator_hash"]) == 64 and "u-1" not in json.dumps(rec)
    assert "nickname" not in rec and "user_id" not in json.dumps(rec)


def test_note_record_feeds_map_note_unchanged():
    rec = build_note_record(SEARCH["items"][0], FEED, "k", NOW)
    post = map_note(rec, [], "salt", "/tmp/raw.json", datetime.now(UTC))
    assert post.kind.value == "video"
    assert post.text.title == FEED["title"]
    assert post.url.endswith("xsec_token=TOK1&xsec_source=pc_search")


def test_comment_records_keep_only_the_allowed_fields():
    recs = build_comment_records(N1, COMMENTS, NOW)
    assert [r["comment_id"] for r in recs] == ["c1", "c2"]
    assert set(recs[0]) == set(COMMENT_FIELDS)
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
    client = FakeClient(
        detail={N1: FEED, N2: {**FEED, "note_id": N2, "type": "normal", "video": None}}
    )
    out = make_runner(client, clipsieve_xhs_note_kinds="all").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1, N2]
    assert client.calls[0][3] == "all"


def test_note_without_stream_is_skipped_not_fatal(tmp_path):
    out = make_runner(FakeClient(), clipsieve_xhs_note_kinds="video").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert any(N3 in e for e in out.errors)
    assert out.returncode == 0


def test_video_note_whose_detail_has_no_stream_is_skipped_with_an_error(tmp_path):
    no_stream = {**FEED, "note_id": N3, "video": {"media": {"stream": {"h264": []}}}}
    client = FakeClient(detail={N1: FEED, N3: no_stream})
    out = make_runner(client, clipsieve_xhs_note_kinds="video").search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert any("no video stream" in e and N3 in e for e in out.errors)
    assert out.returncode == 0
    assert ("detail", N3, "TOK3") in client.calls  # the detail was fetched, then rejected


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


def counting_provider(cookies="a1=A; web_session=W"):
    """A cookies provider that counts how often the runner re-reads the browser session."""
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return cookies

    return provider, calls


def test_login_expired_mid_page_returns_partial_and_stops(tmp_path):
    client = FakeClient(fail={N3: XhsLoginRequired("/feed: login expired (-104)", code=-104)})
    provider, calls = counting_provider()
    runner = make_runner(client, cookies=provider, clipsieve_xhs_note_kinds="video")
    out = runner.search("k", 1, tmp_path)
    assert [n["note_id"] for n in out.notes] == [N1]
    assert out.returncode == 1 and any("login expired" in e for e in out.errors)
    assert calls["n"] == 1
    # the next page must not reuse the dead session: the client is rebuilt from fresh cookies
    out2 = runner.search("k", 2, tmp_path)
    assert out2.returncode == 0 and out2.notes == []
    assert calls["n"] == 2


def test_rate_limit_keeps_the_client_across_pages(tmp_path):
    client = FakeClient(
        fail={N3: XhsRateLimited("/feed: rate limited after 3 attempts (300012)", code=300012)}
    )
    provider, calls = counting_provider()
    runner = make_runner(client, cookies=provider, clipsieve_xhs_note_kinds="video")
    assert runner.search("k", 1, tmp_path).returncode == 1
    assert runner.search("k", 2, tmp_path).returncode == 0
    assert calls["n"] == 1  # throttled, not logged out: the same session is reused


def test_missing_cookies_are_a_page_error(tmp_path):
    def provider():
        raise XhsLoginRequired("missing cookie(s) web_session")

    out = make_runner(FakeClient(), cookies=provider).search("k", 1, tmp_path)
    assert out.notes == [] and out.returncode == 1 and "web_session" in out.errors[0]


def test_rate_limit_during_details_stops_page(tmp_path):
    client = FakeClient(
        fail={N3: XhsRateLimited("/feed: rate limited after 3 attempts (300012)", code=300012)}
    )
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
