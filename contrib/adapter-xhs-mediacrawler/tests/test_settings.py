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
