import csv
import json
from pathlib import Path

import pytest

from clipsieve.adapters.local_import import LocalImportAdapter
from clipsieve.config import Settings
from clipsieve.models import Query
from tests.adapters.contract import run_adapter_contract

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")


@pytest.fixture
def media_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "clips"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"\x00" * 16)
    (folder / "b.mp4").write_bytes(b"\x00" * 16)
    (folder / "c.jpg").write_bytes(PNG_1X1)
    (folder / "notes.txt").write_text("ignored")
    return folder


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "posts.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "title", "caption", "views", "likes", "comments"])
        w.writerow(["https://example.com/v/1", "First", "plain caption", "100", "10", "3"])
        w.writerow(
            [
                "https://example.com/v/2",
                "新加坡人在上海",
                "第一天到上海，房租好贵 😅, 真的",
                "2000",
                "150",
                "12",
            ]
        )
    return p


def test_folder_import_passes_contract(settings, media_folder, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = run_adapter_contract(
        adapter, Query(platform="local", query=str(media_folder), lang="en"), tmp_path
    )
    kinds = sorted(p.kind for p in posts)
    assert kinds == ["image_note", "video", "video"]
    assert all(p.id.startswith("local:") for p in posts)


def test_folder_import_respects_limit(settings, media_folder):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = list(
        adapter.search([Query(platform="local", query=str(media_folder), lang="en")], limit=1)
    )
    assert len(posts) == 1


def test_csv_chinese_caption_roundtrip(settings, csv_file):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = list(
        adapter.search([Query(platform="local", query=str(csv_file), lang="zh")], limit=10)
    )
    assert len(posts) == 2
    zh = next(p for p in posts if p.text.title == "新加坡人在上海")
    assert zh.text.caption == "第一天到上海，房租好贵 😅, 真的"
    assert zh.metrics.views == 2000 and zh.metrics.likes == 150 and zh.metrics.comments == 12
    assert zh.lang == "zh"
    raw = json.loads(Path(zh.raw_ref).read_text(encoding="utf-8"))
    assert raw["caption"] == "第一天到上海，房租好贵 😅, 真的"


def test_csv_rows_have_no_media_and_fetch_media_is_noop(settings, csv_file, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(adapter.search([Query(platform="local", query=str(csv_file), lang="en")], limit=1))
    assert post.media == []
    dest = tmp_path / "m"
    dest.mkdir()
    assert adapter.fetch_media(post, dest).media == []


def test_fetch_media_idempotent(settings, media_folder, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(
        p
        for p in adapter.search([Query(platform="local", query=str(media_folder), lang="en")], 10)
        if p.kind == "video"
    )
    dest = tmp_path / "m"
    dest.mkdir()
    first = adapter.fetch_media(post, dest)
    mtime = (dest / first.media[0].local_path).stat().st_mtime_ns
    second = adapter.fetch_media(first, dest)
    assert second.media[0].local_path == first.media[0].local_path == "video.mp4"
    assert (dest / "video.mp4").stat().st_mtime_ns == mtime


def test_healthcheck_ok(settings):
    assert LocalImportAdapter.from_settings(settings).healthcheck().ok


def test_missing_source_yields_nothing(settings, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    assert (
        list(adapter.search([Query(platform="local", query=str(tmp_path / "nope"), lang="en")], 5))
        == []
    )
