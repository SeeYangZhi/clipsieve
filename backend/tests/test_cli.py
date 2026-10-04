import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipsieve import cli
from clipsieve.cli import app
from clipsieve.config import Settings
from clipsieve.explain.base import ExplainError
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.models import Run, RunEvent

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BRIEF_ZH = "新加坡人搬到上海的生活 vlog"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _settings_from_env_only(monkeypatch):
    """Settings come from the CliRunner env alone: never a real .env, never a stale cache."""
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))


def env(tmp_path):
    return {
        "CLIPSIEVE_DATA_DIR": str(tmp_path),
        "CLIPSIEVE_EXPLAIN_BACKEND": "fake",
        "CLIPSIEVE_FIXTURE_DIR": str(FIXTURES),
    }


def run_args(*extra):
    return ["run", "--brief", "b", "--platforms", "local", "--limit", "5", *extra]


def run_id_of(output):
    return re.search(r"run_id: (run_\w+)", output).group(1)


def stored_run(data_dir, run_id):
    return Run.model_validate_json((data_dir / "runs" / run_id / "run.json").read_text("utf-8"))


def test_help_lists_the_five_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "replay", "reselect", "reindex", "eval"):
        assert command in result.output


def test_run_auto_approve_completes_and_prints_summary(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            "--brief",
            "新加坡人 Shanghai vlog",
            "--platforms",
            "local",
            "--limit",
            "5",
            "--pack",
            "creator-hooks-v1",
            "--auto-approve",
        ],
        env=env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    m = re.search(r"run_id: (run_[0-9a-f]{12})", result.output)
    assert m
    assert result.stdout.splitlines()[0] == f"run_id: {m.group(1)}"
    assert "stage: done" in result.output
    assert "collected: 5" in result.output and "shortlisted:" in result.output
    assert "jev_cost_usd:" in result.output
    assert "progress: planning -> collecting" in result.output
    assert "progress: explaining -> done" in result.output
    assert (tmp_path / "runs" / m.group(1) / "report.json").exists()
    assert stored_run(tmp_path, m.group(1)).stage.value == "done"


def test_run_emits_run_created_exactly_once(tmp_path):
    result = runner.invoke(app, run_args("--auto-approve"), env=env(tmp_path))
    assert result.exit_code == 0, result.output
    lines = (tmp_path / "runs" / run_id_of(result.output) / "events.jsonl").read_text("utf-8")
    types = [json.loads(line)["type"] for line in lines.splitlines()]
    assert types.count("run_created") == 1 and types[0] == "run_created"


def test_run_without_auto_approve_declined_exits_2(tmp_path):
    result = runner.invoke(app, run_args(), input="n\n", env=env(tmp_path))
    assert result.exit_code == 2
    assert "plan" in result.output.lower()
    assert "not approved" in result.output
    run = stored_run(tmp_path, run_id_of(result.output))
    assert run.stage.value == "planning"
    assert (tmp_path / "runs" / run.id / "plan.json").exists()


def test_run_confirmed_on_stdin_runs_to_done(tmp_path):
    result = runner.invoke(app, run_args(), input="y\n", env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "stage: done" in result.output


def test_run_with_no_answer_on_stdin_exits_2_and_names_auto_approve(tmp_path):
    result = runner.invoke(app, run_args(), input="", env=env(tmp_path))
    assert result.exit_code == 2, result.output
    assert "--auto-approve" in result.output
    assert stored_run(tmp_path, run_id_of(result.output)).stage.value == "planning"


def test_run_unknown_platform_or_pack_is_a_usage_error(tmp_path):
    result = runner.invoke(
        app,
        ["run", "--brief", "b", "--platforms", "local,nope", "--auto-approve"],
        env=env(tmp_path),
    )
    assert result.exit_code == 2 and "no adapter for: nope" in result.output
    result = runner.invoke(
        app, run_args("--pack", "no-such-pack", "--auto-approve"), env=env(tmp_path)
    )
    assert result.exit_code == 2 and "unknown rubric pack" in result.output
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())


def test_run_with_a_yaml_that_is_not_a_pack_is_a_usage_error(tmp_path, monkeypatch):
    rubrics = tmp_path / "rubrics"
    rubrics.mkdir()
    real = Path(__file__).resolve().parents[2] / "rubrics" / "creator-hooks-v1.yaml"
    (rubrics / real.name).write_text(real.read_text("utf-8"), encoding="utf-8")
    (rubrics / "foo.zh-examples.yaml").write_text('hook_type:\n  story: "例"\n', "utf-8")
    monkeypatch.setattr("clipsieve.api.context.RUBRICS_DIR_DEFAULT", rubrics)
    data = tmp_path / "data"
    result = runner.invoke(
        app, run_args("--pack", "foo.zh-examples", "--auto-approve"), env=env(data)
    )
    assert result.exit_code == 2 and "unknown rubric pack: foo.zh-examples" in result.output
    assert not (data / "runs").exists() or not any((data / "runs").iterdir())


def test_run_that_fails_exits_1(tmp_path, monkeypatch):
    def broken(self, packet):
        raise ExplainError("backend down")

    monkeypatch.setattr(FakeExplainBackend, "explain", broken)
    result = runner.invoke(app, run_args("--auto-approve"), env=env(tmp_path))
    assert result.exit_code == 1, result.output
    assert "stage: failed" in result.output
    assert "backend down" in result.output


