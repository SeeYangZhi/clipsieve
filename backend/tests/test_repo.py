from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipsieve.models import Brief, Evidence, JudgeAnswer, JudgeResult, Plan, Post, Query, Report
from clipsieve.select.select import Selection
from clipsieve.store.db import get_engine, init_db
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import PostNotFound, RunNotFound, RunRepository

BRIEF = Brief(
    text="Singaporean moving to Shanghai, vlog style",
    topic="Singaporeans living in Shanghai",
    audience="Singaporeans aged 22 to 35 considering a move",
    persona="Singaporean newly arrived in Shanghai",
)


@pytest.fixture
def repo(data_dir: Path) -> RunRepository:
    engine = get_engine(data_dir)
    init_db(engine)
    return RunRepository(data_dir, engine)


def load_fixture_post(fixtures_dir: Path, n: int) -> Post:
    return Post.model_validate_json(
        (fixtures_dir / "posts" / f"local__fx-00{n}.json").read_text(encoding="utf-8")
    )


def test_create_get_list_run(repo: RunRepository, data_dir: Path):
    run = repo.create_run(
        BRIEF, ["youtube", "local"], {"youtube": 500, "local": 10}, "creator-hooks-v1"
    )
    assert run.id.startswith("run_")
    assert run.stage.value == "planning"
    assert run.counters.collected == 0
    assert run.paused is False
    assert RunPaths(data_dir, run.id).run_json.exists()
    assert repo.get_run(run.id).model_dump() == run.model_dump()
    assert [r.id for r in repo.list_runs()] == [run.id]
    with pytest.raises(RunNotFound):
        repo.get_run("run_missing")


def test_list_runs_newest_first(repo: RunRepository):
    a = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    b = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    assert [r.id for r in repo.list_runs()][:2] == [b.id, a.id] or [
        r.id for r in repo.list_runs()
    ] == [b.id, a.id]


def test_save_run_updates_stage(repo: RunRepository):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    run.stage = "collecting"
    run.counters.collected = 3
    repo.save_run(run)
    got = repo.get_run(run.id)
    assert got.stage.value == "collecting"
    assert got.counters.collected == 3


def test_plan_roundtrip(repo: RunRepository):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    assert repo.get_plan(run.id) is None
    plan = Plan(
        run_id=run.id,
        brief=BRIEF,
        queries=[Query(platform="local", query="*", lang="en")],
        quantities={"local": 1},
        rubric_pack="creator-hooks-v1",
        persona_fit_criteria=[
            "Unrelated",
            "Adjacent niche",
            "Same niche, different voice",
            "Close match",
            "Could be the user's own channel",
        ],
    )
    repo.save_plan(run.id, plan)
    assert repo.get_plan(run.id) == plan


def test_posts_roundtrip_preserve_cjk_bytes(
    repo: RunRepository, fixtures_dir: Path, data_dir: Path
):
    run = repo.create_run(BRIEF, ["local"], {"local": 5}, "creator-hooks-v1")
    for n in range(1, 6):
        repo.upsert_post(run.id, load_fixture_post(fixtures_dir, n))
    assert repo.count_posts(run.id) == 5
    listed = repo.list_posts(run.id)
    assert [p.id for p in listed] == [f"local:fx-00{n}" for n in range(1, 6)]
    got = repo.get_post(run.id, "local:fx-003")
    assert got.text.title == "上海超市物价大公开 🇸🇬→🇨🇳"
    on_disk = RunPaths(data_dir, run.id).post_json("local:fx-003").read_text(encoding="utf-8")
    assert "上海超市物价大公开" in on_disk, "file must hold literal CJK, not \\u escapes"
    assert repo.list_posts(run.id, offset=3, limit=10)[0].id == "local:fx-004"
    with pytest.raises(PostNotFound):
        repo.get_post(run.id, "local:nope")


def test_upsert_overwrites(repo: RunRepository, fixtures_dir: Path):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    post = load_fixture_post(fixtures_dir, 1)
    repo.upsert_post(run.id, post)
    post.metrics.views = 1
    repo.upsert_post(run.id, post)
    assert repo.count_posts(run.id) == 1
    assert repo.get_post(run.id, post.id).metrics.views == 1


