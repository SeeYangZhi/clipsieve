import json
from pathlib import Path

import pytest

from clipsieve.adapters.base import AdapterHealth
from clipsieve_xhs.runner import RunnerOutput

FIX = Path(__file__).parent / "fixtures" / "mediacrawler-output"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from clipsieve_xhs.settings import get_xhs_settings

    get_xhs_settings.cache_clear()
    yield
    get_xhs_settings.cache_clear()


class FakeRunner:
    """Replays the fixture output for every keyword and page; records calls."""

    def __init__(self, healthy: bool = True) -> None:
        self.calls: list[tuple[str, int, Path]] = []
        self.healthy = healthy

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        self.calls.append((keyword, start_page, workdir))
        notes = json.loads((FIX / "notes.json").read_text(encoding="utf-8"))
        comments = json.loads((FIX / "comments.json").read_text(encoding="utf-8"))
        return RunnerOutput(notes=notes, comments=comments, errors=[], returncode=0, stderr_tail="")

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(self.healthy, "fake")


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()
