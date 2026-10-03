# clipsieve v0.1 Plan 02: Adapters and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give clipsieve its two ingest layers: platform adapters that turn a search into normalised `Post` records (local import and YouTube Shorts), and the evidence pipeline that turns a post's media into text (transcript, OCR, keyframes, comment summary) and packs it into a Jev state that fits the 32k cap.

**Architecture:** Every external system sits behind a Protocol with a fake. Adapters live in `backend/clipsieve/adapters/` and are discovered by entry point; they never import evidence code. Evidence extractors live in `backend/clipsieve/evidence/`, never touch the network, and write their results through `RunPaths`. The packet builder is pure and deterministic. Plan 01 supplies the generated models, settings, store and event log; this plan consumes them by name and adds nothing to them.

**Tech Stack:** Python 3.12, uv, Pydantic v2 (generated `clipsieve.models`), structlog, yt-dlp (library), httpx, ffmpeg (subprocess), mlx-whisper / faster-whisper (optional extra `asr`), PaddleOCR (optional extra `ocr`), pytest with pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md` sections 5 and 6. Binding names and signatures: `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`.

## Global Constraints

- Python 3.12 exactly (`requires-python = ">=3.12,<3.13"`). Managed by `uv`. Never pip.
- Bun 1.3+ for all JS. Never npm, yarn or pnpm. Next.js 16, React 19, Tailwind 4, shadcn, ultracite 7 (Biome).
- Backend package name `clipsieve`, import root `backend/clipsieve/`. CLI command `sieve`.
- `structlog` only for logging. No `print()` in `backend/clipsieve/`. `print` is allowed in `cli.py` output helpers and in `packages/schema/generate.py`.
- Pydantic v2 everywhere. Settings via `pydantic-settings` reading `.env`.
- Every external system behind a Protocol with a fake: `Adapter`, `ASR`, `OCR`, `FrameExtractor`, `Judge`, `ExplainBackend`.
- Tests: `pytest` with `pytest-asyncio` (mode `auto`) in `backend/tests/`; Vitest in `frontend/`; one Playwright flow in `frontend/e2e/`. No live network in tests. CI uses fakes only.
- Commit after every task with a conventional-commit message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Every new directory with code gets an `AGENTS.md` (DOX child) in the same task that creates it, and the root `AGENTS.md` Child DOX Index is updated in that task.
- No file in the repo may contain a real API key. `.env.example` lists every variable with an empty value.
- Chinese and English UI strings from the first component.

Plan-02 specific constraints:

- `adapters/` never imports from `evidence/`. `evidence/` never imports from `adapters/` and never opens a network connection.
- Heavy dependencies (yt-dlp is the exception, it is a core dependency) are imported lazily inside the class that needs them so `import clipsieve.evidence` works on a machine without Whisper or Paddle installed.
- All run commands below are executed from `backend/` unless stated otherwise.

## Contract decisions made in this plan

These fill gaps the overview leaves open. Plan 03 (Runner) must honour the first three.

1. **Raw payload location.** Adapters do not know the run. Each adapter writes its raw payload to `<data_dir>/incoming/<platform>/<safe_post_id>.json` and sets `Post.raw_ref` to that absolute path. The Runner relocates the file to `RunPaths.raw_path(post.id, "json")` on `post_collected` and rewrites `raw_ref` to the run-relative string `raw/<safe_post_id>.json`.
2. **Media paths.** `fetch_media(post, dest)` writes files directly into `dest` and sets each `Media.local_path` to a filename relative to `dest` (for example `video.mp4`, `img_00.jpg`). `extract_evidence` resolves them as `paths.media_dir(post.id) / media.local_path`. `Evidence.keyframes` are run-relative strings `media/<safe_post_id>/frames/<name>`.
3. **`Evidence.truncated` at extraction time is always `False`.** Truncation depends on the brief, which the extractor does not have. The Runner calls `build_state` and, when it returns `truncated=True`, sets `evidence.truncated = True` and re-saves. `Evidence.token_estimate` is the estimate for transcript plus OCR plus comment summary text only.
4. **Token estimate counts CJK characters as one token each** and other characters as one token per three. The overview comment says `len(text) // 3`; that undercounts Chinese by roughly three times and would blow the Jev cap. The signature is unchanged.
5. **Local import source comes from the query.** `Query.query` holds the folder path or CSV path for platform `local`. The adapter takes no path at construction.
6. **Adapter construction.** Every adapter class has `@classmethod from_settings(cls, settings: Settings) -> "Adapter"`. `load_adapters` calls it. Built-in adapters are also loaded directly by import when their entry point is absent (editable installs without a dist).
7. **Captions sidecar.** When an adapter has captions, it writes `<media_path>.transcript.json` as `{"lang": "en", "segments": [{"start_s": 0.0, "end_s": 1.2, "text": "..."}]}`. Both `FakeASR` and `WhisperASR` return the sidecar when present and skip transcription.
8. **Frame names.** `FrameExtractor.extract` always returns the hook frame first as `hook.jpg` (frame at 0.5 s), then `scene_01.jpg` onward, capped at `max_frames` total.

## Review Focus

1. A Chinese transcript of 15,000 characters must be estimated at roughly 15,000 tokens, not 5,000, and `build_state` must truncate it rather than send an over-cap state. Test: `test_packet.py::test_cjk_estimate_and_truncation`.
2. A CSV row whose caption contains Chinese, an emoji and a comma inside quotes must round-trip into `Post.text.caption` byte-for-byte. Test: `test_local_import.py::test_csv_chinese_caption_roundtrip`.
3. A YouTube auto-caption VTT with rolling duplicate cues must produce a transcript with no repeated sentences and monotonic timestamps. Test: `test_youtube.py::test_parse_vtt_rolling_cues`.
4. A post with more than 50 comments must reach the pipeline with exactly 50, the most-liked ones. Test: `test_youtube.py::test_comments_capped_most_liked`.
5. `fetch_media` called twice on the same post must not re-download and must return identical `local_path` values. Test: `test_local_import.py::test_fetch_media_idempotent` and the contract helper.

---

### Task 1: Adapter protocol, creator hashing, and the reusable contract test

**Files:**
- Create: `backend/clipsieve/adapters/__init__.py`
- Create: `backend/clipsieve/adapters/base.py`
- Create: `backend/tests/adapters/__init__.py`
- Create: `backend/tests/adapters/contract.py`
- Test: `backend/tests/adapters/test_base.py`

**Interfaces:**
- Consumes: `clipsieve.models.Post`, `clipsieve.models.Query` (plan 01).
- Produces: `AdapterHealth`, `Adapter` Protocol, `hash_creator(platform_creator_id: str, salt: str) -> str`, test helper `run_adapter_contract(adapter, query, tmp_path) -> list[Post]`.

- [x] **Step 1: Write the failing test**

`backend/tests/adapters/test_base.py`:

```python
import hashlib

from clipsieve.adapters.base import AdapterHealth, hash_creator


def test_hash_creator_is_salted_sha256_hex():
    out = hash_creator("UCabc123", "pepper")
    assert out == hashlib.sha256(b"pepper:UCabc123").hexdigest()
    assert len(out) == 64


def test_hash_creator_differs_by_salt():
    assert hash_creator("UCabc123", "a") != hash_creator("UCabc123", "b")


def test_hash_creator_never_returns_raw_id():
    assert hash_creator("UCabc123", "") != "UCabc123"


def test_adapter_health_dataclass():
    h = AdapterHealth(ok=False, message="no chrome")
    assert h.ok is False and h.message == "no chrome"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.adapters'`

- [x] **Step 3: Write the protocol and hashing**

`backend/clipsieve/adapters/__init__.py`:

```python
"""Platform adapters: search -> Post, fetch_media -> Post with local media."""
```

`backend/clipsieve/adapters/base.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from clipsieve.models import Post, Query


@dataclass
class AdapterHealth:
    ok: bool
    message: str


@runtime_checkable
class Adapter(Protocol):
    platform: str

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]: ...

    def fetch_media(self, post: Post, dest: Path) -> Post: ...

    def healthcheck(self) -> AdapterHealth: ...


def hash_creator(platform_creator_id: str, salt: str) -> str:
    """Stable, salted, one-way creator identifier. Never store the raw id."""
    return hashlib.sha256(f"{salt}:{platform_creator_id}".encode("utf-8")).hexdigest()


def incoming_dir(data_dir: Path, platform: str) -> Path:
    """Where adapters park raw payloads before the Runner relocates them into the run."""
    d = data_dir / "incoming" / platform
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [x] **Step 4: Write the reusable contract helper**

`backend/tests/adapters/__init__.py` is empty.

`backend/tests/adapters/contract.py`:

```python
"""Adapter contract. Every adapter, including contrib ones, must pass run_adapter_contract."""

from __future__ import annotations

import json
from pathlib import Path

from clipsieve.adapters.base import Adapter
from clipsieve.models import Post, Query


def run_adapter_contract(adapter: Adapter, query: Query, tmp_path: Path, limit: int = 3) -> list[Post]:
    assert isinstance(adapter.platform, str) and adapter.platform

    posts = list(adapter.search([query], limit))
    assert posts, "search must yield at least one post for the fixture query"
    assert len(posts) <= limit

    for post in posts:
        # valid model round trip
        Post.model_validate(post.model_dump(mode="json"))
        assert post.platform == adapter.platform
        assert post.id.startswith(f"{adapter.platform}:")

        raw = Path(post.raw_ref)
        assert raw.is_file(), f"raw_ref must resolve to a file: {post.raw_ref}"
        json.loads(raw.read_text(encoding="utf-8"))

        assert len(post.creator_hash) == 64
        assert post.creator_hash not in post.raw_ref
        assert post.creator_hash != (post.creator_display or "")

        assert len(post.comments) <= 50
        for m in post.media:
            assert m.local_path is None, "search must not download media"

    first = posts[0]
    dest = tmp_path / "media"
    dest.mkdir()
    once = adapter.fetch_media(first, dest)
    twice = adapter.fetch_media(once, dest)
    paths_once = [m.local_path for m in once.media]
    paths_twice = [m.local_path for m in twice.media]
    assert paths_once == paths_twice, "fetch_media must be idempotent"
    for p in paths_once:
        assert p is not None
        assert (dest / p).is_file(), f"local_path must be relative to dest: {p}"
    return posts
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/adapters/test_base.py -v`
Expected: 4 passed

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/adapters/__init__.py backend/clipsieve/adapters/base.py backend/tests/adapters/__init__.py backend/tests/adapters/contract.py backend/tests/adapters/test_base.py
git commit -m "feat(adapters): add Adapter protocol, salted creator hashing, and contract test helper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Adapter registry with entry-point discovery

**Files:**
- Create: `backend/clipsieve/adapters/registry.py`
- Modify: `backend/pyproject.toml` (add `[project.entry-points."clipsieve.adapters"]`)
- Test: `backend/tests/adapters/test_registry.py`

**Interfaces:**
- Consumes: `clipsieve.config.Settings` (plan 01), `Adapter`.
- Produces: `ENTRY_POINT_GROUP = "clipsieve.adapters"`, `load_adapters(settings: Settings) -> dict[str, Adapter]`, `BUILTIN_ADAPTERS: dict[str, str]`.

- [x] **Step 1: Write the failing test**

`backend/tests/adapters/test_registry.py`:

```python
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Iterator

import pytest

from clipsieve.adapters import registry
from clipsieve.adapters.base import AdapterHealth
from clipsieve.config import Settings
from clipsieve.models import Post, Query


class DummyAdapter:
    platform = "dummy"

    @classmethod
    def from_settings(cls, settings: Settings) -> "DummyAdapter":
        return cls()

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        return iter(())

    def fetch_media(self, post: Post, dest: Path) -> Post:
        return post

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(ok=True, message="ok")


class BrokenAdapter:
    platform = "broken"

    @classmethod
    def from_settings(cls, settings: Settings):
        raise RuntimeError("cannot construct")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path, clipsieve_creator_salt="s")


def test_builtins_are_loaded_without_entry_points(monkeypatch, settings):
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [])
    adapters = registry.load_adapters(settings)
    assert set(adapters) >= {"local", "youtube"}
    assert adapters["local"].platform == "local"


