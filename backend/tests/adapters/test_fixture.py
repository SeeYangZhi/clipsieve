import json
from pathlib import Path

import pytest

from clipsieve.adapters import registry
from clipsieve.adapters.base import incoming_dir
from clipsieve.adapters.fixture import FixtureAdapter
from clipsieve.adapters.local_import import LocalImportAdapter
from clipsieve.config import Settings
from clipsieve.models import Query
from clipsieve.store.paths import RunPaths, safe_post_filename
from tests.adapters.contract import relocate_raw, run_adapter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
QUERY = Query(platform="local", query="ignored by the fixture adapter", lang="en")


def test_fixture_adapter_passes_the_contract(tmp_path):
    adapter = FixtureAdapter(FIXTURES, tmp_path / "data")
    posts = run_adapter_contract(adapter, QUERY, tmp_path, limit=3)
    assert [p.id for p in posts] == ["local:fx-001", "local:fx-002", "local:fx-003"]


def test_search_yields_five_posts_ignoring_queries_and_honours_limit(tmp_path):
    adapter = FixtureAdapter(FIXTURES, tmp_path)
    posts = list(adapter.search([], 10))
    assert [p.id for p in posts] == [f"local:fx-00{i}" for i in range(1, 6)]
    assert len(list(adapter.search([QUERY], 2))) == 2
    for post in posts:
        raw = Path(post.raw_ref)
        assert raw == incoming_dir(tmp_path, "local") / f"{safe_post_filename(post.id)}.json"
        assert json.loads(raw.read_text(encoding="utf-8"))["source"] == "local_import"
        assert all(m.local_path is None for m in post.media)


def test_fetch_media_copies_media_and_sidecars(tmp_path):
    adapter = FixtureAdapter(FIXTURES, tmp_path)
    by_id = {p.id: p for p in adapter.search([], 5)}

    video = by_id["local:fx-001"]
    dest = tmp_path / "media" / "v"
    got = adapter.fetch_media(video, dest)
    assert [m.local_path for m in got.media] == ["video.mp4"]
    assert (dest / "video.mp4").is_file()
    assert (dest / "video.mp4.transcript.json").is_file()
    assert (dest / "frames" / "hook.jpg.ocr.json").is_file()

    note = by_id["local:fx-003"]
    dest = tmp_path / "media" / "n"
    got = adapter.fetch_media(note, dest)
    assert [m.local_path for m in got.media] == [f"img_{i:02d}.jpg" for i in range(4)]
    assert all((dest / f"img_{i:02d}.jpg.ocr.json").is_file() for i in range(4))


def test_fetch_media_leaves_missing_fixture_media_unset(tmp_path):
    fixtures = tmp_path / "fx"
    (fixtures / "posts").mkdir(parents=True)
    (fixtures / "raw").mkdir()
    src = FIXTURES / "posts" / "local__fx-001.json"
    (fixtures / "posts" / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    raw = FIXTURES / "raw" / "local__fx-001.json"
    (fixtures / "raw" / raw.name).write_text(raw.read_text(encoding="utf-8"), encoding="utf-8")
    adapter = FixtureAdapter(fixtures, tmp_path / "data")
    (post,) = list(adapter.search([], 5))
    got = adapter.fetch_media(post, tmp_path / "dest")
    assert [m.local_path for m in got.media] == [None]


def test_fetch_media_never_reads_raw_ref(tmp_path):
    adapter = FixtureAdapter(FIXTURES, tmp_path)
    post = next(iter(adapter.search([], 1)))
    paths = RunPaths(tmp_path, "run-x")
    paths.ensure()
    moved = relocate_raw(post, paths)
    got = adapter.fetch_media(moved, paths.media_dir(moved.id))
    assert got.raw_ref == moved.raw_ref == "raw/local__fx-001.json"


def test_healthcheck(tmp_path):
    assert FixtureAdapter(FIXTURES, tmp_path).healthcheck().ok
    missing = FixtureAdapter(tmp_path / "nope", tmp_path).healthcheck()
    assert not missing.ok and "nope" in missing.message


def test_from_settings_requires_fixture_dir(tmp_path):
    with pytest.raises(ValueError, match="CLIPSIEVE_FIXTURE_DIR"):
        FixtureAdapter.from_settings(Settings(_env_file=None, clipsieve_data_dir=tmp_path))
    adapter = FixtureAdapter.from_settings(
        Settings(_env_file=None, clipsieve_data_dir=tmp_path, clipsieve_fixture_dir=FIXTURES)
    )
    assert adapter.platform == "local"


def test_registry_serves_fixture_as_local_only_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "_iter_entry_points", list)
    plain = Settings(_env_file=None, clipsieve_data_dir=tmp_path, clipsieve_creator_salt="s")
    assert isinstance(registry.load_adapters(plain)["local"], LocalImportAdapter)

    fake = Settings(
        _env_file=None,
        clipsieve_data_dir=tmp_path,
        clipsieve_creator_salt="s",
        clipsieve_fixture_dir=FIXTURES,
    )
    adapters = registry.load_adapters(fake)
    assert isinstance(adapters["local"], FixtureAdapter)
    assert "youtube" in adapters


def test_registry_fixture_overrides_a_local_entry_point(tmp_path):
    """pyproject registers `local` as an entry point; fixture mode still wins."""
    fake = Settings(
        _env_file=None,
        clipsieve_data_dir=tmp_path,
        clipsieve_creator_salt="s",
        clipsieve_fixture_dir=FIXTURES,
    )
    assert isinstance(registry.load_adapters(fake)["local"], FixtureAdapter)
