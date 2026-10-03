import json
import shutil
import sys
import types
from pathlib import Path

import httpx
import pytest
from structlog.testing import capture_logs
from yt_dlp.utils import DownloadError

from clipsieve.adapters.youtube import MediaDownloadError, YouTubeAdapter, map_info_to_post
from clipsieve.adapters.ytdlp_client import FakeYtDlpClient, RealYtDlpClient
from clipsieve.config import Settings
from clipsieve.models import Query
from tests.adapters.contract import run_adapter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")


@pytest.fixture
def adapter(settings) -> YouTubeAdapter:
    return YouTubeAdapter(
        client=FakeYtDlpClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="salt"
    )


def test_passes_contract(adapter, tmp_path):
    posts = run_adapter_contract(
        adapter,
        Query(platform="youtube", query="chrome extension no code", lang="en"),
        tmp_path,
        limit=5,
    )
    assert {p.id for p in posts} == {"youtube:aB3dEfGhIjK", "youtube:zH1sH4nGh41"}


def test_shorts_filter_drops_long_videos(adapter):
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], limit=10))
    assert "youtube:LoNgV1dEo00" not in {p.id for p in posts}


def test_mapping_fields():
    info = json.loads((FIXTURES / "aB3dEfGhIjK.json").read_text(encoding="utf-8"))
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert post.url == "https://www.youtube.com/shorts/aB3dEfGhIjK"
    assert post.kind == "video"
    assert post.text.title.startswith("I built")
    assert sorted(post.text.hashtags) == ["buildinpublic", "chromeextension", "nocode"]
    assert (
        post.metrics.views == 182344
        and post.metrics.likes == 15321
        and post.metrics.comments == 412
    )
    assert post.media[0].duration_s == 48 and post.media[0].width == 1080
    assert post.posted_at is not None and post.posted_at.year == 2026 and post.posted_at.month == 9
    assert post.lang == "en"
    assert post.creator_display == "No Code Nat"
    assert "UC_builder_001" not in post.creator_hash


def test_chinese_mapping_preserves_text():
    info = json.loads((FIXTURES / "zH1sH4nGh41.json").read_text(encoding="utf-8"))
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert post.text.title == "新加坡人搬到上海的第一天 | 房租篇"
    assert post.comments[0].text == "同是新加坡人，太真实了"
    assert post.lang == "zh-Hans"


def test_comments_capped_most_liked():
    info = json.loads((FIXTURES / "aB3dEfGhIjK.json").read_text(encoding="utf-8"))
    info["comments"] = [{"id": str(i), "text": f"c{i}", "like_count": i} for i in range(120)]
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert len(post.comments) == 50
    assert post.comments[0].likes == 119 and post.comments[-1].likes == 70


def test_fetch_media_writes_video_and_transcript_sidecar(adapter, tmp_path):
    post = next(
        p
        for p in adapter.search([Query(platform="youtube", query="x", lang="en")], 10)
        if p.id.endswith("aB3dEfGhIjK")
    )
    dest = tmp_path / "m"
    got = adapter.fetch_media(post, dest)
    assert got.media[0].local_path == "video.mp4"
    sidecar = json.loads((dest / "video.mp4.transcript.json").read_text(encoding="utf-8"))
    assert sidecar["lang"] == "en"
    assert sidecar["segments"][0]["text"].startswith("stop scrolling")


def test_fetch_media_is_idempotent_and_does_not_redownload(adapter, tmp_path):
    post = next(adapter.search([Query(platform="youtube", query="x", lang="en")], 1))
    dest = tmp_path / "m"
    adapter.fetch_media(post, dest)
    calls = adapter._client.download_calls
    adapter.fetch_media(post, dest)
    assert adapter._client.download_calls == calls


