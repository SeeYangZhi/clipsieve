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
| `clipsieve/judge/rubric.py` | rubric pack loading, per-pass question selection, TypeSafe primitive conversion, persona criteria |
| `clipsieve/judge/base.py` | `Judge` protocol, `JudgeFailed`, Jev pricing (`cost_usd`) |
| `clipsieve/judge/typesafe_client.py` | `TypeSafeJudge`: one batched, concurrency-bounded, retrying Jev request per post |
| `clipsieve/judge/recorded.py` | `RecordedJudge` fake replaying `tests/fixtures/judge/*.json`, `FixtureMissing` |
| `clipsieve/select/select.py` | `Selection` model (plan 01); selection functions (plan 03) |

Later plans add the rest of `judge/`, then `explain/`, `pipeline/`, `api/`, `cli.py` and extend this table.

## adapters/

Platform adapters turn a `Query` into `Post` records and download media on request.

- Implement `Adapter` from `adapters/base.py`: `platform`, `search(queries, limit)`, `fetch_media(post, dest)`, `healthcheck()`, plus `@classmethod from_settings(settings)`.
- Register in `pyproject.toml` under `[project.entry-points."clipsieve.adapters"]`. `registry.load_adapters` discovers entry points first, then built-ins by import.
- `search` yields posts with `media[].local_path = None`. Raw payloads go to `<data_dir>/incoming/<platform>/<safe_id>.json`; `raw_ref` is that absolute path until the Runner relocates it into the run.
- The Runner moves the raw file to `raw/<safe_id>.json` and rewrites `raw_ref` to that run-relative path BEFORE calling `fetch_media` (overview B.10). `fetch_media` therefore never reads `raw_ref` or the incoming file: everything it needs lives on the `Post` (`url`, `media[]`, `id`).
- `fetch_media` writes into `dest` and sets `local_path` relative to `dest` (for example `video.mp4`; never absolute). It is idempotent: never re-download an existing file. A yt-dlp download failure, or one that leaves no file, raises `MediaDownloadError` (defined in `adapters/base.py`, re-exported by `youtube.py`). `requested_downloads[0]["filepath"]` is honoured.
- Captions, when available, are written as `<media>.transcript.json` (temp file then replace) so ASR is skipped.
- YouTube requests only the post's language, its auto-generated `<lang>-orig` track and `en` (a `-orig` track's sidecar `lang` drops the suffix). yt-dlp aborts the whole download when one caption track fails, so a download error whose message mentions subtitles or captions is retried once with `subtitle_langs=[]` (no captions; logs `youtube.subtitles_skipped`) and Whisper covers the transcript. `YtDlpClient.download` with an empty `subtitle_langs` writes no captions; `FakeYtDlpClient` copies only the requested tracks.
- Creator ids are hashed with `hash_creator(id, salt)`, salt from `ensure_creator_salt(settings)`, at mapping time. Never put the raw id in a `Post`; raw payloads keep platform ids as local provenance, but comment author identifiers are stripped. `creator_display` may hold a display name.
- Comments are capped at 50, most-liked first.
- `registry._iter_entry_points()` is the module-level seam tests (and plan 05) monkeypatch. A failing plugin or built-in is logged (`adapter_entry_point_import_failed`, `adapter_builtin_import_failed`, `adapter_load_failed`, `adapter_not_protocol`) and skipped, never fatal.
- Raw payloads are placed with `incoming_dir(data_dir, platform)` from `base.py`.
- Recorded YouTube fixtures live in `tests/fixtures/youtube/` (`search.json`, `<id>.json`, `<id>.<lang>.vtt`); `FakeYtDlpClient(fixture_dir)` replays them.
- `YouTubeAdapter.from_settings` reads `clipsieve_data_dir` (for the incoming raw dir), the creator salt via `ensure_creator_salt(settings)`, and `youtube_api_key`: Data API search when set, else yt-dlp search.
- `local_import`: folder or CSV. Folder posts get `local:<sha1[:12]>` ids and hidden files are skipped; CSV rows have `media=[]`, so `fetch_media` is a no-op for them. Folder posts' `fetch_media` copies the file behind `Post.url` (`file.resolve().as_uri()`); a vanished source raises `MediaDownloadError`. A non-empty `creator` CSV column sets per-row `creator_hash` and `creator_display`; otherwise the hash is of the CSV path.
- `youtube`: live, upcoming and post-live videos are rejected. Shorts filter is duration < 180 s; a missing duration at the full-info stage means "not a Short". The flat yt-dlp search asks for `SEARCH_OVERFETCH` (3) times the remaining count, since long videos are dropped after it; `search` still stops at the limit before fetching another info. Optional Data API key is sent in the `x-goog-api-key` header. Downloads are capped at 200 MB.
- `vtt.py`: tags are stripped, then character references are unescaped; the cue split tolerates YouTube's `" "` placeholder lines.
- `adapters/` never imports from `evidence/`.
- Every adapter passes `tests/adapters/contract.py::run_adapter_contract` against a recorded fixture. The helper checks unique post ids and a `^[0-9a-f]{64}$` `creator_hash`, relocates every raw file and rewrites `raw_ref` exactly as the Runner does, then calls `fetch_media` twice and requires dest-relative `local_path`s. Tests never hit the network: yt-dlp is behind `YtDlpClient` with `FakeYtDlpClient`; HTTP uses `httpx.MockTransport`.

