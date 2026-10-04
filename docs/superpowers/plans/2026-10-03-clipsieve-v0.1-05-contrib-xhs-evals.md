# clipsieve v0.1 Plan 05: Contrib Xiaohongshu Adapter and Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md` first; it is the binding contract and wins over this file.

**Goal:** Ship the community Xiaohongshu adapter as a separate package that drives a pinned MediaCrawler checkout in CDP mode and maps its output to `Post`, plus the evaluation harness (`evals/score.py`, `sieve eval`) that measures rubric-pack accuracy on golden sets in `raw`, `translate` and `bilingual` modes and writes calibration results.

**Architecture:** `contrib/adapter-xhs-mediacrawler/` is its own uv project that depends on the core `clipsieve` package by path and registers `XhsMediaCrawlerAdapter` through the `clipsieve.adapters` entry point group, so the core discovers it without importing it. MediaCrawler is not pip-installable (its `pyproject.toml` has no `[build-system]`), so the adapter shells out to a sibling checkout pinned to commit `380b426000aac3d612837ed72c99808347dc94c9` and parses the JSONL files it writes. The evals package is plain Python under `evals/` loaded by `sieve eval`; agreement metrics are computed in code against hand-labelled golden JSONL, with the Jev client and any translation step behind the existing `Judge` and a new `Translator` protocol so tests run on fixtures only.

**Tech Stack:** Python 3.12, uv, pydantic v2, pydantic-settings, httpx, structlog, typer, pytest, pytest-asyncio; MediaCrawler (external checkout, Typer CLI, Playwright CDP); TypeSafe `typesafe-sdk` via the core `Judge`.

**Spec:** `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md` (§5.4, §7.3, §13, §14)

## Global Constraints

- Python 3.12 exactly (`requires-python = ">=3.12,<3.13"`). Managed by `uv`. Never pip.
- Bun 1.3+ for all JS. Never npm, yarn or pnpm. Next.js 16, React 19, Tailwind 4, shadcn, ultracite 7 (Biome).
- Backend package name `clipsieve`, import root `backend/clipsieve/`. CLI command `sieve`.
- `structlog` only for logging. No `print()` in `backend/clipsieve/`. `print` is allowed in `cli.py` output helpers and in `packages/schema/generate.py`.
- Pydantic v2 everywhere. Settings via `pydantic-settings` reading `.env`.
- Every external system behind a Protocol with a fake: `Adapter`, `ASR`, `OCR`, `FrameExtractor`, `Judge`, `ExplainBackend`.
- Tests: `pytest` with `pytest-asyncio` (mode `auto`) in `backend/tests/`; Vitest in `frontend/`; one Playwright flow in `frontend/e2e/`. No live network in tests. CI uses fakes only.
- Commit after every task with a conventional-commit message ending in the two trailer lines `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu` (as in every commit block below).
- Every new directory with code gets an `AGENTS.md` (DOX child) in the same task that creates it, and the root `AGENTS.md` Child DOX Index is updated in that task.
- No file in the repo may contain a real API key. `.env.example` lists every variable with an empty value, except the two non-secret XHS settings that ship defaults (`CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler`, `CLIPSIEVE_XHS_TIMEOUT_S=900`; an empty integer would fail validation and silently hide the adapter).
- Chinese and English UI strings from the first component.

Plan-05 additions:

- The core package `backend/clipsieve/` never imports `clipsieve_xhs`. Discovery is only through the entry point group.
- The contrib package never vendors, copies or redistributes MediaCrawler code. It shells out to a user-provided checkout.
- Tests in `contrib/` and `evals/` never spawn MediaCrawler, never open Chrome, never call TypeSafe or Claude, and never touch the network (media downloads run under `respx`). All of those are faked.
- Lint: new Python is ruff-formatted (line length 100). Run `uv run ruff format <paths>` then `uv run ruff check <paths>` on the files a task created before its commit. XHS fixture JSON is formatted with `bunx ultracite fix` from the repo root (Task 3). Task 7 adds `evals/` and `contrib/` to the backend lint script so `bun run check` covers them.

## Review Focus

1. **Chinese survives byte-for-byte.** A note whose `title`, `desc`, `tag_list` and comments contain CJK, emoji and full-width punctuation must map to `Post` and serialise to JSON with identical code points. Pinned in Task 3 (`test_mapping_preserves_cjk_exactly`).
2. **MediaCrawler stops early or crashes mid-run.** A partial JSONL file (last line truncated) must yield every complete record and one structured error, not an exception that loses the batch. Pinned in Task 2 (`test_read_records_skips_truncated_last_line`).
3. **Image notes with zero images.** A `normal` note whose `image_list` is empty must still become a valid `Post` with `kind: image_note` and `media: []` rather than crash or be mis-typed as video. Pinned in Task 3 (`test_normal_note_without_images`).
4. **Healthcheck must never block a run of other adapters.** CDP port refused, checkout missing, or wrong pinned commit each return `AdapterHealth(ok=False, message=...)` within one second; the registry then hides the adapter instead of the brief page failing. Pinned in Task 2 (`test_healthcheck_*`).
5. **Eval must not silently compare against the wrong level indexing.** A golden score label is a 1-based level; Jev score answers are 0-indexed (overview E.3). The predicted level is the argmax `probabilities` key (else `round(value)`), minus the first level (minimum integer legend key, else 0), plus 1, clamped to `1..levels`. A one-off indexing bug would inflate or deflate every score agreement. Pinned in Task 5 (`test_predicted_level_*` and `test_score_agreement_within_one_level`, which use full 0-based dicts).

---

## Verified facts about MediaCrawler (used throughout)

Checked 2026-10-03 against `NanmiCoder/MediaCrawler` at `main` = `380b426000aac3d612837ed72c99808347dc94c9` (pushed 2026-09-19).

| Item | Verified value |
|---|---|
| Licence | `NON-COMMERCIAL LEARNING LICENSE 1.1` (SPDX: none). Not MIT. |
| Packaging | `pyproject.toml` has `name = "mediacrawler"`, `requires-python = ">=3.11"`, no `[build-system]`, no `[project.scripts]`. **Not installable from git**; run from a checkout with `uv run main.py`. |
| Install | `uv sync` then `uv run playwright install` inside the checkout. |
| CLI | Typer. Flags: `--platform {xhs,dy,ks,bili,wb,tieba,zhihu}`, `--lt {qrcode,phone,cookie}`, `--type {search,detail,creator}`, `--keywords <comma-separated>`, `--start <page>`, `--get_comment yes|no`, `--get_sub_comment yes|no`, `--get_media yes|no`, `--save_data_option {csv,db,json,jsonl,sqlite,mongodb,excel,postgres}`, `--headless yes|no`, `--init_db ...`. Booleans accept `yes/true/t/y/1` and `no/false/f/n/0`. |
| CDP config | `config/base_config.py`: `ENABLE_CDP_MODE = True`, `CDP_CONNECT_EXISTING = True`, `CDP_DEBUG_PORT = 9222`, `CDP_HEADLESS = False`, `AUTO_CLOSE_BROWSER = True`, `CUSTOM_BROWSER_PATH = ""`, `SAVE_LOGIN_STATE = True`, `CRAWLER_MAX_NOTES_COUNT = 15`, `CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 10`, `SAVE_DATA_PATH = ""`. **No CLI flag for `SAVE_DATA_PATH`, `CDP_DEBUG_PORT` or `CRAWLER_MAX_NOTES_COUNT`**, and `.env.example` does not expose them. |
| Output path | `tools/async_file_writer.py`: base dir is `f"{config.SAVE_DATA_PATH}/{platform}/{file_type}"` if `SAVE_DATA_PATH` is set, else `f"data/{platform}/{file_type}"` (relative to **cwd**). Filename is `f"{crawler_type}_{item_type}_{get_current_date()}.{file_type}"`, so a search run writes `data/xhs/jsonl/search_contents_<date>.jsonl` and `data/xhs/jsonl/search_comments_<date>.jsonl`. `json` option rewrites a whole array per item; `jsonl` appends one object per line. The exact `<date>` format was **not verified**; the runner globs `search_contents_*.jsonl`. |
| Note record keys | `note_id, type, title, desc, video_url, time, last_update_time, creator_hash, nickname, liked_count, collected_count, comment_count, share_count, image_list, tag_list, last_modify_ts, note_url, source_keyword, xsec_token`. `image_list` is a **comma-joined string** of URLs. `type` is passed through from the platform (`"normal"` or `"video"`). `video_url` is a comma-joined string, best quality first. MediaCrawler already **anonymises** the creator as `creator_hash` and masks `nickname`; raw `user_id` is not in the output. |
| Comment record keys | `comment_id, create_time, note_id, content, creator_hash, nickname, sub_comment_count, pictures, parent_comment_id, last_modify_ts, like_count`. |
| Media | `--get_media yes` downloads through `media_downloader/`; its on-disk layout was **not verified**. The adapter therefore downloads media itself from the URLs in the record. |
| Not verified | `tag_list` delimiter (assumed comma-joined like `image_list`); `time` unit (assumed epoch milliseconds, the Xiaohongshu web API convention); `liked_count` type (string on the platform, assumed string-or-int). All three are handled by the table-driven mapping in Task 3 and overridable in `mapping.py::FIELD_MAP` without touching logic. |

Consequences for this plan: MediaCrawler lives in a **sibling checkout** configured by `CLIPSIEVE_XHS_MEDIACRAWLER_DIR`; the runner pins it by checking `git rev-parse HEAD`; the runner controls the output location by setting the subprocess **cwd** to a per-run temp dir; the note limit is enforced on our side by stopping early and truncating, since `CRAWLER_MAX_NOTES_COUNT` has no flag.

---

## Interfaces consumed from plans 01 to 03 (exact names)

```python
from clipsieve.models import Post, PostText, Media, Metrics, Comment, Query, Brief, JudgeResult, JudgeAnswer, RubricPack, Question
from clipsieve.config import REPO_ROOT, Settings, ensure_creator_salt, get_settings
from clipsieve.adapters.base import Adapter, AdapterHealth, MediaDownloadError, hash_creator, incoming_dir   # MediaDownloadError: B.11; incoming_dir: B.1
from clipsieve.adapters.registry import ENTRY_POINT_GROUP, load_adapters
from clipsieve.store.paths import safe_post_filename
from clipsieve.judge.base import Judge, JudgeFailed, cost_usd
from clipsieve.judge.recorded import RecordedJudge
from clipsieve.judge.rubric import load_pack, find_pack, questions_for_pass, to_typesafe, from_typesafe
from clipsieve.explain.base import ExplainBackend, get_backend
from clipsieve.explain.claude_cli import ClaudeCliBackend
from clipsieve.planner.plan import pack_summaries
from clipsieve.cli import app as cli_app          # typer.Typer()
# backend/tests/adapters/contract.py
def run_adapter_contract(adapter: Adapter, query: Query, tmp_path: Path, limit: int = 3) -> list[Post]: ...   # ONE Query, not a list
```

Binding addenda from the overview that shape this plan: **A8** generated enums are `Enum` classes, so code and tests compare `post.kind.value == "video"`, never `post.kind == "video"`; **B1** adapters write raw payloads to `incoming_dir(data_dir, platform) / f"{safe_post_filename(post.id)}.json"` and set `raw_ref` to that absolute path (the Runner relocates it); **B2** `fetch_media` sets `Media.local_path` relative to `dest` as `video.mp4` or `img_00.jpg`; **B6** every adapter exposes `from_settings(settings)` and the registry loads entry points first; **A10** CI uses `astral-sh/setup-uv@v6`; **B10** the Runner relocates the raw file out of `incoming_dir` before `fetch_media`, so `fetch_media` must never read it (Task 4 keeps its own media-URL cache, overview C.15); **B11** `MediaDownloadError` lives in `clipsieve.adapters.base` and is imported, not redefined; **A11/A12** `Settings` reads `(REPO_ROOT/.env, .env)` and `ensure_creator_salt(settings)` is the only salt source.

Facts from the merged plan 03: `backend/clipsieve/cli.py` has `@app.command("eval") def eval_cmd(pack, golden, mode="raw")` with `Annotated` options; the stub prints a "plan 05" message and exits 2 (overview E.10). Task 6 edits `eval_cmd` in place; the command name stays `eval`.

---

### Task 1: Contrib package skeleton, settings, docs

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/pyproject.toml`
- Create: `contrib/adapter-xhs-mediacrawler/README.md`
- Create: `contrib/adapter-xhs-mediacrawler/AGENTS.md`
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/__init__.py`
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/settings.py`
- Create: `contrib/adapter-xhs-mediacrawler/tests/__init__.py`
- Create: `contrib/adapter-xhs-mediacrawler/tests/conftest.py`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_settings.py`
- Modify: `.env.example` (append two variables with working defaults)
- Modify: `AGENTS.md` (root Child DOX Index table row; rewrite the trailing paragraph)

**Interfaces:**
- Consumes: `clipsieve.config.REPO_ROOT` (env file location, relative-dir base) and `clipsieve.config.Settings.clipsieve_xhs_chrome_cdp_port: int` (default 9222).
- Produces: `clipsieve_xhs.settings.XhsSettings` with fields `clipsieve_xhs_mediacrawler_dir: Path = Path("../MediaCrawler")`, `clipsieve_xhs_timeout_s: int = 900`, `clipsieve_xhs_pinned_commit: str = "380b426000aac3d612837ed72c99808347dc94c9"`; `get_xhs_settings() -> XhsSettings`. `model_config`: `env_file=(REPO_ROOT / ".env", ".env")` (the same tuple as core `Settings`, so the repo-root `.env` is found when uvicorn runs from `backend/`), `extra="ignore"` (the shared `.env` holds every core variable), `env_ignore_empty=True` (an empty `CLIPSIEVE_XHS_TIMEOUT_S=` falls back to the default instead of failing validation).
- **Single owner of the CDP port: core `Settings.clipsieve_xhs_chrome_cdp_port`.** `XhsSettings` has no port field; the adapter reads the core setting in `from_settings`/`__init__` and passes it to `MediaCrawlerRunner(cdp_port=...)` (Task 2). A relative `clipsieve_xhs_mediacrawler_dir` is resolved against `REPO_ROOT` by the runner (Task 2), never against the cwd.

- [ ] **Step 1: Write the failing settings test**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_settings.py
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
```

- [ ] **Step 2: Create the uv project**

```toml
# contrib/adapter-xhs-mediacrawler/pyproject.toml
[project]
name = "clipsieve-adapter-xhs"
version = "0.1.0"
description = "Community Xiaohongshu adapter for clipsieve, driving a local MediaCrawler checkout in CDP mode."
readme = "README.md"
requires-python = ">=3.12,<3.13"
license = "Apache-2.0"
dependencies = [
  "clipsieve",
  "httpx>=0.27",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "structlog>=24.1",
]

[project.entry-points."clipsieve.adapters"]
xiaohongshu = "clipsieve_xhs.adapter:XhsMediaCrawlerAdapter"

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.25", "respx>=0.21", "ruff>=0.8"]