def test_entry_point_adapter_is_discovered(monkeypatch, settings):
    ep = EntryPoint(name="dummy", value=f"{__name__}:DummyAdapter", group=registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [ep])
    adapters = registry.load_adapters(settings)
    assert "dummy" in adapters
    assert adapters["dummy"].healthcheck().ok


def test_broken_entry_point_is_skipped_not_fatal(monkeypatch, settings):
    ep = EntryPoint(name="broken", value=f"{__name__}:BrokenAdapter", group=registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(registry, "_iter_entry_points", lambda: [ep])
    adapters = registry.load_adapters(settings)
    assert "broken" not in adapters
    assert "local" in adapters
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.adapters.registry'`

- [x] **Step 3: Write the registry**

`backend/clipsieve/adapters/registry.py`:

```python
from __future__ import annotations

from importlib import import_module
from importlib.metadata import EntryPoint, entry_points

import structlog

from clipsieve.adapters.base import Adapter
from clipsieve.config import Settings

log = structlog.get_logger(__name__)

ENTRY_POINT_GROUP = "clipsieve.adapters"

BUILTIN_ADAPTERS: dict[str, str] = {
    "local": "clipsieve.adapters.local_import:LocalImportAdapter",
    "youtube": "clipsieve.adapters.youtube:YouTubeAdapter",
}


def _iter_entry_points() -> list[EntryPoint]:
    return list(entry_points(group=ENTRY_POINT_GROUP))


def _load_class(value: str):
    module_name, _, attr = value.partition(":")
    return getattr(import_module(module_name), attr)


def _construct(cls, settings: Settings, source: str) -> Adapter | None:
    try:
        adapter = cls.from_settings(settings)
    except Exception as exc:  # noqa: BLE001 - one bad plugin must not take down the app
        log.warning("adapter_load_failed", source=source, error=str(exc))
        return None
    if not isinstance(adapter, Adapter):
        log.warning("adapter_not_protocol", source=source)
        return None
    return adapter


def load_adapters(settings: Settings) -> dict[str, Adapter]:
    """Built-in adapters plus any registered under the entry point group. Key is platform."""
    adapters: dict[str, Adapter] = {}

    for ep in _iter_entry_points():
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            log.warning("adapter_entry_point_import_failed", name=ep.name, error=str(exc))
            continue
        adapter = _construct(cls, settings, source=f"entry_point:{ep.name}")
        if adapter is not None:
            adapters[adapter.platform] = adapter

    for platform, value in BUILTIN_ADAPTERS.items():
        if platform in adapters:
            continue
        try:
            cls = _load_class(value)
        except Exception as exc:  # noqa: BLE001
            log.warning("adapter_builtin_import_failed", platform=platform, error=str(exc))
            continue
        adapter = _construct(cls, settings, source=f"builtin:{platform}")
        if adapter is not None:
            adapters[adapter.platform] = adapter

    log.info("adapters_loaded", platforms=sorted(adapters))
    return adapters
```

- [x] **Step 4: Register entry points and core dependencies in pyproject**

Modify `backend/pyproject.toml`. Add under `[project]` dependencies (keep plan 01's list, append):

```toml
dependencies = [
    # ... plan 01 entries unchanged ...
    "yt-dlp>=2026.1.1",
    "httpx>=0.28",
    "pillow>=10.4",
]

[project.optional-dependencies]
asr = [
    "mlx-whisper>=0.4; sys_platform == 'darwin' and platform_machine == 'arm64'",
    "faster-whisper>=1.1; sys_platform != 'darwin' or platform_machine != 'arm64'",
]
ocr = [
    "paddleocr>=2.9,<3",
    "paddlepaddle>=3.0",
]

[project.entry-points."clipsieve.adapters"]
local = "clipsieve.adapters.local_import:LocalImportAdapter"
youtube = "clipsieve.adapters.youtube:YouTubeAdapter"
```

Run: `uv sync`
Expected: resolves and installs yt-dlp and httpx; no error.

- [x] **Step 5: Run tests to verify they pass**

The two built-in modules do not exist yet, so `test_builtins_are_loaded_without_entry_points` and `test_broken_entry_point_is_skipped_not_fatal` will still fail on `local`. That is expected until Task 3. Run only the discovery test now:

Run: `uv run pytest tests/adapters/test_registry.py::test_entry_point_adapter_is_discovered -v`
Expected: 1 passed

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/adapters/registry.py backend/pyproject.toml backend/uv.lock backend/tests/adapters/test_registry.py
git commit -m "feat(adapters): add registry with entry-point discovery and built-in fallback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: LocalImportAdapter (folder of media or CSV)

**Files:**
- Create: `backend/clipsieve/adapters/local_import.py`
- Test: `backend/tests/adapters/test_local_import.py`

**Interfaces:**
- Consumes: `Adapter`, `hash_creator`, `incoming_dir`, `clipsieve.store.paths.safe_post_filename`, `Settings`, models `Post, PostText, Media, Metrics, Comment, Query`.
- Produces: `LocalImportAdapter` with `from_settings`, `search`, `fetch_media`, `healthcheck`. Platform `"local"`. Post ids `local:<sha1 of absolute source path>[:12]`.

- [x] **Step 1: Write the failing tests**

`backend/tests/adapters/test_local_import.py`:

```python
import csv
import json
from pathlib import Path

import pytest

from clipsieve.adapters.local_import import LocalImportAdapter
from clipsieve.config import Settings
from clipsieve.models import Query
from tests.adapters.contract import run_adapter_contract

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")


@pytest.fixture
def media_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "clips"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"\x00" * 16)
    (folder / "b.mp4").write_bytes(b"\x00" * 16)
    (folder / "c.jpg").write_bytes(PNG_1X1)
    (folder / "notes.txt").write_text("ignored")
    return folder


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "posts.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "title", "caption", "views", "likes", "comments"])
        w.writerow(["https://example.com/v/1", "First", "plain caption", "100", "10", "3"])
        w.writerow(
            ["https://example.com/v/2", "新加坡人在上海", "第一天到上海，房租好贵 😅, 真的", "2000", "150", "12"]
        )
    return p


def test_folder_import_passes_contract(settings, media_folder, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = run_adapter_contract(adapter, Query(platform="local", query=str(media_folder), lang="en"), tmp_path)
    kinds = sorted(p.kind for p in posts)
    assert kinds == ["image_note", "video", "video"]
    assert all(p.id.startswith("local:") for p in posts)


def test_folder_import_respects_limit(settings, media_folder):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = list(adapter.search([Query(platform="local", query=str(media_folder), lang="en")], limit=1))
    assert len(posts) == 1


def test_csv_chinese_caption_roundtrip(settings, csv_file):
    adapter = LocalImportAdapter.from_settings(settings)
    posts = list(adapter.search([Query(platform="local", query=str(csv_file), lang="zh")], limit=10))
    assert len(posts) == 2
    zh = next(p for p in posts if p.text.title == "新加坡人在上海")
    assert zh.text.caption == "第一天到上海，房租好贵 😅, 真的"
    assert zh.metrics.views == 2000 and zh.metrics.likes == 150 and zh.metrics.comments == 12
    assert zh.lang == "zh"
    raw = json.loads(Path(zh.raw_ref).read_text(encoding="utf-8"))
    assert raw["caption"] == "第一天到上海，房租好贵 😅, 真的"


def test_csv_rows_have_no_media_and_fetch_media_is_noop(settings, csv_file, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(adapter.search([Query(platform="local", query=str(csv_file), lang="en")], limit=1))
    assert post.media == []
    dest = tmp_path / "m"
    dest.mkdir()
    assert adapter.fetch_media(post, dest).media == []


def test_fetch_media_idempotent(settings, media_folder, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    post = next(p for p in adapter.search([Query(platform="local", query=str(media_folder), lang="en")], 10) if p.kind == "video")
    dest = tmp_path / "m"
    dest.mkdir()
    first = adapter.fetch_media(post, dest)
    mtime = (dest / first.media[0].local_path).stat().st_mtime_ns
    second = adapter.fetch_media(first, dest)
    assert second.media[0].local_path == first.media[0].local_path == "video.mp4"
    assert (dest / "video.mp4").stat().st_mtime_ns == mtime


def test_healthcheck_ok(settings):
    assert LocalImportAdapter.from_settings(settings).healthcheck().ok


def test_missing_source_yields_nothing(settings, tmp_path):
    adapter = LocalImportAdapter.from_settings(settings)
    assert list(adapter.search([Query(platform="local", query=str(tmp_path / "nope"), lang="en")], 5)) == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/adapters/test_local_import.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.adapters.local_import'`

- [x] **Step 3: Implement the adapter**

`backend/clipsieve/adapters/local_import.py`:

```python
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import structlog

from clipsieve.adapters.base import AdapterHealth, hash_creator, incoming_dir
from clipsieve.config import Settings
from clipsieve.models import Comment, Media, Metrics, Post, PostText, Query
from clipsieve.store.paths import safe_post_filename

log = structlog.get_logger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
CSV_COLUMNS = ("url", "title", "caption", "views", "likes", "comments")


def _int_or_none(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


class LocalImportAdapter:
    platform = "local"

    def __init__(self, data_dir: Path, salt: str) -> None:
        self._raw_dir = incoming_dir(data_dir, self.platform)
        self._salt = salt

    @classmethod
    def from_settings(cls, settings: Settings) -> "LocalImportAdapter":
        return cls(data_dir=settings.clipsieve_data_dir, salt=settings.clipsieve_creator_salt)

    # -- search -------------------------------------------------------------

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        yielded = 0
        for q in queries:
            source = Path(q.query).expanduser()
            if not source.exists():
                log.warning("local_source_missing", source=str(source))
                continue
            producer = self._from_csv(source, q.lang) if source.suffix.lower() == ".csv" else self._from_folder(source, q.lang)
            for post in producer:
                if yielded >= limit:
                    return
                yield post
                yielded += 1

    def _post_id(self, source: Path) -> str:
        digest = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
        return f"local:{digest}"

    def _write_raw(self, post_id: str, payload: dict) -> str:
        path = self._raw_dir / f"{safe_post_filename(post_id)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _from_folder(self, folder: Path, lang: str) -> Iterator[Post]:
        creator = hash_creator(str(folder.resolve()), self._salt)
        for file in sorted(folder.iterdir()):
            ext = file.suffix.lower()
            if ext in VIDEO_EXT:
                kind, media_type = "video", "video"
            elif ext in IMAGE_EXT:
                kind, media_type = "image_note", "image"
            else:
                continue
            post_id = self._post_id(file)
            payload = {"source": str(file.resolve()), "size": file.stat().st_size, "kind": kind}
            raw_ref = self._write_raw(post_id, payload)
            yield Post(
                id=post_id,
                platform="local",
                url=file.resolve().as_uri(),
                creator_hash=creator,
                creator_display=folder.name,
                kind=kind,
                text=PostText(title=file.stem, caption=None, hashtags=[]),
                media=[Media(type=media_type, index=0)],
                metrics=Metrics(),
                comments=[],
                lang=lang or None,
                raw_ref=raw_ref,
                collected_at=datetime.now(timezone.utc),
            )

    def _from_csv(self, csv_path: Path, lang: str) -> Iterator[Post]:
        creator = hash_creator(str(csv_path.resolve()), self._salt)
        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in ("url",) if c not in (reader.fieldnames or [])]
            if missing:
                log.warning("local_csv_missing_columns", csv=str(csv_path), missing=missing)
                return
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                post_id = f"local:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"
                payload = {k: row.get(k) for k in row}
                raw_ref = self._write_raw(post_id, payload)
                caption = row.get("caption") or None
                hashtags = [w.lstrip("#") for w in (caption or "").split() if w.startswith("#")]
                yield Post(
                    id=post_id,
                    platform="local",
                    url=url,
                    creator_hash=creator,
                    creator_display=csv_path.stem,
                    kind="video",
                    text=PostText(title=row.get("title") or None, caption=caption, hashtags=hashtags),
                    media=[],
                    metrics=Metrics(
                        views=_int_or_none(row.get("views")),
                        likes=_int_or_none(row.get("likes")),
                        comments=_int_or_none(row.get("comments")),
                    ),
                    comments=[],
                    lang=(row.get("lang") or lang or None),
                    raw_ref=raw_ref,
                    collected_at=datetime.now(timezone.utc),
                )

    # -- media ----------------------------------------------------------------

    def fetch_media(self, post: Post, dest: Path) -> Post:
        if not post.media:
            return post
        raw = json.loads(Path(post.raw_ref).read_text(encoding="utf-8"))
        source = Path(raw["source"])
        dest.mkdir(parents=True, exist_ok=True)
        media = []
        for m in post.media:
            name = "video.mp4" if m.type == "video" else f"img_{(m.index or 0):02d}{source.suffix.lower()}"
            target = dest / name
            if not target.exists():
                shutil.copy2(source, target)
            media.append(m.model_copy(update={"local_path": name}))
        return post.model_copy(update={"media": media})

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(ok=True, message="local import ready")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/adapters/test_local_import.py tests/adapters/test_registry.py -v`
Expected: 7 passed in `test_local_import.py`; in `test_registry.py` the builtin test still fails only on `youtube` (next task). Confirm the failure message names `youtube`, not `local`.

- [x] **Step 5: Commit**

```bash
git add backend/clipsieve/adapters/local_import.py backend/tests/adapters/test_local_import.py
git commit -m "feat(adapters): add LocalImportAdapter for media folders and CSV exports

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: yt-dlp client interface, fake client, VTT parser, and YouTube fixtures

**Files:**
- Create: `backend/clipsieve/adapters/ytdlp_client.py`
- Create: `backend/clipsieve/adapters/vtt.py`
- Create: `backend/tests/fixtures/youtube/search.json`
- Create: `backend/tests/fixtures/youtube/aB3dEfGhIjK.json`
- Create: `backend/tests/fixtures/youtube/zH1sH4nGh41.json`
- Create: `backend/tests/fixtures/youtube/aB3dEfGhIjK.en.vtt`
- Create: `backend/tests/fixtures/youtube/zH1sH4nGh41.zh-Hans.vtt`
- Test: `backend/tests/adapters/test_vtt.py`

**Interfaces:**
- Consumes: `clipsieve.models.TranscriptSegment`.
- Produces: `YtDlpClient` Protocol with `search(query: str, n: int) -> list[dict]`, `info(url: str) -> dict`, `download(url: str, dest: Path, subtitle_langs: list[str]) -> dict`; `RealYtDlpClient`; `FakeYtDlpClient(fixture_dir: Path)`; `parse_vtt(text: str) -> list[TranscriptSegment]`; `vtt_lang_from_filename(path: Path) -> str | None`.

- [x] **Step 1: Write the failing VTT tests**

`backend/tests/adapters/test_vtt.py`:

```python
from pathlib import Path

from clipsieve.adapters.vtt import parse_vtt, vtt_lang_from_filename

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"


def test_parse_vtt_rolling_cues():
    segments = parse_vtt((FIXTURES / "aB3dEfGhIjK.en.vtt").read_text(encoding="utf-8"))
    texts = [s.text for s in segments]
    assert texts == [
        "stop scrolling I built a Chrome extension",
        "in 10 minutes with zero code",
        "here's exactly how",
    ]
    starts = [s.start_s for s in segments]
    assert starts == sorted(starts)
    assert all(s.end_s > s.start_s for s in segments)
    assert segments[0].start_s == 0.0 and segments[0].end_s == 2.5


def test_parse_vtt_strips_inline_tags_and_positions():
    raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start position:0%\nhello<00:00:01.500><c> world</c>\n"
    [seg] = parse_vtt(raw)
    assert seg.text == "hello world"


def test_parse_vtt_chinese():
    segments = parse_vtt((FIXTURES / "zH1sH4nGh41.zh-Hans.vtt").read_text(encoding="utf-8"))
    assert segments[0].text == "刚到上海的第一天 房租真的好贵"


def test_vtt_lang_from_filename():
    assert vtt_lang_from_filename(Path("video.en.vtt")) == "en"
    assert vtt_lang_from_filename(Path("video.zh-Hans.vtt")) == "zh-Hans"
    assert vtt_lang_from_filename(Path("video.vtt")) is None
```

- [x] **Step 2: Create the VTT fixtures**

`backend/tests/fixtures/youtube/aB3dEfGhIjK.en.vtt`:

```text
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500 align:start position:0%
 
stop<00:00:00.400><c> scrolling</c><00:00:00.900><c> I</c><00:00:01.100><c> built</c><00:00:01.500><c> a</c><00:00:01.700><c> Chrome</c><00:00:02.100><c> extension</c>

00:00:02.500 --> 00:00:02.510 align:start position:0%
stop scrolling I built a Chrome extension
 

00:00:02.510 --> 00:00:04.800 align:start position:0%
stop scrolling I built a Chrome extension
in<00:00:02.900><c> 10</c><00:00:03.200><c> minutes</c><00:00:03.700><c> with</c><00:00:04.000><c> zero</c><00:00:04.400><c> code</c>

00:00:04.800 --> 00:00:04.810 align:start position:0%
in 10 minutes with zero code
 

00:00:04.810 --> 00:00:06.200 align:start position:0%
in 10 minutes with zero code
here's<00:00:05.200><c> exactly</c><00:00:05.700><c> how</c>

00:00:06.200 --> 00:00:06.210 align:start position:0%
here's exactly how
 
```

`backend/tests/fixtures/youtube/zH1sH4nGh41.zh-Hans.vtt`:

```text
WEBVTT
Kind: captions
Language: zh-Hans

00:00:00.000 --> 00:00:03.000 align:start position:0%
 
刚到上海的第一天<00:00:01.500><c> 房租真的好贵</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
刚到上海的第一天 房租真的好贵
 

00:00:03.010 --> 00:00:05.500 align:start position:0%
刚到上海的第一天 房租真的好贵
新加坡人的真实体验
```

- [x] **Step 3: Create the recorded yt-dlp info fixtures**

`backend/tests/fixtures/youtube/search.json` (shape of `extract_info("ytsearch2:...", download=False)["entries"]` with `extract_flat`):

```json
[
  {"_type": "url", "ie_key": "Youtube", "id": "aB3dEfGhIjK", "url": "https://www.youtube.com/watch?v=aB3dEfGhIjK", "title": "I built a Chrome extension in 10 minutes with zero code", "duration": 48, "view_count": 182344, "channel_id": "UC_builder_001", "uploader": "No Code Nat"},
  {"_type": "url", "ie_key": "Youtube", "id": "zH1sH4nGh41", "url": "https://www.youtube.com/watch?v=zH1sH4nGh41", "title": "新加坡人搬到上海的第一天 | 房租篇", "duration": 57, "view_count": 50321, "channel_id": "UC_sg_shanghai_77", "uploader": "阿明在上海"},
  {"_type": "url", "ie_key": "Youtube", "id": "LoNgV1dEo00", "url": "https://www.youtube.com/watch?v=LoNgV1dEo00", "title": "Full 40 minute tutorial", "duration": 2400, "view_count": 9000, "channel_id": "UC_long", "uploader": "Long Form"}
]
```

`backend/tests/fixtures/youtube/aB3dEfGhIjK.json`:

```json
{
  "id": "aB3dEfGhIjK",
  "title": "I built a Chrome extension in 10 minutes with zero code",
  "description": "Stop scrolling. Zero code, ten minutes. #nocode #chromeextension #buildinpublic",
  "tags": ["no code", "chrome extension"],
  "duration": 48,
  "width": 1080,
  "height": 1920,
  "upload_date": "20260912",
  "timestamp": 1789171200,
  "channel_id": "UC_builder_001",
  "uploader": "No Code Nat",
  "uploader_id": "@nocodenat",
  "view_count": 182344,
  "like_count": 15321,
  "comment_count": 412,
  "language": "en",
  "webpage_url": "https://www.youtube.com/watch?v=aB3dEfGhIjK",
  "automatic_captions": {"en": [{"ext": "vtt", "url": "https://example.invalid/captions/en.vtt"}]},
  "comments": [
    {"id": "c1", "text": "this is the hook I needed", "like_count": 240},
    {"id": "c2", "text": "ok but which tool", "like_count": 88},
    {"id": "c3", "text": "saved", "like_count": 3}
  ]
}
```

`backend/tests/fixtures/youtube/zH1sH4nGh41.json`:

```json
{
  "id": "zH1sH4nGh41",
  "title": "新加坡人搬到上海的第一天 | 房租篇",
  "description": "刚到上海的第一天，房租真的好贵 😅 #上海生活 #新加坡人 #vlog",
  "tags": ["上海", "vlog"],
  "duration": 57,
  "width": 1080,
  "height": 1920,
  "upload_date": "20260901",
  "timestamp": 1788220800,
  "channel_id": "UC_sg_shanghai_77",
  "uploader": "阿明在上海",
  "uploader_id": "@amingshanghai",
  "view_count": 50321,
  "like_count": 4210,
  "comment_count": 97,
  "language": "zh-Hans",
  "webpage_url": "https://www.youtube.com/watch?v=zH1sH4nGh41",
  "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "https://example.invalid/captions/zh.vtt"}]},
  "comments": [
    {"id": "k1", "text": "同是新加坡人，太真实了", "like_count": 310},
    {"id": "k2", "text": "浦东还是浦西？", "like_count": 45}
  ]
}
```

- [x] **Step 4: Run VTT tests to verify they fail**

Run: `uv run pytest tests/adapters/test_vtt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.adapters.vtt'`

- [x] **Step 5: Implement the VTT parser**

`backend/clipsieve/adapters/vtt.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from clipsieve.models import TranscriptSegment

_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})\.(\d{3})")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _to_seconds(stamp: str) -> float:
    m = _TIME.search(stamp)
    if not m:
        raise ValueError(f"bad timestamp: {stamp}")
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000


def _clean(line: str) -> str:
    return _WS.sub(" ", _TAG.sub("", line)).strip()


def parse_vtt(text: str) -> list[TranscriptSegment]:
    """Parse WebVTT, including YouTube's rolling auto-caption cues.

    YouTube repeats the previous line at the top of each cue and emits 10 ms cues
    holding only the completed line. We keep, per cue, only lines not already
    emitted, and drop cues that add nothing.
    """
    segments: list[TranscriptSegment] = []
    seen_lines: list[str] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        start_raw, _, rest = lines[timing_idx].partition("-->")
        end_raw = rest.strip().split(" ")[0]
        start_s, end_s = _to_seconds(start_raw), _to_seconds(end_raw)
        fresh: list[str] = []
        for ln in lines[timing_idx + 1 :]:
            cleaned = _clean(ln)
            if not cleaned or cleaned in seen_lines[-2:]:
                continue
            fresh.append(cleaned)
            seen_lines.append(cleaned)
        if not fresh:
            continue
        if end_s <= start_s:
            end_s = start_s + 0.01
        segments.append(TranscriptSegment(start_s=start_s, end_s=end_s, text=" ".join(fresh)))
    return segments


def vtt_lang_from_filename(path: Path) -> str | None:
    parts = path.name.split(".")
    if len(parts) >= 3 and parts[-1] == "vtt":
        return parts[-2]
    return None
```

- [x] **Step 6: Run VTT tests to verify they pass**

Run: `uv run pytest tests/adapters/test_vtt.py -v`
Expected: 4 passed

- [x] **Step 7: Implement the yt-dlp client interface, real client, and fake**

`backend/clipsieve/adapters/ytdlp_client.py`:

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)

MAX_FILESIZE_BYTES = 200 * 1024 * 1024


class YtDlpClient(Protocol):
    def search(self, query: str, n: int) -> list[dict[str, Any]]: ...

    def info(self, url: str) -> dict[str, Any]: ...

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]: ...


