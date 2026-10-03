# backend/ — AGENTS.md

Python package `clipsieve`. Owns the whole pipeline: config, store, event log, adapters, evidence, judge, select, explain, API, CLI.

## Contract

- Python 3.12 only. `uv` for everything: `uv sync`, `uv run pytest`, `uv add`.
- `clipsieve/models.py` is GENERATED from `packages/schema/`. Never edit it. Run `bun run schema` at the repo root after changing a schema.
- Logging via `clipsieve.logging.get_logger(__name__)`. No `print()`.
- Config via `clipsieve.config.get_settings()`. Never read `os.environ` elsewhere. Nothing depends on cwd: `.env` is read from `REPO_ROOT/.env`, then `./.env` (the cwd file wins), and a relative `CLIPSIEVE_DATA_DIR` resolves against `REPO_ROOT`; absolute paths are kept as given.
- The creator-hash salt comes only from `config.ensure_creator_salt(settings)`: the configured value, else `<data_dir>/creator_salt`, created on first use (32 hex chars, mode 0600). Never log the salt.
- Files under `data/runs/<run_id>/` are canonical; SQLite is an index. Any write goes to the file first, then the row. `RunRepository.reindex` must be able to rebuild rows from files.
- Optional means absent: run files, SQLite `data` columns and `events.jsonl` are dumped with `exclude_none=True` (and `by_alias=True`), so no `null` reaches files that the JSON Schemas type as `string`.
- Every stage emits `RunEvent`s through `clipsieve.events.writer.EventWriter`. Payload shapes are validated there; see the type table in `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`.
- `events.jsonl` is append-only, one writer per run. `EventWriter` terminates a partial last line left by a dead writer before appending (logs `events.repaired_partial_line`) and truncates a failed append. Readers parse bytes, hold back a trailing partial line silently, and log then skip corrupt complete lines (`events.skip_corrupt_line`). `follow_events` ends at the first terminal event (`done`, or stage `failed`) even when `after` filters it out.
- Tests in `tests/`, fixtures in `tests/fixtures/`. No network. Every external system has a fake.
- Shared fixtures live in `tests/conftest.py`: `data_dir` (alias `tmp_data_dir`), `engine` (`init_db`'d), `repo`, `fixtures_dir`, `fixture_posts` (the five posts, id order). An autouse fixture resets structlog and its contextvars after every test; no test may rely on logging state from another.

## Layout

| Path | Owns |
|---|---|
| `clipsieve/config.py` | `Settings`, `get_settings()`, `REPO_ROOT`, `ensure_creator_salt()` |
| `clipsieve/logging.py` | structlog configuration |
| `clipsieve/models.py` | generated models (do not edit) |
| `clipsieve/store/` | `RunPaths`, SQLite engine and tables, `RunRepository` |
| `clipsieve/events/` | `EventWriter`, `read_events`, `follow_events` |
| `clipsieve/events/payloads.py` | `PAYLOAD_MODELS`, one Pydantic model per `RunEventType` |
| `clipsieve/adapters/` | `Adapter` protocol, `registry`, `local_import`, `youtube`, `ytdlp_client`, `vtt` |
| `clipsieve/evidence/` | `asr`, `ocr`, `frames`, `comments`, `packet`, `extract` |
| `clipsieve/select/select.py` | `Selection` model (plan 01); selection functions (plan 03) |

Later plans add `judge/`, `explain/`, `pipeline/`, `api/`, `cli.py` and extend this table.

## adapters/

Platform adapters turn a `Query` into `Post` records and download media on request.

- Implement `Adapter` from `adapters/base.py`: `platform`, `search(queries, limit)`, `fetch_media(post, dest)`, `healthcheck()`, plus `@classmethod from_settings(settings)`.
- Register in `pyproject.toml` under `[project.entry-points."clipsieve.adapters"]`. `registry.load_adapters` discovers entry points first, then built-ins by import.
- `search` yields posts with `media[].local_path = None`. Raw payloads go to `<data_dir>/incoming/<platform>/<safe_id>.json`; `raw_ref` is that absolute path until the Runner relocates it into the run.
- `fetch_media` writes into `dest` and sets `local_path` relative to `dest` (for example `video.mp4`). It is idempotent: never re-download an existing file. A yt-dlp download failure, or one that leaves no file, raises `MediaDownloadError` (defined in `adapters/base.py`, re-exported by `youtube.py`). `requested_downloads[0]["filepath"]` is honoured.
- Captions, when available, are written as `<media>.transcript.json` (temp file then replace) so ASR is skipped.
- Creator ids are hashed with `hash_creator(id, salt)`, salt from `ensure_creator_salt(settings)`, at mapping time. Never put the raw id in a `Post`; raw payloads keep platform ids as local provenance, but comment author identifiers are stripped. `creator_display` may hold a display name.
- Comments are capped at 50, most-liked first.
- `local_import`: folder or CSV. A non-empty `creator` CSV column sets per-row `creator_hash` and `creator_display`; otherwise the hash is of the CSV path.
- `youtube`: live, upcoming and post-live videos are rejected. Shorts filter is duration < 180 s; a missing duration at the full-info stage means "not a Short". Optional Data API key is sent in the `x-goog-api-key` header. Downloads are capped at 200 MB.
- `vtt.py`: tags are stripped, then character references are unescaped; the cue split tolerates YouTube's `" "` placeholder lines.
- `adapters/` never imports from `evidence/`.
- Every adapter passes `tests/adapters/contract.py::run_adapter_contract` against a recorded fixture. Tests never hit the network: yt-dlp is behind `YtDlpClient` with `FakeYtDlpClient`; HTTP uses `httpx.MockTransport`.

## evidence/

Turns a post's media into text. Pure local computation; no network.

- Interfaces with fakes: `ASR` (`WhisperASR`, `FakeASR`), `OCR` (`PaddleOCRBackend`, `FakeOCR`), `FrameExtractor` (`FfmpegFrames`, `FakeFrames`). Heavy libraries are optional extras (`uv sync --extra asr --extra ocr`) imported lazily inside the class; the `paddleocr` extra is pinned `<3` (2.x API).
- Fakes read sidecars: `<media>.transcript.json`, `<image>.ocr.json`. Real backends honour the transcript sidecar too. A corrupt sidecar raises.
- `FfmpegFrames`: the scene pass tolerates ffmpeg exit 234 (no scene changes). Hook frame first. `PNG_1X1` (used by `FakeFrames`) is a valid 1x1 PNG.
- `extract_evidence(post, paths, asr, ocr, frames)` writes `Evidence` to `paths.evidence_json(post.id)`. It assumes one video per post (frames share one `frames/` dir). Keyframes are run-relative paths `media/<safe_id>/frames/<name>`, hook frame first, at most 8.
- A failing ASR, OCR or frame step is caught and logged as `evidence_step_failed`; only that section is left empty and the post still gets evidence.
- Evidence JSON is written `exclude_none` via temp file then replace (optional means absent).
- `extract_evidence` also writes `media/<safe_id>/thumb.jpg` (256px wide, Pillow) from the first keyframe or first image; the dashboard requests it via `GET /api/runs/{id}/media/{post_id}/thumb.jpg`. Never re-written if present.
- `packet.build_state` is the only place that assembles Jev state. `MAX_STATE_TOKENS = 28000`, measured on the serialised state; `estimate_tokens` counts CJK characters as one token each. Truncation order is fixed: comments (sample, then top_terms), OCR from the end, transcript tail (whole segments, then within the head segment), and only then caption, hashtags, title. A brief alone over the cap is logged `packet.over_cap` and returned.
- `Evidence.truncated` is `False` at extraction; the Runner sets it from `build_state`.
- `evidence/` never imports from `adapters/`.
