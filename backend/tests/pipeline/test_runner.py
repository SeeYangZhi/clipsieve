import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clipsieve.adapters.base import AdapterHealth, MediaDownloadError
from clipsieve.adapters.fixture import FixtureAdapter
from clipsieve.config import Settings
from clipsieve.events.reader import read_events
from clipsieve.evidence.asr import FakeASR
from clipsieve.evidence.frames import FakeFrames
from clipsieve.evidence.ocr import FakeOCR
from clipsieve.explain.base import ExplainError, cli_payload
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.judge.base import JudgeFailed
from clipsieve.judge.recorded import RecordedJudge
from clipsieve.models import (
    Brief,
    Comment,
    CommentSummary,
    Evidence,
    OcrItem,
    TranscriptSegment,
)
from clipsieve.pipeline import runner as runner_module
from clipsieve.pipeline.runner import (
    EXPLAIN_TEXT_CAP,
    STAGE_ORDER,
    Runner,
    build_explain_packet,
    post_state,
)
from clipsieve.pipeline.state import load_state
from clipsieve.store.paths import RunPaths, safe_post_filename

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
BRIEF = Brief(text="Singaporean moving to Shanghai vlog", topic="", audience="", persona="")
KEPT = ["local:fx-001", "local:fx-004"]  # top ceil(0.30 * 5) by niche_relevance in pass one
TOKENS = 5 * 640 + 2 * 2900


def make_runner(data_dir, repo, judge=None, explain=None, adapter=None):
    settings = Settings(
        _env_file=None,
        clipsieve_data_dir=data_dir,
        clipsieve_explain_backend="fake",
        clipsieve_fixture_dir=FIXTURES,
    )
    run = repo.create_run(BRIEF, ["local"], {"local": 5}, "creator-hooks-v1")
    runner = Runner(
        run_id=run.id,
        settings=settings,
        repo=repo,
        adapters={"local": adapter or FixtureAdapter(FIXTURES, data_dir)},
        judge=judge or RecordedJudge(FIXTURES),
        explain=explain or FakeExplainBackend(FIXTURES),
        asr=FakeASR(),
        ocr=FakeOCR(),
        frames=FakeFrames(),
        rubrics_dir=RUBRICS,
    )
    return runner, run.id


async def run_to_done(runner):
    plan = await runner.plan()
    await runner.approve(plan)
    await runner.run()


def events(data_dir, run_id):
    return read_events(RunPaths(data_dir, run_id))


def event_types(data_dir, run_id):
    return [e.type.value for e in events(data_dir, run_id)]


def resume(runner, repo, run_id):
    run = repo.get_run(run_id)
    run.paused = False
    repo.save_run(run)
    runner.resume_flag()


def test_stage_order_is_the_contract():
    assert STAGE_ORDER == [
        "planning",
        "collecting",
        "pass_one",
        "extracting",
        "pass_two",
        "selecting",
        "explaining",
        "done",
    ]


async def test_end_to_end_fixture_run(data_dir, repo):
    runner, run_id = make_runner(data_dir, repo)
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "done" and run.paused is False
    evs = events(data_dir, run_id)
    types = [e.type.value for e in evs]
    assert types[0] == "run_created"
    assert types.index("plan_ready") < types.index("plan_approved") < types.index("post_collected")
    assert types.count("post_collected") == 5
    assert types.count("pass_one_judged") == 5
    kept = load_state(RunPaths(data_dir, run_id)).pass_one_kept
    assert kept == KEPT  # ceil(0.30 * 5)
    assert types.count("evidence_ready") == 2 and types.count("judged") == 2
    assert [t for t in types if t != "stage_changed"][-3:] == ["selected", "explained", "done"]
    assert types[-1] == "done"
    # stage_changed walks STAGE_ORDER, "from" on the wire
    changes = [e.payload for e in evs if e.type.value == "stage_changed"]
    assert [c["to"] for c in changes] == STAGE_ORDER[1:]
    assert all(set(c) == {"from", "to"} for c in changes)
    assert changes[0]["from"] == "planning"
    # pass_one_judged carries `kept` for every post
    p1 = {
        e.payload["judge"]["post_id"]: e.payload["kept"]
        for e in evs
        if e.type.value == "pass_one_judged"
    }
    assert {pid for pid, k in p1.items() if k} == set(KEPT)
    # post_collected carries the relocated raw_ref and no media paths
    collected = [e.payload["post"] for e in evs if e.type.value == "post_collected"]
    assert all(p["raw_ref"] == f"raw/{safe_post_filename(p['id'])}.json" for p in collected)
    assert all("local_path" not in m for p in collected for m in p["media"])
    sel = repo.get_selection(run_id)
    assert sel is not None and set(sel.shortlist) | set(sel.review) <= set(kept)
    report = repo.get_report(run_id)
    assert report is not None and report.run_id == run_id
    assert {c.post_id for c in report.clips} == set(sel.shortlist)
    assert run.counters.collected == 5 and run.counters.judged == 2
    assert run.counters.pass_one_kept == 2
    assert run.counters.shortlisted == len(sel.shortlist) and run.counters.errors == 0
    assert run.counters.jev_input_tokens == TOKENS
    assert run.counters.jev_cost_usd == pytest.approx(TOKENS / 1e6 * 0.042)
    assert evs[-1].payload["counters"] == run.counters.model_dump(mode="json")
    # raw payload relocated into the run folder
    post = repo.get_post(run_id, "local:fx-001")
    assert (
        post.raw_ref.startswith("raw/")
        and (RunPaths(data_dir, run_id).root / post.raw_ref).exists()
    )
    assert not list((data_dir / "incoming" / "local").glob("*.json"))
    # fixture media + fakes reproduce the committed evidence snapshots
    for pid in KEPT:
        snap = FIXTURES / "evidence" / f"{safe_post_filename(pid)}.json"
        assert repo.get_evidence(run_id, pid) == Evidence.model_validate_json(snap.read_text())