def test_data_api_search_is_used_when_key_present(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        assert request.url.params["q"] == "shanghai vlog"
        assert request.url.params["videoDuration"] == "short"
        return httpx.Response(
            200,
            json={
                "items": [{"id": {"videoId": "zH1sH4nGh41"}}, {"id": {"videoId": "aB3dEfGhIjK"}}]
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(FIXTURES),
        data_dir=settings.clipsieve_data_dir,
        salt="s",
        api_key="k",
        http=http,
    )
    posts = list(adapter.search([Query(platform="youtube", query="shanghai vlog", lang="en")], 5))
    assert [p.id for p in posts] == ["youtube:zH1sH4nGh41", "youtube:aB3dEfGhIjK"]


def test_healthcheck_reports_ytdlp_import(adapter):
    health = adapter.healthcheck()
    assert isinstance(health.ok, bool) and "yt-dlp" in health.message


def test_from_settings_builds_real_client(settings):
    adapter = YouTubeAdapter.from_settings(settings)
    assert adapter.platform == "youtube"


# -- beyond the brief: Task 4 review notes and the privacy rules ---------------------------------


class WebmClient(FakeYtDlpClient):
    """Format fallback: yt-dlp may hand back a .webm instead of the merged .mp4."""

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict:
        meta = super().download(url, dest, subtitle_langs)
        (dest / "video.mp4").rename(dest / "video.webm")
        meta["requested_downloads"] = [{"filepath": str(dest / "video.webm")}]
        return meta


class OversizeClient(FakeYtDlpClient):
    """yt-dlp skips a file over max_filesize without raising, so no media file appears."""

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict:
        meta = super().download(url, dest, subtitle_langs)
        (dest / "video.mp4").unlink()
        return meta


class CommentAuthorClient(FakeYtDlpClient):
    """Real yt-dlp comment dicts carry author fields."""

    def info(self, url: str) -> dict:
        meta = super().info(url)
        meta["comments"] = [
            {
                **c,
                "author": "Some Viewer",
                "author_id": "UC_viewer_9",
                "author_url": "https://www.youtube.com/channel/UC_viewer_9",
                "author_thumbnail": "https://example.invalid/avatar.jpg",
                "author_is_uploader": False,
            }
            for c in meta["comments"]
        ]
        return meta


@pytest.fixture
def fixture_copy(tmp_path: Path) -> Path:
    d = tmp_path / "fx"
    shutil.copytree(FIXTURES, d)
    return d


def _first(adapter: YouTubeAdapter, suffix: str):
    q = Query(platform="youtube", query="x", lang="en")
    return next(p for p in adapter.search([q], 10) if p.id.endswith(suffix))


def test_fetch_media_uses_the_path_ytdlp_reports(settings, tmp_path):
    client = WebmClient(FIXTURES)
    adapter = YouTubeAdapter(client=client, data_dir=settings.clipsieve_data_dir, salt="salt")
    post = _first(adapter, "aB3dEfGhIjK")
    dest = tmp_path / "m"
    got = adapter.fetch_media(post, dest)
    assert got.media[0].local_path == "video.webm"
    assert (dest / "video.webm.transcript.json").is_file()
    again = adapter.fetch_media(got, dest)
    assert client.download_calls == 1
    assert again.media[0].local_path == "video.webm"


def test_fetch_media_raises_when_no_file_was_written(settings, tmp_path):
    adapter = YouTubeAdapter(
        client=OversizeClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "aB3dEfGhIjK")
    with pytest.raises(MediaDownloadError):
        adapter.fetch_media(post, tmp_path / "m")


def test_fetch_media_skips_captions_when_vtt_is_malformed(settings, fixture_copy, tmp_path):
    (fixture_copy / "aB3dEfGhIjK.en.vtt").write_text(
        "WEBVTT\n\nnot-a-time --> 00:00:01.000\nhello\n", encoding="utf-8"
    )
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(fixture_copy), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "aB3dEfGhIjK")
    dest = tmp_path / "m"
    with capture_logs() as logs:
        got = adapter.fetch_media(post, dest)
    assert got.media[0].local_path == "video.mp4"
    assert not (dest / "video.mp4.transcript.json").exists()
    assert any(e["event"] == "youtube_captions_unparseable" for e in logs)


def test_fetch_media_prefers_captions_in_the_post_language(settings, fixture_copy, tmp_path):
    # An auto-translated English track sits next to the original Chinese one.
    shutil.copy(fixture_copy / "aB3dEfGhIjK.en.vtt", fixture_copy / "zH1sH4nGh41.en.vtt")
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(fixture_copy), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "zH1sH4nGh41")
    dest = tmp_path / "m"
    adapter.fetch_media(post, dest)
    sidecar = json.loads((dest / "video.mp4.transcript.json").read_text(encoding="utf-8"))
    assert sidecar["lang"] == "zh-Hans"
    assert sidecar["segments"][0]["text"] == "刚到上海的第一天 房租真的好贵"


