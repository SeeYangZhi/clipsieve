import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from clipsieve.api.context import build_context
from clipsieve.app import create_app
from clipsieve.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fake_settings(data_dir: Path, **overrides) -> Settings:
    """Fake mode from kwargs only: never a real .env."""
    values = {
        "clipsieve_data_dir": data_dir,
        "clipsieve_explain_backend": "fake",
        "clipsieve_fixture_dir": FIXTURES,
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.fixture
def ctx(tmp_path):
    return build_context(fake_settings(tmp_path))


@pytest.fixture
async def client(ctx):
    app = create_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    # Let background planning and pipeline tasks finish inside this test's event loop.
    pending = [t for t in ctx.tasks.values() if not t.done()]
    if pending:
        _, still = await asyncio.wait(pending, timeout=10)
        for t in still:
            t.cancel()
        await asyncio.gather(*still, return_exceptions=True)


async def wait_for_stage(client, run_id, stage, timeout_s=10.0):
    for _ in range(int(timeout_s / 0.05)):
        r = await client.get(f"/api/runs/{run_id}")
        if r.json()["run"]["stage"] == stage:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {stage}")


async def wait_for_plan(client, run_id, timeout_s=10.0):
    for _ in range(int(timeout_s / 0.05)):
        data = (await client.get(f"/api/runs/{run_id}")).json()
        if data["plan"] is not None:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} never produced a plan")