async def test_resume_after_crash_no_duplicate_judge_calls(data_dir, repo):
    class CrashOnce(RecordedJudge):
        def __init__(self, d):
            super().__init__(d)
            self.crashed = False

        async def judge(self, post_id, pass_name, state, questions, model):
            pass_two_done = [c for c in self.calls if c[1] == "pass_two"]
            if pass_name == "pass_two" and not self.crashed and len(pass_two_done) == 1:
                self.crashed = True
                raise RuntimeError("simulated crash")
            return await super().judge(post_id, pass_name, state, questions, model)

    judge = CrashOnce(FIXTURES)
    runner, run_id = make_runner(data_dir, repo, judge=judge)
    plan = await runner.plan()
    await runner.approve(plan)
    with pytest.raises(RuntimeError):
        await runner.run()
    assert repo.get_run(run_id).stage.value == "pass_two"
    # as if the process died after writing a result but before saving the counters
    crashed = repo.get_run(run_id)
    crashed.counters.collected = crashed.counters.judged = crashed.counters.jev_input_tokens = 0
    repo.save_run(crashed)
    pass_two_calls_before = [c for c in judge.calls if c[1] == "pass_two"]
    await runner.run()  # resume
    run = repo.get_run(run_id)
    assert run.stage.value == "done"
    pass_two_calls = [c for c in judge.calls if c[1] == "pass_two"]
    # exactly one extra successful call per not-yet-judged post; the judged post is not re-judged
    assert len(pass_two_calls) == len(pass_two_calls_before) + 1
    assert len([c for c in judge.calls if c[1] == "pass_one"]) == 5
    assert event_types(data_dir, run_id).count("judged") == 2
    assert event_types(data_dir, run_id).count("evidence_ready") == 2
    assert run.counters.jev_input_tokens == TOKENS and run.counters.judged == 2
    assert run.counters.collected == 5
    assert run.counters.jev_cost_usd == pytest.approx(TOKENS / 1e6 * 0.042)


async def test_resume_mid_extraction_does_not_re_extract(data_dir, repo, monkeypatch):
    class Crash(BaseException):
        pass

    real = runner_module.extract_evidence
    calls: list[str] = []

    def crash_on_second(post, *args):
        calls.append(post.id)
        if post.id == KEPT[1] and calls.count(KEPT[1]) == 1:
            raise Crash
        return real(post, *args)

    monkeypatch.setattr(runner_module, "extract_evidence", crash_on_second)
    runner, run_id = make_runner(data_dir, repo)
    plan = await runner.plan()
    await runner.approve(plan)
    with pytest.raises(Crash):
        await runner.run()
    paths = RunPaths(data_dir, run_id)
    assert repo.get_run(run_id).stage.value == "extracting"
    done_before = list(load_state(paths).extracted)
    assert KEPT[1] not in done_before
    calls_before = len(calls)
    await runner.run()
    assert repo.get_run(run_id).stage.value == "done"
    assert len(calls) - calls_before == len(KEPT) - len(done_before)
    assert sorted(load_state(paths).extracted) == KEPT
    ready = [
        e.payload["post_id"] for e in events(data_dir, run_id) if e.type.value == "evidence_ready"
    ]
    assert sorted(ready) == KEPT


