import shutil
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clipsieve.explain.base import ExplainError, RubricPackSummary
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.judge.rubric import PackNotFound
from clipsieve.models import Brief, Plan, Query
from clipsieve.planner.plan import build_plan, default_lang, pack_summaries

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
BRIEF = "Singaporean moving to Shanghai, vlog style; analyse hooks."
ALL = ["youtube", "xiaohongshu", "local"]
QTY = {"youtube": 10, "xiaohongshu": 20, "local": 5}
SIDECAR = """# Chinese examples appended to creator-hooks-v1 criteria in bilingual language_mode.
hook_type:
  story: "例：「落地第一天，行李丢了」"
  none: "例：开头只有问候或片头"
hook_strength:
  1: "例：开头是「大家好，欢迎回来」"
  5: "例：「你敢信吗？」加上强烈画面对比和明确利益点"
"""


def _rubrics_with_sidecar(tmp_path: Path) -> Path:
    """The real pack plus a plan 05 style `*.zh-examples.yaml` that is YAML but not a pack."""
    d = tmp_path / "rubrics"
    d.mkdir()
    shutil.copy(RUBRICS / "creator-hooks-v1.yaml", d)
    (d / "foo.zh-examples.yaml").write_text(SIDECAR, encoding="utf-8")
    return d


def _plan(backend, platforms=None, quantities=None, hint=None, pack="creator-hooks-v1"):
    platforms = platforms or ALL
    quantities = quantities or {p: QTY[p] for p in platforms}
    return build_plan("run_abc", BRIEF, platforms, quantities, pack, hint, backend, RUBRICS)


class Recording(FakeExplainBackend):
    def __init__(self, fixture_dir, **update):
        super().__init__(fixture_dir)
        self.update = update
        self.seen: tuple | None = None

    def plan(self, brief, packs, platforms):
        self.seen = (brief, packs, platforms)
        return super().plan(brief, packs, platforms).model_copy(update=self.update)


def test_default_lang():
    assert default_lang("xiaohongshu", None) == "zh"
    assert default_lang("douyin", "en") == "zh"
    assert default_lang("bilibili", None) == "zh"
    assert default_lang("youtube", None) == "en"
    assert default_lang("youtube", "zh") == "zh"
    assert default_lang("local", "ms") == "ms"


def test_pack_summaries_lists_real_packs():
    packs = pack_summaries(RUBRICS)
    assert [p.name for p in packs] == ["creator-hooks-v1"]
    assert "hook_type" in packs[0].question_ids
    assert isinstance(packs[0], RubricPackSummary)


