import json
from pathlib import Path

from clipsieve.explain.base import ExplainPacket, RubricPackSummary, validate_report_citations
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.models import Brief

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def empty_brief() -> Brief:
    return Brief(text="b", topic="", audience="", persona="")


def packet_for(posts) -> ExplainPacket:
    return ExplainPacket(
        brief=empty_brief(), posts=posts, evidence={}, judge={}, aggregates={}, keyframes={}
    )


def test_fake_plan_returns_fixture_plan():
    backend = FakeExplainBackend(FIXTURES)
    plan = backend.plan(
        empty_brief(),
        [RubricPackSummary(name="creator-hooks-v1", description="", question_ids=[])],
        ["youtube"],
    )
    assert plan.rubric_pack == "creator-hooks-v1"
    assert len(plan.persona_fit_criteria) == 5
    assert plan.quantities["local"] == 5
    assert plan.run_id == "FIXTURE"  # the caller overwrites run_id
    assert backend.calls == ["plan"]


def test_fake_plan_keeps_a_filled_brief():
    brief = Brief(text="新加坡人 in Shanghai", topic="t", audience="a", persona="p")
    plan = FakeExplainBackend(FIXTURES).plan(brief, [], ["local"])
    assert plan.brief == brief


def test_fake_explain_cites_only_packet_posts(fixture_posts):
    backend = FakeExplainBackend(FIXTURES)
    packet = packet_for([fixture_posts[2], fixture_posts[4]])
    report = backend.explain(packet)
    known = {p.id for p in packet.posts}
    assert validate_report_citations(report, known) == []
    assert [c.post_id for c in report.clips] == [p.id for p in packet.posts]
    assert report.patterns and report.gaps and report.concepts
    assert backend.calls == ["explain"]


def test_fake_explain_one_clip_per_post_beyond_fixture_clips(fixture_posts):
    report = FakeExplainBackend(FIXTURES).explain(packet_for(fixture_posts))
    assert [c.post_id for c in report.clips] == [p.id for p in fixture_posts]
    assert validate_report_citations(report, {p.id for p in fixture_posts}) == []


def test_fake_explain_without_posts_cites_nothing():
    report = FakeExplainBackend(FIXTURES).explain(packet_for([]))
    assert report.clips == [] and report.patterns == [] and report.gaps == []
    assert report.concepts == []
    assert report.caveats  # caveats carry no citations and are kept


def test_fake_reads_fixture_files_fresh(tmp_path, fixture_posts):
    (tmp_path / "explain").mkdir()
    for name in ("plan.json", "report.json"):
        data = json.loads((FIXTURES / "explain" / name).read_text(encoding="utf-8"))
        data["run_id"] = "OTHER"
        (tmp_path / "explain" / name).write_text(json.dumps(data), encoding="utf-8")
    backend = FakeExplainBackend(tmp_path)
    assert backend.plan(empty_brief(), [], ["local"]).run_id == "OTHER"
    assert backend.explain(packet_for(fixture_posts[:1])).run_id == "OTHER"
    assert backend.calls == ["plan", "explain"]
