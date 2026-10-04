from pathlib import Path

from clipsieve_xhs.settings import XhsSettings, get_xhs_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("CLIPSIEVE_XHS_MEDIACRAWLER_DIR", raising=False)
    monkeypatch.delenv("CLIPSIEVE_XHS_TIMEOUT_S", raising=False)
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_mediacrawler_dir == Path("../MediaCrawler")
    assert s.clipsieve_xhs_timeout_s == 900
    assert s.clipsieve_xhs_pinned_commit == "380b426000aac3d612837ed72c99808347dc94c9"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPSIEVE_XHS_MEDIACRAWLER_DIR", str(tmp_path / "mc"))
    monkeypatch.setenv("CLIPSIEVE_XHS_TIMEOUT_S", "120")
    get_xhs_settings.cache_clear()
    s = get_xhs_settings()
    assert s.clipsieve_xhs_mediacrawler_dir == tmp_path / "mc"
    assert s.clipsieve_xhs_timeout_s == 120


def test_empty_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_XHS_TIMEOUT_S", "")
    monkeypatch.setenv("CLIPSIEVE_XHS_MEDIACRAWLER_DIR", "")
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_timeout_s == 900
    assert s.clipsieve_xhs_mediacrawler_dir == Path("../MediaCrawler")


def test_note_kinds_and_max_pages_defaults(monkeypatch):
    monkeypatch.delenv("CLIPSIEVE_XHS_NOTE_KINDS", raising=False)
    monkeypatch.delenv("CLIPSIEVE_XHS_MAX_PAGES", raising=False)
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_note_kinds == "all"
    assert s.clipsieve_xhs_max_pages == 10


def test_note_kinds_rejects_unknown_value():
    import pytest

    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_note_kinds="audio")
    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_max_pages=0)


def test_api_runner_defaults(monkeypatch):
    for name in (
        "CLIPSIEVE_XHS_RUNNER",
        "CLIPSIEVE_XHS_COMMENTS",
        "CLIPSIEVE_XHS_REQUEST_INTERVAL_S",
        "CLIPSIEVE_XHS_PAGE_SIZE",
        "CLIPSIEVE_XHS_MAX_PAGES",
    ):
        monkeypatch.delenv(name, raising=False)
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_runner == "api"
    assert s.clipsieve_xhs_comments is False
    assert s.clipsieve_xhs_request_interval_s == 1.0
    assert s.clipsieve_xhs_page_size == 20
    assert s.clipsieve_xhs_max_pages == 10


def test_api_runner_settings_validate():
    import pytest

    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_runner="playwright")
    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_page_size=21)
    with pytest.raises(ValueError):
        XhsSettings(_env_file=None, clipsieve_xhs_request_interval_s=-1)


def test_api_runner_settings_from_env(monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_XHS_RUNNER", "mediacrawler")
    monkeypatch.setenv("CLIPSIEVE_XHS_COMMENTS", "1")
    monkeypatch.setenv("CLIPSIEVE_XHS_REQUEST_INTERVAL_S", "0.5")
    s = XhsSettings(_env_file=None)
    assert s.clipsieve_xhs_runner == "mediacrawler"
    assert s.clipsieve_xhs_comments is True
    assert s.clipsieve_xhs_request_interval_s == 0.5