def test_pack_summaries_skips_yaml_that_is_not_a_pack(tmp_path):
    d = _rubrics_with_sidecar(tmp_path)
    with capture_logs() as logs:
        packs = pack_summaries(d)
    assert [p.name for p in packs] == ["creator-hooks-v1"]
    skipped = [e for e in logs if e["event"] == "rubric_pack_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["path"] == str(d / "foo.zh-examples.yaml")


def test_build_plan_works_beside_a_sidecar_yaml(tmp_path):
    d = _rubrics_with_sidecar(tmp_path)
    backend = Recording(FIXTURES)
    plan = build_plan(
        "run_abc", BRIEF, ["local"], {"local": 5}, "creator-hooks-v1", None, backend, d
    )
    assert plan.rubric_pack == "creator-hooks-v1"
    assert [p.name for p in backend.seen[1]] == ["creator-hooks-v1"]


def test_build_plan_with_a_sidecar_name_is_pack_not_found(tmp_path):
    d = _rubrics_with_sidecar(tmp_path)
    with pytest.raises(PackNotFound, match="not a rubric pack"):
        build_plan(
            "run_abc",
            BRIEF,
            ["local"],
            {"local": 5},
            "foo.zh-examples",
            None,
            FakeExplainBackend(FIXTURES),
            d,
        )


def test_build_plan_owns_run_id_quantities_pack_and_brief_text():
    backend = FakeExplainBackend(FIXTURES)
    plan = _plan(backend, hint="en")
    assert isinstance(plan, Plan)
    assert plan.run_id == "run_abc"  # fixture says FIXTURE
    assert plan.quantities == QTY  # fixture says 500/500/5
    assert plan.rubric_pack == "creator-hooks-v1"
    assert plan.brief.text == BRIEF
    assert plan.brief.language_hint == "en"
    assert plan.brief.topic  # backend-filled
    for platform in ALL:
        assert any(q.platform == platform for q in plan.queries)
    assert all(q.lang == "zh" for q in plan.queries if q.platform == "xiaohongshu")
    assert len(plan.persona_fit_criteria) == 5
    assert plan.approved_at is None


def test_language_hint_none_is_not_invented():
    plan = _plan(FakeExplainBackend(FIXTURES))
    assert plan.brief.language_hint is None


def test_backend_receives_seed_brief_packs_and_platforms():
    backend = Recording(FIXTURES)
    _plan(backend, platforms=["youtube"], hint="zh")
    brief, packs, platforms = backend.seen
    assert brief == Brief(text=BRIEF, topic="", audience="", persona="", language_hint="zh")
    assert [p.name for p in packs] == ["creator-hooks-v1"]
    assert platforms == ["youtube"]


def test_user_pack_wins_over_backend_suggestion():
    backend = Recording(FIXTURES, rubric_pack="other-pack")
    plan = _plan(backend)
    assert plan.rubric_pack == "creator-hooks-v1"


def test_unknown_user_pack_raises():
    with pytest.raises(PackNotFound):
        _plan(FakeExplainBackend(FIXTURES), pack="nope")


def test_drops_unticked_and_fills_missing_platform_query():
    backend = Recording(FIXTURES, queries=[Query(platform="youtube", query="x", lang="en")])
    plan = _plan(backend, platforms=["xiaohongshu"])
    assert [q.platform for q in plan.queries] == ["xiaohongshu"]
    assert plan.queries[0].lang == "zh"
    assert plan.queries[0].query == plan.brief.topic


def test_local_never_gets_an_invented_query():
    backend = Recording(FIXTURES, queries=[Query(platform="youtube", query="x", lang="en")])
    plan = _plan(backend, platforms=["youtube", "local"])
    assert [q.platform for q in plan.queries] == ["youtube"]
    assert plan.quantities == {"youtube": 10, "local": 5}


def test_backend_local_path_is_kept_verbatim():
    plan = _plan(FakeExplainBackend(FIXTURES))
    assert [q.query for q in plan.queries if q.platform == "local"] == ["./fixtures"]


def test_empty_lang_filled_nonempty_kept():
    backend = Recording(
        FIXTURES,
        queries=[
            Query(platform="xiaohongshu", query="a", lang=""),
            Query(platform="youtube", query="b", lang="ms"),
            Query(platform="youtube", query="c", lang=""),
        ],
    )
    plan = _plan(backend, platforms=["youtube", "xiaohongshu"], hint="en")
    assert [(q.query, q.lang) for q in plan.queries] == [("a", "zh"), ("b", "ms"), ("c", "en")]


def test_query_order_is_deterministic():
    a = _plan(FakeExplainBackend(FIXTURES))
    b = _plan(FakeExplainBackend(FIXTURES))
    assert a == b


def test_wrong_persona_criteria_count_falls_back_to_pack_levels():
    backend = Recording(FIXTURES, persona_fit_criteria=["a", "b"])
    plan = _plan(backend, platforms=["youtube"])
    assert len(plan.persona_fit_criteria) == 5
    assert plan.persona_fit_criteria[0] == "Unrelated creator and situation"


def test_blank_persona_criterion_falls_back():
    backend = Recording(FIXTURES, persona_fit_criteria=["a", "b", "c", " ", "e"])
    plan = _plan(backend, platforms=["youtube"])
    assert plan.persona_fit_criteria[0] == "Unrelated creator and situation"


def test_missing_quantity_for_platform_raises():
    with pytest.raises(ValueError, match="quantit"):
        _plan(
            FakeExplainBackend(FIXTURES), platforms=["youtube", "local"], quantities={"youtube": 1}
        )


def test_backend_failure_propagates():
    class Boom(FakeExplainBackend):
        def plan(self, brief, packs, platforms):
            raise ExplainError("boom")

    with pytest.raises(ExplainError):
        _plan(Boom(FIXTURES))
