"""`get_context()` builds the process context exactly once, even under concurrent first use."""

import asyncio
import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient

from clipsieve.api import context as context_module
from clipsieve.app import create_app
from tests.api.conftest import fake_settings


@pytest.fixture
def counted_builds(tmp_path, monkeypatch):
    """No installed context, fake settings on a fresh data dir, and a slow, counted build."""
    monkeypatch.setattr(context_module, "_CONTEXT", None)
    monkeypatch.setattr(context_module, "get_settings", lambda: fake_settings(tmp_path))
    real_build = context_module.build_context
    builds: list[object] = []

    def slow_build(settings):
        builds.append(settings)
        time.sleep(0.05)  # widen the check-then-build window
        return real_build(settings)

    monkeypatch.setattr(context_module, "build_context", slow_build)
    return builds


async def test_concurrent_first_requests_build_one_context(counted_builds, tmp_path):
    app = create_app()
    # The home page's first load: several routes at once. `/health` is asked afterwards: in this
    # in-process transport its handler would build on the event loop before the dependency
    # threads start and hide the race.
    paths = ["/api/runs", "/api/adapters", "/api/rubrics"] * 2
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        responses = await asyncio.gather(*(c.get(p) for p in paths))
        responses.append(await c.get("/api/health"))
    assert [r.status_code for r in responses] == [200] * (len(paths) + 1)
    assert len(counted_builds) == 1
    salt = (tmp_path / "creator_salt").read_text(encoding="utf-8").strip()
    assert context_module.get_context().settings.clipsieve_creator_salt == salt  # A.12


def test_get_context_from_threads_builds_once(counted_builds):
    results: list[object] = []
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def call() -> None:
        start.wait()
        try:
            results.append(context_module.get_context())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(counted_builds) == 1
    assert len(results) == 4 and all(r is results[0] for r in results)