[tool.uv.sources]
clipsieve = { path = "../../backend", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["clipsieve_xhs"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

Why a path dependency and not a MediaCrawler dependency: MediaCrawler has no build backend, so `uv add git+https://github.com/NanmiCoder/MediaCrawler@380b426` fails to build. The checkout is a runtime requirement located through `CLIPSIEVE_XHS_MEDIACRAWLER_DIR`.

- [ ] **Step 3: Write settings module and package init**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/__init__.py
"""Community Xiaohongshu adapter for clipsieve. See README.md for licence constraints."""

__all__ = ["XhsMediaCrawlerAdapter"]


def __getattr__(name: str):
    if name == "XhsMediaCrawlerAdapter":
        from clipsieve_xhs.adapter import XhsMediaCrawlerAdapter

        return XhsMediaCrawlerAdapter
    raise AttributeError(name)
```

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/settings.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from clipsieve.config import REPO_ROOT

PINNED_COMMIT = "380b426000aac3d612837ed72c99808347dc94c9"


class XhsSettings(BaseSettings):
    # Relative paths are resolved against REPO_ROOT by MediaCrawlerRunner.mc_dir.
    # The CDP port is NOT here: core Settings.clipsieve_xhs_chrome_cdp_port owns it.
    clipsieve_xhs_mediacrawler_dir: Path = Path("../MediaCrawler")
    clipsieve_xhs_timeout_s: int = 900
    clipsieve_xhs_pinned_commit: str = PINNED_COMMIT

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )


@lru_cache
def get_xhs_settings() -> XhsSettings:
    return XhsSettings()
```

```python
# contrib/adapter-xhs-mediacrawler/tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from clipsieve_xhs.settings import get_xhs_settings

    get_xhs_settings.cache_clear()
    yield
    get_xhs_settings.cache_clear()
```

`tests/__init__.py` is empty.

- [ ] **Step 4: Install and run the test**

Run:
```bash
cd contrib/adapter-xhs-mediacrawler && uv sync && uv run pytest tests/test_settings.py -v
```
Expected: `3 passed`.

- [ ] **Step 5: Write README with disclaimer and setup**

````markdown
# clipsieve-adapter-xhs

Community Xiaohongshu (小红书) adapter for [clipsieve](../../README.md). It drives a **local checkout of [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)** in CDP mode against your own logged-in Chrome, then maps the notes and comments MediaCrawler writes into clipsieve `Post` records.

## Read this first

MediaCrawler is distributed under the **NON-COMMERCIAL LEARNING LICENSE 1.1**. Its README states (Chinese original, our translation): "本项目仅供学习和参考之用，禁止用于商业用途" — "This project is for learning and reference only; commercial use is prohibited" — and that it must not be used for any illegal purpose. By using this adapter you accept those terms for your MediaCrawler checkout.

clipsieve itself is Apache-2.0, but **this adapter does not change MediaCrawler's licence**. This package never copies MediaCrawler code; it runs your checkout as a subprocess.

**You are responsible for compliance with Xiaohongshu's terms of service and the laws that apply to you**, including personal-data law (PIPL, GDPR). clipsieve hashes creator identifiers and caps stored comments, and MediaCrawler already anonymises creators in its output, but collecting content you are not permitted to collect is on you, not on the tools.

## Setup

1. Clone MediaCrawler as a **sibling of the repo** (the default `CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler` is resolved against the clipsieve repo root, not your shell's cwd) and pin it to the commit this adapter was tested against:

   ```bash
   cd ..            # the directory that contains clipsieve/
   git clone https://github.com/NanmiCoder/MediaCrawler.git
   cd MediaCrawler && git checkout 380b426000aac3d612837ed72c99808347dc94c9
   uv sync && uv run playwright install
   ```

2. Start Chrome with remote debugging on the port clipsieve expects (default 9222) and log in to xiaohongshu.com in that Chrome:

   ```bash
   # macOS
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.clipsieve-chrome"
   ```

   On the first crawl MediaCrawler shows a QR code in that Chrome if you are not logged in. Scan it once; the session persists in that Chrome profile.

3. Point clipsieve at the checkout in the repo-root `.env` (the first two lines are the shipped defaults; the port is a core setting):

   ```text
   CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler
   CLIPSIEVE_XHS_CHROME_CDP_PORT=9222
   CLIPSIEVE_XHS_TIMEOUT_S=900
   ```

4. Install this adapter into the clipsieve backend environment so the core discovers it:

   ```bash
   cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler
   ```

   `GET /api/adapters` then lists `xiaohongshu` with its health. If health is false, the message says which of Chrome, the checkout or the pinned commit is wrong.

## What it collects

Per note: title, caption (`desc`), hashtags (`tag_list`), likes, saves, comments count, shares, post time, image URLs or video URL, up to 50 top-level comments sorted by likes, and the untouched MediaCrawler record as `raw_ref`. `creator_hash` is clipsieve's salted hash of MediaCrawler's already-anonymised `creator_hash`. Nicknames are kept only as `creator_display`.

## Limits

- Search only (`--type search`). Creator and detail modes are out of scope.
- MediaCrawler decides how many notes a search page yields; the adapter stops once `limit` posts are mapped and discards the rest.
- Media download is done by the adapter with plain HTTP GETs on the URLs in the record. Some CDN URLs expire; a failed download is reported as a recoverable error for that post.
````

- [ ] **Step 6: Write the DOX child and update the root index and `.env.example`**

```markdown
# contrib/adapter-xhs-mediacrawler — AGENTS.md

Community adapter. Inherits the root AGENTS.md; these rules are additive.

## Contract

- Registers `xiaohongshu = "clipsieve_xhs.adapter:XhsMediaCrawlerAdapter"` in entry point group `clipsieve.adapters`.
- **The core package never imports `clipsieve_xhs`.** If you need something from here in `backend/`, it belongs in the `Adapter` protocol instead.
- Never vendor MediaCrawler files. Drive the checkout at `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` as a subprocess (`runner.py`) and parse what it writes.
- Pinned MediaCrawler commit lives in `settings.py::PINNED_COMMIT` and in README step 1. Bump both together after re-running the fixture-based mapping tests against a real output sample.
- Settings: `XhsSettings` reads `(REPO_ROOT/.env, .env)` with `extra="ignore"` and `env_ignore_empty=True`; a relative `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` resolves against `REPO_ROOT`. The CDP port is owned by core `Settings.clipsieve_xhs_chrome_cdp_port`; do not re-declare it here.
- Media URLs are cached by the adapter in `<data_dir>/adapter-cache/xiaohongshu/<safe_id>.media.json` (written by `search`, read by `fetch_media`); `fetch_media` never reads the raw payload because the Runner relocates it first. A missing entry raises `MediaDownloadError` (imported from `clipsieve.adapters.base`).
- Stored raw payloads drop comment `creator_hash`, `nickname`, `pictures` and the note's `xsec_token`.
- Mapping is table-driven in `mapping.py::FIELD_MAP`. Unverified MediaCrawler details (date format in filenames, `tag_list` delimiter, `time` unit) are fixed there, not in logic.
- Tests never start MediaCrawler or Chrome. `FakeRunner` in `tests/conftest.py` replays `tests/fixtures/mediacrawler-output/`.

## Layout

- `clipsieve_xhs/settings.py` env settings (`CLIPSIEVE_XHS_*`).
- `clipsieve_xhs/runner.py` argv, subprocess, healthcheck, output discovery.
- `clipsieve_xhs/mapping.py` MediaCrawler record -> `Post`.
- `clipsieve_xhs/adapter.py` the `Adapter` implementation, raw payload writer and media-URL cache.
- `tests/fixtures/mediacrawler-output/` three realistic notes and their comments.
```

Append to repo-root `.env.example`:

```text
CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler
CLIPSIEVE_XHS_TIMEOUT_S=900
```

These two ship non-empty because an empty `CLIPSIEVE_XHS_TIMEOUT_S=` is not a valid integer (the adapter would be silently absent); `env_ignore_empty=True` is the second line of defence. `CLIPSIEVE_XHS_CHROME_CDP_PORT=` already exists from plan 01 and stays the only place the port is configured.

In root `AGENTS.md`, under `## Child DOX Index`, add a TABLE row after the `rubrics/AGENTS.md` row (the index is a two-column table, not a bullet list):

```markdown
| `contrib/adapter-xhs-mediacrawler/AGENTS.md` | Community Xiaohongshu adapter driving a MediaCrawler checkout; never imported by core |
```

Then rewrite the paragraph that follows the table so it no longer promises these files later. Replace it with:

```markdown
`frontend/` currently holds a placeholder `package.json` so root scripts resolve; plan 04 replaces it and adds `frontend/AGENTS.md`.
```

- [ ] **Step 7: Lint and commit**

Run:
```bash
cd contrib/adapter-xhs-mediacrawler && uv run ruff format . && uv run ruff check . && uv run pytest -q
```
Expected: no lint errors, `3 passed`.

```bash
git add contrib/adapter-xhs-mediacrawler .env.example AGENTS.md
git commit -m "feat(contrib-xhs): add adapter package skeleton, settings and licence docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 2: MediaCrawler runner: argv, output discovery, healthcheck

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/runner.py`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_runner.py`

**Interfaces:**
- Consumes: `XhsSettings`, `clipsieve.config.REPO_ROOT`, `clipsieve.adapters.base.AdapterHealth`.
- Produces:

```python
class RunnerProtocol(Protocol):
    def search(self, keyword: str, start_page: int, workdir: Path) -> "RunnerOutput": ...
    def healthcheck(self) -> AdapterHealth: ...

@dataclass
class RunnerOutput:
    notes: list[dict]
    comments: list[dict]
    errors: list[str]          # non-fatal parse problems
    returncode: int
    stderr_tail: str

class MediaCrawlerRunner(RunnerProtocol):
    def __init__(self, settings: XhsSettings, http: httpx.Client | None = None, cdp_port: int = 9222) -> None   # port comes from core Settings
    @property
    def mc_dir(self) -> Path                                # relative dir resolved against clipsieve.config.REPO_ROOT, then resolve()
    def build_argv(self, keyword: str, start_page: int) -> list[str]
    def output_dir(self, workdir: Path) -> Path            # workdir / "data" / "xhs" / "jsonl"
    def read_records(self, path: Path) -> tuple[list[dict], list[str]]
    def healthcheck(self) -> AdapterHealth
    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput
```

The argv is the verified MediaCrawler invocation (`--lt qrcode`, `--get_comment yes`); overview Addendum C.2 is amended to match.

- [ ] **Step 1: Write the failing runner tests**

```python
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


def test_build_argv_matches_mediacrawler_cli(settings, mc_dir):
    r = MediaCrawlerRunner(settings)
    argv = r.build_argv("新加坡人 上海 vlog", start_page=2)
    assert argv[:4] == ["uv", "run", "--project", str(mc_dir)]
    assert argv[4:6] == ["python", str(mc_dir / "main.py")]
    rest = argv[6:]
    assert rest == [
        "--platform", "xhs",
        "--lt", "qrcode",
        "--type", "search",
        "--keywords", "新加坡人 上海 vlog",
        "--start", "2",
        "--get_comment", "yes",
        "--get_sub_comment", "no",
        "--get_media", "no",
        "--save_data_option", "jsonl",
        "--headless", "no",
    ]


def test_output_dir_is_under_workdir(settings, tmp_path):
    r = MediaCrawlerRunner(settings)
    assert r.output_dir(tmp_path) == tmp_path / "data" / "xhs" / "jsonl"


def test_read_records_skips_truncated_last_line(settings, tmp_path):
    p = tmp_path / "search_contents_2026-10-03.jsonl"
    good = {"note_id": "a1", "title": "完整"}
    p.write_text(json.dumps(good, ensure_ascii=False) + "\n" + '{"note_id": "a2", "title": "截断', encoding="utf-8")
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
    respx.get("http://127.0.0.1:9555/json/version").mock(return_value=httpx.Response(200, json={"Browser": "Chrome/130"}))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="380b426000aac3d612837ed72c99808347dc94c9\n", stderr=""),
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
    respx.get("http://127.0.0.1:9555/json/version").mock(return_value=httpx.Response(200, json={"Browser": "Chrome/130"}))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="deadbeef\n", stderr=""),
    )
    h = MediaCrawlerRunner(settings, cdp_port=9555).healthcheck()
    assert h.ok is False and "pinned" in h.message