def test_raw_payload_has_no_comment_author_identifiers(settings):
    adapter = YouTubeAdapter(
        client=CommentAuthorClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "aB3dEfGhIjK")
    raw_text = Path(post.raw_ref).read_text(encoding="utf-8")
    assert "UC_viewer_9" not in raw_text and "Some Viewer" not in raw_text
    raw = json.loads(raw_text)
    assert [c["text"] for c in raw["comments"]][0] == "this is the hook I needed"
    assert not any(k.startswith("author") for c in raw["comments"] for k in c)
    assert all(set(c.model_dump(exclude_none=True)) <= {"text", "likes"} for c in post.comments)


def test_data_api_failure_falls_back_to_ytdlp_without_logging_the_key(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "quotaExceeded"}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(FIXTURES),
        data_dir=settings.clipsieve_data_dir,
        salt="s",
        api_key="SECRET-KEY",
        http=http,
    )
    with capture_logs() as logs:
        posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], 5))
    assert [p.id for p in posts] == ["youtube:aB3dEfGhIjK", "youtube:zH1sH4nGh41"]
    assert any(e["event"] == "youtube_data_api_failed" for e in logs)
    assert "SECRET-KEY" not in repr(logs)


def test_data_api_key_travels_in_a_header_not_the_url(settings):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [{"id": {"videoId": "aB3dEfGhIjK"}}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(FIXTURES),
        data_dir=settings.clipsieve_data_dir,
        salt="s",
        api_key="SECRET-KEY",
        http=http,
    )
    list(adapter.search([Query(platform="youtube", query="x", lang="zh-Hans")], 1))
    [request] = seen
    assert request.headers["x-goog-api-key"] == "SECRET-KEY"
    assert "SECRET-KEY" not in str(request.url)
    assert request.url.params["relevanceLanguage"] == "zh-Hans"


# -- fix round 1: live streams, shared MediaDownloadError ----------------------------------------


class InfoPatchClient(FakeYtDlpClient):
    """Applies `patch` to the recorded info of aB3dEfGhIjK."""

    def __init__(self, fixture_dir: Path, patch: dict, drop: tuple[str, ...] = ()) -> None:
        super().__init__(fixture_dir)
        self._patch = patch
        self._drop = drop

    def info(self, url: str) -> dict:
        meta = super().info(url)
        if meta["id"] == "aB3dEfGhIjK":
            meta = {k: v for k, v in meta.items() if k not in self._drop} | self._patch
        return meta


class FailingDownloadClient(FakeYtDlpClient):
    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict:
        self.download_calls += 1
        raise RuntimeError("ERROR: [youtube] aB3dEfGhIjK: Video unavailable")


@pytest.mark.parametrize(
    ("patch", "drop"),
    [
        ({"is_live": True}, ("duration",)),
        ({"live_status": "is_live"}, ("duration",)),
        ({"live_status": "is_upcoming"}, ("duration",)),
        ({"live_status": "post_live"}, ()),
        ({}, ("duration",)),  # a finished video always reports a duration
    ],
    ids=["is_live", "live_status_is_live", "is_upcoming", "post_live", "no_duration"],
)
def test_live_and_durationless_videos_are_not_shorts(settings, patch, drop):
    client = InfoPatchClient(FIXTURES, patch, drop)
    adapter = YouTubeAdapter(client=client, data_dir=settings.clipsieve_data_dir, salt="salt")
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], 10))
    assert [p.id for p in posts] == ["youtube:zH1sH4nGh41"]


def test_flat_search_entry_without_duration_still_reaches_info(settings, fixture_copy):
    entries = json.loads((fixture_copy / "search.json").read_text(encoding="utf-8"))
    del entries[0]["duration"]
    (fixture_copy / "search.json").write_text(json.dumps(entries), encoding="utf-8")
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(fixture_copy), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], 10))
    assert "youtube:aB3dEfGhIjK" in {p.id for p in posts}


def test_media_download_error_is_the_shared_base_class():
    from clipsieve.adapters import base

    assert MediaDownloadError is base.MediaDownloadError


def test_fetch_media_wraps_client_download_failures(settings, tmp_path):
    adapter = YouTubeAdapter(
        client=FailingDownloadClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "aB3dEfGhIjK")
    with pytest.raises(MediaDownloadError) as info:
        adapter.fetch_media(post, tmp_path / "m")
    assert isinstance(info.value.__cause__, RuntimeError)
    assert "Video unavailable" in str(info.value)
    assert adapter._client.download_calls == 1, "only a subtitle failure is retried"


# -- final review: caption languages and the subtitle-failure fallback ---------------------------


