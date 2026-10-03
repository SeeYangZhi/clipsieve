from collections.abc import Iterator
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from clipsieve.adapters import registry
from clipsieve.adapters.base import AdapterHealth
from clipsieve.config import Settings
from clipsieve.models import Post, Query


class DummyAdapter:
    platform = "dummy"

    @classmethod
    def from_settings(cls, settings: Settings) -> "DummyAdapter":
        return cls()

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        return iter(())

    def fetch_media(self, post: Post, dest: Path) -> Post:
        return post

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(ok=True, message="ok")


class BrokenAdapter:
    platform = "broken"

    @classmethod
    def from_settings(cls, settings: Settings):
        raise RuntimeError("cannot construct")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path, clipsieve_creator_salt="s")


def test_builtins_are_loaded_without_entry_points(monkeypatch, settings):
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [])
    adapters = registry.load_adapters(settings)
    assert set(adapters) >= {"local", "youtube"}
    assert adapters["local"].platform == "local"


def test_entry_point_adapter_is_discovered(monkeypatch, settings):
    ep = EntryPoint(
        name="dummy", value=f"{__name__}:DummyAdapter", group=registry.ENTRY_POINT_GROUP
    )
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [ep])
    adapters = registry.load_adapters(settings)
    assert "dummy" in adapters
    assert adapters["dummy"].healthcheck().ok


def test_broken_entry_point_is_skipped_not_fatal(monkeypatch, settings):
    ep = EntryPoint(
        name="broken", value=f"{__name__}:BrokenAdapter", group=registry.ENTRY_POINT_GROUP
    )
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [ep])
    adapters = registry.load_adapters(settings)
    assert "broken" not in adapters
    assert "local" in adapters