def test_search_runs_subprocess_in_workdir_and_collects(settings, tmp_path, monkeypatch):
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["cwd"] = kwargs["cwd"]
        out = Path(kwargs["cwd"]) / "data" / "xhs" / "jsonl"
        out.mkdir(parents=True)
        (out / "search_contents_2026-10-03.jsonl").write_text('{"note_id": "n1"}\n', encoding="utf-8")
        (out / "search_comments_2026-10-03.jsonl").write_text('{"comment_id": "c1", "note_id": "n1"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = MediaCrawlerRunner(settings)
    out = r.search("关键词", start_page=1, workdir=tmp_path)
    assert isinstance(out, RunnerOutput)
    assert calls["cwd"] == str(tmp_path)
    assert calls["argv"][7] == "xhs"
    assert out.notes == [{"note_id": "n1"}]
    assert out.comments == [{"comment_id": "c1", "note_id": "n1"}]
    assert out.returncode == 0 and out.errors == []


def test_search_timeout_returns_partial(settings, tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        out = Path(kwargs["cwd"]) / "data" / "xhs" / "jsonl"
        out.mkdir(parents=True)
        (out / "search_contents_2026-10-03.jsonl").write_text('{"note_id": "n1"}\n', encoding="utf-8")
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
    assert r.build_argv("x", 1)[3] == str(r.mc_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest tests/test_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve_xhs.runner'`.

- [ ] **Step 3: Implement the runner**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/runner.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx
import structlog

from clipsieve.adapters.base import AdapterHealth
from clipsieve.config import REPO_ROOT
from clipsieve_xhs.settings import XhsSettings

log = structlog.get_logger(__name__)

CONTENTS_GLOB = "search_contents_*"
COMMENTS_GLOB = "search_comments_*"


@dataclass
class RunnerOutput:
    notes: list[dict]
    comments: list[dict]
    errors: list[str] = field(default_factory=list)
    returncode: int = 0
    stderr_tail: str = ""


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

    def build_argv(self, keyword: str, start_page: int) -> list[str]:
        return [
            "uv", "run", "--project", str(self.mc_dir),
            "python", str(self.mc_dir / "main.py"),
            "--platform", "xhs",
            "--lt", "qrcode",
            "--type", "search",
            "--keywords", keyword,
            "--start", str(start_page),
            "--get_comment", "yes",
            "--get_sub_comment", "no",
            "--get_media", "no",
            "--save_data_option", "jsonl",
            "--headless", "no",
        ]

    def output_dir(self, workdir: Path) -> Path:
        # MediaCrawler writes f"data/{platform}/{file_type}" relative to cwd when SAVE_DATA_PATH is unset.
        return workdir / "data" / "xhs" / "jsonl"

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
            return AdapterHealth(False, f"MediaCrawler checkout not found at {self.mc_dir}; set CLIPSIEVE_XHS_MEDIACRAWLER_DIR")
        port = self.cdp_port
        try:
            resp = self.http.get(f"http://127.0.0.1:{port}/json/version")
            resp.raise_for_status()
            browser = resp.json().get("Browser", "unknown")
        except (httpx.HTTPError, ValueError) as e:
            return AdapterHealth(False, f"Chrome remote debugging not reachable on port {port}: {e}")
        try:
            cp = subprocess.run(
                ["git", "-C", str(self.mc_dir), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            head = cp.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            return AdapterHealth(False, f"cannot read MediaCrawler commit: {e}")
        pinned = self.settings.clipsieve_xhs_pinned_commit
        if head != pinned:
            return AdapterHealth(False, f"MediaCrawler at {head[:12]} differs from pinned {pinned[:12]}; run git checkout {pinned[:12]}")
        return AdapterHealth(True, f"Chrome {browser} on port {port}; MediaCrawler {head[:12]}")

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        workdir.mkdir(parents=True, exist_ok=True)
        argv = self.build_argv(keyword, start_page)
        log.info("mediacrawler.start", keyword=keyword, start_page=start_page, cwd=str(workdir))
        errors: list[str] = []
        returncode = -1
        stderr_tail = ""
        try:
            cp = subprocess.run(
                argv, cwd=str(workdir), capture_output=True, text=True,
                timeout=self.settings.clipsieve_xhs_timeout_s, check=False,
            )
            returncode = cp.returncode
            stderr_tail = (cp.stderr or "")[-2000:]
            if returncode != 0:
                errors.append(f"mediacrawler exited {returncode}")
        except subprocess.TimeoutExpired:
            errors.append(f"mediacrawler timed out after {self.settings.clipsieve_xhs_timeout_s}s; using partial output")
        except OSError as e:
            errors.append(f"cannot start mediacrawler: {e}")
        notes, comments, perrs = self._collect(workdir)
        errors.extend(perrs)
        log.info("mediacrawler.done", keyword=keyword, notes=len(notes), comments=len(comments), errors=len(errors), returncode=returncode)
        return RunnerOutput(notes=notes, comments=comments, errors=errors, returncode=returncode, stderr_tail=stderr_tail)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest tests/test_runner.py -v`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/clipsieve_xhs/runner.py contrib/adapter-xhs-mediacrawler/tests/test_runner.py
git commit -m "feat(contrib-xhs): add MediaCrawler subprocess runner with healthcheck and tolerant output parsing

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 3: Table-driven mapping from MediaCrawler records to Post

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/mapping.py`
- Create: `contrib/adapter-xhs-mediacrawler/tests/fixtures/mediacrawler-output/notes.json`
- Create: `contrib/adapter-xhs-mediacrawler/tests/fixtures/mediacrawler-output/comments.json`
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_mapping.py`

**Interfaces:**
- Consumes: `clipsieve.models.Post, PostText, Media, Metrics, Comment`, `clipsieve.adapters.base.hash_creator`.
- Produces:

```python
FIELD_MAP: dict[str, str]                 # our key -> MediaCrawler key, overridable
LIST_DELIMITER = ","
TIME_UNIT = "ms"                          # "ms" | "s"
MAX_COMMENTS = 50
def map_note(note: dict, comments: list[dict], salt: str, raw_ref: str, collected_at: datetime) -> Post
def group_comments(comments: list[dict]) -> dict[str, list[dict]]   # note_id -> top-level comments
def parse_count(value) -> int | None      # "1.2万" -> 12000, "3,210" -> 3210, 15 -> 15, "" -> None
def split_list(value) -> list[str]
def image_urls(note: dict) -> list[str]
def video_urls(note: dict) -> list[str]
```

- [ ] **Step 1: Write the fixtures**

```json
// contrib/adapter-xhs-mediacrawler/tests/fixtures/mediacrawler-output/notes.json
[
  {
    "note_id": "66f1a2b3c4d5e6f700000001",
    "type": "video",
    "title": "新加坡人搬来上海的第一周｜真实记录 🇸🇬➡️🇨🇳",
    "desc": "从樟宜机场到浦东，落地第一天就被外卖速度震惊了😂 这周的 vlog 记录了租房、办手机卡、第一次坐地铁迷路… #新加坡人在上海 #上海生活 #vlog日常",
    "video_url": "https://sns-video-bd.xhscdn.com/stream/1/110/258/01e7f1a2b3c4d5e6f7.mp4,https://sns-video-bd.xhscdn.com/stream/1/110/259/01e7f1a2b3c4d5e6f7_low.mp4",
    "time": 1758240000000,
    "last_update_time": 1758240000000,
    "creator_hash": "mc_7c1f4a9e2b",
    "nickname": "小*",
    "liked_count": "1.2万",
    "collected_count": "3456",
    "comment_count": "289",
    "share_count": "120",
    "image_list": "",
    "tag_list": "新加坡人在上海,上海生活,vlog日常",
    "last_modify_ts": 1759478400000,
    "note_url": "https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f700000001",
    "source_keyword": "新加坡人 上海 vlog",
    "xsec_token": "ABabc123"
  },
  {
    "note_id": "66f1a2b3c4d5e6f700000002",
    "type": "normal",
    "title": "在上海租房避坑指南（新加坡人视角）",
    "desc": "整理了我在静安、徐汇看房一个月的笔记，给同样从新加坡过来的朋友参考～ 价格、中介费、合同条款全在图里 👇",
    "video_url": "",
    "time": 1757030400000,
    "last_update_time": 1757030400000,
    "creator_hash": "mc_7c1f4a9e2b",
    "nickname": "小*",
    "liked_count": "876",
    "collected_count": "2,310",
    "comment_count": "64",
    "share_count": "33",
    "image_list": "https://sns-webpic-qc.xhscdn.com/202509/01/a1.jpg,https://sns-webpic-qc.xhscdn.com/202509/01/a2.jpg,https://sns-webpic-qc.xhscdn.com/202509/01/a3.jpg",
    "tag_list": "上海租房,新加坡人在上海,租房避坑",
    "last_modify_ts": 1759478400000,
    "note_url": "https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f700000002",
    "source_keyword": "新加坡人 上海 vlog",
    "xsec_token": "ABdef456"
  },
  {
    "note_id": "66f1a2b3c4d5e6f700000003",
    "type": "normal",
    "title": "Singlish in Shanghai: 每天被问「你是哪里人」",
    "desc": "lah、lor、leh 在上海完全没人懂，但大家都很友好 🥹",
    "video_url": "",
    "time": 1756425600000,
    "last_update_time": 1756425600000,
    "creator_hash": "mc_0a0b0c0d0e",
    "nickname": "J*",
    "liked_count": "",
    "collected_count": "",
    "comment_count": "0",
    "share_count": "",
    "image_list": "",
    "tag_list": "",
    "last_modify_ts": 1759478400000,
    "note_url": "https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f700000003",
    "source_keyword": "新加坡人 上海 vlog",
    "xsec_token": "ABghi789"
  }
]
```

```json
// contrib/adapter-xhs-mediacrawler/tests/fixtures/mediacrawler-output/comments.json
[
  {"comment_id": "c001", "create_time": 1758250000000, "note_id": "66f1a2b3c4d5e6f700000001", "content": "外卖速度真的离谱哈哈哈，欢迎来上海！", "creator_hash": "mc_1111", "nickname": "阿*", "sub_comment_count": "2", "pictures": "", "parent_comment_id": "0", "last_modify_ts": 1759478400000, "like_count": "230"},
  {"comment_id": "c002", "create_time": 1758250100000, "note_id": "66f1a2b3c4d5e6f700000001", "content": "同新加坡人，刚到上海一个月，求租房攻略🙏", "creator_hash": "mc_2222", "nickname": "L*", "sub_comment_count": "0", "pictures": "", "parent_comment_id": "0", "last_modify_ts": 1759478400000, "like_count": "98"},
  {"comment_id": "c003", "create_time": 1758250200000, "note_id": "66f1a2b3c4d5e6f700000001", "content": "回复 @L*：下期就出！", "creator_hash": "mc_7c1f4a9e2b", "nickname": "小*", "sub_comment_count": "0", "pictures": "", "parent_comment_id": "c002", "last_modify_ts": 1759478400000, "like_count": "12"},
  {"comment_id": "c004", "create_time": 1758250300000, "note_id": "66f1a2b3c4d5e6f700000001", "content": "地铁迷路那段笑死，我第一次也是坐反方向", "creator_hash": "mc_3333", "nickname": "M*", "sub_comment_count": "0", "pictures": "", "parent_comment_id": "0", "last_modify_ts": 1759478400000, "like_count": "415"},
  {"comment_id": "c005", "create_time": 1757040000000, "note_id": "66f1a2b3c4d5e6f700000002", "content": "中介费那条太真实了，被坑过一次", "creator_hash": "mc_4444", "nickname": "W*", "sub_comment_count": "1", "pictures": "", "parent_comment_id": "0", "last_modify_ts": 1759478400000, "like_count": "57"}
]
```

- [ ] **Step 2: Write the failing mapping tests**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_mapping.py
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipsieve.adapters.base import hash_creator
from clipsieve.models import Post
from clipsieve_xhs import mapping
from clipsieve_xhs.mapping import group_comments, map_note, parse_count, split_list

FIX = Path(__file__).parent / "fixtures" / "mediacrawler-output"
SALT = "test-salt"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def notes() -> list[dict]:
    return json.loads((FIX / "notes.json").read_text(encoding="utf-8"))


@pytest.fixture
def comments() -> dict[str, list[dict]]:
    return group_comments(json.loads((FIX / "comments.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "raw,expected",
    [("1.2万", 12000), ("3,210", 3210), (15, 15), ("", None), (None, None), ("0", 0), ("2.5w", 25000), ("abc", None)],
)
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


def test_split_list_handles_empty_and_delimiter():
    assert split_list("") == []
    assert split_list(None) == []
    assert split_list("a,b, c") == ["a", "b", "c"]
    assert split_list(["x", "y"]) == ["x", "y"]


def test_group_comments_keeps_only_top_level_sorted_by_likes(comments):
    top = comments["66f1a2b3c4d5e6f700000001"]
    assert [c["comment_id"] for c in top] == ["c004", "c001", "c002"]   # c003 is a reply, excluded


def test_video_note_maps_every_field(notes, comments):
    n = notes[0]
    post = map_note(n, comments[n["note_id"]], SALT, raw_ref="raw/xiaohongshu__66f1a2b3c4d5e6f700000001.json", collected_at=NOW)
    assert isinstance(post, Post)
    assert post.id == "xiaohongshu:66f1a2b3c4d5e6f700000001"
    assert post.platform.value == "xiaohongshu"
    assert post.url == "https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f700000001"
    assert post.kind.value == "video"
    assert post.creator_hash == hash_creator("mc_7c1f4a9e2b", SALT)
    assert post.creator_display == "小*"
    assert post.posted_at == datetime.fromtimestamp(1758240000, tz=UTC)
    assert post.text.title == "新加坡人搬来上海的第一周｜真实记录 🇸🇬➡️🇨🇳"
    assert post.text.hashtags == ["新加坡人在上海", "上海生活", "vlog日常"]
    assert len(post.media) == 1 and post.media[0].type.value == "video"
    assert post.media[0].local_path is None
    assert post.metrics.likes == 12000 and post.metrics.saves == 3456
    assert post.metrics.comments == 289 and post.metrics.shares == 120 and post.metrics.views is None
    assert [c.text for c in post.comments] == [
        "地铁迷路那段笑死，我第一次也是坐反方向",
        "外卖速度真的离谱哈哈哈，欢迎来上海！",
        "同新加坡人，刚到上海一个月，求租房攻略🙏",
    ]
    assert post.comments[0].likes == 415
    assert post.lang == "zh"
    assert post.raw_ref == "raw/xiaohongshu__66f1a2b3c4d5e6f700000001.json"
    assert post.collected_at == NOW


def test_image_note_has_one_media_per_image_with_index(notes, comments):
    n = notes[1]
    post = map_note(n, comments[n["note_id"]], SALT, raw_ref="r", collected_at=NOW)
    assert post.kind.value == "image_note"
    assert [m.index for m in post.media] == [0, 1, 2]
    assert all(m.type.value == "image" for m in post.media)
    assert post.metrics.saves == 2310


def test_normal_note_without_images(notes):
    n = notes[2]
    post = map_note(n, [], SALT, raw_ref="r", collected_at=NOW)
    assert post.kind.value == "image_note" and post.media == []
    assert post.metrics.likes is None and post.metrics.comments == 0
    assert post.text.hashtags == [] and post.comments == []


def test_mapping_preserves_cjk_exactly(notes, comments):
    n = notes[0]
    post = map_note(n, comments[n["note_id"]], SALT, raw_ref="r", collected_at=NOW)
    dumped = post.model_dump_json()
    for s in (n["title"], n["desc"], "外卖速度真的离谱哈哈哈，欢迎来上海！", "🇸🇬➡️🇨🇳", "｜"):
        assert s in dumped
    rt = Post.model_validate_json(dumped)
    assert rt.text.title == n["title"] and rt.text.caption == n["desc"]


def test_comments_capped_at_50():
    many = [{"comment_id": f"c{i}", "note_id": "n", "content": f"评论{i}", "like_count": str(i), "parent_comment_id": "0"} for i in range(80)]
    post = map_note({"note_id": "n", "type": "normal", "title": "", "desc": "", "note_url": "https://www.xiaohongshu.com/explore/n", "creator_hash": "x"}, group_comments(many)["n"], SALT, raw_ref="r", collected_at=NOW)
    assert len(post.comments) == 50 and post.comments[0].text == "评论79"


def test_field_map_is_overridable(monkeypatch, notes):
    monkeypatch.setitem(mapping.FIELD_MAP, "caption", "title")
    post = map_note(notes[2], [], SALT, raw_ref="r", collected_at=NOW)
    assert post.text.caption == notes[2]["title"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest tests/test_mapping.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve_xhs.mapping'`.

- [ ] **Step 4: Implement the mapping**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/mapping.py
from __future__ import annotations

import re
from datetime import UTC, datetime

from clipsieve.adapters.base import hash_creator
from clipsieve.models import Comment, Media, Metrics, Post, PostText

# Our field -> MediaCrawler record key. Verified against store/xhs/__init__.py at the pinned commit.
# Override entries here if a MediaCrawler bump renames a key; logic below never hardcodes record keys.
FIELD_MAP: dict[str, str] = {
    "note_id": "note_id",
    "type": "type",
    "title": "title",
    "caption": "desc",
    "video_url": "video_url",
    "time": "time",
    "creator_hash": "creator_hash",
    "nickname": "nickname",
    "liked_count": "liked_count",
    "collected_count": "collected_count",
    "comment_count": "comment_count",
    "share_count": "share_count",
    "image_list": "image_list",
    "tag_list": "tag_list",
    "note_url": "note_url",
    # comments
    "c_note_id": "note_id",
    "c_content": "content",
    "c_like_count": "like_count",
    "c_parent": "parent_comment_id",
}
LIST_DELIMITER = ","        # image_list is ",".join(urls) in MediaCrawler; tag_list assumed the same (unverified)
TIME_UNIT = "ms"            # Xiaohongshu web API uses epoch milliseconds (unverified against MediaCrawler output)
MAX_COMMENTS = 50
TOP_LEVEL_PARENT_VALUES = {"", "0", 0, None}
PLATFORM = "xiaohongshu"

_CJK = re.compile(r"[一-鿿㐀-䶿]")
_NUM = re.compile(r"^\s*([\d.,]+)\s*([万wW]?)\s*$")


def _g(rec: dict, key: str):
    return rec.get(FIELD_MAP[key])


def parse_count(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    m = _NUM.match(str(value))
    if not m:
        return None
    num, unit = m.group(1).replace(",", ""), m.group(2)
    try:
        f = float(num)
    except ValueError:
        return None
    if unit:
        f *= 10_000
    return int(round(f))


def split_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(LIST_DELIMITER) if s.strip()]


def image_urls(note: dict) -> list[str]:
    return split_list(_g(note, "image_list"))


def video_urls(note: dict) -> list[str]:
    return split_list(_g(note, "video_url"))


def _posted_at(note: dict) -> datetime | None:
    raw = _g(note, "time")
    n = parse_count(raw) if not isinstance(raw, (int, float)) else int(raw)
    if n is None or n <= 0:
        return None
    seconds = n / 1000 if TIME_UNIT == "ms" else n
    return datetime.fromtimestamp(seconds, tz=UTC)


def _lang(title: str, caption: str) -> str | None:
    text = f"{title} {caption}"
    if not text.strip():
        return None
    cjk = len(_CJK.findall(text))
    letters = sum(ch.isalpha() for ch in text)
    if letters == 0:
        return None
    return "zh" if cjk / letters >= 0.3 else "en"


def group_comments(comments: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for c in comments:
        if _g(c, "c_parent") not in TOP_LEVEL_PARENT_VALUES:
            continue
        nid = str(_g(c, "c_note_id") or "")
        grouped.setdefault(nid, []).append(c)
    for nid, lst in grouped.items():
        lst.sort(key=lambda c: parse_count(_g(c, "c_like_count")) or 0, reverse=True)
    return grouped


def map_note(note: dict, comments: list[dict], salt: str, raw_ref: str, collected_at: datetime) -> Post:
    note_id = str(_g(note, "note_id"))
    ntype = str(_g(note, "type") or "normal")
    title = str(_g(note, "title") or "")
    caption = str(_g(note, "caption") or "")
    kind = "video" if ntype == "video" else "image_note"
    media: list[Media] = []
    if kind == "video":
        urls = video_urls(note)
        if urls:
            media.append(Media(type="video", local_path=None, index=0))
    else:
        media = [Media(type="image", local_path=None, index=i) for i, _ in enumerate(image_urls(note))]
    top = comments[:MAX_COMMENTS]
    return Post(
        id=f"{PLATFORM}:{note_id}",
        platform=PLATFORM,
        url=str(_g(note, "note_url") or f"https://www.xiaohongshu.com/explore/{note_id}"),
        creator_hash=hash_creator(str(_g(note, "creator_hash") or "unknown"), salt),
        creator_display=(str(_g(note, "nickname")) if _g(note, "nickname") else None),
        posted_at=_posted_at(note),
        kind=kind,
        text=PostText(title=title or None, caption=caption or None, hashtags=split_list(_g(note, "tag_list"))),
        media=media,
        metrics=Metrics(
            views=None,
            likes=parse_count(_g(note, "liked_count")),
            comments=parse_count(_g(note, "comment_count")),
            shares=parse_count(_g(note, "share_count")),
            saves=parse_count(_g(note, "collected_count")),
        ),
        comments=[Comment(text=str(_g(c, "c_content") or ""), likes=parse_count(_g(c, "c_like_count"))) for c in top],
        lang=_lang(title, caption),
        raw_ref=raw_ref,
        collected_at=collected_at,
    )
```

Note on `Media.index` for video: the overview's `Media` has optional `index`; we set `0` for the single video so media ordering is uniform. `duration_s`, `width`, `height` are unknown from MediaCrawler and left unset; plan 02's `extract_evidence` reads duration from the downloaded file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest tests/test_mapping.py -v`
Expected: `16 passed` (8 parametrised `parse_count` cases plus 8 tests).

- [ ] **Step 6: Format the fixture JSON**

The fixtures are checked by Biome (`bun run lint` runs `bunx ultracite check` over the whole repo), and the hand-written rows above are not Biome-formatted. From the **repo root**:

```bash
bunx ultracite fix contrib/adapter-xhs-mediacrawler/tests/fixtures
bunx ultracite check contrib/adapter-xhs-mediacrawler/tests/fixtures
cd contrib/adapter-xhs-mediacrawler && uv run ruff format . && uv run ruff check . && uv run pytest tests/test_mapping.py -q
```

Expected: `ultracite check` exits 0; `16 passed` (formatting does not change the parsed data).

- [ ] **Step 7: Commit**

```bash
git add contrib/adapter-xhs-mediacrawler/clipsieve_xhs/mapping.py contrib/adapter-xhs-mediacrawler/tests/test_mapping.py contrib/adapter-xhs-mediacrawler/tests/fixtures
git commit -m "feat(contrib-xhs): table-driven mapping from MediaCrawler notes and comments to Post

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 4: The adapter, media download, media-URL cache, contract test

**Files:**
- Create: `contrib/adapter-xhs-mediacrawler/clipsieve_xhs/adapter.py`
- Modify: `contrib/adapter-xhs-mediacrawler/tests/conftest.py` (add `FakeRunner`)
- Test: `contrib/adapter-xhs-mediacrawler/tests/test_adapter.py`

No `backend/tests/adapters/test_entry_point_discovery.py`: `tests/adapters/test_registry.py` already covers monkeypatched entry-point discovery, and Step 6 plus the CI job verify real discovery against the installed package.

**Interfaces:**
- Consumes: `Adapter`, `AdapterHealth`, `MediaDownloadError` (from `clipsieve.adapters.base`, not redefined), `ensure_creator_salt`, `Query`, `Post`, `RunnerProtocol`, `MediaCrawlerRunner`, `map_note`, `group_comments`, `image_urls`, `video_urls`, `XhsSettings`, and, in tests, `run_adapter_contract(adapter, query, tmp_path)` loaded from `backend/tests/adapters/contract.py` by file path.
- Produces:

```python
class XhsMediaCrawlerAdapter:
    platform = "xiaohongshu"
    @classmethod
    def from_settings(cls, settings: Settings) -> "XhsMediaCrawlerAdapter"      # Addendum B6; what the registry calls
    def __init__(self, settings: Settings | None = None, xhs_settings: XhsSettings | None = None,
                 runner: RunnerProtocol | None = None, http: httpx.Client | None = None,
                 raw_dir: Path | None = None, cache_dir: Path | None = None,
                 now: Callable[[], datetime] = ...) -> None
    def search(self, queries: list[Query], limit: int) -> Iterator[Post]
    def fetch_media(self, post: Post, dest: Path) -> Post
    def healthcheck(self) -> AdapterHealth
    def media_urls_for(self, post_id: str) -> list[str]        # memory cache, then <cache_dir>/<safe_id>.media.json; raises MediaDownloadError if neither has it
```

Per Addendum B1, raw payloads are written to `incoming_dir(settings.clipsieve_data_dir, "xiaohongshu") / f"{safe_post_filename(post.id)}.json"` and `Post.raw_ref` is that **absolute** path; plan 03's Runner relocates the file into the run folder and rewrites `raw_ref`. `raw_dir` in the constructor exists only so tests can redirect the incoming dir. Per Addendum B2, `fetch_media` writes `video.mp4` or `img_00.jpg`, `img_01.jpg`, ... (always `.jpg`, whatever the URL extension) into `dest` and sets `Media.local_path` to those **dest-relative** names.

**Media-URL cache (overview C.15, pre-flight Ruling 1).** The Runner moves the raw payload out of `incoming_dir` before it calls `fetch_media` (B.10), so `fetch_media` can never rely on the raw file or on `raw_ref`, and an in-memory dict alone is empty after a restart. `search` therefore writes `{"urls": [...]}` to `<cache_dir>/<safe_post_filename(post.id)>.media.json`, where `cache_dir` defaults to `<settings.clipsieve_data_dir>/adapter-cache/xiaohongshu/` (the constructor's `cache_dir` exists so tests can redirect it), and keeps the same list in memory. `fetch_media` reads memory first, then the cache file; if neither has an entry it raises `MediaDownloadError` (the Runner records a recoverable per-post error). `_load_raw` does not exist and `media_urls_for` never reads `incoming_dir` or `raw_ref`. No `Media.url` field is added to the schema.

The stored raw payload is privacy-stripped: comment records drop `creator_hash`, `nickname` and `pictures`, and the note drops `xsec_token` (backend/AGENTS.md: comment author identifiers are not stored in raw). The Post is still mapped from the unstripped records in memory.

- [ ] **Step 1: Add FakeRunner to conftest**

```python
# contrib/adapter-xhs-mediacrawler/tests/conftest.py  (append)
import json
from pathlib import Path

from clipsieve.adapters.base import AdapterHealth
from clipsieve_xhs.runner import RunnerOutput

FIX = Path(__file__).parent / "fixtures" / "mediacrawler-output"


class FakeRunner:
    """Replays the fixture output for every keyword; records calls."""

    def __init__(self, healthy: bool = True) -> None:
        self.calls: list[tuple[str, int, Path]] = []
        self.healthy = healthy

    def search(self, keyword: str, start_page: int, workdir: Path) -> RunnerOutput:
        self.calls.append((keyword, start_page, workdir))
        notes = json.loads((FIX / "notes.json").read_text(encoding="utf-8"))
        comments = json.loads((FIX / "comments.json").read_text(encoding="utf-8"))
        return RunnerOutput(notes=notes, comments=comments, errors=[], returncode=0, stderr_tail="")

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(self.healthy, "fake")


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()
```

- [ ] **Step 2: Write the failing adapter tests**

```python
# contrib/adapter-xhs-mediacrawler/tests/test_adapter.py
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import respx

from clipsieve.adapters.base import MediaDownloadError
from clipsieve.config import Settings
from clipsieve.models import Query
from clipsieve_xhs.adapter import XhsMediaCrawlerAdapter
from clipsieve_xhs.settings import XhsSettings

Q = [Query(platform="xiaohongshu", query="新加坡人 上海 vlog", lang="zh")]
VIDEO_URL = "https://sns-video-bd.xhscdn.com/stream/1/110/258/01e7f1a2b3c4d5e6f7.mp4"
VIDEO_LOW_URL = "https://sns-video-bd.xhscdn.com/stream/1/110/259/01e7f1a2b3c4d5e6f7_low.mp4"
IMAGE_URLS = [f"https://sns-webpic-qc.xhscdn.com/202509/01/a{i}.jpg" for i in (1, 2, 3)]
BACKEND_CONTRACT = (
    Path(__file__).resolve().parents[3] / "backend" / "tests" / "adapters" / "contract.py"
)


def make_adapter(tmp_path, runner, cache_name="cache"):
    core = Settings(
        _env_file=None, clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt"
    )
    xhs = XhsSettings(_env_file=None, clipsieve_xhs_mediacrawler_dir=tmp_path / "mc")
    return XhsMediaCrawlerAdapter(
        core, xhs, runner=runner, raw_dir=tmp_path / "raw", cache_dir=tmp_path / cache_name
    )


@pytest.fixture
def adapter(tmp_path, fake_runner):
    return make_adapter(tmp_path, fake_runner)


def test_search_yields_mapped_posts_and_writes_raw(adapter, fake_runner, tmp_path):
    posts = list(adapter.search(Q, limit=10))
    assert [p.id for p in posts] == [
        "xiaohongshu:66f1a2b3c4d5e6f700000001",
        "xiaohongshu:66f1a2b3c4d5e6f700000002",
        "xiaohongshu:66f1a2b3c4d5e6f700000003",
    ]
    assert fake_runner.calls[0][0] == "新加坡人 上海 vlog"
    raw = tmp_path / "raw" / "xiaohongshu__66f1a2b3c4d5e6f700000001.json"
    assert raw.exists()
    payload = json.loads(raw.read_text(encoding="utf-8"))
    assert payload["note"]["title"].startswith("新加坡人搬来上海")
    assert posts[0].raw_ref == str(raw)  # absolute, Addendum B1; the Runner relocates it
    # Author identifiers and the platform token are not stored (backend/AGENTS.md).
    assert "xsec_token" not in payload["note"]
    assert payload["comments"], "fixture note 1 has top-level comments"
    for c in payload["comments"]:
        assert not {"creator_hash", "nickname", "pictures"} & set(c)
        assert c["content"]


def test_search_writes_media_url_cache(adapter, tmp_path):
    list(adapter.search(Q, limit=10))
    cache = tmp_path / "cache"
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000001.media.json").read_text(encoding="utf-8")
    ) == {"urls": [VIDEO_URL, VIDEO_LOW_URL]}
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000002.media.json").read_text(encoding="utf-8")
    ) == {"urls": IMAGE_URLS}
    assert json.loads(
        (cache / "xiaohongshu__66f1a2b3c4d5e6f700000003.media.json").read_text(encoding="utf-8")
    ) == {"urls": []}


def test_from_settings_uses_incoming_dir_and_data_dir_cache(tmp_path, monkeypatch):
    from clipsieve.adapters.base import incoming_dir

    monkeypatch.setenv("CLIPSIEVE_XHS_MEDIACRAWLER_DIR", str(tmp_path / "mc"))
    core = Settings(
        _env_file=None,
        clipsieve_data_dir=tmp_path / "data",
        clipsieve_creator_salt="salt",
        clipsieve_xhs_chrome_cdp_port=9444,
    )
    a = XhsMediaCrawlerAdapter.from_settings(core)
    assert a.platform == "xiaohongshu"
    assert a.raw_dir == incoming_dir(tmp_path / "data", "xiaohongshu")
    assert a.cache_dir == tmp_path / "data" / "adapter-cache" / "xiaohongshu"
    assert a.runner.cdp_port == 9444  # the core Settings owns the CDP port


def test_search_stops_at_limit_and_dedupes_across_queries(adapter):
    qs = Q + [Query(platform="xiaohongshu", query="上海 新加坡 留学生", lang="zh")]
    posts = list(adapter.search(qs, limit=4))
    assert len(posts) == 3  # 3 unique notes across both queries, fixture repeats
    posts2 = list(adapter.search(Q, limit=2))
    assert len(posts2) == 2


def test_search_ignores_queries_for_other_platforms(adapter, fake_runner):
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], limit=5))
    assert posts == [] and fake_runner.calls == []


@respx.mock
def test_fetch_media_downloads_images_in_order(adapter, tmp_path):
    posts = {p.id: p for p in adapter.search(Q, limit=10)}
    post = posts["xiaohongshu:66f1a2b3c4d5e6f700000002"]
    for i, url in enumerate(IMAGE_URLS, start=1):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"\xff\xd8img" + bytes([i])))
    dest = tmp_path / "media" / "p2"
    out = adapter.fetch_media(post, dest)
    assert [m.local_path for m in out.media] == ["img_00.jpg", "img_01.jpg", "img_02.jpg"]  # B2
    assert (dest / "img_02.jpg").read_bytes().endswith(b"\x03")
    assert respx.calls[0].request.headers["referer"] == "https://www.xiaohongshu.com/"


