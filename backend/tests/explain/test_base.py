import json
from pathlib import Path

import pytest

from clipsieve.config import Settings
from clipsieve.explain.base import (
    PROMPTS_DIR,
    ExplainError,
    ExplainPacket,
    PlanRequest,
    RubricPackSummary,
    cli_payload,
    get_backend,
    validate_report_citations,
)
from clipsieve.explain.claude_api import ClaudeApiBackend
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.models import Brief, Plan, Report

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_POST_IDS = {f"local:fx-00{i}" for i in range(1, 6)}


def load_report():
    return Report.model_validate(
        json.loads((FIXTURES / "explain/report.json").read_text(encoding="utf-8"))
    )


def test_validate_report_citations_finds_unknown_ids_sorted_unique():
    report = load_report()
    assert validate_report_citations(report, {f"local:fx-00{i}" for i in range(1, 6)}) == []
    unknown = validate_report_citations(report, {"local:fx-001"})
    assert unknown == ["local:fx-002", "local:fx-004"]


def test_validate_report_citations_checks_every_citation_field():
    report = Report.model_validate(
        {
            "run_id": "r",
            "patterns": [
                {"title": "t", "observation": "o", "hypothesis": "h", "post_ids": ["x:p"]}
            ],
            "clips": [
                {"post_id": "x:c", "why_it_works": "w", "hook_quote": "q", "weaknesses": "k"}
            ],
            "gaps": [{"title": "t", "rationale": "r", "post_ids": ["x:g", "x:p"]}],
            "concepts": [
                {
                    "hook": "h",
                    "structure": "s",
                    "visual": "v",
                    "proof": "p",
                    "cta": "c",
                    "inspired_by_post_ids": ["x:k", "ok"],
                }
            ],
            "caveats": [],
        }
    )
    assert validate_report_citations(report, {"ok"}) == ["x:c", "x:g", "x:k", "x:p"]


def test_cli_payload_has_mode_and_keeps_unicode():
    brief = Brief(text="新加坡人 in Shanghai", topic="t", audience="a", persona="p")
    body = PlanRequest(
        brief=brief,
        packs=[RubricPackSummary(name="x", description="d", question_ids=["q"])],
        platforms=["youtube"],
    )
    raw = cli_payload("plan", body)
    data = json.loads(raw)
    assert data["mode"] == "plan"
    assert data["brief"]["text"] == "新加坡人 in Shanghai"
    assert "新加坡人" in raw  # ensure_ascii=False


def test_cli_payload_adds_only_mode_and_omits_absent_optionals():
    body = PlanRequest(
        brief=Brief(text="x", topic="t", audience="a", persona="p"), packs=[], platforms=["local"]
    )
    data = json.loads(cli_payload("plan", body))
    assert set(data) == {"mode", *PlanRequest.model_fields}
    assert "language_hint" not in data["brief"]  # optional means absent, never null


def test_explain_packet_serialises(fixture_posts):
    packet = ExplainPacket(
        brief=Brief(text="x", topic="t", audience="a", persona="p"),
        posts=fixture_posts[:2],
        evidence={},
        judge={},
        aggregates={"hook_type": {"story": 2}},
        keyframes={},
    )
    data = json.loads(cli_payload("explain", packet))
    assert data["mode"] == "explain" and len(data["posts"]) == 2


def test_explain_fixtures_are_valid_and_null_free():
    raw_plan = json.loads((FIXTURES / "explain/plan.json").read_text(encoding="utf-8"))
    raw_report = json.loads((FIXTURES / "explain/report.json").read_text(encoding="utf-8"))
    plan = Plan.model_validate(raw_plan)
    report = Report.model_validate(raw_report)
    assert plan.run_id == report.run_id == "FIXTURE"
    assert len(plan.persona_fit_criteria) == 5
    assert plan.quantities["local"] == 5
    # Optional means absent: the files hold no nulls the JSON Schemas would reject.
    assert plan.model_dump(mode="json", exclude_none=True) == raw_plan
    assert report.model_dump(mode="json", exclude_none=True) == raw_report
    assert validate_report_citations(report, FIXTURE_POST_IDS) == []


def test_get_backend_fake_needs_fixture_dir():
    settings = Settings(_env_file=None, clipsieve_explain_backend="fake")
    assert isinstance(get_backend(settings, fixture_dir=FIXTURES), FakeExplainBackend)
    with pytest.raises(ExplainError, match="fixture_dir"):
        get_backend(settings)


def test_get_backend_claude_api_is_the_stub():
    settings = Settings(_env_file=None, clipsieve_explain_backend="claude_api")
    assert isinstance(get_backend(settings), ClaudeApiBackend)


def test_prompts_exist_cite_only_given_posts_and_carry_no_policy():
    plan = (PROMPTS_DIR / "plan.md").read_text(encoding="utf-8")
    explain = (PROMPTS_DIR / "explain.md").read_text(encoding="utf-8")
    assert '`mode: "plan"`' in plan and '`mode: "explain"`' in explain
    assert "must be the `id` of a post in `posts`" in explain
    # Policy (weights, thresholds, quotas) lives in rubric YAML and code, never in a prompt.
    for text in (plan, explain):
        lowered = text.lower()
        for word in ("weight", "threshold", "quota", "max_share", "shortlist_size", "risky_claim"):
            assert word not in lowered, word
