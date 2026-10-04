# contrib/adapter-xhs-mediacrawler/tests/test_adapter.py
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import respx
from clipsieve.adapters.base import MediaDownloadError
from clipsieve.config import Settings
from clipsieve.models import Query

from clipsieve_xhs.adapter import XhsMediaCrawlerAdapter
from clipsieve_xhs.runner import RunnerOutput
from clipsieve_xhs.settings import XhsSettings
from tests.conftest import FIX

Q = [Query(platform="xiaohongshu", query="新加坡人 上海 vlog", lang="zh")]
VIDEO_URL = "https://sns-video-bd.xhscdn.com/stream/1/110/258/01e7f1a2b3c4d5e6f7.mp4"
VIDEO_LOW_URL = "https://sns-video-bd.xhscdn.com/stream/1/110/259/01e7f1a2b3c4d5e6f7_low.mp4"
IMAGE_URLS = [f"https://sns-webpic-qc.xhscdn.com/202509/01/a{i}.jpg" for i in (1, 2, 3)]
BACKEND_CONTRACT = (
    Path(__file__).resolve().parents[3] / "backend" / "tests" / "adapters" / "contract.py"
)


def make_adapter(tmp_path, runner, cache_name="cache"):
    core = Settings(
        _env_file=None, clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt"
    )
    xhs = XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=tmp_path / "mc")
    return XhsMediaCrawlerAdapter(
        core, xhs, runner=runner, raw_dir=tmp_path / "raw", cache_dir=tmp_path / cache_name
    )


@pytest.fixture
def adapter(tmp_path, fake_runner):
    return make_adapter(tmp_path, fake_runner)


def test_search_yields_mapped_posts_and_writes_raw(adapter, fake_runner, tmp_path):
    posts = list(adapter.search(Q, limit=10))
    assert [p.id for p in posts] == [
        "xiaohongshu:66f1a2b3c4d5e6f700000001",
        "xiaohongshu:66f1a2b3c4d5e6f700000002",
        "xiaohongshu:66f1a2b3c4d5e6f700000003",
    ]
    assert fake_runner.calls[0][0] == "新加坡人 上海 vlog"
    raw = tmp_path / "raw" / "xiaohongshu__66f1a2b3c4d5e6f700000001.json"
    assert raw.exists()
    payload = json.loads(raw.read_text(encoding="utf-8"))
    assert payload["note"]["title"].startswith("新加坡人搬来上海")
    assert posts[0].raw_ref == str(raw)  # absolute, Addendum B1; the Runner relocates it
    # Author identifiers and the platform token are not stored (backend/AGENTS.md).
    assert "xsec_token" not in payload["note"]
    assert payload["comments"], "fixture note 1 has top-level comments"
    for c in payload["comments"]:
        assert not {"creator_hash", "nickname", "pictures"} & set(c)
        assert c["content"]


def test_search_writes_media_url_cache(adapter, tmp_path):
    list(adapter.search(Q, limit=10))
    cache = tmp_path / "cache"
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000001.media.json").read_text(encoding="utf-8")
    ) == {"urls": [VIDEO_URL, VIDEO_LOW_URL]}
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000002.media.json").read_text(encoding="utf-8")
    ) == {"urls": IMAGE_URLS}
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000003.media.json").read_text(encoding="utf-8")
    ) == {"urls": []}


def test_from_settings_uses_incoming_dir_and_data_dir_cache(tmp_path, monkeypatch):
    from clipsieve.adapters.base import incoming_dir

    monkeypatch.setenv("CLIPSIEVE_XHS_MEDIACRAWLER_DIR", str(tmp_path / "mc"))
    core = Settings(
        _env_file=None,
        clipsieve_data_dir=tmp_path / "data",
        clipsieve_creator_salt="salt",
        clipsieve_xhs_chrome_cdp_port=9444,
    )
    a = XhsMediaCrawlerAdapter.from_settings(core)
    assert a.platform == "xiaohongshu"
    assert a.raw_dir == incoming_dir(tmp_path / "data", "xiaohongshu")
    assert a.cache_dir == tmp_path / "data" / "adapter-cache" / "xiaohongshu"
    assert a.runner.cdp_port == 9444  # the core Settings owns the CDP port


def test_search_stops_at_limit_and_dedupes_across_queries(adapter):
    qs = Q + [Query(platform="xiaohongshu", query="上海 新加坡 留学生", lang="zh")]
    posts = list(adapter.search(qs, limit=4))
    assert len(posts) == 3  # 3 unique notes across both queries, fixture repeats
    posts2 = list(adapter.search(Q, limit=2))
    assert len(posts2) == 2


