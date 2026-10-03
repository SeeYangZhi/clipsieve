import asyncio

from clipsieve.models import Brief, Stage
from tests.api.conftest import fake_settings, wait_for_plan, wait_for_stage

BODY = {
    "brief": "新加坡人搬到上海的 vlog，分析开头和风格",
    "platforms": ["local"],
    "quantities": {"local": 5},
    "rubric_pack": "creator-hooks-v1",
}


def _create(ctx, text: str):
    """A run straight in the repository: no Runner, no planning task."""
    brief = Brief(text=text, topic="", audience="", persona="")
    return ctx.repo.create_run(brief, ["local"], {"local": 1}, "creator-hooks-v1")


async def test_create_run_plans_in_background(client):
    r = await client.post("/api/runs", json=BODY)
    assert r.status_code == 201
    run = r.json()
    assert run["id"].startswith("run_") and run["stage"] == "planning"
    data = await wait_for_plan(client, run["id"])
    assert data["plan"]["rubric_pack"] == "creator-hooks-v1"
    assert data["run"]["brief"]["text"] == BODY["brief"]


async def test_list_runs_newest_first(client):
    a = (await client.post("/api/runs", json=BODY)).json()["id"]
    b = (await client.post("/api/runs", json=BODY)).json()["id"]
    ids = [r["id"] for r in (await client.get("/api/runs")).json()]
    assert ids.index(b) < ids.index(a)


async def test_unknown_run_is_404(client):
    r = await client.get("/api/runs/run_nope")
    assert r.status_code == 404 and isinstance(r.json()["detail"], str)
    assert (await client.get("/api/runs/run_nope/report")).status_code == 404