## evidence/

Turns a post's media into text. No per-post network calls; Whisper and PaddleOCR download model weights on first use.

- Interfaces with fakes: `ASR` (`WhisperASR`, `FakeASR`), `OCR` (`PaddleOCRBackend`, `FakeOCR`), `FrameExtractor` (`FfmpegFrames`, `FakeFrames`). Heavy libraries are optional extras (`uv sync --extra asr --extra ocr`) imported lazily inside the class; the `paddleocr` extra is pinned `<3` (2.x API).
- `WhisperASR.transcribe` passes the language hint through `normalize_lang_hint` (`asr.py`): lowercase primary subtag (`zh-Hans` -> `zh`, `en-US` -> `en`, a few legacy aliases such as `iw` -> `he`), `None` (auto-detect) when not in `WHISPER_LANGUAGES`. Never hand a raw `Post.lang` to a Whisper backend.
- `WhisperASR` and `PaddleOCRBackend` are shared across the Runner's concurrent extractions (concurrency 2 via `asyncio.to_thread`), so each serialises model or engine construction and inference behind a per-instance `threading.Lock` (`WhisperASR` takes it after the sidecar check). Any new heavy backend must do the same.
- Fakes read sidecars: `<media>.transcript.json`, `<image>.ocr.json`. Real backends honour the transcript sidecar too. A corrupt sidecar raises. Formats: `<media>.transcript.json` = `{"lang"?: str, "segments": [{start_s, end_s, text}]}`; `<image>.ocr.json` = JSON list of strings.
- `FfmpegFrames`: the scene pass runs with `check=False` and tolerates any non-zero exit when no scene files were written (ffmpeg returns 234 for no scene changes); the hook pass still raises. Hook frame first. `PNG_1X1` (used by `FakeFrames`) is a valid 1x1 PNG.
- `extract_evidence(post, paths, asr, ocr, frames)` writes `Evidence` to `paths.evidence_json(post.id)`. It assumes one video per post (frames share one `frames/` dir). Keyframes are run-relative paths `media/<safe_id>/frames/<name>`, hook frame first, at most 8.
- A failing ASR, OCR or frame step is caught and logged as `evidence_step_failed`; only that section is left empty and the post still gets evidence.
- Evidence JSON is written `exclude_none` via temp file then replace (optional means absent).
- `extract_evidence` also writes `media/<safe_id>/thumb.jpg` (256px wide, Pillow) from the first keyframe or first image; plan 03 serves it at `GET /api/runs/{id}/media/{post_id}/thumb.jpg`. Never re-written if present.
- `packet.build_metadata_state` (pass one) and `packet.build_state` (pass two) are the only places that assemble Jev state; `state_json` serialises it. `MAX_STATE_TOKENS = 28000`, measured on the serialised state; `estimate_tokens` counts CJK characters as one token each. Truncation order is fixed: comments (sample, then top_terms), OCR from the end, transcript tail (whole segments, then within the head segment), and only then caption, hashtags, title. If the brief plus the post block (id, platform, kind, any remaining post text) still exceeds the cap after all truncation, `packet.over_cap` is logged and the state is returned anyway.
- `Evidence.truncated` is `False` at extraction; the Runner sets it from `build_state`.
- Helpers: `ocr_lang_for_post` (zh to `ch`, else `en`), `read_sidecar_transcript` (`asr.py`), `write_thumbnail`, `resolve_media`, `run_relative` (`extract.py`).
- `evidence/` never imports from `adapters/`.

