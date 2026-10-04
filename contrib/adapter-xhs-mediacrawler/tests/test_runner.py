# contrib/adapter-xhs-mediacrawler/tests/test_runner.py
import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from clipsieve_xhs.runner import MediaCrawlerRunner, RunnerOutput
from clipsieve_xhs.settings import XhsSettings


@pytest.fixture
def mc_dir(tmp_path: Path) -> Path:
    d = tmp_path / "MediaCrawler"
    (d / ".git").mkdir(parents=True)
    (d / "main.py").write_text("# stub\n")
    (d / "uv.lock").write_text("")
    return d


@pytest.fixture
def settings(mc_dir: Path) -> XhsSettings:
    return XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=mc_dir)


def test_build_argv_matches_mediacrawler_cli(settings, mc_dir, tmp_path):
    r = MediaCrawlerRunner(settings)
    argv = r.build_argv("新加坡人 上海 vlog", start_page=2, workdir=tmp_path)
    assert argv[:4] == ["uv", "run", "--project", str(mc_dir)]
    assert argv[4:6] == ["python", str(mc_dir / "main.py")]
    rest = argv[6:]
    assert rest == [
        "--platform",
        "xhs",
        "--lt",
        "qrcode",
        "--type",
        "search",
        "--keywords",
        "新加坡人 上海 vlog",
        "--start",
        "2",
        "--get_comment",
        "yes",
        "--get_sub_comment",
        "no",
        "--get_media",
        "no",
        "--save_data_option",
        "jsonl",
        "--save_data_path",
        str(tmp_path),
        "--headless",
        "no",
    ]


def test_output_dir_is_under_workdir(settings, tmp_path):
    # MediaCrawler writes f"{SAVE_DATA_PATH}/{platform}/{file_type}" (tools/async_file_writer.py)
    r = MediaCrawlerRunner(settings)
    assert r.output_dir(tmp_path) == tmp_path / "xhs" / "jsonl"


def test_read_records_skips_truncated_last_line(settings, tmp_path):
    p = tmp_path / "search_contents_2026-10-03.jsonl"
    good = {"note_id": "a1", "title": "完整"}
    p.write_text(
        json.dumps(good, ensure_ascii=False) + "\n" + '{"note_id": "a2", "title": "截断',
        encoding="utf-8",
    )
    r = MediaCrawlerRunner(settings)
    records, errors = r.read_records(p)
    assert records == [good]
    assert len(errors) == 1 and "line 2" in errors[0]


def test_read_records_accepts_json_array(settings, tmp_path):
    p = tmp_path / "search_contents_2026-10-03.json"
    p.write_text(json.dumps([{"note_id": "a1"}, {"note_id": "a2"}]), encoding="utf-8")
    r = MediaCrawlerRunner(settings)
    records, errors = r.read_records(p)
    assert [x["note_id"] for x in records] == ["a1", "a2"] and errors == []


@respx.mock
def test_healthcheck_ok(settings, mc_dir, monkeypatch):
    respx.get("http://127.0.0.1:9555/json/version").mock(
        return_value=httpx.Response(200, json={"Browser": "Chrome/130"})
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="380b426000aac3d612837ed72c99808347dc94c9\n", stderr=""
        ),
    )
    h = MediaCrawlerRunner(settings, cdp_port=9555).healthcheck()
    assert h.ok is True and "Chrome/130" in h.message


@respx.mock
def test_healthcheck_cdp_refused(settings, monkeypatch):
    respx.get("http://127.0.0.1:9555/json/version").mock(side_effect=httpx.ConnectError("refused"))
    h = MediaCrawlerRunner(settings, cdp_port=9555).healthcheck()
    assert h.ok is False and "Chrome" in h.message and "9555" in h.message


def test_healthcheck_checkout_missing(tmp_path):
    s = XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=tmp_path / "nope")
    h = MediaCrawlerRunner(s).healthcheck()
    assert h.ok is False and "MediaCrawler checkout" in h.message


@respx.mock
def test_healthcheck_wrong_commit(settings, monkeypatch):
    respx.get("http://127.0.0.1:9555/json/version").mock(
        return_value=httpx.Response(200, json={"Browser": "Chrome/130"})
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="deadbeef\n", stderr=""),
    )
    h = MediaCrawlerRunner(settings, cdp_port=9555).healthcheck()
    assert h.ok is False and "pinned" in h.message


def test_search_runs_in_the_checkout_and_collects_from_workdir(settings, tmp_path, monkeypatch):
    """MediaCrawler opens libs/*.js relative to cwd, so cwd must be the checkout; the output goes
    to the per-run workdir through --save_data_path."""
    calls = {}
    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["cwd"] = kwargs["cwd"]
        out = Path(argv[argv.index("--save_data_path") + 1]) / "xhs" / "jsonl"
        out.mkdir(parents=True)
        (out / "search_contents_2026-10-03.jsonl").write_text(
            '{"note_id": "n1"}\n', encoding="utf-8"
        )
        (out / "search_comments_2026-10-03.jsonl").write_text(
            '{"comment_id": "c1", "note_id": "n1"}\n', encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = MediaCrawlerRunner(settings)
    out = r.search("关键词", start_page=1, workdir=workdir)
    assert isinstance(out, RunnerOutput)
    assert calls["cwd"] == str(r.mc_dir)
    assert calls["argv"][7] == "xhs"
    assert calls["argv"][calls["argv"].index("--save_data_path") + 1] == str(workdir)
    assert out.notes == [{"note_id": "n1"}]
    assert out.comments == [{"comment_id": "c1", "note_id": "n1"}]
    assert out.returncode == 0 and out.errors == []


def test_search_timeout_returns_partial(settings, tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        out = Path(argv[argv.index("--save_data_path") + 1]) / "xhs" / "jsonl"
        out.mkdir(parents=True)
        (out / "search_contents_2026-10-03.jsonl").write_text(
            '{"note_id": "n1"}\n', encoding="utf-8"
        )
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = MediaCrawlerRunner(settings).search("x", 1, tmp_path)
    assert out.notes == [{"note_id": "n1"}]
    assert out.returncode == -1 and any("timed out" in e for e in out.errors)


def test_relative_mc_dir_resolves_against_repo_root_not_cwd(tmp_path, monkeypatch):
    from clipsieve.config import REPO_ROOT

    monkeypatch.chdir(tmp_path)
    s = XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=Path("../MediaCrawler"))
    r = MediaCrawlerRunner(s)
    assert r.mc_dir == (REPO_ROOT / "../MediaCrawler").resolve()
    assert r.mc_dir != (tmp_path / "../MediaCrawler").resolve()
    assert r.build_argv("x", 1, tmp_path)[3] == str(r.mc_dir)