async def test_full_flow_approve_posts_report_reselect(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    plan = (await wait_for_plan(client, run_id))["plan"]
    plan["queries"][0]["query"] = "edited"
    r = await client.put(f"/api/runs/{run_id}/plan", json=plan)
    assert r.status_code == 200 and r.json()["queries"][0]["query"] == "edited"
    r = await client.post(f"/api/runs/{run_id}/approve")
    assert r.status_code == 200 and r.json()["stage"] == "collecting"
    await wait_for_stage(client, run_id, "done")

    page = (await client.get(f"/api/runs/{run_id}/posts?offset=0&limit=3")).json()
    assert page["total"] == 5 and len(page["items"]) == 3
    items = (await client.get(f"/api/runs/{run_id}/posts?limit=100")).json()["items"]
    states = {i["post"]["id"]: i["state"] for i in items}
    allowed = {"collected", "dropped_pass_one", "judged", "shortlisted", "review", "judge_failed"}
    assert set(states.values()) <= allowed
    assert list(states.values()).count("dropped_pass_one") == 3
    shortlisted = [pid for pid, s in states.items() if s == "shortlisted"]
    item = next(i for i in items if i["post"]["id"] == shortlisted[0])
    assert "pass_two" in item["judge"] and item["composite"] is not None
    dropped = next(i for i in items if i["state"] == "dropped_pass_one")
    assert "composite" not in dropped and "pass_two" not in dropped["judge"]  # absent, not null

    report = (await client.get(f"/api/runs/{run_id}/report")).json()
    assert report["run_id"] == run_id
    assert {c["post_id"] for c in report["clips"]} == set(shortlisted)

    r = await client.post(f"/api/runs/{run_id}/reselect", json={"weights": {"hook_strength": 1.0}})
    sel = r.json()
    assert r.status_code == 200
    assert set(sel["shortlist"]) | set(sel["review"]) <= set(states)


async def test_approve_twice_is_409(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    assert (await client.post(f"/api/runs/{run_id}/approve")).status_code == 200
    assert (await client.post(f"/api/runs/{run_id}/approve")).status_code == 409


async def test_pause_and_resume_routes(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    # pause before approve is allowed and sticky
    assert (await client.post(f"/api/runs/{run_id}/pause")).status_code == 200
    await client.post(f"/api/runs/{run_id}/approve")
    for _ in range(100):
        run = (await client.get(f"/api/runs/{run_id}")).json()["run"]
        if run["paused"]:
            break
        await asyncio.sleep(0.05)
    assert run["paused"] is True
    r = await client.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 200 and r.json()["paused"] is False
    await wait_for_stage(client, run_id, "done")


async def test_meta_routes(client):
    adapters = (await client.get("/api/adapters")).json()
    assert any(a["platform"] == "local" and a["healthy"] for a in adapters)
    rubrics = (await client.get("/api/rubrics")).json()
    assert rubrics[0]["name"] == "creator-hooks-v1"


async def test_media_route_decodes_post_id_and_blocks_traversal(client, ctx):
    from clipsieve.store.paths import RunPaths

    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    media_dir = RunPaths(ctx.settings.clipsieve_data_dir, run_id).media_dir("local:fx-001")
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    r = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/thumb.jpg")
    assert r.status_code == 200 and r.content == b"\xff\xd8\xff\xd9"
    missing = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/missing.jpg")
    assert missing.status_code == 404
    up = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/..%2F..%2Frun.json")
    assert up.status_code == 404


# ---- contract details beyond the brief's flow ----------------------------------------------


async def test_media_route_serves_keyframes_and_blocks_post_id_traversal(client, ctx):
    from clipsieve.store.paths import RunPaths

    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    paths = RunPaths(ctx.settings.clipsieve_data_dir, run_id)
    frames = paths.media_dir("local:fx-001") / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "hook.jpg").write_bytes(b"hook")
    url = f"/api/runs/{run_id}/media/local%3Afx-001/frames/hook.jpg"
    r = await client.get(url)
    assert r.status_code == 200 and r.content == b"hook"
    assert paths.run_json.is_file()
    # a post id of ".." would put the media dir at the run root
    assert (await client.get(f"/api/runs/{run_id}/media/%2E%2E/run.json")).status_code == 404
    absolute = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/%2Fetc%2Fhosts")
    assert absolute.status_code == 404
    dotdot = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/%2E%2E")
    assert dotdot.status_code == 404


async def test_create_run_validation_is_422_with_string_detail(client):
    bad_platform = await client.post("/api/runs", json={**BODY, "platforms": ["myspace"]})
    assert bad_platform.status_code == 422 and "myspace" in bad_platform.json()["detail"]
    bad_pack = await client.post("/api/runs", json={**BODY, "rubric_pack": "nope"})
    assert bad_pack.status_code == 422 and isinstance(bad_pack.json()["detail"], str)
    no_brief = await client.post("/api/runs", json={"platforms": ["local"]})
    assert no_brief.status_code == 422 and isinstance(no_brief.json()["detail"], str)
    zero = await client.post("/api/runs", json={**BODY, "quantities": {"local": 0}})
    assert zero.status_code == 422
    assert (await client.get("/api/runs")).json() == []


async def test_optional_fields_are_absent_and_missing_plan_is_null(client, ctx):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    run = (await client.get(f"/api/runs/{run_id}")).json()["run"]
    assert "language_hint" not in run["brief"] and "error" not in run
    bare = _create(ctx, "b")
    data = (await client.get(f"/api/runs/{bare.id}")).json()
    assert "plan" in data and data["plan"] is None


async def test_plan_edits_are_validated_and_locked_after_approval(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    plan = (await wait_for_plan(client, run_id))["plan"]
    r = await client.put(f"/api/runs/{run_id}/plan", json={**plan, "rubric_pack": "nope"})
    assert r.status_code == 422
    assert (await client.post(f"/api/runs/{run_id}/approve")).status_code == 200
    assert (await client.put(f"/api/runs/{run_id}/plan", json=plan)).status_code == 409


async def test_reselect_before_selection_is_409(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    r = await client.post(f"/api/runs/{run_id}/reselect", json={"weights": {}})
    assert r.status_code == 409


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "backend": "fake"}


def _bare_run(ctx, stage: Stage, paused: bool):
    run = _create(ctx, "b")
    run.stage = stage
    run.paused = paused
    ctx.repo.save_run(run)
    return run.id


class ScriptedRunner:
    """Stands in for a Runner whose `run()` ends paused once, as when a late pause wins."""

    def __init__(self, ctx, run_id, gate: asyncio.Event | None = None):
        self.ctx, self.run_id, self.gate, self.calls = ctx, run_id, gate, 0

    def pause(self):
        pass

    def resume_flag(self):
        pass

    async def run(self):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        run = self.ctx.repo.get_run(self.run_id)
        if self.calls == 1:
            run.paused = True
        else:
            run.stage = Stage.done
        self.ctx.repo.save_run(run)


async def test_resume_reruns_when_a_late_pause_wins(client, ctx):
    run_id = _bare_run(ctx, Stage.collecting, paused=True)
    stub = ScriptedRunner(ctx, run_id)
    ctx.runners[run_id] = stub
    r = await client.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 200 and r.json()["paused"] is False
    data = await wait_for_stage(client, run_id, "done")
    assert stub.calls == 2 and data["run"]["paused"] is False


async def test_outstanding_pause_keeps_the_run_paused(client, ctx):
    run_id = _bare_run(ctx, Stage.collecting, paused=True)
    gate = asyncio.Event()
    stub = ScriptedRunner(ctx, run_id, gate)
    ctx.runners[run_id] = stub
    assert (await client.post(f"/api/runs/{run_id}/resume")).status_code == 200
    assert (await client.post(f"/api/runs/{run_id}/pause")).status_code == 200
    gate.set()
    await asyncio.wait_for(ctx.tasks[run_id], timeout=5)
    assert stub.calls == 1
    assert (await client.get(f"/api/runs/{run_id}")).json()["run"]["paused"] is True


def test_build_context_fake_mode_defaults(tmp_path, monkeypatch):
    from clipsieve.adapters.fixture import FixtureAdapter
    from clipsieve.api.context import DEFAULT_FIXTURE_DIR, build_context
    from clipsieve.evidence.asr import FakeASR
    from clipsieve.evidence.frames import FakeFrames
    from clipsieve.evidence.ocr import FakeOCR
    from clipsieve.explain.fake import FakeExplainBackend
    from clipsieve.judge.recorded import RecordedJudge

    for var in ("CLIPSIEVE_FIXTURE_DIR", "CLIPSIEVE_CREATOR_SALT"):
        monkeypatch.delenv(var, raising=False)
    ctx = build_context(fake_settings(tmp_path, clipsieve_fixture_dir=None))
    assert ctx.settings.clipsieve_fixture_dir == DEFAULT_FIXTURE_DIR
    assert (DEFAULT_FIXTURE_DIR / "posts").is_dir()
    assert isinstance(ctx.adapters["local"], FixtureAdapter)
    assert isinstance(ctx.judge, RecordedJudge)
    assert isinstance(ctx.explain, FakeExplainBackend)
    assert isinstance(ctx.asr, FakeASR) and isinstance(ctx.ocr, FakeOCR)
    assert isinstance(ctx.frames, FakeFrames)
    salt_file = tmp_path / "creator_salt"
    assert salt_file.is_file()  # A.12: created once, up front
    assert ctx.settings.clipsieve_creator_salt == salt_file.read_text(encoding="utf-8").strip()


def test_build_context_real_mode_shares_one_backend_each(tmp_path, monkeypatch):
    from clipsieve.api.context import build_context
    from clipsieve.evidence.asr import WhisperASR
    from clipsieve.evidence.frames import FfmpegFrames
    from clipsieve.evidence.ocr import PaddleOCRBackend
    from clipsieve.explain.claude_cli import ClaudeCliBackend
    from clipsieve.judge.typesafe_client import TypeSafeJudge

    monkeypatch.delenv("CLIPSIEVE_FIXTURE_DIR", raising=False)
    settings = fake_settings(
        tmp_path, clipsieve_explain_backend="claude_cli", clipsieve_fixture_dir=None
    )
    ctx = build_context(settings)
    assert isinstance(ctx.judge, TypeSafeJudge) and isinstance(ctx.explain, ClaudeCliBackend)
    assert isinstance(ctx.asr, WhisperASR) and isinstance(ctx.ocr, PaddleOCRBackend)
    assert isinstance(ctx.frames, FfmpegFrames)
    a = _create(ctx, "a")
    b = _create(ctx, "b")
    ra, rb = ctx.runner_for(a.id), ctx.runner_for(b.id)
    assert ctx.runner_for(a.id) is ra  # one Runner per run id
    assert ra.asr is rb.asr is ctx.asr and ra.ocr is rb.ocr and ra.judge is rb.judge  # B.13


async def test_planning_failure_becomes_a_recoverable_error_event(client, ctx):
    from clipsieve.events.reader import read_events
    from clipsieve.explain.base import ExplainError

    class BrokenPlanner:
        def plan(self, brief, packs, platforms):
            raise ExplainError("claude -p is not logged in")

        def explain(self, packet):
            raise AssertionError("not reached")

    ctx.explain = BrokenPlanner()
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await asyncio.wait_for(ctx.tasks[run_id], timeout=5)
    events = read_events(ctx.repo.paths(run_id))
    assert [e.type.value for e in events] == ["run_created", "error"]
    assert events[-1].payload == {
        "where": "planner",
        "message": "claude -p is not logged in",
        "recoverable": True,
    }
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["plan"] is None and data["run"]["counters"]["errors"] == 1
    assert data["run"]["stage"] == "planning"