def test_evidence_judge_selection_report_roundtrip(repo: RunRepository, fixtures_dir: Path):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    post = load_fixture_post(fixtures_dir, 2)
    repo.upsert_post(run.id, post)

    ev = Evidence(
        post_id=post.id,
        transcript=[{"start_s": 0.0, "end_s": 2.5, "text": "押一付三是什么？"}],
        transcript_lang="zh",
        ocr=[{"source": "keyframe", "index": 0, "text": "租房避坑"}],
        keyframes=["media/local__fx-002/kf_00.png"],
        comment_summary={
            "count": 3,
            "top_terms": ["押一付三", "中介"],
            "sample": ["押一付三真的离谱"],
        },
        token_estimate=120,
        truncated=False,
    )
    repo.save_evidence(run.id, ev)
    assert repo.get_evidence(run.id, post.id) == ev
    assert repo.get_evidence(run.id, "local:nope") is None

    jr = JudgeResult(
        post_id=post.id,
        pass_name="pass_two",
        model="jev-1.13.0",
        input_tokens=1800,
        latency_ms=410,
        answers={
            "hook_type": JudgeAnswer(
                type="choice",
                value="problem",
                probabilities={"problem": 0.7, "story": 0.3},
                confidence=0.57,
            ),
            "hook_strength": JudgeAnswer(
                type="score",
                value=3.4,
                probabilities={"3": 0.6, "4": 0.4},
                confidence=0.8,
                legend={"3": "Question or claim with some tension."},
            ),
            "risky_claim": JudgeAnswer(type="noul", value=0.04),
        },
    )
    repo.save_judge_result(run.id, jr)
    assert repo.get_judge_result(run.id, post.id, "pass_two") == jr
    assert repo.get_judge_result(run.id, post.id, "pass_one") is None
    assert repo.list_judge_results(run.id, "pass_two") == [jr]

    sel = Selection(shortlist=[post.id], review=[], scores={post.id: 0.81}, dropped={})
    repo.save_selection(run.id, sel)
    assert repo.get_selection(run.id) == sel

    rep = Report(
        run_id=run.id,
        patterns=[],
        clips=[
            {
                "post_id": post.id,
                "why_it_works": "names a shared pain",
                "hook_quote": "押一付三是什么？",
                "weaknesses": "slow middle",
            }
        ],
        gaps=[],
        concepts=[],
        caveats=["five posts only"],
    )
    repo.save_report(run.id, rep)
    assert repo.get_report(run.id) == rep


def test_reindex_rebuilds_rows_from_files(repo: RunRepository, fixtures_dir: Path, data_dir: Path):
    run = repo.create_run(BRIEF, ["local"], {"local": 2}, "creator-hooks-v1")
    for n in (1, 2):
        repo.upsert_post(run.id, load_fixture_post(fixtures_dir, n))
    jr = JudgeResult(
        post_id="local:fx-001",
        pass_name="pass_one",
        model="jev-1.13.0",
        input_tokens=300,
        latency_ms=90,
        answers={"niche_relevance": JudgeAnswer(type="score", value=4.2, confidence=0.9)},
    )
    repo.save_judge_result(run.id, jr)
    repo.save_report(
        run.id, Report(run_id=run.id, patterns=[], clips=[], gaps=[], concepts=[], caveats=[])
    )

    (data_dir / "clipsieve.db").unlink()
    engine = get_engine(data_dir)
    init_db(engine)
    fresh = RunRepository(data_dir, engine)
    assert fresh.list_runs() == []
    fresh.reindex(run.id)
    assert fresh.get_run(run.id).id == run.id
    assert fresh.count_posts(run.id) == 2
    assert fresh.get_judge_result(run.id, "local:fx-001", "pass_one") == jr
    assert fresh.get_report(run.id) is not None


SHANGHAI = timezone(timedelta(hours=8))


def test_list_posts_orders_by_instant_across_utc_offsets(
    repo: RunRepository, fixtures_dir: Path, data_dir: Path
):
    run = repo.create_run(BRIEF, ["local"], {"local": 2}, "creator-hooks-v1")
    base = load_fixture_post(fixtures_dir, 1)
    # 09:00+08:00 is 01:00 UTC, so it is earlier than 05:00 UTC despite sorting later as text.
    # Ids are chosen so post_id order contradicts time order.
    earlier = base.model_copy(
        update={"id": "local:z-shanghai", "collected_at": datetime(2026, 10, 3, 9, tzinfo=SHANGHAI)}
    )
    later = base.model_copy(
        update={"id": "local:a-utc", "collected_at": datetime(2026, 10, 3, 5, tzinfo=UTC)}
    )
    repo.upsert_post(run.id, later)
    repo.upsert_post(run.id, earlier)
    assert [p.id for p in repo.list_posts(run.id)] == ["local:z-shanghai", "local:a-utc"]
    on_disk = RunPaths(data_dir, run.id).post_json("local:z-shanghai").read_text(encoding="utf-8")
    assert "2026-10-03T09:00:00+08:00" in on_disk, "file keeps the original offset"
    assert repo.get_post(run.id, "local:z-shanghai").collected_at.utcoffset() == timedelta(hours=8)


def test_list_runs_orders_by_instant_across_utc_offsets(repo: RunRepository):
    a = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    b = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    a.created_at = datetime(2026, 10, 3, 9, tzinfo=SHANGHAI)  # 01:00 UTC, older
    b.created_at = datetime(2026, 10, 3, 5, tzinfo=UTC)  # newer
    repo.save_run(a)
    repo.save_run(b)
    assert [r.id for r in repo.list_runs()] == [b.id, a.id]