## judge/

Turns rubric packs into TypeSafe Jev requests and Jev answers into `JudgeAnswer`s.

- `rubric.py` owns the conversion between pack questions and `typesafe_sdk` primitives. `to_typesafe` maps `choice` to `Choice(instructions, criteria=dict)`, `score` to `Score(instructions, criteria=list)` (level n is list index n, from 0), `noul` to `Noul(instructions)`.
- `from_typesafe(question_id, question, response)` reads `response.choices`, `response.scores` or `response.nouls` (the `SystemOneResponse` cached views). `JudgeAnswer.value` is the label for choice, the fractional score for score, the yes-probability for noul. Score `legend` and `probabilities` keys are the SDK's integer levels as strings (`"0"` is the lowest level). Noul answers carry no `confidence` and no `probabilities`.
- `find_pack(name, rubrics_dir)` reads `<rubrics_dir>/<name>.yaml` and raises `PackNotFound` for a missing file or a name that is not a plain file stem (letters, digits, `.`, `_`, `-`).
- `questions_for_pass`: `pass_one` returns the `metadata_pass` questions in that order; `pass_two` returns every question.
- `with_persona_criteria(pack, criteria)` returns a deep copy with `persona_fit` replaced by a validated 5-level `ScoreQuestion`; the input pack is never mutated.
- `base.py`: `Judge.judge(post_id, pass_name, state, questions, model) -> JudgeResult`. A failed Jev call (client construction, the request once retries are spent, or a missing or malformed answer) surfaces as `JudgeFailed(post_id, attempts, cause)`. Caller errors (an unsupported question type, an unknown `pass_name`) raise as they are. `cost_usd(input_tokens)` prices input tokens at `JEV_USD_PER_MILLION_INPUT = 0.042`.
- `TypeSafeJudge` sends every question for one post in ONE `AsyncTypeSafeClient.system_one(state=..., questions=..., model=...)` call and fills `JudgeResult.model`/`input_tokens` from the response, `latency_ms` from the successful attempt. `state` is the packet dict, not `state_json` output: the SDK encodes it compact with non-ASCII literal, so the wire size matches the `packet` token estimate; a string would be sent as text state.
- Retries are split. `TypeSafeJudge` owns 429 and 529: status 429 or 529 (`status_code`, or the SDK's `status`), or an exception class name containing `ratelimit` or `overloaded`. Backoff is `0.5 s * 2^(n-1)` capped at 8 s plus up to 0.1 s jitter, or the server's `retry_after_ms` when longer (capped at 30 s), through the injected `sleeper`. `max_retries` counts attempts in total (5 means at most 5), unlike the SDK's `RetryPolicy.max_retries`; then `JudgeFailed`.
- The default client keeps the SDK's own retries for connection errors, timeouts and 408/5xx with 429 and 529 removed (`SDK_RETRY`: SDK defaults, 2 retries, 30 s budget). They run inside one of our attempts, so a network blip or a 503 never fails a post on its own. Anything the SDK gives up on that is not 429/529, and a 200 with a missing or malformed answer, raise `JudgeFailed` at once.
- `asyncio.Semaphore(concurrency)` (default 16) bounds in-flight requests per `TypeSafeJudge`. A post backing off keeps its slot; other posts proceed in the rest (`test_one_post_rate_limited_others_proceed`). The client is built lazily from `client_factory` and closed by `aclose()`. Never log the API key; `jev_retry` logs post id, attempt, error class and delay.
- Tests never call the TypeSafe API. `from_typesafe` tests use hand-built response objects; `TypeSafeJudge` tests use a fake client returning real `SystemOneResponse`s, plus the real SDK client over `httpx2.MockTransport`.
- `RecordedJudge(fixture_dir)` reads `<fixture_dir>/judge/<safe_post_filename(post_id)>.<pass_name>.json`, filters answers to the questions asked, records `calls: list[(post_id, pass_name)]`, raises `FixtureMissing(FileNotFoundError)`. Fixtures (five posts x two passes) come from `tests/fixtures/judge/make_fixtures.py`, which reads labels, levels and legends from `creator-hooks-v1` and emits `from_typesafe`-shaped answers; rerun it after a pack change (a test compares committed files to its output).