@respx.mock
def test_fetch_media_video_uses_first_url(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, content=b"mp4data"))
    out = adapter.fetch_media(post, tmp_path / "v")
    assert out.media[0].local_path == "video.mp4"
    assert (tmp_path / "v" / "video.mp4").read_bytes() == b"mp4data"


@respx.mock
def test_fetch_media_is_idempotent(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    route = respx.get(VIDEO_URL).mock(return_value=httpx.Response(200, content=b"mp4data"))
    adapter.fetch_media(post, tmp_path / "v")
    adapter.fetch_media(post, tmp_path / "v")
    assert route.call_count == 1


@respx.mock
def test_fetch_media_failure_raises_media_error(adapter, tmp_path):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    respx.get(VIDEO_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(MediaDownloadError):
        adapter.fetch_media(post, tmp_path / "v")


@respx.mock
def test_fetch_media_works_in_a_second_adapter_instance(tmp_path, fake_runner):
    """Restart safety: the Runner relocates the raw file before fetch_media (B.10) and a new
    process has an empty memory cache, so only the on-disk media-URL cache can serve this."""
    first = make_adapter(tmp_path, fake_runner)
    post = next(p for p in first.search(Q, limit=10) if p.id.endswith("0002"))
    for f in (tmp_path / "raw").glob("*.json"):
        f.unlink()  # what the Runner's relocation does to incoming/
    second = make_adapter(tmp_path, fake_runner)
    assert second is not first
    for i, url in enumerate(IMAGE_URLS, start=1):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"img" + bytes([i])))
    out = second.fetch_media(post, tmp_path / "media" / "p2")
    assert [m.local_path for m in out.media] == ["img_00.jpg", "img_01.jpg", "img_02.jpg"]


