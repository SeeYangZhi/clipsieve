"""`sieve eval` and the calibration writer. No network: RecordedJudge fixtures, fake translators."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipsieve.calibration import RESULTS_END, RESULTS_START, write_results
from clipsieve.cli import app
from clipsieve.config import Settings
from clipsieve.judge.recorded import RecordedJudge

REPO = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
GOLDEN = FIX / "golden" / "sample-5.jsonl"
runner = CliRunner()

if str(REPO) not in sys.path:  # `evals.score` is patched by module path below
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    # No real .env and no cached settings leak in (same trick as tests/test_cli.py).
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("clipsieve.cli.get_settings", lambda: Settings(_env_file=None))


@pytest.fixture
def rubrics(tmp_path):
    """A rubrics dir holding a copy of the real pack, so the calibration file lands in tmp."""
    d = tmp_path / "rubrics"
    d.mkdir()
    src = REPO / "rubrics" / "creator-hooks-v1.yaml"
    (d / "creator-hooks-v1.yaml").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return d


# ---- write_results --------------------------------------------------------------------------


def test_write_results_replaces_block_and_keeps_rest(tmp_path):
    p = tmp_path / "x.calibration.md"
    p.write_text(
        "# Calibration\n\nintro\n\n<!-- results:start -->\nold\n<!-- results:end -->\n\nfooter\n",
        encoding="utf-8",
    )
    write_results(p, "zh-100", "raw", "| a |\n", datetime(2026, 10, 3, tzinfo=UTC))
    text = p.read_text(encoding="utf-8")
    assert "old" not in text and "intro" in text and "footer" in text
    assert (
        text.index(RESULTS_START)
        < text.index("### zh-100 raw (2026-10-03)")
        < text.index(RESULTS_END)
    )


def test_write_results_keys_sections_by_stem_and_mode(tmp_path):
    p = tmp_path / "x.calibration.md"
    write_results(p, "en-100", "raw", "| en raw |\n", datetime(2026, 10, 3, tzinfo=UTC))
    write_results(p, "zh-100", "raw", "| zh raw |\n", datetime(2026, 10, 3, tzinfo=UTC))
    write_results(p, "zh-100", "bilingual", "| zh bi |\n", datetime(2026, 10, 4, tzinfo=UTC))
    write_results(p, "zh-100", "raw", "| zh raw2 |\n", datetime(2026, 10, 5, tzinfo=UTC))
    text = p.read_text(encoding="utf-8")
    assert "| zh raw2 |" in text and "| zh raw |\n" not in text
    assert "| en raw |" in text and "| zh bi |" in text
    assert "### en-100 raw (2026-10-03)" in text and "### zh-100 raw (2026-10-05)" in text
    assert text.count("### zh-100 raw") == 1


def test_write_results_creates_file_with_header(tmp_path):
    p = tmp_path / "new.calibration.md"
    write_results(p, "zh-100", "raw", "| a |\n", datetime(2026, 10, 3, tzinfo=UTC))
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# new calibration") and RESULTS_START in text and RESULTS_END in text


def test_write_results_rewrite_is_idempotent(tmp_path):
    """Rewriting one section leaves the others byte-identical (no blank lines accumulate)."""
    p = tmp_path / "x.calibration.md"
    when = datetime(2026, 10, 3, tzinfo=UTC)
    write_results(p, "en-100", "raw", "| en |\n\n", when)
    write_results(p, "zh-100", "raw", "| zh |\n", when)
    before = p.read_text(encoding="utf-8")
    write_results(p, "zh-100", "raw", "| zh |\n", when)
    write_results(p, "zh-100", "raw", "| zh |\n", when)
    assert p.read_text(encoding="utf-8") == before


# ---- sieve eval -----------------------------------------------------------------------------


def test_eval_command_prints_table_and_writes_calibration(rubrics):
    result = runner.invoke(
        app,
        [
            "eval",
            "--pack",
            "creator-hooks-v1",
            "--golden",
            str(GOLDEN),
            "--mode",
            "raw",
            "--rubrics-dir",
            str(rubrics),
            "--judge-fixtures",
            str(FIX),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "| question |" in result.stdout and "hook_strength" in result.stdout
    cal = (rubrics / "creator-hooks-v1.calibration.md").read_text(encoding="utf-8")
    assert "### sample-5 raw (" in cal and "hook_strength" in cal
    assert f"wrote {rubrics / 'creator-hooks-v1.calibration.md'}" in result.output


def test_eval_rejects_unknown_mode():
    result = runner.invoke(
        app, ["eval", "--pack", "creator-hooks-v1", "--golden", str(GOLDEN), "--mode", "magic"]
    )
    assert result.exit_code == 2 and "mode" in result.output.lower()


def test_eval_unknown_pack_exits_2_without_a_traceback(tmp_path):
    result = runner.invoke(
        app,
        [
            "eval",
            "--pack",
            "no-such-pack",
            "--golden",
            str(GOLDEN),
            "--rubrics-dir",
            str(tmp_path),
            "--judge-fixtures",
            str(FIX),
        ],
    )
    assert result.exit_code == 2 and "no-such-pack" in result.output
    assert "Traceback" not in result.output


def test_eval_without_typesafe_key_or_fixtures_exits_2():
    result = runner.invoke(app, ["eval", "--pack", "creator-hooks-v1", "--golden", str(GOLDEN)])
    assert result.exit_code == 2 and "TYPESAFE_API_KEY" in result.output


def test_eval_translate_with_fixtures_is_refused(rubrics):
    """Fixtures replay recorded answers, so translating the state would only spend money."""
    result = runner.invoke(
        app,
        [
            "eval",
            "--pack",
            "creator-hooks-v1",
            "--golden",
            str(GOLDEN),
            "--mode",
            "translate",
            "--rubrics-dir",
            str(rubrics),
            "--judge-fixtures",
            str(FIX),
        ],
    )
    assert result.exit_code == 2 and "translate" in result.output
    assert not (rubrics / "creator-hooks-v1.calibration.md").exists()


class _FakeTranslator:
    built: list[tuple] = []
    calls: list[list[str]] = []
    fail: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:
        type(self).built.append((args, kwargs))

    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        if type(self).fail is not None:
            raise type(self).fail
        type(self).calls.append(list(texts))
        return list(texts), 0.0


@pytest.fixture
def real_mode(monkeypatch):
    """`--mode translate` against the "real" judge: TypeSafeJudge swapped for RecordedJudge
    (no network) and ClaudeCliTranslator swapped for a recording fake (no `claude`)."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setattr("clipsieve.cli.TypeSafeJudge", lambda api_key: RecordedJudge(FIX))
    _FakeTranslator.built, _FakeTranslator.calls, _FakeTranslator.fail = [], [], None
    monkeypatch.setattr("evals.score.ClaudeCliTranslator", _FakeTranslator)
    return _FakeTranslator


