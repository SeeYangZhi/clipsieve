import json
import subprocess
from pathlib import Path

import pytest

from clipsieve.config import Settings
from clipsieve.explain import claude_cli
from clipsieve.explain.base import ExplainError, ExplainPacket, RubricPackSummary, get_backend
from clipsieve.explain.claude_cli import EXPLAIN_TASK, PLAN_TASK, ClaudeCliBackend
from clipsieve.models import Brief

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SHIM = str(FIXTURES / "claude-shim" / "claude")


@pytest.fixture
def packet(fixture_posts):
    # All five posts: the fixture report cites local:fx-001, -002 and -004.
    return ExplainPacket(
        brief=Brief(text="b", topic="t", audience="a", persona="p"),
        posts=fixture_posts,
        evidence={},
        judge={},
        aggregates={},
        keyframes={},
    )


@pytest.fixture
def shim_env(monkeypatch, tmp_path):
    state = tmp_path / "shim.state"
    monkeypatch.setenv("CLIPSIEVE_SHIM_STATE", str(state))
    monkeypatch.delenv("CLIPSIEVE_SHIM_BAD_FIRST", raising=False)
    monkeypatch.delenv("CLIPSIEVE_SHIM_FAIL", raising=False)
    return state


def test_argv_is_exactly_the_contract(shim_env, packet):
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=2.5)
    backend.explain(packet)
    argv = Path(str(shim_env) + ".argv").read_text(encoding="utf-8").splitlines()
    assert argv[:12] == [
        "-p",
        "--model",
        "opus",
        "--effort",
        "high",
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--system-prompt-file",
    ]
    assert argv[12].endswith("prompts/explain.md")
    assert argv[13:16] == ["--output-format", "json", "--json-schema"]
    assert json.loads(argv[16])["title"] == "Report"
    assert argv[17:19] == ["--max-budget-usd", "2.5"]
    assert argv[19] == EXPLAIN_TASK
    assert "--bare" not in argv


def test_plan_and_explain_roundtrip(shim_env, packet):
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    plan = backend.plan(
        packet.brief,
        [RubricPackSummary(name="creator-hooks-v1", description="", question_ids=[])],
        ["youtube"],
    )
    assert plan.rubric_pack == "creator-hooks-v1"
    report = backend.explain(packet)
    assert report.patterns and report.run_id == "FIXTURE"


def test_bad_citation_retried_once_then_ok(shim_env, packet, monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_SHIM_BAD_FIRST", "1")
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    report = backend.explain(packet)
    assert "local:does-not-exist" not in {pid for p in report.patterns for pid in p.post_ids}
    argv = Path(str(shim_env) + ".argv").read_text(encoding="utf-8").splitlines()
    assert "local:does-not-exist" in argv[-1]  # retry task line names the unknown id


def test_bad_citation_twice_raises(shim_env, packet, monkeypatch):
    # Packet with no overlap with the fixture report -> every call cites unknown ids
    # -> ExplainError after one retry.
    monkeypatch.setenv("CLIPSIEVE_SHIM_BAD_FIRST", "0")
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    lonely = packet.model_copy(
        update={"posts": [packet.posts[0].model_copy(update={"id": "local:only"})]}
    )
    with pytest.raises(ExplainError) as ei:
        backend.explain(lonely)
    assert "unknown post ids" in str(ei.value)


def test_is_error_envelope_raises(shim_env, packet, monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_SHIM_FAIL", "1")
    with pytest.raises(ExplainError) as ei:
        ClaudeCliBackend(bin=SHIM, max_budget_usd=3).explain(packet)
    assert "shim failure" in str(ei.value)


def test_missing_binary_raises(packet):
    with pytest.raises(ExplainError):
        ClaudeCliBackend(bin="/definitely/not/claude", max_budget_usd=3).explain(packet)


def test_get_backend_claude_cli_uses_settings(shim_env, packet):
    settings = Settings(
        _env_file=None,
        clipsieve_explain_backend="claude_cli",
        clipsieve_claude_bin=SHIM,
        clipsieve_claude_max_budget_usd=1.5,
    )
    backend = get_backend(settings)
    assert isinstance(backend, ClaudeCliBackend)
    backend.explain(packet)
    argv = Path(str(shim_env) + ".argv").read_text(encoding="utf-8").splitlines()
    assert argv[17:19] == ["--max-budget-usd", "1.5"]


# Below, `subprocess.run` is replaced by a scripted fake: no binary runs at all.


def completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def envelope(structured: object, returncode: int = 0) -> subprocess.CompletedProcess:
    body = {"is_error": False, "structured_output": structured, "total_cost_usd": 0.0}
    return completed(json.dumps(body), returncode)


@pytest.fixture
def fake_run(monkeypatch):
    calls: list[dict] = []
    replies: list = []

    def run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(claude_cli.subprocess, "run", run)
    return calls, replies


def test_timeout_is_enforced_and_raises(fake_run, packet):
    calls, replies = fake_run
    replies.append(subprocess.TimeoutExpired(cmd="claude", timeout=900))
    with pytest.raises(ExplainError, match="timed out after 900s"):
        ClaudeCliBackend(bin="claude", max_budget_usd=3).explain(packet)
    assert calls[0]["timeout"] == 900 and calls[0]["check"] is False
    assert json.loads(calls[0]["input"])["mode"] == "explain"  # packet goes on stdin


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (completed("", returncode=1, stderr="Error: not logged in"), "not logged in"),
        (completed("oops"), "non-JSON"),
        (completed('{"is_error": false}'), "no structured_output"),
        (completed('{"is_error": true, "subtype": "error_max_budget_usd"}', 1), "max_budget"),
        (envelope({}, returncode=1), "exited 1"),
    ],
)
def test_cli_failures_raise(fake_run, packet, reply, message):
    _, replies = fake_run
    replies.append(reply)
    with pytest.raises(ExplainError, match=message):
        ClaudeCliBackend(bin="claude", max_budget_usd=3).explain(packet)


def test_plan_schema_failure_retried_once_then_ok(fake_run, packet):
    calls, replies = fake_run
    plan_fixture = json.loads((FIXTURES / "explain" / "plan.json").read_text(encoding="utf-8"))
    replies.extend([envelope({"run_id": "x"}), envelope(plan_fixture)])
    plan = ClaudeCliBackend(bin="claude", max_budget_usd=3).plan(packet.brief, [], ["youtube"])
    assert plan.rubric_pack == "creator-hooks-v1"
    assert calls[0]["argv"][-1] == PLAN_TASK
    retry_task = calls[1]["argv"][-1]
    assert retry_task.startswith(PLAN_TASK) and "failed schema validation" in retry_task
    assert "Return a valid Plan." in retry_task


def test_schema_failure_twice_raises(fake_run, packet):
    calls, replies = fake_run
    replies.extend([envelope({}), envelope({})])
    with pytest.raises(ExplainError, match="failed schema validation"):
        ClaudeCliBackend(bin="claude", max_budget_usd=3).explain(packet)
    assert len(calls) == 2  # one retry, never a third call