class RealYtDlpClient:
    """Thin wrapper over yt_dlp.YoutubeDL. Only this class imports yt_dlp."""

    def _ydl(self, **opts: Any):
        import yt_dlp  # lazy: keep adapters importable without yt_dlp for tooling

        base = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _YtLogger()}
        base.update(opts)
        return yt_dlp.YoutubeDL(base)

    def search(self, query: str, n: int) -> list[dict[str, Any]]:
        with self._ydl(extract_flat="in_playlist", skip_download=True) as ydl:
            result = ydl.extract_info(f"ytsearch{n}:{query}", download=False) or {}
        return list(result.get("entries") or [])

    def info(self, url: str) -> dict[str, Any]:
        with self._ydl(skip_download=True, getcomments=True, extractor_args={"youtube": {"max_comments": ["50", "all", "0", "0"]}}) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]:
        dest.mkdir(parents=True, exist_ok=True)
        opts = {
            "outtmpl": str(dest / "video.%(ext)s"),
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "merge_output_format": "mp4",
            "max_filesize": MAX_FILESIZE_BYTES,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": subtitle_langs,
            "subtitlesformat": "vtt",
        }
        with self._ydl(**opts) as ydl:
            return ydl.extract_info(url, download=True) or {}


class _YtLogger:
    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        log.debug("ytdlp", msg=msg)

    def info(self, msg: str) -> None:
        log.debug("ytdlp", msg=msg)

    def warning(self, msg: str) -> None:
        log.warning("ytdlp", msg=msg)

    def error(self, msg: str) -> None:
        log.error("ytdlp", msg=msg)


