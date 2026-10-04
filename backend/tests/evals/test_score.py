"""Scorer tests. No network: RecordedJudge fixtures and in-memory translators only."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from evals.score import (  # noqa: E402
    ClaudeCliTranslator,
    EvalReport,
    IdentityTranslator,
    apply_mode,
    is_correct,
    load_zh_examples,
    predicted_level,
    read_golden,
    render_markdown,
    score_pack,
)

from clipsieve.judge.base import JudgeFailed  # noqa: E402
from clipsieve.judge.recorded import RecordedJudge  # noqa: E402
from clipsieve.judge.rubric import load_pack  # noqa: E402
from clipsieve.models import JudgeAnswer  # noqa: E402
from clipsieve.planner.plan import pack_summaries  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIX / "golden" / "sample-5.jsonl"
PACK = REPO / "rubrics" / "creator-hooks-v1.yaml"


def test_read_golden_skips_comments_and_parses_types():
    items = read_golden(GOLDEN)
    assert len(items) == 5
    assert items[0].post_id == "local:fx-001"
    assert items[0].labels["hook_strength"] == 4 and items[3].labels["risky_claim"] is True
    assert items[1].state["post"]["title"] == "新加坡人在上海的一天｜早餐只要8块"


def _score(key: int, levels: int, first: int = 0) -> JudgeAnswer:
    """A score answer whose argmax is `key`; legend keys start at `first` (Jev is 0-based)."""
    keys = [str(first + i) for i in range(levels)]
    return JudgeAnswer(
        type="score",
        value=float(key),
        probabilities={k: (1.0 if k == str(key) else 0.0) for k in keys},
        confidence=1.0,
        legend={k: "x" for k in keys},
    )


def test_predicted_level_prefers_argmax_probabilities():
    a = JudgeAnswer(
        type="score",
        value=2.4,
        probabilities={"1": 0.05, "2": 0.3, "3": 0.6, "4": 0.05},
        confidence=0.7,
        legend={"1": "a", "2": "b", "3": "c", "4": "d"},
    )
    assert predicted_level(a, levels=4) == 3  # first legend key is 1, argmax key 3: 3 - 1 + 1
    assert predicted_level(_score(2, levels=4), levels=4) == 3  # 0-based keys: level = key + 1


def test_predicted_level_falls_back_to_round_value():
    a = JudgeAnswer(type="score", value=2.4, probabilities=None, confidence=None, legend=None)
    assert predicted_level(a, levels=4) == 3  # no legend: 0-indexed, round(2.4) = 2, level 3 (E.3)
    a0 = JudgeAnswer(
        type="score",
        value=1.6,
        probabilities={"0": 0.2, "1": 0.8},
        confidence=0.8,
        legend={"0": "a", "1": "b"},
    )
    assert predicted_level(a0, levels=2) == 2  # 0-based legend keys: key 1 is level 2


def test_score_agreement_within_one_level():
    pack = load_pack(PACK)
    q = pack.questions["hook_strength"]  # 5 levels; the golden label is 1-based
    assert is_correct(q, _score(3, levels=5), 4) is True  # key 3 is level 4, equal to the label
    assert is_correct(q, _score(1, levels=5), 4) is False  # key 1 is level 2, two away


def test_choice_exact_and_noul_threshold():
    pack = load_pack(PACK)
    hook_type = pack.questions["hook_type"]
    risky = pack.questions["risky_claim"]
    assert is_correct(
        hook_type,
        JudgeAnswer(
            type="choice", value="result_first", probabilities={"result_first": 0.9}, confidence=0.9
        ),
        "result_first",
    )
    assert not is_correct(
        hook_type,
        JudgeAnswer(type="choice", value="story", probabilities={"story": 0.5}, confidence=0.4),
        "result_first",
    )
    assert is_correct(risky, JudgeAnswer(type="noul", value=0.71), True)
    assert is_correct(risky, JudgeAnswer(type="noul", value=0.2), False)
    assert not is_correct(risky, JudgeAnswer(type="noul", value=0.5), True)


def test_apply_mode_bilingual_appends_examples():
    pack = load_pack(PACK)
    item = read_golden(GOLDEN)[1]
    zh = load_zh_examples("creator-hooks-v1", REPO / "rubrics")
    p2, state, cost = apply_mode(pack, item, "bilingual", IdentityTranslator(), zh)
    assert "例：" in p2.questions["hook_type"].criteria["bold_claim"]
    assert (
        p2.questions["hook_strength"]
        .criteria[4]
        .endswith("例：「你敢信吗？」加上强烈画面对比和明确利益点")
    )
    assert state == item.state and cost == 0.0
    assert "例：" not in pack.questions["hook_type"].criteria["bold_claim"]  # original untouched


def test_apply_mode_translate_rewrites_text_fields_and_counts_cost():
    class UpperTranslator:
        def translate(self, texts):
            return [t.upper() for t in texts], 0.01 * len(texts)

    pack = load_pack(PACK)
    item = read_golden(GOLDEN)[1]
    _, state, cost = apply_mode(pack, item, "translate", UpperTranslator(), {})
    assert state["post"]["title"] == item.state["post"]["title"].upper()
    assert state["transcript"][0]["text"] == item.state["transcript"][0]["text"].upper()
    assert state["ocr"][0]["text"] == item.state["ocr"][0]["text"].upper()
    assert state["comments"]["sample"][0] == item.state["comments"]["sample"][0].upper()
    assert state["brief"] == item.state["brief"]
    assert cost > 0


async def test_score_pack_with_recorded_judge():
    pack = load_pack(PACK)
    judge = RecordedJudge(FIX)  # RecordedJudge appends "judge/" itself
    report = await score_pack(pack, GOLDEN, judge, mode="raw", rubrics_dir=REPO / "rubrics")
    assert isinstance(report, EvalReport)
    assert report.n_items == 5 and report.n_skipped == 0
    assert report.mode == "raw" and report.pack == "creator-hooks-v1"
    ids = {q.question_id for q in report.questions}
    assert ids == set(pack.questions)
    for q in report.questions:
        assert 0.0 <= q.agreement <= 1.0 and q.n == 5
    assert report.jev_input_tokens > 0 and report.jev_cost_usd > 0
    md = render_markdown(report)
    assert "| question |" in md and "hook_strength" in md


async def test_score_pack_counts_judge_failed_items_as_skipped():
    class FailsOnFirst(RecordedJudge):
        async def judge(self, post_id, *args, **kwargs):
            if post_id == "local:fx-001":
                raise JudgeFailed(post_id, 3, RuntimeError("boom"))
            return await super().judge(post_id, *args, **kwargs)

    pack = load_pack(PACK)
    report = await score_pack(
        pack, GOLDEN, FailsOnFirst(FIX), mode="raw", rubrics_dir=REPO / "rubrics"
    )
    assert report.n_items == 5 and report.n_skipped == 1
    assert all(q.n == 4 for q in report.questions)


def test_pack_summaries_still_lists_only_the_pack_with_the_sidecar_present():
    rubrics = REPO / "rubrics"
    assert (rubrics / "creator-hooks-v1.zh-examples.yaml").exists()
    assert [s.name for s in pack_summaries(rubrics)] == ["creator-hooks-v1"]  # sidecar skipped


def _fake_run(stdout: str, calls: list):
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return run


def test_claude_cli_translator_argv_and_parse(monkeypatch: pytest.MonkeyPatch):
    calls: list = []
    envelope = json.dumps(
        {
            "is_error": False,
            "structured_output": {"translations": ["A", "B"]},
            "total_cost_usd": 0.02,
        }
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(envelope, calls))
    tr = ClaudeCliTranslator(bin="/fake/claude", max_budget_usd=0.5, model="haiku", timeout_s=7)
    assert tr.translate([]) == ([], 0.0) and calls == []  # nothing to translate, no process
    out, cost = tr.translate(["甲", "乙"])
    assert out == ["A", "B"] and cost == 0.02
    ((argv, kwargs),) = calls
    assert argv[:2] == ["/fake/claude", "-p"] and argv[-1] == tr.TASK
    for flag, value in (
        ("--model", "haiku"),
        ("--effort", "low"),
        ("--tools", ""),
        ("--setting-sources", ""),
        ("--output-format", "json"),
        ("--json-schema", tr.SCHEMA),
        ("--max-budget-usd", "0.5"),
        ("--system-prompt", tr.SYSTEM_PROMPT),
    ):
        assert argv[argv.index(flag) + 1] == value
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert kwargs["timeout"] == 7 and kwargs["check"] is False and kwargs["text"] is True
    assert json.loads(kwargs["input"]) == {"texts": ["甲", "乙"]}


def test_claude_cli_translator_timeout_and_bad_envelopes(monkeypatch: pytest.MonkeyPatch):
    tr = ClaudeCliTranslator(timeout_s=3)

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out after 3s"):
        tr.translate(["x"])
    monkeypatch.setattr(
        subprocess, "run", _fake_run(json.dumps({"is_error": True, "result": "budget"}), [])
    )
    with pytest.raises(RuntimeError, match="translation failed: budget"):
        tr.translate(["x"])
    short = json.dumps({"is_error": False, "structured_output": {"translations": ["only one"]}})
    monkeypatch.setattr(subprocess, "run", _fake_run(short, []))
    with pytest.raises(RuntimeError, match="count mismatch 1 != 2"):
        tr.translate(["x", "y"])
