from __future__ import annotations

from importlib import import_module
from importlib.metadata import EntryPoint, entry_points

from clipsieve.adapters.base import Adapter
from clipsieve.config import Settings
from clipsieve.logging import get_logger

log = get_logger(__name__)

ENTRY_POINT_GROUP = "clipsieve.adapters"

BUILTIN_ADAPTERS: dict[str, str] = {
    "local": "clipsieve.adapters.local_import:LocalImportAdapter",
    "youtube": "clipsieve.adapters.youtube:YouTubeAdapter",
}


def _iter_entry_points() -> list[EntryPoint]:
    return list(entry_points(group=ENTRY_POINT_GROUP))


def _load_class(value: str):
    module_name, _, attr = value.partition(":")
    return getattr(import_module(module_name), attr)


def _construct(cls, settings: Settings, source: str) -> Adapter | None:
    try:
        adapter = cls.from_settings(settings)
    except Exception as exc:  # noqa: BLE001 - one bad plugin must not take down the app
        log.warning("adapter_load_failed", source=source, error=str(exc))
        return None
    if not isinstance(adapter, Adapter):
        log.warning("adapter_not_protocol", source=source)
        return None
    return adapter


def load_adapters(settings: Settings) -> dict[str, Adapter]:
    """Built-in adapters plus any registered under the entry point group. Key is platform."""
    adapters: dict[str, Adapter] = {}

    for ep in _iter_entry_points():
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            log.warning("adapter_entry_point_import_failed", name=ep.name, error=str(exc))
            continue
        adapter = _construct(cls, settings, source=f"entry_point:{ep.name}")
        if adapter is not None:
            adapters[adapter.platform] = adapter

    for platform, value in BUILTIN_ADAPTERS.items():
        if platform in adapters:
            continue
        try:
            cls = _load_class(value)
        except Exception as exc:  # noqa: BLE001
            log.warning("adapter_builtin_import_failed", platform=platform, error=str(exc))
            continue
        adapter = _construct(cls, settings, source=f"builtin:{platform}")
        if adapter is not None:
            adapters[adapter.platform] = adapter

    if settings.clipsieve_fixture_dir is not None:
        # Fake mode: the fixture posts replace folder/CSV import as `local`, whatever is registered.
        from clipsieve.adapters.fixture import FixtureAdapter

        adapter = _construct(FixtureAdapter, settings, source="fixture")
        if adapter is not None:
            adapters[adapter.platform] = adapter

    log.info("adapters_loaded", platforms=sorted(adapters))
    return adapters