class FakeYtDlpClient:
    """Replays recorded info dicts from tests/fixtures/youtube. No network."""

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = fixture_dir
        self.download_calls = 0

    def search(self, query: str, n: int) -> list[dict[str, Any]]:
        entries = json.loads((self._dir / "search.json").read_text(encoding="utf-8"))
        return entries[:n]

    def info(self, url: str) -> dict[str, Any]:
        video_id = url.rsplit("v=", 1)[-1].split("&")[0]
        path = self._dir / f"{video_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"no recorded info for {video_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def download(self, url: str, dest: Path, subtitle_langs: list[str]) -> dict[str, Any]:
        self.download_calls += 1
        meta = self.info(url)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "video.mp4").write_bytes(b"\x00" * 1024)
        for vtt in self._dir.glob(f"{meta['id']}.*.vtt"):
            shutil.copy(vtt, dest / vtt.name.replace(meta["id"], "video"))
        meta = dict(meta)
        meta["requested_downloads"] = [{"filepath": str(dest / "video.mp4")}]
        return meta
```

- [x] **Step 8: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` and no files would be reformatted.

```bash
git add backend/clipsieve/adapters/ytdlp_client.py backend/clipsieve/adapters/vtt.py backend/tests/fixtures/youtube backend/tests/adapters/test_vtt.py
git commit -m "feat(adapters): add yt-dlp client interface with fake, VTT parser, and YouTube fixtures

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: YouTubeAdapter

**Files:**
- Create: `backend/clipsieve/adapters/youtube.py`
- Test: `backend/tests/adapters/test_youtube.py`

**Interfaces:**
- Consumes: `YtDlpClient`, `FakeYtDlpClient`, `parse_vtt`, `vtt_lang_from_filename`, `hash_creator`, `incoming_dir`, `safe_post_filename`, `Settings`, models.
- Produces: `YouTubeAdapter(client: YtDlpClient, data_dir: Path, salt: str, api_key: str = "", http: httpx.Client | None = None, max_duration_s: int = 180)` with `from_settings`, `search`, `fetch_media`, `healthcheck`; `map_info_to_post(info: dict, salt: str, raw_ref: str) -> Post`; `write_transcript_sidecar(media_path: Path, lang: str | None, segments) -> Path`.

- [x] **Step 1: Write the failing tests**

`backend/tests/adapters/test_youtube.py`:

```python
import json
from pathlib import Path

import httpx
import pytest

from clipsieve.adapters.youtube import YouTubeAdapter, map_info_to_post
from clipsieve.adapters.ytdlp_client import FakeYtDlpClient
from clipsieve.config import Settings
from clipsieve.models import Query
from tests.adapters.contract import run_adapter_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(clipsieve_data_dir=tmp_path / "data", clipsieve_creator_salt="salt")


@pytest.fixture
def adapter(settings) -> YouTubeAdapter:
    return YouTubeAdapter(client=FakeYtDlpClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="salt")


def test_passes_contract(adapter, tmp_path):
    posts = run_adapter_contract(adapter, Query(platform="youtube", query="chrome extension no code", lang="en"), tmp_path, limit=5)
    assert {p.id for p in posts} == {"youtube:aB3dEfGhIjK", "youtube:zH1sH4nGh41"}


def test_shorts_filter_drops_long_videos(adapter):
    posts = list(adapter.search([Query(platform="youtube", query="x", lang="en")], limit=10))
    assert "youtube:LoNgV1dEo00" not in {p.id for p in posts}


def test_mapping_fields():
    info = json.loads((FIXTURES / "aB3dEfGhIjK.json").read_text(encoding="utf-8"))
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert post.url == "https://www.youtube.com/shorts/aB3dEfGhIjK"
    assert post.kind == "video"
    assert post.text.title.startswith("I built")
    assert sorted(post.text.hashtags) == ["buildinpublic", "chromeextension", "nocode"]
    assert post.metrics.views == 182344 and post.metrics.likes == 15321 and post.metrics.comments == 412
    assert post.media[0].duration_s == 48 and post.media[0].width == 1080
    assert post.posted_at is not None and post.posted_at.year == 2026 and post.posted_at.month == 9
    assert post.lang == "en"
    assert post.creator_display == "No Code Nat"
    assert "UC_builder_001" not in post.creator_hash


def test_chinese_mapping_preserves_text():
    info = json.loads((FIXTURES / "zH1sH4nGh41.json").read_text(encoding="utf-8"))
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert post.text.title == "新加坡人搬到上海的第一天 | 房租篇"
    assert post.comments[0].text == "同是新加坡人，太真实了"
    assert post.lang == "zh-Hans"


def test_comments_capped_most_liked():
    info = json.loads((FIXTURES / "aB3dEfGhIjK.json").read_text(encoding="utf-8"))
    info["comments"] = [{"id": str(i), "text": f"c{i}", "like_count": i} for i in range(120)]
    post = map_info_to_post(info, salt="salt", raw_ref="/tmp/raw.json")
    assert len(post.comments) == 50
    assert post.comments[0].likes == 119 and post.comments[-1].likes == 70


def test_fetch_media_writes_video_and_transcript_sidecar(adapter, tmp_path):
    post = next(p for p in adapter.search([Query(platform="youtube", query="x", lang="en")], 10) if p.id.endswith("aB3dEfGhIjK"))
    dest = tmp_path / "m"
    got = adapter.fetch_media(post, dest)
    assert got.media[0].local_path == "video.mp4"
    sidecar = json.loads((dest / "video.mp4.transcript.json").read_text(encoding="utf-8"))
    assert sidecar["lang"] == "en"
    assert sidecar["segments"][0]["text"].startswith("stop scrolling")


def test_fetch_media_is_idempotent_and_does_not_redownload(adapter, tmp_path):
    post = next(adapter.search([Query(platform="youtube", query="x", lang="en")], 1))
    dest = tmp_path / "m"
    adapter.fetch_media(post, dest)
    calls = adapter._client.download_calls
    adapter.fetch_media(post, dest)
    assert adapter._client.download_calls == calls


