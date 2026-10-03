from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from clipsieve.models import Brief, Evidence, JudgeAnswer, JudgeResult, Plan, Post, Query, Report
from clipsieve.select.select import Selection
from clipsieve.store.db import PostRow, RunRow, get_engine, init_db
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import PostNotFound, RunNotFound, RunRepository

BRIEF = Brief(
    text="Singaporean moving to Shanghai, vlog style",
    topic="Singaporeans living in Shanghai",
    audience="Singaporeans aged 22 to 35 considering a move",
    persona="Singaporean newly arrived in Shanghai",
)


def make_plan(run_id: str) -> Plan:
    return Plan(
        run_id=run_id,
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


def make_evidence(post_id: str) -> Evidence:
    return Evidence(
        post_id=post_id,
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
    assert [r.id for r in repo.list_runs()] == [b.id, a.id]


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
    plan = make_plan(run.id)
    repo.save_plan(run.id, plan)
    assert repo.get_plan(run.id) == plan


def test_posts_roundtrip_preserve_cjk_bytes(
    repo: RunRepository, fixture_posts: list[Post], data_dir: Path
):
    run = repo.create_run(BRIEF, ["local"], {"local": 5}, "creator-hooks-v1")
    for p in fixture_posts:
        repo.upsert_post(run.id, p)
    assert repo.count_posts(run.id) == 5
    listed = repo.list_posts(run.id)
    assert [p.id for p in listed] == [f"local:fx-00{n}" for n in range(1, 6)]
    for p in fixture_posts:
        assert repo.get_post(run.id, p.id) == p
    got = repo.get_post(run.id, "local:fx-003")
    assert got.text.title == "上海超市物价大公开 🇸🇬→🇨🇳"
    paths = RunPaths(data_dir, run.id)
    on_disk = paths.post_json("local:fx-003").read_text(encoding="utf-8")
    assert "上海超市物价大公开 🇸🇬→🇨🇳" in on_disk, "file must hold literal CJK, not \\u escapes"
    assert "同样一篮子东西，新加坡 vs 上海，差价吓到我了。第4张是重点。" in on_disk
    assert "第4张真的绝了" in on_disk
    for p in fixture_posts:
        assert "\\u" not in paths.post_json(p.id).read_text(encoding="utf-8"), p.id
    assert repo.list_posts(run.id, offset=3, limit=10)[0].id == "local:fx-004"
    with pytest.raises(PostNotFound):
        repo.get_post(run.id, "local:nope")


def test_upsert_overwrites(repo: RunRepository, fixture_posts: list[Post]):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    post = fixture_posts[0]
    repo.upsert_post(run.id, post)
    post.metrics.views = 1
    repo.upsert_post(run.id, post)
    assert repo.count_posts(run.id) == 1
    assert repo.get_post(run.id, post.id).metrics.views == 1


def test_evidence_judge_selection_report_roundtrip(repo: RunRepository, fixture_posts: list[Post]):
    run = repo.create_run(BRIEF, ["local"], {"local": 1}, "creator-hooks-v1")
    post = fixture_posts[1]
    repo.upsert_post(run.id, post)

    ev = make_evidence(post.id)
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


def test_reindex_rebuilds_rows_from_files(
    repo: RunRepository, fixture_posts: list[Post], data_dir: Path
):
    run = repo.create_run(BRIEF, ["local"], {"local": 2}, "creator-hooks-v1")
    posts = fixture_posts[:2]
    for p in posts:
        repo.upsert_post(run.id, p)
    plan = make_plan(run.id)
    repo.save_plan(run.id, plan)
    ev = make_evidence("local:fx-002")
    repo.save_evidence(run.id, ev)
    sel = Selection(
        shortlist=["local:fx-001"],
        review=["local:fx-002"],
        scores={"local:fx-001": 0.81, "local:fx-002": 0.4},
        dropped={},
    )
    repo.save_selection(run.id, sel)
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

    repo.engine.dispose()
    (data_dir / "clipsieve.db").unlink()
    engine = get_engine(data_dir)
    init_db(engine)
    fresh = RunRepository(data_dir, engine)
    assert fresh.list_runs() == []
    fresh.reindex(run.id)
    assert fresh.get_run(run.id) == run
    assert fresh.count_posts(run.id) == 2
    for p in posts:
        assert fresh.get_post(run.id, p.id) == p
    assert fresh.get_plan(run.id) == plan
    assert fresh.get_evidence(run.id, "local:fx-002") == ev
    assert fresh.get_selection(run.id) == sel
    assert fresh.get_judge_result(run.id, "local:fx-001", "pass_one") == jr
    assert fresh.get_report(run.id) is not None
    engine.dispose()


SHANGHAI = timezone(timedelta(hours=8))


def test_list_posts_orders_by_instant_across_utc_offsets(
    repo: RunRepository, fixture_posts: list[Post], data_dir: Path
):
    run = repo.create_run(BRIEF, ["local"], {"local": 2}, "creator-hooks-v1")
    base = fixture_posts[0]
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


def test_none_fields_are_absent_from_files_and_rows(
    repo: RunRepository, fixture_posts: list[Post], data_dir: Path
):
    """Optional means absent (Addendum A.13): no `null` where the JSON Schema says string."""
    run = repo.create_run(BRIEF, ["local"], {"local": 5}, "creator-hooks-v1")
    assert run.error is None
    paths = RunPaths(data_dir, run.id)
    run_text = paths.run_json.read_text(encoding="utf-8")
    assert '"error"' not in run_text
    assert "null" not in run_text
    with Session(repo.engine) as s:
        assert '"error"' not in s.get(RunRow, run.id).data
    assert repo.get_run(run.id) == run

    for p in fixture_posts:
        repo.upsert_post(run.id, p)
        assert ": null" not in paths.post_json(p.id).read_text(encoding="utf-8"), p.id
        with Session(repo.engine) as s:
            assert ":null" not in s.get(PostRow, (run.id, p.id)).data, p.id
        assert repo.get_post(run.id, p.id) == p