async def test_pause_then_resume_completes(data_dir, repo):
    runner, run_id = make_runner(data_dir, repo)
    plan = await runner.plan()
    await runner.approve(plan)
    runner.pause()
    await runner.run()
    run = repo.get_run(run_id)
    assert run.paused is True and run.stage.value in ("collecting", "pass_one")
    resume(runner, repo, run_id)
    await runner.run()
    assert repo.get_run(run_id).stage.value == "done"
    types = event_types(data_dir, run_id)
    assert types.count("post_collected") == 5 and types.count("done") == 1


async def test_pause_mid_pass_one_resumes_without_rejudging(data_dir, repo):
    class PauseOnFirst(RecordedJudge):
        runner: Runner | None = None

        async def judge(self, post_id, pass_name, state, questions, model):
            if pass_name == "pass_one" and not self.calls:
                self.runner.pause()
            return await super().judge(post_id, pass_name, state, questions, model)

    judge = PauseOnFirst(FIXTURES)
    runner, run_id = make_runner(data_dir, repo, judge=judge)
    judge.runner = runner
    plan = await runner.plan()
    await runner.approve(plan)
    await runner.run()
    run = repo.get_run(run_id)
    assert run.paused is True and run.stage.value == "pass_one"
    assert len(judge.calls) == 1
    # the keep set is never decided on a partial pass
    assert "pass_one_judged" not in event_types(data_dir, run_id)
    assert load_state(RunPaths(data_dir, run_id)).pass_one_kept == []
    resume(runner, repo, run_id)
    await runner.run()
    run = repo.get_run(run_id)
    assert run.stage.value == "done"
    assert len([c for c in judge.calls if c[1] == "pass_one"]) == 5
    assert event_types(data_dir, run_id).count("pass_one_judged") == 5
    assert run.counters.jev_input_tokens == TOKENS