class RecordingClient(FakeYtDlpClient):
    """Records the subtitle languages of every download call."""

    def __init__(self, fixture_dir: Path) -> None:
        super().__init__(fixture_dir)
        self.subtitle_requests: list[list[str]] = []

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict:
        self.subtitle_requests.append(list(subtitle_langs))
        return super().download(url, dest, subtitle_langs)


class SubtitleFailsClient(RecordingClient):
    """yt-dlp raises DownloadError on a failed caption track (429 on auto-translated ones)."""

    def __init__(self, fixture_dir: Path, failures: int = 1) -> None:
        super().__init__(fixture_dir)
        self._failures = failures

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict:
        if self._failures > 0:
            self._failures -= 1
            self.subtitle_requests.append(list(subtitle_langs))
            self.download_calls += 1
            raise DownloadError(
                "ERROR: Unable to download video subtitles for 'zh-Hans-orig': "
                "HTTP Error 429: Too Many Requests"
            )
        return super().download(url, dest, subtitle_langs)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("zh-Hans", ["zh-Hans", "zh-Hans-orig", "en"]),
        ("en", ["en", "en-orig"]),
        (None, ["en"]),
    ],
)
def test_download_requests_only_the_post_language_its_orig_track_and_en(
    settings, tmp_path, lang, expected
):
    client = RecordingClient(FIXTURES)
    adapter = YouTubeAdapter(client=client, data_dir=settings.clipsieve_data_dir, salt="salt")
    post = _first(adapter, "zH1sH4nGh41").model_copy(update={"lang": lang})
    adapter.fetch_media(post, tmp_path / "m")
    assert client.subtitle_requests == [expected]


def test_subtitle_failure_retries_once_without_subtitles(settings, tmp_path):
    client = SubtitleFailsClient(FIXTURES)
    adapter = YouTubeAdapter(client=client, data_dir=settings.clipsieve_data_dir, salt="salt")
    post = _first(adapter, "aB3dEfGhIjK")
    dest = tmp_path / "m"
    with capture_logs() as logs:
        got = adapter.fetch_media(post, dest)
    assert got.media[0].local_path == "video.mp4"
    assert (dest / "video.mp4").is_file()
    # Whisper covers the transcript instead.
    assert not (dest / "video.mp4.transcript.json").exists()
    assert client.download_calls == 2
    assert client.subtitle_requests == [["en", "en-orig"], []]
    assert any(e["event"] == "youtube.subtitles_skipped" for e in logs)


def test_subtitle_failure_on_the_retry_raises_media_error(settings, tmp_path):
    client = SubtitleFailsClient(FIXTURES, failures=2)
    adapter = YouTubeAdapter(client=client, data_dir=settings.clipsieve_data_dir, salt="salt")
    post = _first(adapter, "aB3dEfGhIjK")
    with pytest.raises(MediaDownloadError):
        adapter.fetch_media(post, tmp_path / "m")
    assert client.download_calls == 2


def test_orig_caption_track_writes_the_plain_language(settings, fixture_copy, tmp_path):
    (fixture_copy / "aB3dEfGhIjK.en.vtt").rename(fixture_copy / "aB3dEfGhIjK.en-orig.vtt")
    adapter = YouTubeAdapter(
        client=FakeYtDlpClient(fixture_copy), data_dir=settings.clipsieve_data_dir, salt="salt"
    )
    post = _first(adapter, "aB3dEfGhIjK")
    dest = tmp_path / "m"
    adapter.fetch_media(post, dest)
    sidecar = json.loads((dest / "video.mp4.transcript.json").read_text(encoding="utf-8"))
    assert sidecar["lang"] == "en"


@pytest.mark.parametrize(
    ("langs", "writes"), [(["en", "en-orig"], True), ([], False)], ids=["with", "without"]
)
def test_real_client_disables_subtitles_for_an_empty_language_list(
    tmp_path, monkeypatch, langs, writes
):
    seen: list[dict] = []
    fake = types.ModuleType("yt_dlp")

    class YoutubeDL:
        def __init__(self, opts: dict) -> None:
            seen.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict:
            return {"id": "x"}

    fake.YoutubeDL = YoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    RealYtDlpClient().download("https://www.youtube.com/watch?v=x", tmp_path / "m", langs)
    [opts] = seen
    assert opts["writesubtitles"] is writes and opts["writeautomaticsub"] is writes
    assert opts.get("subtitleslangs", []) == langs