def test_fetch_media_without_cache_entry_raises_media_error(tmp_path, fake_runner, adapter):
    post = next(p for p in adapter.search(Q, limit=10) if p.kind.value == "video")
    elsewhere = make_adapter(tmp_path, fake_runner, cache_name="other-cache")
    with pytest.raises(MediaDownloadError):
        elsewhere.fetch_media(post, tmp_path / "v")


def test_healthcheck_delegates(adapter, fake_runner):
    assert adapter.healthcheck().ok is True
    fake_runner.healthy = False
    assert adapter.healthcheck().ok is False


@respx.mock
def test_passes_shared_adapter_contract(adapter, tmp_path):
    # `tests` is also this package's name, so load the backend contract by file path.
    spec = importlib.util.spec_from_file_location("backend_adapter_contract", BACKEND_CONTRACT)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    for url in (VIDEO_URL, *IMAGE_URLS):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"media-bytes"))
    posts = contract.run_adapter_contract(adapter, Q[0], tmp_path)  # ONE Query, no network
    assert posts
```

`FakeRunner` and the `fake_runner` fixture in `conftest.py` are unchanged.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd contrib/adapter-xhs-mediacrawler && uv run pytest tests/test_adapter.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve_xhs.adapter'`.

- [ ] **Step 4: Implement the adapter**

```python
# contrib/adapter-xhs-mediacrawler/clipsieve_xhs/adapter.py
from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from clipsieve.adapters.base import (
    Adapter,
    AdapterHealth,
    MediaDownloadError,
    incoming_dir,
)
from clipsieve.config import Settings, ensure_creator_salt, get_settings
from clipsieve.models import Post, Query
from clipsieve.store.paths import safe_post_filename
from clipsieve_xhs.mapping import PLATFORM, group_comments, image_urls, map_note, video_urls
from clipsieve_xhs.runner import MediaCrawlerRunner, RunnerProtocol
from clipsieve_xhs.settings import XhsSettings, get_xhs_settings

log = structlog.get_logger(__name__)

REFERER = "https://www.xiaohongshu.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
CACHE_SUBDIR = "adapter-cache"
# Dropped before the raw payload is written (backend/AGENTS.md: author identifiers are not stored).
RAW_NOTE_DROP = frozenset({"xsec_token"})
RAW_COMMENT_DROP = frozenset({"creator_hash", "nickname", "pictures"})


def _strip(record: dict, drop: frozenset[str]) -> dict:
    return {k: v for k, v in record.items() if k not in drop}


class XhsMediaCrawlerAdapter(Adapter):
    platform = PLATFORM

    def __init__(
        self,
        settings: Settings | None = None,
        xhs_settings: XhsSettings | None = None,
        runner: RunnerProtocol | None = None,
        http: httpx.Client | None = None,
        raw_dir: Path | None = None,
        cache_dir: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self.settings = settings or get_settings()
        self.xhs = xhs_settings or get_xhs_settings()
        self.runner = runner or MediaCrawlerRunner(
            self.xhs, cdp_port=self.settings.clipsieve_xhs_chrome_cdp_port
        )
        self.http = http or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"Referer": REFERER, "User-Agent": USER_AGENT},
        )
        self.raw_dir = raw_dir or incoming_dir(self.settings.clipsieve_data_dir, self.platform)
        self.cache_dir = cache_dir or (
            self.settings.clipsieve_data_dir / CACHE_SUBDIR / self.platform
        )
        self._now = now
        self._media_cache: dict[str, list[str]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> XhsMediaCrawlerAdapter:
        return cls(settings=settings)

    @staticmethod
    def _val(x):
        return getattr(x, "value", x)  # generated enums are Enum classes (overview Addendum A8)

    # ---- Adapter protocol -------------------------------------------------

    def healthcheck(self) -> AdapterHealth:
        return self.runner.healthcheck()

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        seen: set[str] = set()
        yielded = 0
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        salt = ensure_creator_salt(self.settings)
        for q in queries:
            if q.platform != self.platform or yielded >= limit:
                continue
            with tempfile.TemporaryDirectory(prefix="clipsieve-xhs-") as tmp:
                out = self.runner.search(q.query, start_page=1, workdir=Path(tmp))
            for err in out.errors:
                log.warning("xhs.runner.error", query=q.query, error=err)
            grouped = group_comments(out.comments)
            for note in out.notes:
                note_id = str(note.get("note_id") or "")
                if not note_id or note_id in seen:
                    continue
                seen.add(note_id)
                post_id = f"{PLATFORM}:{note_id}"
                comments = grouped.get(note_id, [])
                raw_path = self.raw_dir / f"{safe_post_filename(post_id)}.json"
                payload = {
                    "note": _strip(note, RAW_NOTE_DROP),
                    "comments": [_strip(c, RAW_COMMENT_DROP) for c in comments],
                    "query": q.query,
                }
                raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                self._remember_media_urls(post_id, note)
                yield map_note(note, comments, salt, raw_ref=str(raw_path), collected_at=self._now())
                yielded += 1
                if yielded >= limit:
                    break

    def media_urls_for(self, post_id: str) -> list[str]:
        """Memory first, then the on-disk cache `search` wrote. Never reads the raw payload:
        the Runner relocates it before `fetch_media` runs (overview B.10)."""
        if post_id in self._media_cache:
            return self._media_cache[post_id]
        path = self._cache_path(post_id)
        try:
            urls = list(json.loads(path.read_text(encoding="utf-8"))["urls"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise MediaDownloadError(f"{post_id}: no cached media URLs ({e}); run search first") from e
        self._media_cache[post_id] = urls
        return urls

    def fetch_media(self, post: Post, dest: Path) -> Post:
        urls = self.media_urls_for(post.id)  # raises MediaDownloadError when nothing is cached
        dest.mkdir(parents=True, exist_ok=True)
        if not urls:
            return post
        media = [m.model_copy() for m in post.media]
        if self._val(post.kind) == "video":
            name = "video.mp4"
            self._download(urls[0], dest / name)
            if media:
                media[0].local_path = name  # dest-relative (Addendum B2)
        else:
            for i, (m, url) in enumerate(zip(media, urls, strict=False)):
                name = f"img_{i:02d}.jpg"  # fixed extension (B2), whatever the URL says
                self._download(url, dest / name)
                m.local_path = name
        return post.model_copy(update={"media": media})

    # ---- helpers ----------------------------------------------------------

    def _cache_path(self, post_id: str) -> Path:
        return self.cache_dir / f"{safe_post_filename(post_id)}.media.json"

    def _remember_media_urls(self, post_id: str, note: dict) -> None:
        urls = video_urls(note) if str(note.get("type")) == "video" else image_urls(note)
        self._media_cache[post_id] = urls
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(post_id).write_text(
            json.dumps({"urls": urls}, ensure_ascii=False), encoding="utf-8"
        )

    def _download(self, url: str, target: Path) -> None:
        if target.exists() and target.stat().st_size > 0:
            return
        try:
            with self.http.stream("GET", url) as resp:
                resp.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".part")
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
                tmp.replace(target)
        except httpx.HTTPError as e:
            raise MediaDownloadError(f"{url}: {e}") from e
```

`Adapter` is a `runtime_checkable` `typing.Protocol`; subclassing it explicitly is fine (`FixtureAdapter` does the same). `fetch_media` creates `dest` only after the cache lookup succeeds, so a missing cache entry leaves no empty directory behind.

- [ ] **Step 5: Run the contrib tests**

Run:
```bash
cd contrib/adapter-xhs-mediacrawler && uv run ruff format . && uv run ruff check . && uv run pytest -v
```
Expected: contrib `42 passed` (3 settings + 11 runner + 16 mapping + 12 adapter).

- [ ] **Step 6: Verify real discovery after install, then commit**

Run:
```bash
cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler && uv run python -c "from clipsieve.adapters.registry import load_adapters; from clipsieve.config import Settings; print(sorted(load_adapters(Settings(_env_file=None))))"
```
Expected: `['local', 'xiaohongshu', 'youtube']`. (Health will be false without Chrome; discovery is what this verifies.)

```bash
git add contrib/adapter-xhs-mediacrawler
git commit -m "feat(contrib-xhs): XhsMediaCrawlerAdapter with media download, media-URL cache and contract test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 5: Evals package: golden format, sample set, scorer with three language modes

**Files:**
- Create: `evals/AGENTS.md`
- Create: `evals/README.md`
- Create: `evals/__init__.py`
- Create: `evals/score.py`
- Create: `evals/ruff.toml` (`extend = "../backend/pyproject.toml"`, so `evals/` is linted with the backend rules; Task 7 adds it to the lint script)
- Create: `evals/golden/en-100.jsonl` (header line only)
- Create: `evals/golden/zh-100.jsonl` (header line only)
- Create: `rubrics/creator-hooks-v1.zh-examples.yaml`
- Create: `backend/tests/fixtures/golden/sample-5.jsonl`
- Test: `backend/tests/evals/__init__.py`
- Test: `backend/tests/evals/test_score.py`
- Modify: `AGENTS.md` (root Child DOX Index table row)

`backend/pyproject.toml` is not touched: `pyyaml` is already a backend dependency.

**Interfaces:**
- Consumes: `Judge`, `JudgeFailed`, `RecordedJudge`, `cost_usd`, `load_pack`, `questions_for_pass`, `RubricPack`, `Question`, `JudgeResult`, `JudgeAnswer`, `pack_summaries`, `ClaudeCliBackend` (for argv shape only).
- Produces:

```python
# evals/score.py
class GoldenItem(BaseModel): post_id: str; state: dict; labels: dict[str, str | int | bool]
class QuestionAgreement(BaseModel): question_id: str; type: str; n: int; correct: int; agreement: float; mean_conf_correct: float | None; mean_conf_incorrect: float | None
class EvalReport(BaseModel): pack: str; mode: str; n_items: int; n_skipped: int; questions: list[QuestionAgreement]; jev_input_tokens: int; jev_cost_usd: float; translate_cost_usd: float
class Translator(Protocol):
    def translate(self, texts: list[str]) -> tuple[list[str], float]: ...     # (translations, cost_usd)
class IdentityTranslator(Translator)
class ClaudeCliTranslator(Translator)                         # subprocess has a timeout (timeout_s, default 300)
def read_golden(path: Path) -> list[GoldenItem]              # skips lines starting with '#'
def predicted_level(answer: JudgeAnswer, levels: int) -> int  # 1-based level from a 0-indexed Jev answer (E.3)
def is_correct(question: Question, answer: JudgeAnswer, label) -> bool
def apply_mode(pack: RubricPack, item: GoldenItem, mode: str, translator: Translator, zh_examples: dict) -> tuple[RubricPack, dict, float]
def load_zh_examples(pack_name: str, rubrics_dir: Path) -> dict
async def score_pack(pack: RubricPack, golden_path: Path, judge: Judge,   # a JudgeFailed item is skipped and counted in n_skipped
                      mode: str = "raw", translator: Translator | None = None, rubrics_dir: Path = Path("rubrics")) -> EvalReport
def render_markdown(report: EvalReport) -> str
```

Golden line format (one JSON object per line; lines starting with `#` are comments):

```json
{"post_id": "local:fx-001", "state": {"brief": {...}, "post": {...}, "transcript": [...], "ocr": [...], "comments": {...}}, "labels": {"hook_type": "result_first", "hook_strength": 4, "format": "vlog_montage", "persona_fit": 3, "risky_claim": false, "niche_relevance": 5, "format_guess": "vlog_montage"}}
```

Label types: Choice label string; Score 1-based integer level; Noul boolean.

- [ ] **Step 1: Write the golden files**

`evals/golden/en-100.jsonl` and `evals/golden/zh-100.jsonl` each contain exactly one line:

```text
# clipsieve golden set. One JSON object per line: {"post_id", "state", "labels"}. Labels: choice -> label string, score -> 1-based level int, noul -> bool. Lines starting with # are ignored. See evals/README.md for the labelling protocol.
```