def test_planning_failure_is_logged_as_an_error_event_and_exits_1(tmp_path, monkeypatch):
    def broken(self, brief, packs, platforms):
        raise ExplainError("planner down")

    monkeypatch.setattr(FakeExplainBackend, "plan", broken)
    result = runner.invoke(app, run_args("--auto-approve"), env=env(tmp_path))
    assert result.exit_code == 1, result.output
    assert "planner down" in result.output
    run = stored_run(tmp_path, run_id_of(result.output))
    assert run.stage.value == "planning" and run.counters.errors == 1
    lines = (tmp_path / "runs" / run.id / "events.jsonl").read_text("utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["type"] == "error" and last["payload"]["where"] == "planner"
    assert last["payload"]["recoverable"] is True


def test_data_dir_option_overrides_the_environment(tmp_path):
    flag_dir = tmp_path / "flag"
    e = env(tmp_path / "env")
    result = runner.invoke(app, run_args("--auto-approve", "--data-dir", str(flag_dir)), env=e)
    assert result.exit_code == 0, result.output
    run_id = run_id_of(result.output)
    assert (flag_dir / "runs" / run_id / "events.jsonl").exists()
    assert not (tmp_path / "env" / "runs" / run_id).exists()
    replayed = runner.invoke(
        app, ["replay", run_id, "--speed", "0", "--data-dir", str(flag_dir)], env=e
    )
    assert replayed.exit_code == 0 and run_id in replayed.output
    assert runner.invoke(app, ["replay", run_id], env=e).exit_code == 1


def test_replay_prints_events_in_order_fast(tmp_path):
    r = runner.invoke(
        app,
        ["run", "--brief", BRIEF_ZH, "--platforms", "local", "--limit", "5", "--auto-approve"],
        env=env(tmp_path),
    )
    run_id = re.search(r"run_id: (run_\w+)", r.output).group(1)
    result = runner.invoke(app, ["replay", run_id, "--speed", "1000"], env=env(tmp_path))
    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
    assert [e["seq"] for e in lines] == list(range(1, len(lines) + 1))
    assert lines[0]["type"] == "run_created" and lines[-1]["type"] == "done"
    assert len(lines) == len(result.stdout.splitlines())  # stdout holds the events only
    assert BRIEF_ZH in result.stdout  # real UTF-8, not \u escapes
    assert lines[0]["payload"]["brief"]["text"] == BRIEF_ZH


def test_replay_sleeps_the_original_gaps_divided_by_speed(tmp_path, monkeypatch):
    run_id = "run_000000000001"
    root = tmp_path / "runs" / run_id
    root.mkdir(parents=True)
    t0 = datetime(2026, 10, 4, tzinfo=UTC)
    events = [
        RunEvent(run_id=run_id, seq=1, ts=t0, type="run_created", stage="planning", payload={}),
        RunEvent(
            run_id=run_id,
            seq=2,
            ts=t0 + timedelta(seconds=2),
            type="stage_changed",
            stage="collecting",
            payload={"from": "planning", "to": "collecting"},
        ),
        RunEvent(
            run_id=run_id,
            seq=3,
            ts=t0 + timedelta(seconds=5),
            type="done",
            stage="done",
            payload={},
        ),
    ]
    (root / "events.jsonl").write_text(
        "".join(e.model_dump_json() + "\n" for e in events), encoding="utf-8"
    )
    slept: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", slept.append)

    result = runner.invoke(app, ["replay", run_id, "--speed", "2"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert slept == [1.0, 1.5]
    assert [json.loads(line)["seq"] for line in result.stdout.splitlines()] == [1, 2, 3]

    slept.clear()
    result = runner.invoke(app, ["replay", run_id], env=env(tmp_path))
    assert result.exit_code == 0 and slept == [2.0, 3.0]  # speed 1.0: original timing

    slept.clear()
    result = runner.invoke(app, ["replay", run_id, "--speed", "0"], env=env(tmp_path))
    assert result.exit_code == 0 and slept == []  # 0: no delay at all

    result = runner.invoke(app, ["replay", run_id, "--speed", "-1"], env=env(tmp_path))
    assert result.exit_code == 2


def test_reselect_and_reindex(tmp_path):
    r = runner.invoke(app, run_args("--auto-approve"), env=env(tmp_path))
    run_id = re.search(r"run_id: (run_\w+)", r.output).group(1)
    result = runner.invoke(
        app, ["reselect", run_id, "--weights", "hook_strength=1.0"], env=env(tmp_path)
    )
    assert result.exit_code == 0 and "shortlist" in result.output
    selection = json.loads(result.stdout)
    assert "shortlist" in selection and "scores" in selection
    result = runner.invoke(app, ["reindex", run_id], env=env(tmp_path))
    assert result.exit_code == 0 and "reindexed" in result.output


def test_reselect_bad_weights_is_a_usage_error(tmp_path):
    result = runner.invoke(
        app, ["reselect", "run_nope", "--weights", "hook_strength"], env=env(tmp_path)
    )
    assert result.exit_code == 2
    result = runner.invoke(
        app, ["reselect", "run_nope", "--weights", "hook_strength=x"], env=env(tmp_path)
    )
    assert result.exit_code == 2


def test_reselect_before_any_selection_exits_1(tmp_path):
    r = runner.invoke(app, run_args(), input="n\n", env=env(tmp_path))
    run_id = run_id_of(r.output)
    result = runner.invoke(
        app, ["reselect", run_id, "--weights", "hook_strength=1"], env=env(tmp_path)
    )
    assert result.exit_code == 1 and "no selection" in result.output


def test_unknown_run_exits_1(tmp_path):
    result = runner.invoke(app, ["replay", "run_nope"], env=env(tmp_path))
    assert result.exit_code == 1 and "not found" in result.output
    for args in (["reselect", "run_nope", "--weights", "hook_strength=1"], ["reindex", "run_nope"]):
        result = runner.invoke(app, args, env=env(tmp_path))
        assert result.exit_code == 1 and "not found" in result.output
