import csv
import json
import shutil
from pathlib import Path

import pytest

from clipsieve.adapters.base import hash_creator
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


def test_csv_creator_column_gives_each_row_its_creator(settings, tmp_path):
    src = tmp_path / "creators.csv"
    with src.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "title", "creator"])
        w.writerow(["https://example.com/v/a", "A", "小红"])
        w.writerow(["https://example.com/v/b", "B", "bob"])
        w.writerow(["https://example.com/v/c", "C", ""])
    adapter = LocalImportAdapter.from_settings(settings)
    query = Query(platform="local", query=str(src), lang="en")
    posts = {p.text.title: p for p in adapter.search([query], limit=10)}
    assert posts["A"].creator_hash == hash_creator("小红", "salt")
    assert posts["B"].creator_hash == hash_creator("bob", "salt")
    assert posts["A"].creator_hash != posts["B"].creator_hash
    assert posts["A"].creator_display == "小红"
    # An empty creator cell falls back to the CSV-path creator.
    assert posts["C"].creator_hash == hash_creator(str(src.resolve()), "salt")
    assert posts["C"].creator_display == "creators"


def test_csv_without_creator_column_uses_path_creator(settings, csv_file):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = list(adapter.search([Query(platform="local", query=str(csv_file), lang="en")], 10))
    expected = hash_creator(str(csv_file.resolve()), "salt")
    assert [p.creator_hash for p in posts] == [expected, expected]
    assert {p.creator_display for p in posts} == {"posts"}


def test_csv_rows_have_no_media_and_fetch_media_is_noop(settings, csv_file, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(adapter.search([Query(platform="local", query=str(csv_file), lang="en")], limit=1))
    assert post.media == []
    dest = tmp_path / "m"
    dest.mkdir()
    assert adapter.fetch_media(post, dest).media == []


def test_fetch_media_idempotent(settings, media_folder, tmp_path, monkeypatch):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(
        p
        for p in adapter.search([Query(platform="local", query=str(media_folder), lang="en")], 10)
        if p.kind == "video"
    )
    dest = tmp_path / "m"
    dest.mkdir()
    # copy2 preserves the source mtime, so mtime alone cannot reveal a second copy.
    copies: list[object] = []
    real_copy2 = shutil.copy2

    def counting_copy2(src, dst, *args, **kwargs):
        copies.append(dst)
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", counting_copy2)
    first = adapter.fetch_media(post, dest)
    before = (dest / first.media[0].local_path).stat()
    second = adapter.fetch_media(first, dest)
    after = (dest / "video.mp4").stat()
    assert second.media[0].local_path == first.media[0].local_path == "video.mp4"
    assert len(copies) == 1, "second fetch_media must not copy again"
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns


def test_healthcheck_ok(settings):
    assert LocalImportAdapter.from_settings(settings).healthcheck().ok


def test_missing_source_yields_nothing(settings, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    assert (
        list(adapter.search([Query(platform="local", query=str(tmp_path / "nope"), lang="en")], 5))
        == []
    )
