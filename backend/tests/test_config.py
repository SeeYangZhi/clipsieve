import os
import re
import stat
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clipsieve.config import REPO_ROOT, Settings, ensure_creator_salt, get_settings

ENV_KEYS = [
    "TYPESAFE_API_KEY",
    "CLIPSIEVE_EXPLAIN_BACKEND",
    "CLIPSIEVE_CLAUDE_BIN",
    "CLIPSIEVE_CLAUDE_MAX_BUDGET_USD",
    "ANTHROPIC_API_KEY",
    "YOUTUBE_API_KEY",
    "CLIPSIEVE_DATA_DIR",
    "CLIPSIEVE_CREATOR_SALT",
    "CLIPSIEVE_XHS_CHROME_CDP_PORT",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults_when_env_empty(clean_env):
    s = Settings(_env_file=None)
    assert s.typesafe_api_key == ""
    assert s.clipsieve_explain_backend == "claude_cli"
    assert s.clipsieve_claude_bin == "claude"
    assert s.clipsieve_claude_max_budget_usd == 3.0
    assert s.clipsieve_data_dir == REPO_ROOT / "data"
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


def test_repo_root_is_the_repository_root():
    assert (REPO_ROOT / "backend" / "pyproject.toml").is_file()
    assert (REPO_ROOT / "packages" / "schema").is_dir()
    assert REPO_ROOT.is_absolute()


def test_default_data_dir_resolves_against_repo_root_not_cwd(clean_env, tmp_path: Path):
    clean_env.chdir(tmp_path)
    assert Settings(_env_file=None).clipsieve_data_dir == REPO_ROOT / "data"


def test_relative_data_dir_from_env_resolves_against_repo_root(clean_env, tmp_path: Path):
    clean_env.chdir(tmp_path)
    clean_env.setenv("CLIPSIEVE_DATA_DIR", "runs-data")
    assert Settings(_env_file=None).clipsieve_data_dir == REPO_ROOT / "runs-data"


def test_absolute_data_dir_is_kept_as_given(clean_env, tmp_path: Path):
    clean_env.chdir(tmp_path)
    given = tmp_path / "elsewhere" / "data"
    clean_env.setenv("CLIPSIEVE_DATA_DIR", str(given))
    assert Settings(_env_file=None).clipsieve_data_dir == given


def test_env_file_reads_repo_root_first_then_cwd():
    env_files = Settings.model_config["env_file"]
    assert env_files == (REPO_ROOT / ".env", ".env")
    assert Path(env_files[0]).is_absolute()


def test_root_env_file_is_read_from_backend_cwd(clean_env, tmp_path: Path):
    """Hermetic stand-in for the real layout: a fake repo root with its own .env and backend/."""
    root = tmp_path / "repo"
    backend = root / "backend"
    backend.mkdir(parents=True)
    (root / ".env").write_text(
        "CLIPSIEVE_CREATOR_SALT=root-salt\nCLIPSIEVE_EXPLAIN_BACKEND=fake\n", encoding="utf-8"
    )
    clean_env.setitem(Settings.model_config, "env_file", (root / ".env", ".env"))
    clean_env.chdir(backend)
    s = Settings()
    assert s.clipsieve_creator_salt == "root-salt"
    assert s.clipsieve_explain_backend == "fake"
    (backend / ".env").write_text("CLIPSIEVE_CREATOR_SALT=backend-salt\n", encoding="utf-8")
    s = Settings()
    assert s.clipsieve_creator_salt == "backend-salt", "a cwd .env overrides the root one"
    assert s.clipsieve_explain_backend == "fake"


def test_ensure_creator_salt_creates_file_once(tmp_path: Path):
    data_dir = tmp_path / "fresh-data"  # does not exist yet
    s = Settings(_env_file=None, clipsieve_data_dir=data_dir, clipsieve_creator_salt="")
    with capture_logs() as logs:
        salt = ensure_creator_salt(s)
    salt_file = data_dir / "creator_salt"
    assert salt_file.is_file()
    assert re.fullmatch(r"[0-9a-f]{32}", salt)
    assert salt_file.read_text(encoding="utf-8").strip() == salt
    if os.name == "posix":
        assert stat.S_IMODE(salt_file.stat().st_mode) == 0o600
    assert [entry["event"] for entry in logs] == ["creator_salt_created"]
    assert salt not in str(logs), "the salt itself is never logged"
    with capture_logs() as logs:
        assert ensure_creator_salt(s) == salt
    assert logs == []


def test_ensure_creator_salt_reads_existing_file_stripped(data_dir: Path):
    (data_dir / "creator_salt").write_text("  existing-salt\n", encoding="utf-8")
    s = Settings(_env_file=None, clipsieve_data_dir=data_dir, clipsieve_creator_salt="")
    assert ensure_creator_salt(s) == "existing-salt"


def test_ensure_creator_salt_prefers_configured_value(data_dir: Path):
    s = Settings(_env_file=None, clipsieve_data_dir=data_dir, clipsieve_creator_salt="from-env")
    assert ensure_creator_salt(s) == "from-env"
    assert not (data_dir / "creator_salt").exists()


def test_ensure_creator_salt_replaces_empty_file(data_dir: Path):
    salt_file = data_dir / "creator_salt"
    salt_file.write_text("\n", encoding="utf-8")
    salt_file.chmod(0o644)
    s = Settings(_env_file=None, clipsieve_data_dir=data_dir, clipsieve_creator_salt="")
    salt = ensure_creator_salt(s)
    assert re.fullmatch(r"[0-9a-f]{32}", salt)
    assert salt_file.read_text(encoding="utf-8") == salt
    if os.name == "posix":
        assert stat.S_IMODE(salt_file.stat().st_mode) == 0o600