def test_data_api_search_is_used_when_key_present(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        assert request.url.params["q"] == "shanghai vlog"
        assert request.url.params["videoDuration"] == "short"
        return httpx.Response(200, json={"items": [{"id": {"videoId": "zH1sH4nGh41"}}, {"id": {"videoId": "aB3dEfGhIjK"}}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = YouTubeAdapter(client=FakeYtDlpClient(FIXTURES), data_dir=settings.clipsieve_data_dir, salt="s", api_key="k", http=http)
    posts = list(adapter.search([Query(platform="youtube", query="shanghai vlog", lang="en")], 5))
    assert [p.id for p in posts] == ["youtube:zH1sH4nGh41", "youtube:aB3dEfGhIjK"]


def test_healthcheck_reports_ytdlp_import(adapter):
    health = adapter.healthcheck()
    assert isinstance(health.ok, bool) and "yt-dlp" in health.message


def test_from_settings_builds_real_client(settings):
    adapter = YouTubeAdapter.from_settings(settings)
    assert adapter.platform == "youtube"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/adapters/test_youtube.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.adapters.youtube'`

- [x] **Step 3: Implement the adapter**

`backend/clipsieve/adapters/youtube.py`:

```python
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import structlog

from clipsieve.adapters.base import AdapterHealth, hash_creator, incoming_dir
from clipsieve.adapters.vtt import parse_vtt, vtt_lang_from_filename
from clipsieve.adapters.ytdlp_client import FakeYtDlpClient, RealYtDlpClient, YtDlpClient
from clipsieve.config import Settings
from clipsieve.models import Comment, Media, Metrics, Post, PostText, Query, TranscriptSegment
from clipsieve.store.paths import safe_post_filename

log = structlog.get_logger(__name__)

HASHTAG = re.compile(r"#([\w一-鿿]+)")
DATA_API_SEARCH = "https://www.googleapis.com/youtube/v3/search"
MAX_COMMENTS = 50
DEFAULT_MAX_DURATION_S = 180


def _posted_at(info: dict[str, Any]) -> datetime | None:
    if info.get("timestamp"):
        return datetime.fromtimestamp(int(info["timestamp"]), tz=timezone.utc)
    if info.get("upload_date"):
        return datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def map_info_to_post(info: dict[str, Any], salt: str, raw_ref: str) -> Post:
    video_id = info["id"]
    description = info.get("description") or ""
    tags = {t.strip().replace(" ", "") for t in (info.get("tags") or []) if t.strip()}
    hashtags = sorted(tags | set(HASHTAG.findall(description)))
    comments = sorted(
        (c for c in (info.get("comments") or []) if (c.get("text") or "").strip()),
        key=lambda c: int(c.get("like_count") or 0),
        reverse=True,
    )[:MAX_COMMENTS]
    return Post(
        id=f"youtube:{video_id}",
        platform="youtube",
        url=f"https://www.youtube.com/shorts/{video_id}",
        creator_hash=hash_creator(info.get("channel_id") or info.get("uploader_id") or video_id, salt),
        creator_display=info.get("uploader") or info.get("channel"),
        posted_at=_posted_at(info),
        kind="video",
        text=PostText(title=info.get("title"), caption=description or None, hashtags=hashtags),
        media=[Media(type="video", duration_s=info.get("duration"), width=info.get("width"), height=info.get("height"))],
        metrics=Metrics(views=info.get("view_count"), likes=info.get("like_count"), comments=info.get("comment_count")),
        comments=[Comment(text=c["text"], likes=c.get("like_count")) for c in comments],
        lang=info.get("language"),
        raw_ref=raw_ref,
        collected_at=datetime.now(timezone.utc),
    )


def write_transcript_sidecar(media_path: Path, lang: str | None, segments: list[TranscriptSegment]) -> Path:
    sidecar = media_path.with_name(media_path.name + ".transcript.json")
    sidecar.write_text(
        json.dumps({"lang": lang, "segments": [s.model_dump(mode="json") for s in segments]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return sidecar


class YouTubeAdapter:
    platform = "youtube"

    def __init__(
        self,
        client: YtDlpClient,
        data_dir: Path,
        salt: str,
        api_key: str = "",
        http: httpx.Client | None = None,
        max_duration_s: int = DEFAULT_MAX_DURATION_S,
    ) -> None:
        self._client = client
        self._raw_dir = incoming_dir(data_dir, self.platform)
        self._salt = salt
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=20.0)
        self._max_duration_s = max_duration_s

    @classmethod
    def from_settings(cls, settings: Settings) -> "YouTubeAdapter":
        return cls(
            client=RealYtDlpClient(),
            data_dir=settings.clipsieve_data_dir,
            salt=settings.clipsieve_creator_salt,
            api_key=settings.youtube_api_key,
        )

    # -- search ---------------------------------------------------------------

    def _candidate_ids(self, query: Query, n: int) -> list[str]:
        if self._api_key:
            try:
                return self._data_api_ids(query, n)
            except httpx.HTTPError as exc:
                log.warning("youtube_data_api_failed", error=str(exc))
        entries = self._client.search(query.query, n)
        ids: list[str] = []
        for e in entries:
            duration = e.get("duration")
            if duration is not None and duration >= self._max_duration_s:
                continue
            if e.get("id"):
                ids.append(e["id"])
        return ids

    def _data_api_ids(self, query: Query, n: int) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < n:
            params = {
                "part": "id",
                "type": "video",
                "videoDuration": "short",
                "q": query.query,
                "maxResults": min(50, n - len(ids)),
                "key": self._api_key,
            }
            if query.lang:
                params["relevanceLanguage"] = query.lang.split("-")[0]
            if page_token:
                params["pageToken"] = page_token
            resp = self._http.get(DATA_API_SEARCH, params=params)
            resp.raise_for_status()
            body = resp.json()
            ids.extend(item["id"]["videoId"] for item in body.get("items", []) if item.get("id", {}).get("videoId"))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return ids[:n]

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        seen: set[str] = set()
        yielded = 0
        for q in queries:
            if yielded >= limit:
                return
            for video_id in self._candidate_ids(q, limit - yielded):
                if video_id in seen or yielded >= limit:
                    continue
                seen.add(video_id)
                try:
                    info = self._client.info(f"https://www.youtube.com/watch?v={video_id}")
                except Exception as exc:  # noqa: BLE001 - one bad video must not stop the search
                    log.warning("youtube_info_failed", video_id=video_id, error=str(exc))
                    continue
                duration = info.get("duration")
                if duration is not None and duration >= self._max_duration_s:
                    continue
                post_id = f"youtube:{video_id}"
                raw_path = self._raw_dir / f"{safe_post_filename(post_id)}.json"
                raw_path.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
                yield map_info_to_post(info, self._salt, str(raw_path))
                yielded += 1

    # -- media ----------------------------------------------------------------

    def fetch_media(self, post: Post, dest: Path) -> Post:
        dest.mkdir(parents=True, exist_ok=True)
        video = dest / "video.mp4"
        if not video.exists():
            langs = ["en", "zh-Hans", "zh-Hant", "zh"]
            if post.lang and post.lang not in langs:
                langs.insert(0, post.lang)
            self._client.download(post.url, dest, subtitle_langs=langs)
            self._write_sidecar_from_vtt(dest, video)
        media = [m.model_copy(update={"local_path": "video.mp4"}) for m in post.media]
        return post.model_copy(update={"media": media})

    def _write_sidecar_from_vtt(self, dest: Path, video: Path) -> None:
        vtts = sorted(dest.glob("video.*.vtt"))
        if not vtts:
            return
        chosen = vtts[0]
        segments = parse_vtt(chosen.read_text(encoding="utf-8"))
        if segments:
            write_transcript_sidecar(video, vtt_lang_from_filename(chosen), segments)

    def healthcheck(self) -> AdapterHealth:
        try:
            import yt_dlp  # noqa: F401

            return AdapterHealth(ok=True, message="yt-dlp importable")
        except ImportError:
            return AdapterHealth(ok=False, message="yt-dlp not installed; run uv sync")


__all__ = ["YouTubeAdapter", "map_info_to_post", "write_transcript_sidecar", "FakeYtDlpClient"]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/adapters -v`
Expected: all tests in `test_base.py`, `test_registry.py` (now including the builtin test), `test_local_import.py`, `test_vtt.py`, `test_youtube.py` pass.

- [x] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

```bash
git add backend/clipsieve/adapters/youtube.py backend/tests/adapters/test_youtube.py
git commit -m "feat(adapters): add YouTubeAdapter with Shorts filter, caption sidecar, and optional Data API search

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: ASR interface, Whisper backend, fake, and the sidecar rule

**Files:**
- Create: `backend/clipsieve/evidence/__init__.py`
- Create: `backend/clipsieve/evidence/asr.py`
- Create: `backend/tests/evidence/__init__.py`
- Test: `backend/tests/evidence/test_asr.py`

**Interfaces:**
- Consumes: `clipsieve.models.TranscriptSegment`.
- Produces: `ASR` Protocol, `WhisperASR(model_name: str = "large-v3")`, `FakeASR()`, `read_sidecar_transcript(media: Path) -> tuple[list[TranscriptSegment], str | None] | None`.

- [x] **Step 1: Write the failing tests**

`backend/tests/evidence/test_asr.py`:

```python
import json
import sys
import types
from pathlib import Path

from clipsieve.evidence.asr import ASR, FakeASR, WhisperASR, read_sidecar_transcript


def _write_sidecar(media: Path) -> None:
    media.with_name(media.name + ".transcript.json").write_text(
        json.dumps({"lang": "zh-Hans", "segments": [{"start_s": 0.0, "end_s": 2.0, "text": "刚到上海"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_fake_asr_returns_sidecar(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    _write_sidecar(media)
    segments, lang = FakeASR().transcribe(media, None)
    assert lang == "zh-Hans" and segments[0].text == "刚到上海"


def test_fake_asr_without_sidecar_is_empty(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    assert FakeASR().transcribe(media, "en") == ([], None)


def test_read_sidecar_none_when_missing(tmp_path):
    assert read_sidecar_transcript(tmp_path / "x.mp4") is None


def test_whisper_asr_prefers_sidecar_and_never_loads_model(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    _write_sidecar(media)
    asr = WhisperASR()
    monkeypatch.setattr(asr, "_transcribe_mlx", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model loaded")))
    monkeypatch.setattr(asr, "_transcribe_faster", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model loaded")))
    segments, lang = asr.transcribe(media, None)
    assert lang == "zh-Hans" and len(segments) == 1


def test_whisper_asr_uses_mlx_when_importable(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    fake_mlx = types.ModuleType("mlx_whisper")

    def transcribe(path, path_or_hf_repo, word_timestamps, language):
        assert word_timestamps is True
        return {"language": "en", "segments": [{"start": 0.0, "end": 1.5, "text": " hello there "}]}

    fake_mlx.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)
    segments, lang = WhisperASR().transcribe(media, None)
    assert lang == "en" and segments[0].text == "hello there" and segments[0].end_s == 1.5


def test_whisper_asr_falls_back_to_faster_whisper(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # import raises ImportError
    fake_fw = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="auto"):
            assert name == "large-v3"

        def transcribe(self, path, word_timestamps, language):
            Seg = types.SimpleNamespace
            return iter([Seg(start=0.0, end=2.0, text=" 你好 ")]), types.SimpleNamespace(language="zh")

    fake_fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    segments, lang = WhisperASR().transcribe(media, "zh")
    assert lang == "zh" and segments[0].text == "你好"


def test_protocol_conformance():
    assert isinstance(FakeASR(), ASR)
    assert isinstance(WhisperASR(), ASR)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_asr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence'`

- [x] **Step 3: Implement ASR**

`backend/clipsieve/evidence/__init__.py`:

```python
"""Evidence extraction: media -> text. Never touches the network."""
```

`backend/tests/evidence/__init__.py` is empty.

`backend/clipsieve/evidence/asr.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

from clipsieve.models import TranscriptSegment

log = structlog.get_logger(__name__)

MLX_REPO = "mlx-community/whisper-large-v3-mlx"


def read_sidecar_transcript(media: Path) -> tuple[list[TranscriptSegment], str | None] | None:
    sidecar = media.with_name(media.name + ".transcript.json")
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    segments = [TranscriptSegment.model_validate(s) for s in data.get("segments", [])]
    return segments, data.get("lang")


@runtime_checkable
class ASR(Protocol):
    def transcribe(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]: ...


class FakeASR:
    def transcribe(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]:
        return read_sidecar_transcript(media) or ([], None)


class WhisperASR:
    """mlx-whisper on Apple Silicon when importable, faster-whisper otherwise."""

    def __init__(self, model_name: str = "large-v3") -> None:
        self._model_name = model_name
        self._faster_model = None

    def transcribe(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]:
        sidecar = read_sidecar_transcript(media)
        if sidecar is not None:
            log.info("asr_sidecar_used", media=str(media))
            return sidecar
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            return self._transcribe_faster(media, lang_hint)
        return self._transcribe_mlx(media, lang_hint)

    def _transcribe_mlx(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(media), path_or_hf_repo=MLX_REPO, word_timestamps=True, language=lang_hint
        )
        segments = [
            TranscriptSegment(start_s=float(s["start"]), end_s=float(s["end"]), text=str(s["text"]).strip())
            for s in result.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
        return segments, result.get("language")

    def _transcribe_faster(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]:
        from faster_whisper import WhisperModel

        if self._faster_model is None:
            self._faster_model = WhisperModel(self._model_name, device="auto", compute_type="auto")
        raw_segments, info = self._faster_model.transcribe(str(media), word_timestamps=True, language=lang_hint)
        segments = [
            TranscriptSegment(start_s=float(s.start), end_s=float(s.end), text=s.text.strip())
            for s in raw_segments
            if s.text.strip()
        ]
        return segments, getattr(info, "language", None)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/evidence/test_asr.py -v`
Expected: 7 passed

- [x] **Step 5: Commit**

```bash
git add backend/clipsieve/evidence/__init__.py backend/clipsieve/evidence/asr.py backend/tests/evidence/__init__.py backend/tests/evidence/test_asr.py
git commit -m "feat(evidence): add ASR protocol with Whisper backend, fake, and caption sidecar rule

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: OCR interface, PaddleOCR backend, and fake

**Files:**
- Create: `backend/clipsieve/evidence/ocr.py`
- Test: `backend/tests/evidence/test_ocr.py`

**Interfaces:**
- Produces: `OCR` Protocol, `PaddleOCRBackend(min_confidence: float = 0.6)`, `FakeOCR()`, `ocr_lang_for_post(lang: str | None) -> str` returning `"ch"` for any `zh*` language else `"en"`.

- [x] **Step 1: Write the failing tests**

`backend/tests/evidence/test_ocr.py`:

```python
import json
import sys
import types
from pathlib import Path

from clipsieve.evidence.ocr import OCR, FakeOCR, PaddleOCRBackend, ocr_lang_for_post


def test_lang_mapping():
    assert ocr_lang_for_post("zh") == "ch"
    assert ocr_lang_for_post("zh-Hans") == "ch"
    assert ocr_lang_for_post("en") == "en"
    assert ocr_lang_for_post(None) == "en"


def test_fake_ocr_reads_sidecar(tmp_path):
    img = tmp_path / "hook.jpg"
    img.write_bytes(b"\xff")
    img.with_name("hook.jpg.ocr.json").write_text(json.dumps(["房租 8000", "STOP SCROLLING"], ensure_ascii=False), encoding="utf-8")
    assert FakeOCR().read(img, "ch") == ["房租 8000", "STOP SCROLLING"]


def test_fake_ocr_without_sidecar_is_empty(tmp_path):
    img = tmp_path / "hook.jpg"
    img.write_bytes(b"\xff")
    assert FakeOCR().read(img, "en") == []


def test_paddle_backend_filters_low_confidence_and_caches_per_lang(tmp_path, monkeypatch):
    constructed = []
    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, use_angle_cls, lang, show_log):
            constructed.append(lang)

        def ocr(self, path, cls):
            return [[
                [[[0, 0], [1, 0], [1, 1], [0, 1]], ("STOP SCROLLING", 0.97)],
                [[[0, 0], [1, 0], [1, 1], [0, 1]], ("blurry", 0.41)],
                [[[0, 0], [1, 0], [1, 1], [0, 1]], ("房租好贵", 0.88)],
            ]]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff")
    backend = PaddleOCRBackend()
    assert backend.read(img, "ch") == ["STOP SCROLLING", "房租好贵"]
    backend.read(img, "ch")
    backend.read(img, "en")
    assert constructed == ["ch", "en"]


def test_paddle_backend_handles_empty_result(tmp_path, monkeypatch):
    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, **kw): ...

        def ocr(self, path, cls):
            return [None]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff")
    assert PaddleOCRBackend().read(img, "en") == []


def test_protocol_conformance():
    assert isinstance(FakeOCR(), OCR)
    assert isinstance(PaddleOCRBackend(), OCR)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_ocr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence.ocr'`

- [x] **Step 3: Implement OCR**

`backend/clipsieve/evidence/ocr.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)


def ocr_lang_for_post(lang: str | None) -> str:
    return "ch" if (lang or "").lower().startswith("zh") else "en"


@runtime_checkable
class OCR(Protocol):
    def read(self, image: Path, lang: str) -> list[str]: ...


class FakeOCR:
    def read(self, image: Path, lang: str) -> list[str]:
        sidecar = image.with_name(image.name + ".ocr.json")
        if not sidecar.exists():
            return []
        return [str(t) for t in json.loads(sidecar.read_text(encoding="utf-8"))]


class PaddleOCRBackend:
    def __init__(self, min_confidence: float = 0.6) -> None:
        self._min_confidence = min_confidence
        self._engines: dict[str, Any] = {}

    def _engine(self, lang: str):
        if lang not in self._engines:
            from paddleocr import PaddleOCR

            self._engines[lang] = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        return self._engines[lang]

    def read(self, image: Path, lang: str) -> list[str]:
        result = self._engine(lang).ocr(str(image), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                try:
                    text, conf = item[1]
                except (IndexError, TypeError, ValueError):
                    continue
                if float(conf) >= self._min_confidence and str(text).strip():
                    lines.append(str(text).strip())
        log.debug("ocr_done", image=str(image), lines=len(lines))
        return lines
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/evidence/test_ocr.py -v`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add backend/clipsieve/evidence/ocr.py backend/tests/evidence/test_ocr.py
git commit -m "feat(evidence): add OCR protocol with PaddleOCR backend and sidecar fake

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Keyframe extraction with ffmpeg and a fake

**Files:**
- Create: `backend/clipsieve/evidence/frames.py`
- Test: `backend/tests/evidence/test_frames.py`

**Interfaces:**
- Produces: `FrameExtractor` Protocol, `FfmpegFrames(ffmpeg_bin: str = "ffmpeg", scene_threshold: float = 0.3, width: int = 640)`, `FakeFrames(count: int = 2)`, `build_hook_argv(...)`, `build_scene_argv(...)`, `PNG_1X1: bytes`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/evidence/test_frames.py`:

```python
from pathlib import Path

from clipsieve.evidence.frames import FakeFrames, FfmpegFrames, FrameExtractor


def test_fake_frames_writes_hook_first(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    dest = tmp_path / "frames"
    frames = FakeFrames(count=3).extract(video, dest, max_frames=8)
    assert [p.name for p in frames] == ["hook.jpg", "scene_01.jpg", "scene_02.jpg"]
    assert all(p.is_file() for p in frames)


def test_fake_frames_respects_cap(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    frames = FakeFrames(count=10).extract(video, tmp_path / "f", max_frames=4)
    assert len(frames) == 4


def test_hook_argv():
    argv = FfmpegFrames().build_hook_argv(Path("/v/video.mp4"), Path("/v/frames"))
    assert argv[:3] == ["ffmpeg", "-hide_banner", "-loglevel"]
    assert "-ss" in argv and argv[argv.index("-ss") + 1] == "0.5"
    assert argv[-1] == "/v/frames/hook.jpg"
    assert "-frames:v" in argv and argv[argv.index("-frames:v") + 1] == "1"


def test_scene_argv_uses_threshold_and_cap():
    argv = FfmpegFrames(scene_threshold=0.3).build_scene_argv(Path("/v/video.mp4"), Path("/v/frames"), max_frames=8)
    vf = argv[argv.index("-vf") + 1]
    assert "select='gt(scene,0.3)'" in vf and "scale=640:-2" in vf
    assert argv[argv.index("-frames:v") + 1] == "7"  # hook frame takes one slot
    assert argv[-1] == "/v/frames/scene_%02d.jpg"


def test_ffmpeg_frames_collects_outputs_in_order(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    dest = tmp_path / "frames"

    def fake_run(argv, check, capture_output):
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.name == "hook.jpg":
            out.write_bytes(b"h")
        else:
            for i in (1, 2, 3):
                (out.parent / f"scene_{i:02d}.jpg").write_bytes(b"s")
        return None

    monkeypatch.setattr("clipsieve.evidence.frames.subprocess.run", fake_run)
    frames = FfmpegFrames().extract(video, dest, max_frames=3)
    assert [p.name for p in frames] == ["hook.jpg", "scene_01.jpg", "scene_02.jpg"]


def test_protocol_conformance():
    assert isinstance(FakeFrames(), FrameExtractor)
    assert isinstance(FfmpegFrames(), FrameExtractor)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_frames.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence.frames'`

- [ ] **Step 3: Implement frames**

`backend/clipsieve/evidence/frames.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)

HOOK_FRAME_AT_S = 0.5

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


@runtime_checkable
class FrameExtractor(Protocol):
    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]: ...


class FakeFrames:
    """Writes `count` tiny PNG files named like the real extractor. No ffmpeg."""

    def __init__(self, count: int = 2) -> None:
        self._count = count

    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        names = ["hook.jpg"] + [f"scene_{i:02d}.jpg" for i in range(1, self._count)]
        out: list[Path] = []
        for name in names[:max_frames]:
            p = dest / name
            p.write_bytes(PNG_1X1)
            out.append(p)
        return out


class FfmpegFrames:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", scene_threshold: float = 0.3, width: int = 640) -> None:
        self._bin = ffmpeg_bin
        self._threshold = scene_threshold
        self._width = width

    def build_hook_argv(self, video: Path, dest: Path) -> list[str]:
        return [
            self._bin, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(HOOK_FRAME_AT_S), "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={self._width}:-2",
            str(dest / "hook.jpg"),
        ]

    def build_scene_argv(self, video: Path, dest: Path, max_frames: int) -> list[str]:
        scene_cap = max(0, max_frames - 1)
        return [
            self._bin, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video),
            "-vf", f"select='gt(scene,{self._threshold})',scale={self._width}:-2",
            "-vsync", "vfr", "-frames:v", str(scene_cap),
            str(dest / "scene_%02d.jpg"),
        ]

    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(self.build_hook_argv(video, dest), check=True, capture_output=True)
        if max_frames > 1:
            subprocess.run(self.build_scene_argv(video, dest, max_frames), check=True, capture_output=True)
        frames = [dest / "hook.jpg"] if (dest / "hook.jpg").exists() else []
        frames += sorted(dest.glob("scene_*.jpg"))
        frames = frames[:max_frames]
        log.debug("frames_extracted", video=str(video), count=len(frames))
        return frames
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/evidence/test_frames.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/clipsieve/evidence/frames.py backend/tests/evidence/test_frames.py
git commit -m "feat(evidence): add keyframe extraction via ffmpeg scene detection with hook frame and fake

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Comment summary in code, English and Chinese

**Files:**
- Create: `backend/clipsieve/evidence/comments.py`
- Test: `backend/tests/evidence/test_comments.py`

**Interfaces:**
- Consumes: `clipsieve.models.Comment`, `clipsieve.models.CommentSummary`.
- Produces: `summarize_comments(comments: list[Comment], lang: str | None) -> CommentSummary`, `tokenize(text: str, lang: str | None) -> list[str]`, `is_cjk(text: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/evidence/test_comments.py`:

```python
from clipsieve.evidence.comments import is_cjk, summarize_comments, tokenize
from clipsieve.models import Comment


def test_english_top_terms_exclude_stopwords():
    comments = [
        Comment(text="this hook is the best hook ever", likes=10),
        Comment(text="the hook works, great hook", likes=5),
        Comment(text="saved it", likes=1),
    ]
    s = summarize_comments(comments, "en")
    assert s.count == 3
    assert s.top_terms[0] == "hook"
    assert "the" not in s.top_terms and "is" not in s.top_terms


def test_samples_are_top_five_by_likes():
    comments = [Comment(text=f"c{i}", likes=i) for i in range(8)] + [Comment(text="nolikes", likes=None)]
    s = summarize_comments(comments, "en")
    assert s.sample == ["c7", "c6", "c5", "c4", "c3"]


def test_chinese_bigrams_and_stop_chars():
    comments = [
        Comment(text="房租好贵，房租真的贵", likes=3),
        Comment(text="上海房租太贵了", likes=9),
        Comment(text="我也是新加坡人", likes=2),
    ]
    s = summarize_comments(comments, "zh")
    assert "房租" in s.top_terms[:2]
    assert all("的" not in t and "了" not in t for t in s.top_terms)
    assert s.sample[0] == "上海房租太贵了"


def test_cjk_detection_and_tokenize():
    assert is_cjk("房租好贵") and not is_cjk("rent is high")
    assert tokenize("Stop scrolling, I built it!", "en") == ["stop", "scrolling", "i", "built", "it"]
    assert tokenize("房租好贵", "zh") == ["房租", "租好", "好贵"]


def test_empty_comments():
    s = summarize_comments([], None)
    assert s.count == 0 and s.top_terms == [] and s.sample == []


def test_mixed_language_auto_detects_cjk_when_lang_missing():
    s = summarize_comments([Comment(text="上海房租", likes=1), Comment(text="上海生活", likes=1)], None)
    assert "上海" in s.top_terms
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_comments.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence.comments'`

- [ ] **Step 3: Implement**

`backend/clipsieve/evidence/comments.py`:

```python
from __future__ import annotations

import re
from collections import Counter

from clipsieve.models import Comment, CommentSummary

TOP_TERMS = 10
SAMPLES = 5

_EN_STOP = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "i", "you", "he", "she", "we", "they", "me", "my", "your", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "as", "so", "if", "then", "than", "too", "very", "just", "not", "no", "yes",
    "do", "does", "did", "have", "has", "had", "what", "which", "who", "how", "why", "when", "where", "there",
    "here", "all", "any", "can", "will", "would", "should", "could", "ever", "also", "about", "up", "out",
}
_ZH_STOP_CHARS = set("的了是我你他她它们在和就不都也这那有人吗呢吧啊呀哦嗯很太还又把被让给对去来说看到")

_CJK = re.compile(r"[一-鿿]")
_EN_WORD = re.compile(r"[a-zA-Z']+")
_CJK_RUN = re.compile(r"[一-鿿]+")


def is_cjk(text: str) -> bool:
    cjk = len(_CJK.findall(text))
    letters = len(_EN_WORD.findall(text))
    return cjk > 0 and cjk >= letters


def tokenize(text: str, lang: str | None) -> list[str]:
    use_cjk = (lang or "").lower().startswith("zh") or (lang is None and is_cjk(text))
    if use_cjk:
        tokens: list[str] = []
        for run in _CJK_RUN.findall(text):
            chars = [c for c in run]
            tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
        return tokens
    return [w.lower().strip("'") for w in _EN_WORD.findall(text) if w.strip("'")]


def _is_stop(token: str, cjk: bool) -> bool:
    if cjk:
        return any(c in _ZH_STOP_CHARS for c in token)
    return token in _EN_STOP or len(token) < 2


def summarize_comments(comments: list[Comment], lang: str | None) -> CommentSummary:
    if not comments:
        return CommentSummary(count=0, top_terms=[], sample=[])
    joined = " ".join(c.text for c in comments)
    cjk = (lang or "").lower().startswith("zh") or (lang is None and is_cjk(joined))
    counter: Counter[str] = Counter()
    for c in comments:
        for tok in tokenize(c.text, "zh" if cjk else "en"):
            if not _is_stop(tok, cjk):
                counter[tok] += 1
    top_terms = [t for t, _ in counter.most_common(TOP_TERMS)]
    ranked = sorted(comments, key=lambda c: (c.likes or 0), reverse=True)
    sample = [c.text for c in ranked[:SAMPLES]]
    return CommentSummary(count=len(comments), top_terms=top_terms, sample=sample)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/evidence/test_comments.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/clipsieve/evidence/comments.py backend/tests/evidence/test_comments.py
git commit -m "feat(evidence): summarise comments in code with English and Chinese tokenisation

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Jev state packet builder with CJK-aware token estimate and ordered truncation

**Files:**
- Create: `backend/clipsieve/evidence/packet.py`
- Test: `backend/tests/evidence/test_packet.py`

**Interfaces:**
- Consumes: models `Brief, Post, Evidence`.
- Produces: `MAX_STATE_TOKENS = 28_000`, `estimate_tokens(text: str) -> int`, `build_metadata_state(brief: Brief, post: Post) -> dict`, `build_state(brief: Brief, post: Post, evidence: Evidence | None) -> tuple[dict, bool]`, `state_json(state: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/evidence/test_packet.py`:

```python
from datetime import datetime, timezone

from clipsieve.evidence.packet import MAX_STATE_TOKENS, build_metadata_state, build_state, estimate_tokens, state_json
from clipsieve.models import Brief, Comment, CommentSummary, Evidence, Media, Metrics, OcrItem, Post, PostText, TranscriptSegment


def _brief() -> Brief:
    return Brief(text="Singaporean moving to Shanghai, vlog style", topic="Shanghai expat life", audience="Singaporeans in China", persona="Singaporean vlogger new to Shanghai")


def _post(lang: str = "en") -> Post:
    return Post(
        id="youtube:abc", platform="youtube", url="https://www.youtube.com/shorts/abc", creator_hash="0" * 64,
        creator_display="Nat", posted_at=datetime(2026, 9, 1, tzinfo=timezone.utc), kind="video",
        text=PostText(title="Day one", caption="房租好贵 #上海", hashtags=["上海"]), media=[Media(type="video", duration_s=50)],
        metrics=Metrics(views=1000, likes=100, comments=10),
        comments=[Comment(text="真实", likes=5), Comment(text="great", likes=2)], lang=lang, raw_ref="raw/x.json",
        collected_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )


def _evidence(transcript_chars: int = 100, ocr_items: int = 2, zh: bool = False) -> Evidence:
    word = "房" if zh else "word "
    seg_text = word * (40 if zh else 8)
    n = max(1, transcript_chars // len(seg_text))
    return Evidence(
        post_id="youtube:abc",
        transcript=[TranscriptSegment(start_s=i * 2.0, end_s=i * 2.0 + 2.0, text=seg_text) for i in range(n)],
        transcript_lang="zh" if zh else "en",
        ocr=[OcrItem(source="keyframe", index=i, text=f"ocr {i}") for i in range(ocr_items)],
        keyframes=["media/youtube__abc/frames/hook.jpg"],
        comment_summary=CommentSummary(count=2, top_terms=["真实", "great"], sample=["真实", "great"]),
        token_estimate=0, truncated=False,
    )


def test_estimate_tokens_counts_cjk_per_char():
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("房租好贵") == 4
    assert estimate_tokens("房租 rent") == 2 + len(" rent") // 3


def test_metadata_state_has_no_transcript_or_ocr():
    state = build_metadata_state(_brief(), _post())
    assert set(state) == {"brief", "post", "comments"}
    assert state["post"]["caption"] == "房租好贵 #上海"
    assert state["comments"] == ["真实", "great"]


def test_state_under_cap_untouched():
    state, truncated = build_state(_brief(), _post(), _evidence())
    assert truncated is False
    assert set(state) == {"brief", "post", "transcript", "ocr", "comments"}
    assert len(state["transcript"]) == 2 and len(state["ocr"]) == 2
    assert state["comments"]["sample"] == ["真实", "great"]


def test_state_without_evidence_has_empty_sections():
    state, truncated = build_state(_brief(), _post(), None)
    assert state["transcript"] == [] and state["ocr"] == [] and truncated is False


def test_truncation_order_comments_then_ocr_then_transcript():
    ev = _evidence(transcript_chars=MAX_STATE_TOKENS * 3 + 3000, ocr_items=5)
    state, truncated = build_state(_brief(), _post(), ev)
    assert truncated is True
    assert state["comments"]["sample"] == [] and state["comments"]["top_terms"] == []
    assert state["ocr"] == []
    assert 0 < len(state["transcript"]) < len(ev.transcript)
    assert state["transcript"][0]["text"] == ev.transcript[0].text  # head kept, tail dropped
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def test_partial_truncation_stops_as_soon_as_it_fits():
    ev = _evidence(transcript_chars=MAX_STATE_TOKENS * 3 - 600, ocr_items=400)
    state, truncated = build_state(_brief(), _post(), ev)
    assert truncated is True
    assert state["comments"]["sample"] == []
    assert len(state["transcript"]) == len(ev.transcript)  # transcript untouched: ocr trimming was enough
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def test_cjk_estimate_and_truncation():
    ev = _evidence(transcript_chars=15_000, zh=True)
    joined = "".join(s.text for s in ev.transcript)
    assert estimate_tokens(joined) >= 14_000
    ev_big = _evidence(transcript_chars=40_000, zh=True)
    state, truncated = build_state(_brief(), _post("zh"), ev_big)
    assert truncated is True
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS
    assert state["post"]["caption"] == "房租好贵 #上海"


def test_state_json_is_deterministic_and_unicode():
    state, _ = build_state(_brief(), _post(), _evidence())
    a, b = state_json(state), state_json(state)
    assert a == b and "房租好贵" in a and "\\u" not in a
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_packet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence.packet'`

- [ ] **Step 3: Implement**

`backend/clipsieve/evidence/packet.py`:

```python
from __future__ import annotations

import json
import re
from typing import Any

from clipsieve.models import Brief, Evidence, Post

MAX_STATE_TOKENS = 28_000
METADATA_COMMENTS = 20
METADATA_COMMENT_CHARS = 200

_CJK = re.compile(r"[一-鿿぀-ヿ가-힯]")


def estimate_tokens(text: str) -> int:
    """CJK characters are about one token each; everything else about one token per three chars."""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk) // 3


def state_json(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _brief_block(brief: Brief) -> dict[str, Any]:
    return {"text": brief.text, "topic": brief.topic, "audience": brief.audience, "persona": brief.persona}


def _post_block(post: Post) -> dict[str, Any]:
    return {
        "id": post.id,
        "platform": post.platform,
        "kind": post.kind,
        "lang": post.lang,
        "title": post.text.title,
        "caption": post.text.caption,
        "hashtags": list(post.text.hashtags),
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "duration_s": next((m.duration_s for m in post.media if m.duration_s is not None), None),
        "metrics": post.metrics.model_dump(mode="json", exclude_none=True),
    }


def build_metadata_state(brief: Brief, post: Post) -> dict[str, Any]:
    comments = [c.text[:METADATA_COMMENT_CHARS] for c in sorted(post.comments, key=lambda c: c.likes or 0, reverse=True)]
    return {"brief": _brief_block(brief), "post": _post_block(post), "comments": comments[:METADATA_COMMENTS]}


def build_state(brief: Brief, post: Post, evidence: Evidence | None) -> tuple[dict[str, Any], bool]:
    transcript = [{"t": round(s.start_s, 1), "text": s.text} for s in (evidence.transcript if evidence else [])]
    ocr = [{"source": o.source, "index": o.index, "text": o.text} for o in (evidence.ocr if evidence else [])]
    if evidence:
        comments: dict[str, Any] = {
            "count": evidence.comment_summary.count,
            "top_terms": list(evidence.comment_summary.top_terms),
            "sample": list(evidence.comment_summary.sample),
        }
    else:
        comments = {"count": len(post.comments), "top_terms": [], "sample": [c.text for c in post.comments[:5]]}

    state: dict[str, Any] = {
        "brief": _brief_block(brief),
        "post": _post_block(post),
        "transcript": transcript,
        "ocr": ocr,
        "comments": comments,
    }
    truncated = False

    def fits() -> bool:
        return estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS

    if fits():
        return state, truncated

    # 1. comments: samples first, then terms
    if state["comments"]["sample"]:
        state["comments"]["sample"] = []
        truncated = True
    if not fits() and state["comments"]["top_terms"]:
        state["comments"]["top_terms"] = []
        truncated = True
    # 2. ocr: drop from the end
    while not fits() and state["ocr"]:
        state["ocr"].pop()
        truncated = True
    # 3. transcript: drop the tail, keep the hook
    while not fits() and len(state["transcript"]) > 1:
        state["transcript"].pop()
        truncated = True
    if not fits() and state["transcript"]:
        # single enormous segment: hard-cut its text
        seg = state["transcript"][0]
        budget_chars = max(200, (MAX_STATE_TOKENS - estimate_tokens(state_json({**state, "transcript": []}))) * 3 // 2)
        seg["text"] = seg["text"][:budget_chars]
        truncated = True
    return state, truncated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/evidence/test_packet.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/clipsieve/evidence/packet.py backend/tests/evidence/test_packet.py
git commit -m "feat(evidence): build Jev state packets with CJK-aware token estimate and ordered truncation

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: extract_evidence orchestration and evidence snapshots for the fixture posts

**Files:**
- Create: `backend/clipsieve/evidence/extract.py`
- Create: `backend/tests/fixtures/evidence/local__fx-001.json` through `local__fx-005.json` (generated by the snapshot test, then committed)
- Test: `backend/tests/evidence/test_extract.py`

**Interfaces:**
- Consumes: `RunPaths` (plan 01), `ASR`, `OCR`, `FrameExtractor`, `summarize_comments`, `estimate_tokens`, `ocr_lang_for_post`, models, fixture posts `backend/tests/fixtures/posts/local__fx-00N.json`.
- Produces: `extract_evidence(post: Post, paths: RunPaths, asr: ASR, ocr: OCR, frames: FrameExtractor) -> Evidence`, `resolve_media(paths: RunPaths, post: Post, media: Media) -> Path`, `run_relative(paths: RunPaths, path: Path) -> str`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/evidence/test_extract.py`:

```python
import json
import os
from pathlib import Path

import pytest

from clipsieve.evidence.asr import FakeASR
from clipsieve.evidence.extract import extract_evidence, resolve_media, run_relative
from clipsieve.evidence.frames import PNG_1X1, FakeFrames
from clipsieve.evidence.ocr import FakeOCR
from clipsieve.models import Evidence, Post
from clipsieve.store.paths import RunPaths, safe_post_filename

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOTS = FIXTURES / "evidence"


def _load_posts() -> list[Post]:
    return [Post.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted((FIXTURES / "posts").glob("*.json"))]


def _materialise_media(paths: RunPaths, post: Post) -> Post:
    """Create fake media files plus sidecars so fakes have something to read."""
    dest = paths.media_dir(post.id)
    dest.mkdir(parents=True, exist_ok=True)
    media = []
    for m in post.media:
        if m.type == "video":
            name = "video.mp4"
            (dest / name).write_bytes(b"\x00" * 64)
            (dest / f"{name}.transcript.json").write_text(
                json.dumps({"lang": post.lang or "en", "segments": [
                    {"start_s": 0.0, "end_s": 2.0, "text": f"hook line for {post.id}"},
                    {"start_s": 2.0, "end_s": 5.0, "text": "second line 第二句"},
                ]}, ensure_ascii=False), encoding="utf-8")
        else:
            name = f"img_{(m.index or 0):02d}.png"
            (dest / name).write_bytes(PNG_1X1)
            (dest / f"{name}.ocr.json").write_text(json.dumps([f"overlay {m.index} 房租"], ensure_ascii=False), encoding="utf-8")
        media.append(m.model_copy(update={"local_path": name}))
    # keyframe OCR sidecars for FakeFrames output
    frames_dir = dest / "frames"
    frames_dir.mkdir(exist_ok=True)
    (frames_dir / "hook.jpg.ocr.json").write_text(json.dumps(["STOP SCROLLING"]), encoding="utf-8")
    return post.model_copy(update={"media": media})


@pytest.fixture
def paths(tmp_path: Path) -> RunPaths:
    p = RunPaths(tmp_path / "data", "run-test")
    p.ensure()
    return p


def test_video_post_gets_transcript_frames_and_keyframe_ocr(paths):
    post = next(p for p in _load_posts() if p.kind == "video")
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    assert ev.post_id == post.id
    assert [s.text for s in ev.transcript][0].startswith("hook line")
    assert ev.keyframes[0] == f"media/{safe_post_filename(post.id)}/frames/hook.jpg"
    assert any(o.source == "keyframe" and o.text == "STOP SCROLLING" for o in ev.ocr)
    assert ev.truncated is False and ev.token_estimate > 0
    assert paths.evidence_json(post.id).is_file()


def test_image_note_gets_ocr_per_image_and_no_transcript(paths):
    post = next(p for p in _load_posts() if p.kind == "image_note")
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert ev.transcript == [] and ev.keyframes == []
    assert len([o for o in ev.ocr if o.source == "image"]) == len(post.media)
    assert "房租" in ev.ocr[0].text


def test_thumbnail_written_256_wide_for_video_and_image_note(paths):
    from PIL import Image

    video = _materialise_media(paths, next(p for p in _load_posts() if p.kind == "video"))
    extract_evidence(video, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    thumb = paths.media_dir(video.id) / "thumb.jpg"
    assert thumb.is_file()
    with Image.open(thumb) as im:
        assert im.width == 256 and im.format == "JPEG"

    note = _materialise_media(paths, next(p for p in _load_posts() if p.kind == "image_note"))
    extract_evidence(note, paths, FakeASR(), FakeOCR(), FakeFrames())
    thumb = paths.media_dir(note.id) / "thumb.jpg"
    assert thumb.is_file()
    with Image.open(thumb) as im:
        assert im.width == 256
    before = thumb.stat().st_mtime_ns
    extract_evidence(note, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert thumb.stat().st_mtime_ns == before  # idempotent


def test_missing_media_file_yields_empty_sections_not_crash(paths):
    post = next(p for p in _load_posts() if p.kind == "video")
    post = post.model_copy(update={"media": [m.model_copy(update={"local_path": "video.mp4"}) for m in post.media]})
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert ev.transcript == [] and ev.ocr == [] and ev.keyframes == []
    assert ev.comment_summary.count == len(post.comments)
    assert not (paths.media_dir(post.id) / "thumb.jpg").exists()


def test_resolve_and_relative_paths(paths):
    post = _load_posts()[0]
    m = post.media[0].model_copy(update={"local_path": "video.mp4"})
    abs_path = resolve_media(paths, post, m)
    assert abs_path == paths.media_dir(post.id) / "video.mp4"
    assert run_relative(paths, abs_path) == f"media/{safe_post_filename(post.id)}/video.mp4"


@pytest.mark.parametrize("post", _load_posts(), ids=lambda p: p.id)
def test_snapshot_matches_fixture(paths, post):
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    snap = SNAPSHOTS / f"{safe_post_filename(post.id)}.json"
    rendered = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not snap.exists():
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        snap.write_text(rendered, encoding="utf-8")
    assert Evidence.model_validate_json(snap.read_text(encoding="utf-8")) == ev
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/evidence/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.evidence.extract'`

- [ ] **Step 3: Implement**

`backend/clipsieve/evidence/extract.py`:

```python
from __future__ import annotations

from pathlib import Path

import structlog

from clipsieve.evidence.asr import ASR
from clipsieve.evidence.comments import summarize_comments
from clipsieve.evidence.frames import FrameExtractor
from clipsieve.evidence.ocr import OCR, ocr_lang_for_post
from clipsieve.evidence.packet import estimate_tokens
from clipsieve.models import Evidence, Media, OcrItem, Post, TranscriptSegment
from clipsieve.store.paths import RunPaths

log = structlog.get_logger(__name__)

MAX_KEYFRAMES = 8
THUMB_WIDTH = 256
THUMB_NAME = "thumb.jpg"


def write_thumbnail(paths: RunPaths, post: Post, source: Path | None) -> Path | None:
    """Write media_dir/thumb.jpg, 256px wide, from the first keyframe or first image. Idempotent."""
    if source is None or not source.exists():
        return None
    target = paths.media_dir(post.id) / THUMB_NAME
    if target.exists():
        return target
    try:
        from PIL import Image

        with Image.open(source) as im:
            im = im.convert("RGB")
            height = max(1, round(im.height * THUMB_WIDTH / max(1, im.width)))
            im.resize((THUMB_WIDTH, height)).save(target, format="JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001 - a bad frame must not fail extraction
        log.warning("thumbnail_failed", post_id=post.id, source=str(source), error=repr(exc))
        return None
    return target


def resolve_media(paths: RunPaths, post: Post, media: Media) -> Path:
    if media.local_path is None:
        raise FileNotFoundError(f"media for {post.id} has no local_path")
    return paths.media_dir(post.id) / media.local_path


def run_relative(paths: RunPaths, path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def extract_evidence(post: Post, paths: RunPaths, asr: ASR, ocr: OCR, frames: FrameExtractor) -> Evidence:
    ocr_lang = ocr_lang_for_post(post.lang)
    transcript: list[TranscriptSegment] = []
    transcript_lang: str | None = None
    ocr_items: list[OcrItem] = []
    keyframes: list[str] = []

    for media in post.media:
        if media.local_path is None:
            log.warning("evidence_media_missing_path", post_id=post.id)
            continue
        path = resolve_media(paths, post, media)
        if not path.exists():
            log.warning("evidence_media_missing_file", post_id=post.id, path=str(path))
            continue

        if media.type == "video":
            frame_paths = frames.extract(path, paths.media_dir(post.id) / "frames", max_frames=MAX_KEYFRAMES)
            for i, frame in enumerate(frame_paths):
                keyframes.append(run_relative(paths, frame))
                text = " ".join(ocr.read(frame, ocr_lang)).strip()
                if text:
                    ocr_items.append(OcrItem(source="keyframe", index=i, text=text))
            segments, lang = asr.transcribe(path, (post.lang or None))
            transcript.extend(segments)
            transcript_lang = transcript_lang or lang
        else:
            text = " ".join(ocr.read(path, ocr_lang)).strip()
            if text:
                ocr_items.append(OcrItem(source="image", index=media.index or 0, text=text))

    thumb_source: Path | None = None
    if keyframes:
        thumb_source = paths.root / keyframes[0]
    else:
        first_image = next((m for m in post.media if m.type == "image" and m.local_path), None)
        if first_image is not None:
            thumb_source = resolve_media(paths, post, first_image)
    write_thumbnail(paths, post, thumb_source)

    comment_summary = summarize_comments(list(post.comments), post.lang)
    text_blob = " ".join(
        [s.text for s in transcript] + [o.text for o in ocr_items] + comment_summary.sample + comment_summary.top_terms
    )
    evidence = Evidence(
        post_id=post.id,
        transcript=transcript,
        transcript_lang=transcript_lang,
        ocr=ocr_items,
        keyframes=keyframes[:MAX_KEYFRAMES],
        comment_summary=comment_summary,
        token_estimate=estimate_tokens(text_blob),
        truncated=False,
    )
    out = paths.evidence_json(post.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    log.info("evidence_extracted", post_id=post.id, segments=len(transcript), ocr=len(ocr_items), keyframes=len(keyframes))
    return evidence
```

- [ ] **Step 4: Run tests, generating the snapshots on the first run**

Run: `UPDATE_SNAPSHOTS=1 uv run pytest tests/evidence/test_extract.py -v`
Expected: 10 passed (5 behaviour tests, 5 parametrised snapshots). Five new files appear under `tests/fixtures/evidence/`.

Run again without the flag: `uv run pytest tests/evidence/test_extract.py -v`
Expected: 10 passed, no file changes (`git status --short tests/fixtures/evidence` shows only the five untracked files, none modified).

- [ ] **Step 5: Run the whole backend suite and lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all tests pass, lint clean.

- [ ] **Step 6: Commit**

```bash
git add backend/clipsieve/evidence/extract.py backend/tests/evidence/test_extract.py backend/tests/fixtures/evidence
git commit -m "feat(evidence): orchestrate extraction and snapshot evidence for the five fixture posts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: DOX pass for adapters and evidence, full repo check

**Files:**
- Modify: `backend/AGENTS.md`
- Modify: `.env.example` (add `YOUTUBE_API_KEY=` if plan 01 did not)
- Modify: `README.md` (one line under a new "Adapters" heading)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only.

- [ ] **Step 1: Add the adapters and evidence sections to `backend/AGENTS.md`**

Append to `backend/AGENTS.md` after its existing sections:

```markdown
## adapters/

Platform adapters turn a `Query` into `Post` records and download media on request.

- Implement `Adapter` from `adapters/base.py`: `platform`, `search(queries, limit)`, `fetch_media(post, dest)`, `healthcheck()`, plus `@classmethod from_settings(settings)`.
- Register in `pyproject.toml` under `[project.entry-points."clipsieve.adapters"]`. `registry.load_adapters` discovers entry points first, then built-ins by import.
- `search` yields posts with `media[].local_path = None`. Raw payloads go to `<data_dir>/incoming/<platform>/<safe_id>.json`; `raw_ref` is that absolute path until the Runner relocates it into the run.
- `fetch_media` writes into `dest` and sets `local_path` relative to `dest` (for example `video.mp4`). It must be idempotent: never re-download an existing file.
- Captions, when available, are written as `<media>.transcript.json` so ASR is skipped.
- Creator ids are hashed with `hash_creator(id, settings.clipsieve_creator_salt)` at mapping time. Never persist the raw id outside the raw payload.
- Comments are capped at 50, most-liked first.
- `adapters/` never imports from `evidence/`.
- Every adapter passes `tests/adapters/contract.py::run_adapter_contract` against a recorded fixture. Tests never hit the network: yt-dlp is behind `YtDlpClient` with `FakeYtDlpClient`; HTTP uses `httpx.MockTransport`.

## evidence/

Turns a post's media into text. Pure local computation; no network.

- Interfaces with fakes: `ASR` (`WhisperASR`, `FakeASR`), `OCR` (`PaddleOCRBackend`, `FakeOCR`), `FrameExtractor` (`FfmpegFrames`, `FakeFrames`). Heavy libraries are optional extras (`uv sync --extra asr --extra ocr`) imported lazily inside the class.
- Fakes read sidecars: `<media>.transcript.json`, `<image>.ocr.json`. Real backends honour the transcript sidecar too.
- `extract_evidence(post, paths, asr, ocr, frames)` writes `Evidence` to `paths.evidence_json(post.id)`. Keyframes are run-relative paths `media/<safe_id>/frames/<name>`, hook frame first.
- `extract_evidence` also writes `media/<safe_id>/thumb.jpg` (256px wide, Pillow) from the first keyframe or first image; the dashboard requests it via `GET /api/runs/{id}/media/{post_id}/thumb.jpg`. Never re-written if present.
- `packet.build_state` is the only place that assembles Jev state. `MAX_STATE_TOKENS = 28000`. Truncation order is fixed: comment samples, comment terms, OCR from the end, transcript tail. `estimate_tokens` counts CJK characters as one token each.
- `Evidence.truncated` is `False` at extraction; the Runner sets it from `build_state`.
- `evidence/` never imports from `adapters/`.
```

- [ ] **Step 2: Keep `.env.example` and README current**

Confirm `.env.example` contains `YOUTUBE_API_KEY=`; add it if absent. Append to `README.md` under Principles:

```markdown
## Adapters

Built in: `local` (folder of media or a CSV export) and `youtube` (yt-dlp, Shorts under 180 s, auto-captions). Community adapters that drive a logged-in browser live in `contrib/` with their own terms. See `backend/AGENTS.md` for the adapter contract.
```

- [ ] **Step 3: Run the full repo check from the repo root**

Run (from repo root): `bun run check`
Expected: schema drift check passes (no generated files changed in this plan), lint clean for TS and Python, typecheck passes, backend tests pass, frontend tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/AGENTS.md .env.example README.md
git commit -m "docs(dox): document adapters and evidence contracts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review against the spec

**Spec coverage.** Section 5.1 interface and contract test: Task 1. Entry-point registration and healthy-only listing: Task 2 (the API filter itself is plan 03). 5.2 local_import folder and CSV: Task 3. 5.3 youtube with yt-dlp search, captions seeding the transcript, 200 MB cap, 180 s Shorts filter, optional Data API: Tasks 4 and 5. Section 6 ASR with mlx/faster-whisper, large-v3, auto language, skipped on captions: Task 6. Keyframes at scene threshold 0.3 capped at 8 plus the 0.5 s hook frame: Task 8. OCR with PaddleOCR `ch`/`en` and the 0.6 cutoff on keyframes and image-note images: Tasks 7 and 11. Comments in code: Task 9. Packet with named fields and fixed truncation order under 28,000 tokens: Task 10. Fakes for every interface: Tasks 6 to 8. Section 5.4 is plan 05.

**Placeholder scan.** No TBD, TODO, "similar to", or "add validation" phrasing. Every code step shows the code.

**Type consistency.** `TranscriptSegment(start_s, end_s, text)` used identically in `vtt.py`, `asr.py`, `packet.py`, `extract.py`. `OcrItem(source, index, text)` in `extract.py` and `packet.py`. `CommentSummary(count, top_terms, sample)` in `comments.py`, `packet.py`, `extract.py`. `safe_post_filename` imported from `clipsieve.store.paths` in both adapters and the extract test. `from_settings` classmethod on both adapters and asserted by the registry.

**Review Focus.** Line 1 pinned by `test_cjk_estimate_and_truncation` (Task 10). Line 2 by `test_csv_chinese_caption_roundtrip` (Task 3). Line 3 by `test_parse_vtt_rolling_cues` (Task 4). Line 4 by `test_comments_capped_most_liked` (Task 5). Line 5 by `test_fetch_media_idempotent`, `test_fetch_media_is_idempotent_and_does_not_redownload` and the contract helper (Tasks 1, 3, 5).
