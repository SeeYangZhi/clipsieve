from pathlib import Path

from clipsieve.config import Settings, get_settings


def test_defaults_when_env_empty(monkeypatch):
    for key in [
        "TYPESAFE_API_KEY",
        "CLIPSIEVE_EXPLAIN_BACKEND",
        "CLIPSIEVE_CLAUDE_BIN",
        "CLIPSIEVE_CLAUDE_MAX_BUDGET_USD",
        "ANTHROPIC_API_KEY",
        "YOUTUBE_API_KEY",
        "CLIPSIEVE_DATA_DIR",
        "CLIPSIEVE_CREATOR_SALT",
        "CLIPSIEVE_XHS_CHROME_CDP_PORT",
    ]:
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.typesafe_api_key == ""
    assert s.clipsieve_explain_backend == "claude_cli"
    assert s.clipsieve_claude_bin == "claude"
    assert s.clipsieve_claude_max_budget_usd == 3.0
    assert s.clipsieve_data_dir == Path("./data")
    assert s.clipsieve_xhs_chrome_cdp_port == 9222


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setenv("CLIPSIEVE_EXPLAIN_BACKEND", "fake")
    monkeypatch.setenv("CLIPSIEVE_DATA_DIR", "/tmp/clipsieve-test")
    monkeypatch.setenv("CLIPSIEVE_CLAUDE_MAX_BUDGET_USD", "1.5")
    s = Settings(_env_file=None)
    assert s.typesafe_api_key == "ts-test"
    assert s.clipsieve_explain_backend == "fake"
    assert s.clipsieve_data_dir == Path("/tmp/clipsieve-test")
    assert s.clipsieve_claude_max_budget_usd == 1.5


def test_invalid_backend_rejected(monkeypatch):
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("CLIPSIEVE_EXPLAIN_BACKEND", "gpt")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("CLIPSIEVE_CREATOR_SALT", "salt-a")
    a = get_settings()
    monkeypatch.setenv("CLIPSIEVE_CREATOR_SALT", "salt-b")
    b = get_settings()
    assert a is b
    assert a.clipsieve_creator_salt == "salt-a"
    get_settings.cache_clear()