`backend/tests/fixtures/golden/sample-5.jsonl` (states are compact text evidence consistent with plan 02's fixture posts `local:fx-001` to `local:fx-005`; three video, two image_note; two English, three Chinese):

```json
# sample golden set for tests; compact hand-written states for the five local:fx-* posts (transcript items use start_s/end_s and there are no hashtags, unlike build_state's {t,text} items); the scorer reads only the post title/caption and the text fields
{"post_id": "local:fx-001", "state": {"brief": {"topic": "Singaporean moving to Shanghai vlogs", "audience": "Singaporeans in their 20s considering a move to China", "persona": "Singaporean in Shanghai, candid vlog voice"}, "post": {"kind": "video", "lang": "en", "title": "I moved from Singapore to Shanghai. Week one.", "caption": "Everything that surprised me #singaporean #shanghai #vlog", "metrics": {"views": 84000, "likes": 6100, "comments": 310}}, "transcript": [{"start_s": 0.0, "end_s": 2.8, "text": "I got my apartment keys in Shanghai in under 48 hours. Here's how."}, {"start_s": 2.8, "end_s": 9.0, "text": "First, the agent fee. In Singapore it's half a month. Here it's a full month, and they expect it upfront."}], "ocr": [{"source": "keyframe", "index": 0, "text": "48 HOURS TO KEYS"}], "comments": {"count": 310, "top_terms": ["agent", "fee", "wechat", "pay"], "sample": ["Wait, a full month upfront?!", "Need the WeChat Pay setup video pls"]}}, "labels": {"hook_type": "result_first", "hook_strength": 4, "format": "vlog_montage", "persona_fit": 5, "risky_claim": false, "niche_relevance": 5, "format_guess": "vlog_montage"}}
{"post_id": "local:fx-002", "state": {"brief": {"topic": "Singaporean moving to Shanghai vlogs", "audience": "Singaporeans in their 20s considering a move to China", "persona": "Singaporean in Shanghai, candid vlog voice"}, "post": {"kind": "video", "lang": "zh", "title": "新加坡人在上海的一天｜早餐只要8块", "caption": "来上海三个月，最爱的早餐摊 #上海生活 #新加坡人", "metrics": {"views": 230000, "likes": 18000, "comments": 920}}, "transcript": [{"start_s": 0.0, "end_s": 3.1, "text": "你敢信吗？这一整份早餐只要八块钱。"}, {"start_s": 3.1, "end_s": 8.0, "text": "在新加坡这个价钱连一杯咖啡都买不到。"}], "ocr": [{"source": "keyframe", "index": 0, "text": "¥8 早餐"}], "comments": {"count": 920, "top_terms": ["早餐", "便宜", "新加坡", "物价"], "sample": ["新加坡物价真的太高了", "这家在哪里！"]}}, "labels": {"hook_type": "bold_claim", "hook_strength": 4, "format": "vlog_montage", "persona_fit": 5, "risky_claim": false, "niche_relevance": 5, "format_guess": "vlog_montage"}}
{"post_id": "local:fx-003", "state": {"brief": {"topic": "Singaporean moving to Shanghai vlogs", "audience": "Singaporeans in their 20s considering a move to China", "persona": "Singaporean in Shanghai, candid vlog voice"}, "post": {"kind": "image_note", "lang": "zh", "title": "上海租房合同必看的5个坑", "caption": "被中介坑过一次之后整理的 #上海租房 #避坑", "metrics": {"views": null, "likes": 4300, "comments": 150, "saves": 9800}}, "transcript": [], "ocr": [{"source": "image", "index": 0, "text": "第一坑：押一付三还是押二付一？"}, {"source": "image", "index": 1, "text": "第二坑：中介费谁付"}], "comments": {"count": 150, "top_terms": ["中介费", "押金", "合同"], "sample": ["太实用了收藏", "我就是被第三条坑的"]}}, "labels": {"hook_type": "problem", "hook_strength": 3, "format": "image_carousel", "persona_fit": 2, "risky_claim": false, "niche_relevance": 3, "format_guess": "image_carousel"}}
{"post_id": "local:fx-004", "state": {"brief": {"topic": "Singaporean moving to Shanghai vlogs", "audience": "Singaporeans in their 20s considering a move to China", "persona": "Singaporean in Shanghai, candid vlog voice"}, "post": {"kind": "video", "lang": "en", "title": "This supplement fixed my jet lag in one day", "caption": "Link in bio #shanghai #travel", "metrics": {"views": 12000, "likes": 400, "comments": 20}}, "transcript": [{"start_s": 0.0, "end_s": 3.0, "text": "Doctors hate this. One pill and my jet lag was gone."}], "ocr": [{"source": "keyframe", "index": 0, "text": "JET LAG CURE"}], "comments": {"count": 20, "top_terms": ["link", "price"], "sample": ["Is this legit?"]}}, "labels": {"hook_type": "bold_claim", "hook_strength": 3, "format": "talking_head", "persona_fit": 1, "risky_claim": true, "niche_relevance": 1, "format_guess": "talking_head"}}
{"post_id": "local:fx-005", "state": {"brief": {"topic": "Singaporean moving to Shanghai vlogs", "audience": "Singaporeans in their 20s considering a move to China", "persona": "Singaporean in Shanghai, candid vlog voice"}, "post": {"kind": "image_note", "lang": "zh", "title": "周末去了趟苏州", "caption": "随手拍 #苏州", "metrics": {"views": null, "likes": 120, "comments": 4}}, "transcript": [], "ocr": [], "comments": {"count": 4, "top_terms": ["好看"], "sample": ["好看"]}}, "labels": {"hook_type": "none", "hook_strength": 1, "format": "image_carousel", "persona_fit": 2, "risky_claim": false, "niche_relevance": 1, "format_guess": "image_carousel"}}
```

`rubrics/creator-hooks-v1.zh-examples.yaml` (bilingual mode appends these to the English criteria):

```yaml
# Chinese examples appended to creator-hooks-v1 criteria in bilingual language_mode.
# choice: label -> example phrase. score: 1-based level -> example situation.
hook_type:
  curiosity_gap: "例：「来上海之前没人告诉我这件事」"
  bold_claim: "例：「上海早餐8块钱，新加坡买不到一杯咖啡」"
  result_first: "例：「48小时拿到钥匙，过程在这」"
  problem: "例：「被中介坑了一个月房租」"
  story: "例：「落地第一天，行李丢了」"
  authority: "例：「在上海住了十年的新加坡人告诉你」"
  none: "例：开头只有问候或片头"
hook_strength:
  1: "例：开头是「大家好，欢迎回来」"
  2: "例：只说了「今天聊聊上海租房」"
  3: "例：「上海租房有个坑你可能没注意」"
  4: "例：「8块钱早餐」配上价格特写"
  5: "例：「你敢信吗？」加上强烈画面对比和明确利益点"
format:
  talking_head: "例：一个人对镜头说话"
  vlog_montage: "例：街拍、地铁、外卖等生活片段剪辑"
  image_carousel: "例：多张图文笔记"
persona_fit:
  1: "例：与新加坡人、上海都无关"
  3: "例：在上海生活的外国人，但不是新加坡人"
  5: "例：新加坡人在上海，第一人称真实口吻"
```

- [ ] **Step 2: Write the failing scorer tests**

```python
# backend/tests/evals/test_score.py
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from clipsieve.judge.base import JudgeFailed  # noqa: E402
from clipsieve.judge.recorded import RecordedJudge  # noqa: E402
from clipsieve.judge.rubric import load_pack  # noqa: E402
from clipsieve.models import JudgeAnswer  # noqa: E402
from clipsieve.planner.plan import pack_summaries  # noqa: E402
from evals.score import (  # noqa: E402
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
    """A score answer whose argmax is `key`; legend keys start at `first` (Jev answers are 0-based)."""
    keys = [str(first + i) for i in range(levels)]
    return JudgeAnswer(
        type="score",
        value=float(key),
        probabilities={k: (1.0 if k == str(key) else 0.0) for k in keys},
        confidence=1.0,
        legend={k: "x" for k in keys},
    )


def test_predicted_level_prefers_argmax_probabilities():
    a = JudgeAnswer(type="score", value=2.4, probabilities={"1": 0.05, "2": 0.3, "3": 0.6, "4": 0.05}, confidence=0.7, legend={"1": "a", "2": "b", "3": "c", "4": "d"})
    assert predicted_level(a, levels=4) == 3  # first legend key is 1, argmax key 3: 3 - 1 + 1
    assert predicted_level(_score(2, levels=4), levels=4) == 3  # 0-based keys: level = key + 1


def test_predicted_level_falls_back_to_round_value():
    a = JudgeAnswer(type="score", value=2.4, probabilities=None, confidence=None, legend=None)
    assert predicted_level(a, levels=4) == 3  # no legend: 0-indexed, round(2.4) = 2, level 3 (E.3)
    a0 = JudgeAnswer(type="score", value=1.6, probabilities={"0": 0.2, "1": 0.8}, confidence=0.8, legend={"0": "a", "1": "b"})
    assert predicted_level(a0, levels=2) == 2  # 0-based legend keys: key 1 is level 2


def test_score_agreement_within_one_level():
    pack = load_pack(PACK)
    q = pack.questions["hook_strength"]  # 5 levels; the golden label is 1-based
    assert is_correct(q, _score(3, levels=5), 4) is True  # key 3 is level 4, equal to the label
    assert is_correct(q, _score(1, levels=5), 4) is False  # key 1 is level 2, two away


def test_choice_exact_and_noul_threshold():
    pack = load_pack(PACK)
    assert is_correct(pack.questions["hook_type"], JudgeAnswer(type="choice", value="result_first", probabilities={"result_first": 0.9}, confidence=0.9), "result_first")
    assert not is_correct(pack.questions["hook_type"], JudgeAnswer(type="choice", value="story", probabilities={"story": 0.5}, confidence=0.4), "result_first")
    assert is_correct(pack.questions["risky_claim"], JudgeAnswer(type="noul", value=0.71), True)
    assert is_correct(pack.questions["risky_claim"], JudgeAnswer(type="noul", value=0.2), False)
    assert not is_correct(pack.questions["risky_claim"], JudgeAnswer(type="noul", value=0.5), True)


def test_apply_mode_bilingual_appends_examples():
    pack = load_pack(PACK)
    item = read_golden(GOLDEN)[1]
    zh = load_zh_examples("creator-hooks-v1", REPO / "rubrics")
    p2, state, cost = apply_mode(pack, item, "bilingual", IdentityTranslator(), zh)
    assert "例：" in p2.questions["hook_type"].criteria["bold_claim"]
    assert p2.questions["hook_strength"].criteria[4].endswith("例：「你敢信吗？」加上强烈画面对比和明确利益点")
    assert state == item.state and cost == 0.0
    assert "例：" not in pack.questions["hook_type"].criteria["bold_claim"]   # original untouched


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
    report = await score_pack(pack, GOLDEN, FailsOnFirst(FIX), mode="raw", rubrics_dir=REPO / "rubrics")
    assert report.n_items == 5 and report.n_skipped == 1
    assert all(q.n == 4 for q in report.questions)


def test_pack_summaries_still_lists_only_the_pack_with_the_sidecar_present():
    rubrics = REPO / "rubrics"
    assert (rubrics / "creator-hooks-v1.zh-examples.yaml").exists()
    assert [s.name for s in pack_summaries(rubrics)] == ["creator-hooks-v1"]  # sidecar is skipped (E.14c)
```

`RecordedJudge(fixture_dir)` reads `<fixture_dir>/judge/<safe post id>.<pass_name>.json`, so tests pass `FIX` (`backend/tests/fixtures`), never `FIX / "judge"`; `score_pack` calls `judge.judge(item.post_id, "pass_two", state, questions, pack.jev_model)`, so the existing `pass_two` fixtures for `local:fx-001` to `fx-005` serve as recorded answers.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/evals/test_score.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals'`.

- [ ] **Step 4: Implement the scorer**

```python
# evals/__init__.py
"""clipsieve evaluation harness. Import via repo root on sys.path; see evals/README.md."""
```

```python
# evals/score.py
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Protocol

import structlog
import yaml
from pydantic import BaseModel

from clipsieve.judge.base import Judge, JudgeFailed, cost_usd
from clipsieve.models import JudgeAnswer, Question, RubricPack

log = structlog.get_logger(__name__)

MODES = ("raw", "translate", "bilingual")
TRANSLATE_FIELDS = (("post", "title"), ("post", "caption"))   # plus transcript[].text, ocr[].text, comments.sample[]


class GoldenItem(BaseModel):
    post_id: str
    state: dict
    labels: dict[str, str | int | bool]


class QuestionAgreement(BaseModel):
    question_id: str
    type: str
    n: int
    correct: int
    agreement: float
    mean_conf_correct: float | None
    mean_conf_incorrect: float | None


class EvalReport(BaseModel):
    pack: str
    mode: str
    n_items: int
    n_skipped: int = 0
    questions: list[QuestionAgreement]
    jev_input_tokens: int
    jev_cost_usd: float
    translate_cost_usd: float


class Translator(Protocol):
    def translate(self, texts: list[str]) -> tuple[list[str], float]: ...


class IdentityTranslator:
    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        return list(texts), 0.0


class ClaudeCliTranslator:
    """Translates a batch of strings to English through `claude -p` with the same flag set as ClaudeCliBackend."""

    SCHEMA = json.dumps({"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "string"}}}, "required": ["translations"], "additionalProperties": False})

    def __init__(
        self, bin: str = "claude", max_budget_usd: float = 1.0, model: str = "sonnet", timeout_s: int = 300
    ) -> None:
        self.bin, self.max_budget_usd, self.model, self.timeout_s = bin, max_budget_usd, model, timeout_s

    def translate(self, texts: list[str]) -> tuple[list[str], float]:
        if not texts:
            return [], 0.0
        argv = [
            self.bin, "-p", "--model", self.model, "--effort", "low",
            "--tools", "", "--strict-mcp-config", "--setting-sources", "",
            "--no-session-persistence",
            "--system-prompt", "Translate each string in `texts` to natural English. Preserve order and count. Return only the JSON.",
            "--output-format", "json", "--json-schema", self.SCHEMA,
            "--max-budget-usd", str(self.max_budget_usd),
            "Translate the strings in the JSON on stdin.",
        ]
        try:
            cp = subprocess.run(
                argv, input=json.dumps({"texts": texts}, ensure_ascii=False),
                capture_output=True, text=True, check=False, timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"translation timed out after {self.timeout_s}s") from e
        env = json.loads(cp.stdout or "{}")
        if env.get("is_error") or "structured_output" not in env:
            raise RuntimeError(f"translation failed: {env.get('result')}")
        out = env["structured_output"]["translations"]
        if len(out) != len(texts):
            raise RuntimeError(f"translation count mismatch {len(out)} != {len(texts)}")
        return out, float(env.get("total_cost_usd") or 0.0)


def read_golden(path: Path) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            items.append(GoldenItem.model_validate_json(line))
        except ValueError as e:
            raise ValueError(f"{path.name} line {i}: {e}") from e
    return items


def _first_level(answer: JudgeAnswer) -> int:
    """Lowest level index: the minimum integer legend key, else 0 (mirrors select/scoring.py, E.3)."""
    if answer.legend:
        keys = [int(k) for k in answer.legend if str(k).lstrip("-").isdigit()]
        if keys:
            return min(keys)
    return 0


def predicted_level(answer: JudgeAnswer, levels: int) -> int:
    """1-based level of a 0-indexed Jev score answer: (argmax key, else round(value)) - first + 1."""
    index: int | None = None
    if answer.probabilities:
        keyed = {int(k): p for k, p in answer.probabilities.items() if str(k).lstrip("-").isdigit()}
        if keyed:
            index = max(keyed, key=lambda k: keyed[k])
    if index is None:
        index = int(round(float(answer.value)))
    return max(1, min(levels, index - _first_level(answer) + 1))


def is_correct(question: Question, answer: JudgeAnswer, label) -> bool:
    if question.type == "choice":
        return str(answer.value) == str(label)
    if question.type == "score":
        return abs(predicted_level(answer, len(question.criteria)) - int(label)) <= 1
    if question.type == "noul":
        p = float(answer.value)
        return (p > 0.5) if bool(label) else (p < 0.5)
    raise ValueError(f"unknown question type {question.type}")


def load_zh_examples(pack_name: str, rubrics_dir: Path) -> dict:
    p = rubrics_dir / f"{pack_name}.zh-examples.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _collect_text_refs(state: dict) -> list[tuple[dict | list, str | int]]:
    refs: list[tuple[dict | list, str | int]] = []
    post = state.get("post") or {}
    for _, key in TRANSLATE_FIELDS:
        if isinstance(post.get(key), str) and post[key]:
            refs.append((post, key))
    for seg in state.get("transcript") or []:
        if isinstance(seg, dict) and seg.get("text"):
            refs.append((seg, "text"))
    for item in state.get("ocr") or []:
        if isinstance(item, dict) and item.get("text"):
            refs.append((item, "text"))
    sample = (state.get("comments") or {}).get("sample") or []
    for i, s in enumerate(sample):
        if isinstance(s, str) and s:
            refs.append((sample, i))
    return refs


def apply_mode(pack: RubricPack, item: GoldenItem, mode: str, translator: Translator, zh_examples: dict) -> tuple[RubricPack, dict, float]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "raw":
        return pack, item.state, 0.0
    if mode == "translate":
        state = copy.deepcopy(item.state)
        refs = _collect_text_refs(state)
        translated, cost = translator.translate([container[key] for container, key in refs])
        for (container, key), text in zip(refs, translated, strict=True):
            container[key] = text
        return pack, state, cost
    p2 = pack.model_copy(deep=True)
    for qid, examples in zh_examples.items():
        q = p2.questions.get(qid)
        if q is None or not isinstance(examples, dict):
            continue
        if q.type == "choice":
            for label, ex in examples.items():
                if label in q.criteria:
                    q.criteria[label] = f"{q.criteria[label]} {ex}"
        elif q.type == "score":
            for level, ex in examples.items():
                idx = int(level) - 1
                if 0 <= idx < len(q.criteria):
                    q.criteria[idx] = f"{q.criteria[idx]} {ex}"
    return p2, item.state, 0.0


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


async def score_pack(
    pack: RubricPack,
    golden_path: Path,
    judge: Judge,
    mode: str = "raw",
    translator: Translator | None = None,
    rubrics_dir: Path = Path("rubrics"),
) -> EvalReport:
    translator = translator or IdentityTranslator()
    items = read_golden(golden_path)
    zh = load_zh_examples(pack.name, rubrics_dir) if mode == "bilingual" else {}
    per_q: dict[str, dict] = {qid: {"type": q.type, "n": 0, "correct": 0, "conf_ok": [], "conf_bad": []} for qid, q in pack.questions.items()}
    tokens = 0
    translate_cost = 0.0
    skipped = 0
    for item in items:
        p2, state, tcost = apply_mode(pack, item, mode, translator, zh)
        translate_cost += tcost
        try:
            result = await judge.judge(item.post_id, "pass_two", state, dict(p2.questions), p2.jev_model)
        except JudgeFailed as e:
            skipped += 1  # one failed post must not lose the whole eval
            log.warning("eval.item_skipped", post_id=item.post_id, error=str(e))
            continue
        tokens += result.input_tokens
        for qid, q in p2.questions.items():
            if qid not in item.labels or qid not in result.answers:
                continue
            ans = result.answers[qid]
            ok = is_correct(q, ans, item.labels[qid])
            s = per_q[qid]
            s["n"] += 1
            s["correct"] += int(ok)
            conf = ans.confidence if ans.confidence is not None else (abs(2 * float(ans.value) - 1) if q.type == "noul" else None)
            if conf is not None:
                (s["conf_ok"] if ok else s["conf_bad"]).append(conf)
    questions = [
        QuestionAgreement(
            question_id=qid, type=s["type"], n=s["n"], correct=s["correct"],
            agreement=(s["correct"] / s["n"]) if s["n"] else 0.0,
            mean_conf_correct=_mean(s["conf_ok"]), mean_conf_incorrect=_mean(s["conf_bad"]),
        )
        for qid, s in per_q.items()
    ]
    report = EvalReport(pack=pack.name, mode=mode, n_items=len(items), n_skipped=skipped, questions=questions, jev_input_tokens=tokens, jev_cost_usd=cost_usd(tokens), translate_cost_usd=translate_cost)
    log.info("eval.done", pack=pack.name, mode=mode, n=len(items), skipped=skipped, cost=report.jev_cost_usd)
    return report


def render_markdown(report: EvalReport) -> str:
    def f(x: float | None) -> str:
        return "-" if x is None else f"{x:.2f}"

    lines = [
        f"**Pack:** `{report.pack}`  **Mode:** `{report.mode}`  **Items:** {report.n_items}  **Skipped:** {report.n_skipped}  **Jev cost:** ${report.jev_cost_usd:.4f}  **Translate cost:** ${report.translate_cost_usd:.4f}",
        "",
        "| question | type | n | agreement | conf when right | conf when wrong |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for q in report.questions:
        lines.append(f"| {q.question_id} | {q.type} | {q.n} | {q.agreement:.2f} | {f(q.mean_conf_correct)} | {f(q.mean_conf_incorrect)} |")
    return "\n".join(lines) + "\n"
```

`pyyaml` is already a backend dependency (the rubric loader uses it); do not touch `backend/pyproject.toml`. Create `evals/ruff.toml` with the single line `extend = "../backend/pyproject.toml"`.

- [ ] **Step 5: Write evals docs and DOX child, update root index**

```markdown
# evals/README.md

# clipsieve evals

Measures how well a rubric pack's Jev answers agree with human labels, per question, in three language modes.

## Golden format

One JSON object per line in `evals/golden/<lang>-<n>.jsonl`:

- `post_id`: any stable id, usually `platform:id`.
- `state`: the Jev state in the shape `backend/clipsieve/evidence/packet.py::build_state` produces (`brief`, flat `post`, `transcript[].text`, `ocr[].text`, `comments`). It need not be byte-identical: the scorer reads only `post.title`, `post.caption` and the `text` fields (translate mode) and forwards the rest to the judge. Text evidence only, no media paths, creator ids already hashed.
- `labels`: `question_id -> label`. Choice: the label key. Score: 1-based level integer. Noul: `true`/`false`.

Lines starting with `#` are ignored.

## Labelling protocol

1. Pull 100 posts per language from a real run with `sieve export-golden RUN_ID --n 100 --lang zh` (plan 03 follow-up; until then copy `state` from `data/runs/<id>/evidence/` and `posts/`).
2. Two people label independently with the pack's criteria text in front of them. Disagreements are resolved by discussion; unresolved items are dropped.
3. Record the labelling date and the pack version in the file's first comment line.
4. Never commit media or raw platform payloads. States are text evidence only.

## Running

```bash
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode raw
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode translate
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode bilingual
```

Each run prints a markdown table and rewrites its `### <golden stem> <mode> (<date>)` section inside the results block of `rubrics/<pack>.calibration.md` (other golden sets and modes are kept). A post whose judge call fails after retries is skipped and counted as `Skipped`. Agreement rules: choice exact match; score within one level; noul correct when the probability is on the labelled side of 0.5.

## Modes

- `raw`: state sent as-is.
- `translate`: text fields translated to English with `claude -p` (cost reported separately). Tests the hypothesis that Jev's lower CJK accuracy is the bottleneck.
- `bilingual`: English criteria with Chinese examples from `rubrics/<pack>.zh-examples.yaml` appended. Tests whether grounding the rubric is enough without translating evidence.

Pick the winner per pack and set `language_mode` in the pack YAML.
```

```markdown
# evals — AGENTS.md

Inherits root AGENTS.md.

- `score.py` is pure Python importable with the repo root on `sys.path`; `sieve eval` loads it that way. Keep it free of FastAPI and frontend imports.
- Never call TypeSafe or Claude in tests. Use `RecordedJudge` and `IdentityTranslator`.
- Golden files hold text evidence only. No media, no raw payloads, no unhashed creator ids.
- Agreement rules (choice exact, score within one level of a 0-indexed answer mapped to a 1-based level, noul side of 0.5) are documented in README.md; change both together.
- A `JudgeFailed` item is skipped and counted, never fatal. `ClaudeCliTranslator` always runs with a subprocess timeout.
- `evals/ruff.toml` extends the backend ruff config; `bun run lint` covers this folder.
```

Root `AGENTS.md` Child DOX Index: add a TABLE row (after the `contrib/adapter-xhs-mediacrawler/AGENTS.md` row):

```markdown
| `evals/AGENTS.md` | Golden sets (`golden/`) and `score.py`; agreement rules live in `evals/README.md` |
```

- [ ] **Step 6: Run tests and commit**

Run: `cd backend && uv run ruff format ../evals tests/evals && uv run ruff check ../evals tests/evals && uv run pytest tests/evals -v`
Expected: `10 passed` (read_golden, 2 predicted_level, within-one, choice/noul, 2 apply_mode, score_pack, judge-failed skip, pack_summaries sidecar).

```bash
git add evals rubrics/creator-hooks-v1.zh-examples.yaml backend/tests/fixtures/golden backend/tests/evals AGENTS.md
git commit -m "feat(evals): golden format, sample set, scorer with raw/translate/bilingual modes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 6: `sieve eval` command and calibration file writer

**Files:**
- Modify: `backend/clipsieve/cli.py` (edit the existing `eval_cmd` in place; keep `@app.command("eval")`; hoist the new imports to the top of the file)
- Create: `backend/clipsieve/calibration.py`
- Test: `backend/tests/test_cli_eval.py`
- Modify: `backend/tests/test_cli.py` (delete `test_eval_is_a_stub`; the stub it asserts no longer exists)
- Modify: `rubrics/creator-hooks-v1.calibration.md` (keep the header and the Decision section, replace the two placeholder tables with the marker block)
- Modify: `backend/AGENTS.md` (cli section and layout: `eval` is implemented; new `clipsieve/calibration.py` row)
- Modify: `rubrics/AGENTS.md` (one line: results live between the markers, one `### <stem> <mode> (<date>)` section each)

**Interfaces:**
- Consumes: `app`, `find_pack`, `PackNotFound`, `RecordedJudge`, `TypeSafeJudge`, `get_settings`, `REPO_ROOT`, `evals.score.score_pack`, `render_markdown`, `ClaudeCliTranslator`, `IdentityTranslator`.
- Produces:

```python
# backend/clipsieve/calibration.py
RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
def write_results(calibration_path: Path, stem: str, mode: str, table_md: str, when: datetime) -> None
    # replaces the section "### <stem> <mode> (<date>)" between the markers, keeps every other
    # section and all text outside the markers; creates the file with a header if missing
def repo_root() -> Path   # returns clipsieve.config.REPO_ROOT (overview C.11)
```

`sieve eval` options (all `Annotated`, like the other commands): `--pack`, `--golden`, `--mode raw|translate|bilingual` (default `raw`), `--rubrics-dir` (default `<repo>/rubrics`), `--judge-fixtures DIR` (a fixtures directory; `RecordedJudge` reads `<DIR>/judge/`, so tests pass `FIX`, not `FIX / "judge"`). Exit codes follow E.10: bad `--mode`, unknown pack (`PackNotFound`), or no `TYPESAFE_API_KEY` without `--judge-fixtures` exit 2 with a message on stderr; success exits 0.

- [ ] **Step 1: Write the failing CLI tests**

```python
# backend/tests/test_cli_eval.py
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipsieve.calibration import RESULTS_END, RESULTS_START, write_results
from clipsieve.cli import app
from clipsieve.config import Settings

FIX = Path(__file__).parent / "fixtures"
GOLDEN = FIX / "golden" / "sample-5.jsonl"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    # No real .env and no cached settings leak in (same trick as tests/test_cli.py).
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("clipsieve.cli.get_settings", lambda: Settings(_env_file=None))


def test_write_results_replaces_block_and_keeps_rest(tmp_path):
    p = tmp_path / "x.calibration.md"
    p.write_text("# Calibration\n\nintro\n\n<!-- results:start -->\nold\n<!-- results:end -->\n\nfooter\n", encoding="utf-8")
    write_results(p, "zh-100", "raw", "| a |\n", datetime(2026, 10, 3, tzinfo=UTC))
    text = p.read_text(encoding="utf-8")
    assert "old" not in text and "intro" in text and "footer" in text
    assert text.index(RESULTS_START) < text.index("### zh-100 raw (2026-10-03)") < text.index(RESULTS_END)


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


def test_eval_command_prints_table_and_writes_calibration(tmp_path):
    rubrics = tmp_path / "rubrics"
    rubrics.mkdir()
    src = Path(__file__).resolve().parents[2] / "rubrics" / "creator-hooks-v1.yaml"
    (rubrics / "creator-hooks-v1.yaml").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(app, [
        "eval", "--pack", "creator-hooks-v1", "--golden", str(GOLDEN),
        "--mode", "raw", "--rubrics-dir", str(rubrics), "--judge-fixtures", str(FIX),
    ])
    assert result.exit_code == 0, result.output
    assert "| question |" in result.stdout and "hook_strength" in result.stdout
    cal = (rubrics / "creator-hooks-v1.calibration.md").read_text(encoding="utf-8")
    assert "### sample-5 raw (" in cal and "hook_strength" in cal


def test_eval_rejects_unknown_mode():
    result = runner.invoke(app, ["eval", "--pack", "creator-hooks-v1", "--golden", str(GOLDEN), "--mode", "magic"])
    assert result.exit_code == 2 and "mode" in result.output.lower()


def test_eval_unknown_pack_exits_2_without_a_traceback(tmp_path):
    result = runner.invoke(app, [
        "eval", "--pack", "no-such-pack", "--golden", str(GOLDEN),
        "--rubrics-dir", str(tmp_path), "--judge-fixtures", str(FIX),
    ])
    assert result.exit_code == 2 and "no-such-pack" in result.output
    assert "Traceback" not in result.output


def test_eval_without_typesafe_key_or_fixtures_exits_2():
    result = runner.invoke(app, ["eval", "--pack", "creator-hooks-v1", "--golden", str(GOLDEN)])
    assert result.exit_code == 2 and "TYPESAFE_API_KEY" in result.output
```

Also delete `test_eval_is_a_stub` from `backend/tests/test_cli.py` (it asserts the plan 03 stub's exit 2 and "plan 05" text, which this task removes).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli_eval.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.calibration'`.

- [ ] **Step 3: Implement calibration writer and the command**

```python
# backend/clipsieve/calibration.py
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from clipsieve.config import REPO_ROOT

RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
_SECTION = re.compile(
    r"^### (?P<stem>\S+) (?P<mode>\w+) \((?P<date>\d{4}-\d{2}-\d{2})\)\n(?P<body>.*?)(?=^### |\Z)",
    re.S | re.M,
)


def repo_root() -> Path:
    return REPO_ROOT


def _header(path: Path) -> str:
    name = path.name.removesuffix(".calibration.md")
    return (
        f"# {name} calibration\n\nResults written by `sieve eval`. Do not edit inside the markers.\n\n"
        f"{RESULTS_START}\n{RESULTS_END}\n"
    )


def write_results(
    calibration_path: Path, stem: str, mode: str, table_md: str, when: datetime
) -> None:
    text = (
        calibration_path.read_text(encoding="utf-8")
        if calibration_path.exists()
        else _header(calibration_path)
    )
    if RESULTS_START not in text or RESULTS_END not in text:
        text = text.rstrip("\n") + f"\n\n{RESULTS_START}\n{RESULTS_END}\n"
    head, rest = text.split(RESULTS_START, 1)
    block, tail = rest.split(RESULTS_END, 1)
    sections = {
        (m.group("stem"), m.group("mode")): (m.group("date"), m.group("body"))
        for m in _SECTION.finditer(block)
    }
    sections[(stem, mode)] = (when.strftime("%Y-%m-%d"), table_md.rstrip("\n") + "\n")
    new_block = "\n" + "".join(
        f"### {s} {m} ({dt})\n{body}\n" for (s, m), (dt, body) in sorted(sections.items())
    )
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_path.write_text(f"{head}{RESULTS_START}{new_block}{RESULTS_END}{tail}", encoding="utf-8")
```

Hoist the new imports to the top of `backend/clipsieve/cli.py`, in isort order with the existing ones (ruff `I001`/`E402` fail on mid-file imports). The existing imports already provide `asyncio`, `sys`, `Path`, `Annotated`, `typer`, `get_settings`, `PackNotFound` and `find_pack`; add:

```python
from datetime import UTC, datetime                      # stdlib block, after `from contextlib import contextmanager`
...
from clipsieve.calibration import repo_root, write_results   # after `from clipsieve.api.context import ...`
from clipsieve.judge.recorded import RecordedJudge           # before `from clipsieve.judge.rubric import ...`
from clipsieve.judge.typesafe_client import TypeSafeJudge    # after `from clipsieve.judge.rubric import ...`
```

Also change the module docstring's "2 usage error, declined plan or not implemented" to "2 usage error or declined plan". `evals.score` is the one import that stays inside the function, because the repo root must be on `sys.path` first.

Edit the existing `eval_cmd` IN PLACE (same decorator, same name, `Annotated` options like its neighbours):

```python
# backend/clipsieve/cli.py  (replace the body and signature of the existing eval_cmd)
@app.command("eval")
def eval_cmd(
    pack: Annotated[str, typer.Option("--pack", help="Rubric pack name, e.g. creator-hooks-v1")],
    golden: Annotated[
        Path, typer.Option("--golden", exists=True, dir_okay=False, help="Golden JSONL file")
    ],
    mode: Annotated[str, typer.Option("--mode", help="raw | translate | bilingual")] = "raw",
    rubrics_dir: Annotated[
        Path | None, typer.Option("--rubrics-dir", help="Defaults to <repo>/rubrics")
    ] = None,
    judge_fixtures: Annotated[
        Path | None,
        typer.Option(
            "--judge-fixtures",
            help="Use RecordedJudge on this fixtures dir (reads <dir>/judge/) instead of TypeSafe",
        ),
    ] = None,
) -> None:
    """Score a rubric pack against a golden set and write rubrics/<pack>.calibration.md."""
    if mode not in ("raw", "translate", "bilingual"):
        _say("--mode must be raw, translate or bilingual", err=True)
        raise typer.Exit(2)
    root = repo_root()
    rubrics = rubrics_dir or root / "rubrics"
    try:
        rp = find_pack(pack, rubrics)
    except PackNotFound as exc:
        _say(str(exc), err=True)
        raise typer.Exit(2) from exc
    settings = get_settings()
    if judge_fixtures is None and not settings.typesafe_api_key:
        _say("TYPESAFE_API_KEY is not set; set it in .env or pass --judge-fixtures", err=True)
        raise typer.Exit(2)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from evals.score import ClaudeCliTranslator, IdentityTranslator, render_markdown, score_pack

    judge = (
        RecordedJudge(judge_fixtures)
        if judge_fixtures
        else TypeSafeJudge(settings.typesafe_api_key)
    )
    translator = (
        ClaudeCliTranslator(settings.clipsieve_claude_bin)
        if mode == "translate" and judge_fixtures is None
        else IdentityTranslator()
    )

    async def _run():
        try:
            return await score_pack(
                rp, golden, judge, mode=mode, translator=translator, rubrics_dir=rubrics
            )
        finally:
            aclose = getattr(judge, "aclose", None)  # TypeSafeJudge has one, RecordedJudge does not
            if aclose is not None:
                await aclose()

    report = asyncio.run(_run())
    table = render_markdown(report)
    _say(table)
    cal = rubrics / f"{pack}.calibration.md"
    write_results(cal, golden.stem, mode, table, datetime.now(tz=UTC))
    _say(f"wrote {cal}")
```

Rewrite `rubrics/creator-hooks-v1.calibration.md`: keep the title, the pack/model/status line and the whole `## Decision` section; replace the placeholder "English golden set" and "Chinese golden set" tables with the marker block. The file becomes:

```markdown
# creator-hooks-v1 calibration

Pack version: 1. Jev model: jev-1.13.0. Status: NOT CALIBRATED.

Filled by `sieve eval` between the markers below: one `### <golden stem> <mode> (<date>)` section per golden set (`en-100`, `zh-100`) and mode (`raw`, `translate`, `bilingual`). Do not edit inside the markers.

<!-- results:start -->
<!-- results:end -->

## Decision

language_mode: raw (default until a mode wins by at least 5 points of agreement on hook_type and hook_strength).
```

Add one line to `rubrics/AGENTS.md` after the calibration bullet: "`sieve eval` writes only between the `<!-- results:start -->` / `<!-- results:end -->` markers, one `### <golden stem> <mode> (<date>)` section each; everything else in the file is hand-written."

Update `backend/AGENTS.md`: in the `cli.py` section replace "`eval --pack P --golden FILE [--mode M]` (stub until plan 05)" with "`eval --pack P --golden FILE [--mode M] [--rubrics-dir DIR] [--judge-fixtures DIR]`", and in the exit-codes bullet replace ", or `eval`" with "; `eval` also exits 2 for an unknown pack or a missing `TYPESAFE_API_KEY` without `--judge-fixtures`"; in the Layout table change the `clipsieve/cli.py` row's "`eval` stub" to "`eval`" and add the row ``| `clipsieve/calibration.py` | `write_results(path, stem, mode, table_md, when)`: rewrites one `### <stem> <mode> (<date>)` section between the results markers of `<pack>.calibration.md`; `repo_root()` |``. The `evals/` scorer is documented in `evals/AGENTS.md`.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && uv run ruff format clipsieve tests && uv run ruff check clipsieve tests && uv run pytest tests/test_cli_eval.py tests/test_cli.py tests/evals -v
```
Expected: `test_cli_eval.py` 7 passed (3 writer, 4 command) and `tests/evals` 10 passed; `tests/test_cli.py` passes with `test_eval_is_a_stub` removed.

- [ ] **Step 5: Commit**

```bash
git add backend/clipsieve/cli.py backend/clipsieve/calibration.py backend/tests/test_cli_eval.py backend/tests/test_cli.py backend/AGENTS.md rubrics/AGENTS.md rubrics/creator-hooks-v1.calibration.md
git commit -m "feat(cli): implement sieve eval with calibration results writer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
```

---

### Task 7: Root docs, CI, and full check

**Files:**
- Modify: `README.md` (root; add "Community adapters" and "Evaluation" sections)
- Modify: `package.json` (root; the `lint` script also lints `evals/` and `contrib/`)
- Modify: `.github/workflows/check.yml` (add contrib job)
- Modify: `AGENTS.md` (root; confirm the Child DOX Index table has the `contrib/` and `evals/` rows and the trailing paragraph no longer promises them)
- Create: `contrib/adapter-xhs-mediacrawler/uv.lock` (committed; CI uses `--frozen`)

**Interfaces:**
- Consumes: root `bun run check` from plan 01; CI workflow from plan 01.
- Produces: CI runs contrib tests with the runner faked.

- [ ] **Step 1: Add README sections**

Insert into root `README.md` immediately after the `## Adapters` section (before `## Development`), as two new sections:

```markdown
## Community adapters

Browser-session adapters live under `contrib/` as separate packages with their own licences and disclaimers. They are **not** part of the core and the core never imports them.

| Adapter | Platform | How it works | Licence constraints |
|---|---|---|---|
| [`contrib/adapter-xhs-mediacrawler`](contrib/adapter-xhs-mediacrawler/README.md) | Xiaohongshu (小红书) | Drives a local [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout in CDP mode against your own logged-in Chrome | MediaCrawler is Non-Commercial Learning License 1.1: learning and research only, no commercial use |

Install one into the backend environment and clipsieve discovers it:

```bash
cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler
```

You are responsible for complying with each platform's terms of service and the laws that apply to you.

## Evaluation

Rubric packs ship with calibration numbers. `sieve eval` scores a pack against a hand-labelled golden set per question, in `raw`, `translate` and `bilingual` modes, and writes the results into `rubrics/<pack>.calibration.md`. See [`evals/README.md`](evals/README.md) for the golden format and labelling protocol.
```

- [ ] **Step 2: Cover `evals/` and `contrib/` in the root lint script**

`bun run check` runs `bun run lint`, which today lints only `backend/`. In the root `package.json` replace the `lint` script with:

```json
"lint": "bunx ultracite check && (cd backend && uv run ruff check . ../evals ../contrib && uv run ruff format --check . ../evals ../contrib)",
```

(`format` gets the same extra paths: `"format": "bunx ultracite fix && (cd backend && uv run ruff format . ../evals ../contrib)"`.) Ruff resolves each file's config from the nearest `pyproject.toml`/`ruff.toml`, so `contrib/adapter-xhs-mediacrawler/` uses its own `[tool.ruff]` and `evals/` uses `evals/ruff.toml`, which extends the backend config.

- [ ] **Step 3: Extend the CI workflow**

Add a job to `.github/workflows/check.yml` (keep the existing `check` job untouched):

```yaml
  contrib-xhs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - name: Install core and contrib
        run: |
          cd backend && uv sync --frozen
          cd ../contrib/adapter-xhs-mediacrawler && uv sync --frozen
      - name: Lint contrib
        run: cd contrib/adapter-xhs-mediacrawler && uv run ruff check . && uv run ruff format --check .
      - name: Test contrib (runner and Chrome faked)
        run: cd contrib/adapter-xhs-mediacrawler && uv run pytest -q
      - name: Verify entry point discovery
        run: |
          cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler
          uv run python -c "from clipsieve.adapters.registry import load_adapters; from clipsieve.config import Settings; a = load_adapters(Settings(_env_file=None)); assert 'xiaohongshu' in a, a; print(sorted(a))"
```

Run `cd contrib/adapter-xhs-mediacrawler && uv lock` so `uv.lock` exists for `--frozen`, and **commit it** (Step 5 stages it explicitly; the job fails without it).

- [ ] **Step 4: Run the full check locally**

Run:
```bash
bun run check
cd contrib/adapter-xhs-mediacrawler && uv run pytest -q
```
Expected: `bun run check` exits 0 (schema unchanged, lint clean including `evals/` and `contrib/`, typecheck clean, backend and frontend tests pass); contrib tests pass (`42 passed`).

- [ ] **Step 5: Commit and push**

```bash
git add README.md package.json .github/workflows/check.yml AGENTS.md contrib/adapter-xhs-mediacrawler/uv.lock
git commit -m "docs(contrib,evals): community adapters and evaluation sections; CI job for contrib adapter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XC9nMme23mc4K4ZUvwK5Bu"
git push origin HEAD
```

---

## Self-review

**Spec coverage.** §5.4 (separate uv project, CDP against user's Chrome, `--type search --keywords`, JSON output mapping, image notes as `image_note` with one media per image, disclaimer in README and AGENTS.md, core never imports, listed in root README as community adapter, healthcheck for Chrome port and login state) → Tasks 1, 2, 3, 4, 7. The spec's "MediaCrawler as a git dependency pinned to a commit" and "video notes download through MediaCrawler's media option" are **amended** by this plan because MediaCrawler is not installable from git and its media layout is unverified; the plan pins a sibling checkout by commit and downloads media itself. Login state: in CDP mode the session lives in the user's Chrome, so the healthcheck verifies Chrome reachability and the pinned commit rather than a MediaCrawler state file (Task 2). §7.3 (three modes, per-question agreement, set `language_mode` to winner, numbers in calibration file) → Tasks 5, 6. §13 evals bullet (`sieve eval` prints agreement; golden sets text-only with hashed creators) → Tasks 5, 6, and the README protocol. §14 (contrib packages with own notices; user responsibility statement; creators hashed; comments capped) → Tasks 1, 3.

**Placeholder scan.** No TBD/TODO. Every code step has full code. The two golden `*-100.jsonl` files are deliberately header-only because labelling is manual work outside the plan; `sample-5.jsonl` carries the real test data.

**Overview addenda alignment.** A8 (`.value` on enums) applied in Task 3 and 4 tests and in `fetch_media`. B1 (`incoming_dir`, absolute `raw_ref`) applied in Task 4. B2 (dest-relative `video.mp4` / `img_NN.jpg`) applied in Task 4. B6 (`from_settings`) applied in Task 4. B10 and Ruling 1 (persistent media-URL cache, `fetch_media` never reads the raw file) applied in Task 4; B11 (`MediaDownloadError` imported from `clipsieve.adapters.base`) in Task 4; A11/A12 (`REPO_ROOT` env tuple, `ensure_creator_salt`) in Tasks 1, 2 and 4; E.3 (0-indexed score answers) in Task 5; E.10 (exit 2 for usage errors) in Task 6; E.14c (sidecar YAML skipped by `pack_summaries`) pinned in Task 5. A10 (`setup-uv@v6`) applied in Task 7. Addendum C is amended to match (C.2, C.8, C.12, C.13, new C.15 to C.18).

**Type consistency.** `RunnerOutput` fields used identically in Tasks 2 and 4. `FIELD_MAP` keys used only through `_g`. `map_note(note, comments, salt, raw_ref, collected_at)` signature identical in Tasks 3 and 4. `score_pack(pack, golden_path, judge, mode, translator, rubrics_dir)` identical in Tasks 5 and 6. `Judge.judge(post_id, pass_name, state, questions, model)` matches the overview. `write_results(path, stem, mode, table_md, when)` identical in Task 6 code and tests. `MediaCrawlerRunner(settings, cdp_port=...)` is built the same way in Tasks 2 and 4, with the port always read from core `Settings`.

**Review Focus.** 1 → `test_mapping_preserves_cjk_exactly` (Task 3). 2 → `test_read_records_skips_truncated_last_line`, `test_search_timeout_returns_partial` (Task 2). 3 → `test_normal_note_without_images` (Task 3). 4 → the four `test_healthcheck_*` tests (Task 2) plus `test_healthcheck_delegates` (Task 4). 5 → `test_predicted_level_prefers_argmax_probabilities`, `test_predicted_level_falls_back_to_round_value`, `test_score_agreement_within_one_level` (Task 5).

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-05-contrib-xhs-evals.md`. It depends on plans 02 and 03 being merged. Recommended execution: **subagent-driven**, because Tasks 2 to 4 share the `RunnerOutput` and mapping contracts and a reviewer catching a key-name drift between them before Task 4 is cheaper than debugging it against a real MediaCrawler run.