def _translate_args(rubrics):
    return [
        "eval",
        "--pack",
        "creator-hooks-v1",
        "--golden",
        str(GOLDEN),
        "--mode",
        "translate",
        "--rubrics-dir",
        str(rubrics),
    ]


def test_eval_translate_builds_the_claude_translator(rubrics, real_mode):
    result = runner.invoke(app, _translate_args(rubrics))
    assert result.exit_code == 0, result.output
    assert real_mode.built == [(("claude",), {})]
    assert len(real_mode.calls) == 5 and all(real_mode.calls)  # one batch per golden item
    cal = (rubrics / "creator-hooks-v1.calibration.md").read_text(encoding="utf-8")
    assert "### sample-5 translate (" in cal


def test_eval_translator_failure_exits_1_without_traceback(rubrics, real_mode):
    real_mode.fail = OSError("claude: command not found")
    result = runner.invoke(app, _translate_args(rubrics))
    assert result.exit_code == 1, result.output
    assert "claude: command not found" in result.output
    assert "Traceback" not in result.output
    assert not (rubrics / "creator-hooks-v1.calibration.md").exists()


def test_eval_empty_golden_exits_2_before_any_judge_or_write(rubrics, tmp_path, monkeypatch):
    """A header-only golden set (as shipped) must not score, build a judge or touch the file."""
    golden = tmp_path / "empty-100.jsonl"
    golden.write_text("# labelled 2026-10-03, pack creator-hooks-v1\n\n", encoding="utf-8")
    cal = rubrics / "creator-hooks-v1.calibration.md"
    write_results(cal, "zh-100", "raw", "| keep |\n", datetime(2026, 10, 3, tzinfo=UTC))
    before = cal.read_text(encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("judge must not be constructed for an empty golden set")

    monkeypatch.setattr("clipsieve.cli.RecordedJudge", _boom)
    monkeypatch.setattr("clipsieve.cli.TypeSafeJudge", _boom)
    result = runner.invoke(
        app,
        [
            "eval",
            "--pack",
            "creator-hooks-v1",
            "--golden",
            str(golden),
            "--rubrics-dir",
            str(rubrics),
            "--judge-fixtures",
            str(FIX),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "golden set has no items" in result.output and "evals/README.md" in result.output
    assert cal.read_text(encoding="utf-8") == before


def test_render_markdown_shows_dash_when_a_question_has_no_samples():
    from evals.score import EvalReport, QuestionAgreement, render_markdown

    report = EvalReport(
        pack="p",
        mode="raw",
        n_items=0,
        questions=[
            QuestionAgreement(
                question_id="q",
                type="choice",
                n=0,
                correct=0,
                agreement=0.0,
                mean_conf_correct=0.5,
                mean_conf_incorrect=None,
            )
        ],
        jev_input_tokens=0,
        jev_cost_usd=0.0,
        translate_cost_usd=0.0,
    )
    assert "| q | choice | 0 | - | - | - |" in render_markdown(report)