class PagedRunner:
    """Page 1 has note 1, page 2 adds note 2, page 3 repeats page 2 (nothing new)."""

    def __init__(self) -> None:
        self.pages: list[int] = []
        notes = json.loads((FIX / "notes.json").read_text(encoding="utf-8"))
        self.by_page = {1: notes[:1], 2: notes[:2], 3: notes[:2]}

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        self.pages.append(start_page)
        return RunnerOutput(notes=self.by_page.get(start_page, []), comments=[])

    def healthcheck(self):
        raise AssertionError("not used")


def test_search_pages_until_no_new_notes(tmp_path):
    runner = PagedRunner()
    posts = list(make_adapter(tmp_path, runner).search(Q, limit=10))
    assert [p.id[-1] for p in posts] == ["1", "2"]
    assert runner.pages == [1, 2, 3]  # page 3 added nothing, so paging stopped there


def test_search_pages_stop_at_limit(tmp_path):
    runner = PagedRunner()
    posts = list(make_adapter(tmp_path, runner).search(Q, limit=2))
    assert len(posts) == 2
    assert runner.pages == [1, 2]  # limit reached on page 2; page 3 never requested


def test_search_ignores_queries_for_other_platforms(adapter, fake_runner):
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], limit=5))
    assert posts == [] and fake_runner.calls == []


@respx.mock
def test_fetch_media_downloads_images_in_order(adapter, tmp_path):
    posts = {p.id: p for p in adapter.search(Q, limit=10)}
    post = posts["xiaohongshu:66f1a2b3c4d5e6f700000002"]
    for i, url in enumerate(IMAGE_URLS, start=1):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"\xff\xd8img" + bytes([i])))
    dest = tmp_path / "media" / "p2"
    out = adapter.fetch_media(post, dest)
    assert [m.local_path for m in out.media] == ["img_00.jpg", "img_01.jpg", "img_02.jpg"]  # B2
    assert (dest / "img_02.jpg").read_bytes().endswith(b"\x03")
    assert respx.calls[0].request.headers["referer"] == "https://www.xiaohongshu.com/"


@respx.mock
def test_fetch_media_video_uses_first_url(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, content=b"mp4data"))
    out = adapter.fetch_media(post, tmp_path / "v")
    assert out.media[0].local_path == "video.mp4"
    assert (tmp_path / "v" / "video.mp4").read_bytes() == b"mp4data"


@respx.mock
def test_fetch_media_is_idempotent(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    route = respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, content=b"mp4data"))
    adapter.fetch_media(post, tmp_path / "v")
    adapter.fetch_media(post, tmp_path / "v")
    assert route.call_count == 1


@respx.mock
def test_fetch_media_failure_raises_media_error(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    respx.get(VIDEO_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(MediaDownloadError):
        adapter.fetch_media(post, tmp_path / "v")
    assert not (tmp_path / "v" / "video.mp4").exists()  # no half-written file left behind


@respx.mock
def test_fetch_media_network_error_raises_media_error(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    respx.get(VIDEO_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(MediaDownloadError):
        adapter.fetch_media(post, tmp_path / "v")


@respx.mock
def test_fetch_media_works_in_a_second_adapter_instance(tmp_path, fake_runner):
    """Restart safety: the Runner relocates the raw file before fetch_media (B.10) and a new
    process has an empty memory cache, so only the on-disk media-URL cache can serve this."""
    first = make_adapter(tmp_path, fake_runner)
    post = next(p for p in first.search(Q, limit=10) if p.id.endswith("0002"))
    for f in (tmp_path / "raw").glob("*.json"):
        f.unlink()  # what the Runner's relocation does to incoming/
    second = make_adapter(tmp_path, fake_runner)
    assert second is not first
    for i, url in enumerate(IMAGE_URLS, start=1):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"img" + bytes([i])))
    out = second.fetch_media(post, tmp_path / "media" / "p2")
    assert [m.local_path for m in out.media] == ["img_00.jpg", "img_01.jpg", "img_02.jpg"]


def test_fetch_media_without_cache_entry_raises_media_error(tmp_path, fake_runner, adapter):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    elsewhere = make_adapter(tmp_path, fake_runner, cache_name="other-cache")
    with pytest.raises(MediaDownloadError):
        elsewhere.fetch_media(post, tmp_path / "v")
    assert not (tmp_path / "v").exists()  # nothing created when there is nothing to fetch


def test_healthcheck_delegates(adapter, fake_runner):
    assert adapter.healthcheck().ok is True
    fake_runner.healthy = False
    assert adapter.healthcheck().ok is False


@respx.mock
def test_passes_shared_adapter_contract(adapter, tmp_path):
    # `tests` is also this package's name, so load the backend contract by file path.
    spec = importlib.util.spec_from_file_location("backend_adapter_contract", BACKEND_CONTRACT)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    for url in (VIDEO_URL, *IMAGE_URLS):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"media-bytes"))
    posts = contract.run_adapter_contract(adapter, Q[0], tmp_path)  # ONE Query, no network
    assert posts