async def test_judge_failed_post_excluded_run_completes(data_dir, repo):
    class FailOne(RecordedJudge):
        async def judge(self, post_id, pass_name, state, questions, model):
            if post_id == "local:fx-001":
                raise JudgeFailed(post_id, 5, RuntimeError("429"))
            return await super().judge(post_id, pass_name, state, questions, model)

    runner, run_id = make_runner(data_dir, repo, judge=FailOne(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "done"
    state = load_state(RunPaths(data_dir, run_id))
    assert "local:fx-001" in state.judge_failed
    assert "local:fx-001" not in state.pass_one_kept + state.pass_one_dropped
    errors = [e for e in events(data_dir, run_id) if e.type.value == "error"]
    assert any(
        e.payload.get("post_id") == "local:fx-001"
        and e.payload["where"] == "judge.pass_one"
        and e.payload["recoverable"]
        for e in errors
    )
    assert run.counters.errors >= 1
    sel = repo.get_selection(run_id)
    assert "local:fx-001" not in sel.shortlist + sel.review


async def test_pass_two_judge_failure_is_recorded(data_dir, repo):
    class FailPassTwo(RecordedJudge):
        async def judge(self, post_id, pass_name, state, questions, model):
            if post_id == KEPT[0] and pass_name == "pass_two":
                raise JudgeFailed(post_id, 5, RuntimeError("529"))
            return await super().judge(post_id, pass_name, state, questions, model)

    runner, run_id = make_runner(data_dir, repo, judge=FailPassTwo(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "done" and run.counters.judged == 1
    assert KEPT[0] in load_state(RunPaths(data_dir, run_id)).judge_failed
    (err,) = [e for e in events(data_dir, run_id) if e.type.value == "error"]
    assert err.payload["where"] == "judge.pass_two" and err.payload["post_id"] == KEPT[0]
    assert err.stage.value == "pass_two"
    assert repo.get_selection(run_id).shortlist == [KEPT[1]]


async def test_explain_failure_marks_run_failed_with_shortlist_intact(data_dir, repo):
    class Broken(FakeExplainBackend):
        def explain(self, packet):
            raise ExplainError("report cites unknown post ids after retry: ['x']")

    runner, run_id = make_runner(data_dir, repo, explain=Broken(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "failed" and "unknown post ids" in (run.error or "")
    assert repo.get_selection(run_id) is not None
    assert repo.get_report(run_id) is None
    evs = events(data_dir, run_id)
    # E.8 as amended: the error (stage explaining) first, then stage_changed to failed, last.
    err, last = evs[-2], evs[-1]
    assert err.type.value == "error" and err.stage.value == "explaining"
    assert err.payload["where"] == "explain" and err.payload["recoverable"] is False
    assert "post_id" not in err.payload
    assert last.type.value == "stage_changed" and last.stage.value == "failed"
    assert last.payload == {"from": "explaining", "to": "failed"}
    assert "done" not in [e.type.value for e in evs]
    await runner.run()  # a failed run is not resumed
    assert len(events(data_dir, run_id)) == len(evs)


def test_explain_packet_drops_raw_comments_and_caps_text(fixture_posts):
    big = fixture_posts[0].model_copy(
        update={"comments": [Comment(text=f"评论 {i}", likes=i) for i in range(50)]}
    )
    stored = Evidence(
        post_id=big.id,
        transcript=[
            TranscriptSegment(start_s=i, end_s=i + 1, text="字" * 1000) for i in range(20)
        ],  # 20 000 characters
        ocr=[OcrItem(source="keyframe", index=i, text="o" * 1500) for i in range(4)],
        keyframes=["media/local__fx-001/frames/hook.jpg"],
        comment_summary=CommentSummary(count=50, top_terms=["上海"], sample=["评论 0", "评论 1"]),
        token_estimate=26000,
        truncated=False,
    )
    before = stored.model_copy(deep=True)
    small = fixture_posts[3]
    small_ev = Evidence.model_validate_json(
        (FIXTURES / "evidence" / f"{safe_post_filename(small.id)}.json").read_text()
    )
    with capture_logs() as logs:
        packet = build_explain_packet(
            "run_x", BRIEF, [big, small], {big.id: stored, small.id: small_ev}, {}, {}
        )
    payload = cli_payload("explain", packet)
    posts = json.loads(payload)["posts"]
    # (a) no raw comments: not a field of the packet post, not a key on the wire
    assert [p["id"] for p in posts] == [big.id, small.id]
    assert all("comments" not in p for p in posts)
    assert all("comments" not in type(p).model_fields for p in packet.posts)
    # (b) transcript and OCR text capped per post, structure kept, a trailing marker
    ev = packet.evidence[big.id]
    transcript = "".join(s.text for s in ev.transcript)
    ocr = "".join(o.text for o in ev.ocr)
    assert len(transcript) <= EXPLAIN_TEXT_CAP + len("…") and transcript.endswith("…")
    assert transcript[:-1] == ("字" * 20000)[:EXPLAIN_TEXT_CAP]
    assert len(ocr) <= EXPLAIN_TEXT_CAP + len("…") and ocr.endswith("…")
    assert ev.transcript[0] == stored.transcript[0] and ev.ocr[0] == stored.ocr[0]
    assert ev.comment_summary == stored.comment_summary  # the summary and samples stay
    assert ev.truncated is True
    assert packet.keyframes == {
        big.id: ["media/local__fx-001/frames/hook.jpg"],
        small.id: list(small_ev.keyframes),
    }
    assert packet.evidence[small.id] == small_ev  # under the cap: unchanged
    assert stored == before and big.comments  # never mutates what is stored
    # (c) one info log with the size
    (entry,) = [e for e in logs if e["event"] == "explain_packet_built"]
    assert entry["log_level"] == "info" and entry["run_id"] == "run_x" and entry["posts"] == 2
    assert entry["approx_chars"] == len(payload)
    assert 0 < entry["approx_tokens"] <= entry["approx_chars"]


async def test_run_explains_a_packet_without_raw_comments(data_dir, repo):
    seen = []

    class Spy(FakeExplainBackend):
        def explain(self, packet):
            seen.append(packet)
            return super().explain(packet)

    runner, run_id = make_runner(data_dir, repo, explain=Spy(FIXTURES))
    with capture_logs() as logs:
        await run_to_done(runner)
    (packet,) = seen
    shortlist = repo.get_selection(run_id).shortlist
    assert [p.id for p in packet.posts] == shortlist
    assert all("comments" not in p for p in json.loads(cli_payload("explain", packet))["posts"])
    assert all(repo.get_post(run_id, pid).comments for pid in shortlist)  # stored posts keep them
    assert {c.post_id for c in repo.get_report(run_id).clips} == set(shortlist)
    assert any(e["event"] == "explain_packet_built" and e["run_id"] == run_id for e in logs)


@pytest.mark.parametrize("case", ["every_judge_call_fails", "zero_posts_collected"])
async def test_empty_shortlist_fails_at_explaining_without_calling_backend(data_dir, repo, case):
    class AllFail(RecordedJudge):
        async def judge(self, post_id, pass_name, state, questions, model):
            raise JudgeFailed(post_id, 5, RuntimeError("429"))

    class Empty(FixtureAdapter):
        def search(self, queries, limit):
            return iter(())

    explain = FakeExplainBackend(FIXTURES)
    if case == "every_judge_call_fails":
        runner, run_id = make_runner(data_dir, repo, judge=AllFail(FIXTURES), explain=explain)
    else:
        runner, run_id = make_runner(
            data_dir, repo, explain=explain, adapter=Empty(FIXTURES, data_dir)
        )
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "failed"
    assert run.error == "nothing to explain: no post reached the shortlist"
    assert explain.calls.count("explain") == 0  # no backend call, zero spend
    assert repo.get_selection(run_id).shortlist == []
    assert repo.get_report(run_id) is None
    evs = events(data_dir, run_id)
    # E.8: the error (stage explaining) first, then stage_changed to failed as the last event.
    err, last = evs[-2], evs[-1]
    assert err.type.value == "error" and err.stage.value == "explaining"
    assert err.payload == {
        "where": "explain",
        "message": "nothing to explain: no post reached the shortlist",
        "recoverable": False,
    }
    assert last.type.value == "stage_changed" and last.stage.value == "failed"
    assert last.payload == {"from": "explaining", "to": "failed"}
    types = [e.type.value for e in evs]
    assert "explained" not in types and "done" not in types
    assert types.index("selected") < len(types) - 2


@pytest.mark.parametrize("kind", ["unknown_citation", "backend_crash"])
async def test_explain_bad_report_or_crash_fails_run(data_dir, repo, kind):
    class Bad(FakeExplainBackend):
        def explain(self, packet):
            if kind == "backend_crash":
                raise NotImplementedError("claude_api backend is a stub")
            report = super().explain(packet)
            clip = report.clips[0].model_copy(update={"post_id": "local:fx-003"})
            return report.model_copy(update={"clips": [*report.clips, clip]})

    runner, run_id = make_runner(data_dir, repo, explain=Bad(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "failed" and repo.get_report(run_id) is None
    expected = "local:fx-003" if kind == "unknown_citation" else "NotImplementedError"
    assert expected in (run.error or "")
    assert [e.type.value for e in events(data_dir, run_id)][-2:] == ["error", "stage_changed"]


async def test_reselect_uses_stored_results_without_judge(data_dir, repo):
    runner, run_id = make_runner(data_dir, repo)
    await run_to_done(runner)
    calls_before = len(runner.judge.calls)
    sel = await runner.reselect({"hook_strength": 1.0})
    kept = load_state(RunPaths(data_dir, run_id)).pass_one_kept
    assert set(sel.shortlist) | set(sel.review) <= set(kept)
    assert sel.shortlist == ["local:fx-004", "local:fx-001"]  # hook_strength alone reorders
    assert len(runner.judge.calls) == calls_before
    assert repo.get_selection(run_id) == sel
    assert event_types(data_dir, run_id).count("selected") == 2


async def test_raw_is_relocated_before_fetch_media(data_dir, repo):
    seen: list[tuple[str, bool]] = []

    class Spy(FixtureAdapter):
        def fetch_media(self, post, dest):
            incoming = data_dir / "incoming" / "local" / f"{safe_post_filename(post.id)}.json"
            seen.append((post.raw_ref, incoming.exists()))
            return super().fetch_media(post, dest)

    runner, run_id = make_runner(data_dir, repo, adapter=Spy(FIXTURES, data_dir))
    await run_to_done(runner)
    # extraction runs concurrently, so compare as a set rather than in order
    assert sorted(seen) == sorted((f"raw/{safe_post_filename(pid)}.json", False) for pid in KEPT)


async def test_media_download_error_is_recoverable_and_extraction_still_runs(data_dir, repo):
    class NoMedia(FixtureAdapter):
        def fetch_media(self, post, dest):
            raise MediaDownloadError(f"gone: {post.id}")

    runner, run_id = make_runner(data_dir, repo, adapter=NoMedia(FIXTURES, data_dir))
    await run_to_done(runner)
    assert repo.get_run(run_id).stage.value == "done"
    errors = [e.payload for e in events(data_dir, run_id) if e.type.value == "error"]
    assert sorted(e["post_id"] for e in errors) == KEPT
    assert all(e["where"] == "adapter.local" and e["recoverable"] for e in errors)
    for pid in KEPT:
        ev = repo.get_evidence(run_id, pid)
        assert ev is not None and ev.transcript == [] and ev.comment_summary.count > 0
    assert event_types(data_dir, run_id).count("evidence_ready") == 2


async def test_extract_failure_is_recoverable_with_empty_evidence(data_dir, repo, monkeypatch):
    def boom(post, *args):
        raise OSError("disk full")

    monkeypatch.setattr(runner_module, "extract_evidence", boom)
    runner, run_id = make_runner(data_dir, repo)
    await run_to_done(runner)
    assert repo.get_run(run_id).stage.value == "done"
    errors = [e.payload for e in events(data_dir, run_id) if e.type.value == "error"]
    assert sorted(e["post_id"] for e in errors) == KEPT
    assert all(e["where"] == "evidence.extract" and e["recoverable"] for e in errors)
    ev = repo.get_evidence(run_id, KEPT[0])
    assert ev.transcript == [] and ev.keyframes == [] and ev.truncated is False
    assert event_types(data_dir, run_id).count("judged") == 2


async def test_truncated_state_marks_evidence(data_dir, repo, monkeypatch):
    real = runner_module.build_state

    def always_truncated(brief, post, evidence):
        state, _ = real(brief, post, evidence)
        return state, True

    monkeypatch.setattr(runner_module, "build_state", always_truncated)
    runner, run_id = make_runner(data_dir, repo)
    await run_to_done(runner)
    for pid in KEPT:
        assert repo.get_evidence(run_id, pid).truncated is True
        assert Evidence.model_validate_json(
            RunPaths(data_dir, run_id).evidence_json(pid).read_text()
        ).truncated


async def test_search_failure_is_a_recoverable_adapter_error(data_dir, repo):
    class Down(FixtureAdapter):
        def search(self, queries, limit):
            raise ConnectionError("platform down")
            yield  # pragma: no cover

    runner, run_id = make_runner(data_dir, repo, adapter=Down(FIXTURES, data_dir))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    # Zero posts means an empty shortlist, so the run fails at explaining (see below).
    assert run.stage.value == "failed" and run.counters.collected == 0
    errors = [e for e in events(data_dir, run_id) if e.type.value == "error"]
    (err,) = [e for e in errors if e.payload["where"] == "adapter.local"]
    assert "post_id" not in err.payload and err.payload["recoverable"] is True
    assert err.stage.value == "collecting"


async def test_unhealthy_adapter_is_skipped(data_dir, repo):
    class Sick(FixtureAdapter):
        def healthcheck(self):
            return AdapterHealth(ok=False, message="login expired")

    runner, run_id = make_runner(data_dir, repo, adapter=Sick(FIXTURES, data_dir))
    await run_to_done(runner)
    errors = [e.payload for e in events(data_dir, run_id) if e.type.value == "error"]
    (err,) = [e for e in errors if e["where"] == "adapter.local"]
    assert "login expired" in err["message"]
    assert repo.get_run(run_id).stage.value == "failed"  # nothing collected, nothing to explain


async def test_run_needs_an_approved_plan_and_approve_is_once(data_dir, repo):
    runner, run_id = make_runner(data_dir, repo)
    with pytest.raises(RuntimeError):
        await runner.run()
    plan = await runner.plan()
    await runner.approve(plan)
    with pytest.raises(RuntimeError):
        await runner.approve(plan)
    approved = repo.get_plan(run_id)
    assert approved.approved_at is not None and approved.run_id == run_id


def test_post_state_mapping():
    from clipsieve.pipeline.state import RunState
    from clipsieve.select.select import Selection

    state = RunState(pass_one_kept=["a", "b", "c", "d"], pass_one_dropped=["z"], judge_failed=["d"])
    sel = Selection(shortlist=["a"], review=["b"], scores={}, dropped={"c": "not_selected"})
    assert post_state("z", state, sel, {"a", "b", "c"}) == "dropped_pass_one"
    assert post_state("d", state, sel, {"a", "b", "c"}) == "judge_failed"
    assert post_state("a", state, sel, {"a", "b", "c"}) == "shortlisted"
    assert post_state("b", state, sel, {"a", "b", "c"}) == "review"
    assert post_state("c", state, sel, {"a", "b", "c"}) == "judged"
    assert post_state("c", state, None, set()) == "collected"
