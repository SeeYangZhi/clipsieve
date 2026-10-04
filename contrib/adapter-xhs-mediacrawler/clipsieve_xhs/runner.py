# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/runner.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from clipsieve.adapters.base import AdapterHealth
from clipsieve.config import REPO_ROOT
from clipsieve.logging import get_logger
from clipsieve_xhs.settings import XhsSettings

log = get_logger(__name__)

CONTENTS_GLOB = "search_contents_*"
COMMENTS_GLOB = "search_comments_*"


@dataclass
class RunnerOutput:
    notes: list[dict]
    comments: list[dict]
    errors: list[str] = field(default_factory=list)
    returncode: int = 0
    stderr_tail: str = ""
    # The runner's session is dead for the rest of the run (login expired, risk control, rate
    # limit): the adapter yields this page's notes, then raises so core stops the platform.
    # Only the api runner sets it.
    fatal: bool = False


class RunnerProtocol(Protocol):
    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput: ...
    def healthcheck(self) -> AdapterHealth: ...


class MediaCrawlerRunner:
    """Drives a pinned MediaCrawler checkout as a subprocess. Never imports it."""

    def __init__(
        self, settings: XhsSettings, http: httpx.Client | None = None, cdp_port: int = 9222
    ) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=1.0)
        self.cdp_port = cdp_port  # owned by core Settings.clipsieve_xhs_chrome_cdp_port

    @property
    def mc_dir(self) -> Path:
        d = self.settings.clipsieve_xhs_mediacrawler_dir.expanduser()
        if not d.is_absolute():
            d = REPO_ROOT / d  # never the cwd: uvicorn runs from backend/, tests from contrib/
        return d.resolve()

    def build_argv(self, keyword: str, start_page: int, workdir: Path) -> list[str]:
        return [
            "uv",
            "run",
            "--project",
            str(self.mc_dir),
            "python",
            str(self.mc_dir / "main.py"),
            "--platform",
            "xhs",
            "--lt",
            "qrcode",
            "--type",
            "search",
            "--keywords",
            keyword,
            "--start",
            str(start_page),
            "--get_comment",
            "yes",
            "--get_sub_comment",
            "no",
            "--get_media",
            "no",
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(workdir),
            "--headless",
            "no",
        ]

    def output_dir(self, workdir: Path) -> Path:
        # MediaCrawler writes f"{SAVE_DATA_PATH}/{platform}/{file_type}"
        # (tools/async_file_writer.py); --save_data_path is the workdir, so nothing lands in
        # the checkout.
        return workdir / "xhs" / "jsonl"

    def read_records(self, path: Path) -> tuple[list[dict], list[str]]:
        text = path.read_text(encoding="utf-8")
        errors: list[str] = []
        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                return [], [f"{path.name}: invalid JSON array: {e}"]
            return ([data] if isinstance(data, dict) else list(data)), errors
        records: list[dict] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"{path.name} line {i}: {e.msg}")
        return records, errors

    def _collect(self, workdir: Path) -> tuple[list[dict], list[dict], list[str]]:
        out = self.output_dir(workdir)
        notes: list[dict] = []
        comments: list[dict] = []
        errors: list[str] = []
        if not out.exists():
            return notes, comments, [f"no output directory {out}"]
        for p in sorted(out.glob(CONTENTS_GLOB)):
            recs, errs = self.read_records(p)
            notes.extend(recs)
            errors.extend(errs)
        for p in sorted(out.glob(COMMENTS_GLOB)):
            recs, errs = self.read_records(p)
            comments.extend(recs)
            errors.extend(errs)
        return notes, comments, errors

    def healthcheck(self) -> AdapterHealth:
        if not (self.mc_dir / "main.py").exists():
            return AdapterHealth(
                False,
                f"MediaCrawler checkout not found at {self.mc_dir}; "
                "set CLIPSIEVE_XHS_MEDIACRAWLER_DIR",
            )
        port = self.cdp_port
        try:
            resp = self.http.get(f"http://127.0.0.1:{port}/json/version")
            resp.raise_for_status()
            browser = resp.json().get("Browser", "unknown")
        except (httpx.HTTPError, ValueError) as e:
            return AdapterHealth(
                False, f"Chrome remote debugging not reachable on port {port}: {e}"
            )
        try:
            cp = subprocess.run(
                ["git", "-C", str(self.mc_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            head = cp.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return AdapterHealth(False, f"cannot read MediaCrawler commit: {e}")
        pinned = self.settings.clipsieve_xhs_pinned_commit
        if head != pinned:
            return AdapterHealth(
                False,
                f"MediaCrawler at {head[:12]} differs from pinned {pinned[:12]}; "
                f"run git checkout {pinned[:12]}",
            )
        return AdapterHealth(True, f"Chrome {browser} on port {port}; MediaCrawler {head[:12]}")

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        workdir.mkdir(parents=True, exist_ok=True)
        argv = self.build_argv(keyword, start_page, workdir)
        log.info("mediacrawler.start", keyword=keyword, start_page=start_page, workdir=str(workdir))
        errors: list[str] = []
        returncode = -1
        stderr_tail = ""
        try:
            cp = subprocess.run(
                argv,
                # MediaCrawler opens libs/*.js relative to cwd, so cwd must be the checkout.
                cwd=str(self.mc_dir),
                capture_output=True,
                text=True,
                timeout=self.settings.clipsieve_xhs_timeout_s,
                check=False,
            )
            returncode = cp.returncode
            stderr_tail = (cp.stderr or "")[-2000:]
            if returncode != 0:
                errors.append(f"mediacrawler exited {returncode}")
        except subprocess.TimeoutExpired:
            errors.append(
                f"mediacrawler timed out after {self.settings.clipsieve_xhs_timeout_s}s; "
                "using partial output"
            )
        except OSError as e:
            errors.append(f"cannot start mediacrawler: {e}")
        notes, comments, perrs = self._collect(workdir)
        errors.extend(perrs)
        log.info(
            "mediacrawler.done",
            keyword=keyword,
            notes=len(notes),
            comments=len(comments),
            errors=len(errors),
            returncode=returncode,
        )
        return RunnerOutput(
            notes=notes,
            comments=comments,
            errors=errors,
            returncode=returncode,
            stderr_tail=stderr_tail,
        )
