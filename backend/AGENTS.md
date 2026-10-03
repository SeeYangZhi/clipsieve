# backend/ — AGENTS.md

Python package `clipsieve`. Owns the whole pipeline: config, store, event log, adapters, evidence, judge, select, explain, API, CLI.

## Contract

- Python 3.12 only. `uv` for everything: `uv sync`, `uv run pytest`, `uv add`.
- `clipsieve/models.py` is GENERATED from `packages/schema/`. Never edit it. Run `bun run schema` at the repo root after changing a schema.
- Logging via `clipsieve.logging.get_logger(__name__)`. No `print()`.
- Config via `clipsieve.config.get_settings()`. Never read `os.environ` elsewhere. Nothing depends on cwd: `.env` is read from `REPO_ROOT/.env`, then `./.env` (the cwd file wins), and a relative `CLIPSIEVE_DATA_DIR` resolves against `REPO_ROOT`; absolute paths are kept as given.
- `CLIPSIEVE_FIXTURE_DIR` (`clipsieve_fixture_dir`) is for tests, fake mode and the Playwright flow only. A blank value means unset (not the cwd); a relative one resolves against `REPO_ROOT`.
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
| `clipsieve/adapters/` | `Adapter` protocol, `registry`, `local_import`, `youtube`, `ytdlp_client`, `vtt`, `fixture` |
| `clipsieve/evidence/` | `asr`, `ocr`, `frames`, `comments`, `packet`, `extract` |
| `clipsieve/judge/rubric.py` | rubric pack loading, per-pass question selection, TypeSafe primitive conversion, persona criteria |
| `clipsieve/judge/base.py` | `Judge` protocol, `JudgeFailed`, Jev pricing (`cost_usd`) |
| `clipsieve/judge/typesafe_client.py` | `TypeSafeJudge`: one batched, concurrency-bounded, retrying Jev request per post |
| `clipsieve/judge/recorded.py` | `RecordedJudge` fake replaying `tests/fixtures/judge/*.json`, `FixtureMissing` |
| `clipsieve/select/scoring.py` | Pure scoring: `normalize_score`, `answer_confidence`, `composite`, `passes_hard_filters`, `needs_review` |
| `clipsieve/select/quotas.py` | `violates_quota`: diversity cap per choice label, at least one per label |
| `clipsieve/select/select.py` | `Selection` model; `select()` (hard filter, rank by composite, quotas; review posts skip the shortlist; dropped reasons `hard_filter`/`quota`/`not_selected`) and `pass_one_keep()` (top fraction, ceil, min one, metadata questions only) |
| `clipsieve/explain/base.py` | `ExplainBackend` protocol, `ExplainPacket`, `PlanRequest`, `RubricPackSummary`, `ExplainError`, `validate_report_citations`, `cli_payload`, `get_backend`, `PROMPTS_DIR` |
| `clipsieve/explain/prompts/` | `plan.md`, `explain.md`: system prompts for the `claude -p` backend |
| `clipsieve/explain/fake.py` | `FakeExplainBackend` replaying `tests/fixtures/explain/plan.json` and `report.json` |
| `clipsieve/explain/claude_cli.py` | `ClaudeCliBackend`: `claude -p` with structured output, one retry on a schema failure or an unknown citation; `PLAN_TASK`, `EXPLAIN_TASK` |
| `clipsieve/explain/claude_api.py` | `ClaudeApiBackend` stub: both methods raise `NotImplementedError` (v0.2 follow-up) |
| `clipsieve/planner/plan.py` | `build_plan`, `pack_summaries`, `default_lang`: brief to approvable `Plan` through an `ExplainBackend` |
| `clipsieve/pipeline/state.py` | `RunState` (`pass_one_kept`, `pass_one_dropped`, `judge_failed`, `extracted`) in `<run>/state.json`; `load_state`, `save_state` |
| `clipsieve/pipeline/runner.py` | `Runner` (`plan`, `approve`, `run`, `pause`, `resume_flag`, `reselect`), `STAGE_ORDER`, `RunPaused`, `post_state` |
| `clipsieve/api/context.py` | `AppContext` (dataclass), `build_context`, `set_context`, `get_context`, `RUBRICS_DIR_DEFAULT`, `DEFAULT_FIXTURE_DIR` |
| `clipsieve/api/runs.py` | Run lifecycle routes, posts view, report, reselect; `CreateRunBody`, `ReselectBody`, `PostView`, `PostsPage`, `RunWithPlan`; background `_plan` / `_drive` |
| `clipsieve/api/events.py` | `GET /runs/{id}/events` SSE, `format_sse` |
| `clipsieve/api/meta.py` | `GET /adapters`, `GET /rubrics`, `GET /runs/{id}/media/{post_id}/{filename}` |
| `clipsieve/app.py` | `create_app(ctx=None)`, module-level `app` for `uvicorn clipsieve.app:app` |
| `tests/fixtures/evidence/<safe_id>/` | Fixture media plus sidecars that `FixtureAdapter.fetch_media` copies; with the fakes they reproduce `tests/fixtures/evidence/<safe_id>.json` |
| `tests/fixtures/claude-shim/claude` | Test-only bash stand-in for the `claude` binary (executable, mode 100755) |

Later tasks add `cli.py` and extend this table.

## planner/

Turns a brief into a `Plan` (not yet approved: `approved_at` is `None`).

- `build_plan(run_id, brief_text, platforms, quantities, rubric_pack, language_hint, backend, rubrics_dir)` sends the backend a seed brief (empty topic/audience/persona) plus `pack_summaries(rubrics_dir)` and the ticked platforms, then enforces invariants in code. The planner owns `run_id`, `quantities` (the run's own; a ticked platform without one raises `ValueError`), `rubric_pack` (the user's choice, resolved with `find_pack`, so an unknown pack raises `PackNotFound`), `brief.text` and `brief.language_hint`. The backend fills topic, audience, persona, queries, persona criteria.
- Queries: only ticked platforms; an empty `lang` becomes `default_lang` (`xiaohongshu`/`douyin`/`bilibili` -> `zh`, else hint or `en`), a non-empty one is kept. A ticked non-`local` platform with no query gets one from `brief.topic` (else the brief text). `local` is never invented: its query is a folder or CSV path, so without a backend-given path it has no query.
- `persona_fit_criteria` must be five non-blank strings; otherwise the pack's own `persona_fit` criteria are used (logs `plan_persona_criteria_fallback`), and `ExplainError` is raised if the pack cannot supply five.

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
- `fixture` (`FixtureAdapter(fixture_dir, data_dir)`, platform `local`): `search` ignores queries and yields the five `posts/*.json` in id order up to `limit`, copying `raw/<safe_id>.json` to `incoming/local/`. `fetch_media` copies `evidence/<safe_id>/` (including `frames/` OCR sidecars) into `dest`, keeping existing files; media named `video.mp4` / `img_NN.jpg` (NN = media position), `local_path` stays `None` when the fixture has no file. `registry.load_adapters` puts it in place of `local` (over any entry point) only when `clipsieve_fixture_dir` is set.
- `youtube`: live, upcoming and post-live videos are rejected. Shorts filter is duration < 180 s; a missing duration at the full-info stage means "not a Short". The flat yt-dlp search asks for `SEARCH_OVERFETCH` (3) times the remaining count, since long videos are dropped after it; `search` still stops at the limit before fetching another info. Optional Data API key is sent in the `x-goog-api-key` header. Downloads are capped at 200 MB.
- `vtt.py`: tags are stripped, then character references are unescaped; the cue split tolerates YouTube's `" "` placeholder lines.
- `adapters/` never imports from `evidence/`.
- Every adapter passes `tests/adapters/contract.py::run_adapter_contract` against a recorded fixture. The helper checks unique post ids and a `^[0-9a-f]{64}$` `creator_hash`, relocates every raw file and rewrites `raw_ref` exactly as the Runner does, then calls `fetch_media` twice and requires dest-relative `local_path`s. Tests never hit the network: yt-dlp is behind `YtDlpClient` with `FakeYtDlpClient`; HTTP uses `httpx.MockTransport`.

## pipeline/

`Runner` drives one run through its stages and is the only event writer for that run in the process. One `run()` at a time per Runner.

- Constructor: `Runner(run_id, settings, repo, adapters, judge, explain, asr, ocr, frames, rubrics_dir)`. Paths come from `repo.paths(run_id)`. `asr`/`ocr`/`frames` are one shared instance each for the whole run (B.13). A fresh run's log starts with `run_created`, emitted by the constructor when the log is empty, so build the Runner right after `repo.create_run` and never emit `run_created` elsewhere.
- `STAGE_ORDER = planning, collecting, pass_one, extracting, pass_two, selecting, explaining, done`. `Run.stage` is always assigned a `Stage` member; every change emits `stage_changed {"from", "to"}`.
- `plan()` (stage `planning` only) calls `build_plan` and emits `plan_ready`. `approve(plan)` (stage `planning` only, else `RuntimeError`) validates the pack, stamps `run_id` and `approved_at`, copies brief, rubric pack and quantities onto the run, emits `plan_approved`, then moves to `collecting`. `run()` before approval raises `RuntimeError`; on a `done` or `failed` run it returns at once.
- Success order: `run_created`, `plan_ready`, `plan_approved`, `post_collected` x N, `pass_one_judged` x N, `evidence_ready` x kept, `judged` x kept, `selected`, `explained`, `done {counters}` last (each stage preceded by its `stage_changed`).
- Collecting pulls posts one at a time from `adapter.search` in a thread. Each post's raw file moves from `incoming/<platform>/` to `raw/<safe_id>.json` and `raw_ref` becomes that run-relative path BEFORE the post is stored and before any `fetch_media` (B.1/B.10). `post_collected` carries the post with no media paths. Posts already stored are skipped when a resumed collection re-runs the search. Missing adapter, failed healthcheck, failed search or a post that cannot be stored: recoverable `error` `where: adapter.<platform>`; a platform stops after 10+ posts with over 20% failing.
- Pass one: one Jev request per post with the pass's questions (`questions_for_pass`), pack = `with_persona_criteria(find_pack(plan.rubric_pack), plan.persona_fit_criteria)`, model `pack.jev_model`, at most `JUDGE_CONCURRENCY` (16) in flight. The keep set (`pass_one_keep`) is decided only after every post is judged or failed, then `pass_one_judged {judge, kept, composite}` is emitted per post and `RunState` records kept and dropped.
- Extracting (kept posts, `EXTRACT_CONCURRENCY` 2, `asyncio.to_thread`): `fetch_media` and `extract_evidence` in separate try blocks. A `fetch_media` failure (including `MediaDownloadError`) is a recoverable `adapter.<platform>` error and extraction still runs on whatever media exists (C.6); an extraction failure is `evidence.extract` and the post gets empty evidence. Then `evidence_ready` and `RunState.extracted`.
- Pass two: `build_state(brief, post, evidence)`; when it reports truncation the evidence is re-saved with `truncated: true` (B.3). `judged {judge, composite}` per post. A `JudgeFailed` in either pass is a recoverable `error` `where: judge.pass_one|judge.pass_two` with `post_id`, recorded in `RunState.judge_failed`; that post is excluded from later stages, selection and `post_state` (`judge_failed`), and the run continues. Any other judge exception propagates.
- Selecting: `select` over pass-two results minus `judge_failed`; `selected`. `reselect(weights_override)` re-runs it on stored results (no Jev calls, no new report, elapsed unchanged) and emits another `selected`; it needs a first selection.
- Explaining: the packet holds the shortlist's posts, evidence, pass-two results and keyframes plus choice-label counts per question over all pass-two results. The Runner overwrites `report.run_id`, then `validate_report_citations` against the shortlist. `ExplainError`, any other backend exception, or unknown cited ids fail the run: `error` (`where: explain`, `recoverable: false`, stage `explaining`) FIRST, then `run.stage = failed`, `run.error` set, and `stage_changed {from: explaining, to: failed}` as the LAST event (E.8 as amended). The selection stays saved; no report is written; `run()` does not resume a failed run.
- Resume: `run()` again continues from the saved stage. Per-post idempotency: a post with a judge result file is not re-judged; a post in `RunState.extracted` is not re-extracted; pass one is not redone once its keep set is saved. Counters `collected`, `pass_one_kept`, `judged`, `jev_input_tokens`, `jev_cost_usd` are recounted from the run's files at the start of `run()`. A crash in one per-post task lets in-flight posts finish and record, starts no new ones, then re-raises with the stage unchanged.
- Pause: `pause()` is cooperative. In-flight posts finish, no new post or stage starts; `run()` sets `run.paused = True` and returns normally. To resume: clear `run.paused`, call `resume_flag()`, then `run()`.
- Counters: `jev_cost_usd = round(cost_usd(jev_input_tokens), 6)`; `elapsed_s` is `created_at` to now, rounded to 0.1 s; `errors` counts every `error` event.
- `post_state(post_id, state, selection, judged_pass_two)` returns `judge_failed | dropped_pass_one | shortlisted | review | judged | collected`, in that precedence.
- Tests (`tests/pipeline/`) run the whole pipeline on `FixtureAdapter`, `RecordedJudge`, `FakeExplainBackend` and the evidence fakes; no network.

## api/

FastAPI under `/api`. The binding HTTP contract is the overview plan's; this is how it is met.

- Routes: `POST /runs` (201, planning starts in the background), `GET /runs` (newest first), `GET /runs/{id}` (`{run, plan}`), `PUT /runs/{id}/plan`, `POST /runs/{id}/approve|pause|resume`, `GET /runs/{id}/events?after=N` (SSE), `GET /runs/{id}/posts?offset&limit` (`{items: PostView[], total}`), `GET /runs/{id}/report`, `POST /runs/{id}/reselect` (`{weights}` -> `Selection`), `GET /adapters`, `GET /rubrics`, `GET /runs/{id}/media/{post_id}/{filename}`, `GET /health` (`{status, backend}`).
- Errors are always `{"detail": str}`, request validation included (`app._on_validation_error`). 404 unknown run or media, missing report; 409 edit or approve after approval, approve before a plan exists or while the planner runs, reselect with no selection or while a pipeline task runs; 422 unknown platform or rubric pack, bad body, a plan whose pack or persona criteria do not validate.
- Every route sets `response_model_exclude_none=True`: optional fields are absent, never `null`. The one `null` is `RunWithPlan.plan` before a plan exists (contract `plan|null`; a wrap serializer keeps the key).
- `POST /runs` never emits `run_created`: it builds the run's `Runner` (`ctx.runner_for`), whose constructor does.
- `build_context(settings)`: fake mode is `clipsieve_explain_backend == "fake"`; with `clipsieve_fixture_dir` unset it becomes `DEFAULT_FIXTURE_DIR` (`backend/tests/fixtures`), so `local` is `FixtureAdapter`, judge `RecordedJudge`, ASR/OCR/frames fakes, explain `FakeExplainBackend`. Real mode: `TypeSafeJudge(typesafe_api_key)`, `WhisperASR`, `PaddleOCRBackend`, `FfmpegFrames` (imported lazily), `get_backend(settings)`. One shared instance each per process (B.13). It calls `ensure_creator_salt` once and puts the salt on `ctx.settings` before `load_adapters` (A.12).
- `create_app(ctx)` installs `ctx` with `set_context`; without one, `get_context()` builds it from `get_settings()` on the first request, so importing `clipsieve.app` is cheap. The lifespan calls `configure_logging()` (servers only; in-process test transports skip lifespan).
- Background work: `asyncio.create_task`, the latest task per run in `ctx.tasks[run_id]` (`ctx.busy(run_id)`), a done-callback logs `run_task_failed` with the traceback or `run_task_cancelled`. `_plan` turns a planning failure into a logged `run_plan_failed` plus a recoverable `error` event (`where: planner`), counted in `counters.errors`; the run stays in `planning` and a hand-written plan can still be PUT.
- `_drive` runs `runner.run()` under `ctx.lock_for(run_id)` (one `run()` per Runner). Pause adds the run to `ctx.pause_requests` and calls `runner.pause()`; resume clears both, clears `run.paused` and starts `_drive` unless a task is running. When `run()` returns paused with no pause outstanding (a late pause won, Task 9), `_drive` clears `paused` and runs again (at most `MAX_LATE_PAUSE_RERUNS`).
- Posts view: `PostView {post, judge: {pass_name: JudgeResult}, composite?, state}`; `composite` is the selection score when there is one (it follows reselect weights), else the pass-two composite, absent otherwise; `state` from `post_state`.
- SSE: `id: <seq>`, `event: run_event`, `data: <RunEvent JSON>`; the data line is the `events.jsonl` line byte for byte (`by_alias`, `exclude_none`, CJK literal). The stream holds exactly the events with `seq > max(after, Last-Event-ID)`. A finished run (a `done` event, or any event with stage `failed`) is served whole from that point and the stream closes, including events after `done` such as a reselect's `selected`; a live run is followed with `follow_events` until its first terminal event.
- Media: `post_id` arrives URL-decoded (`local%3Afx-001`). `filename` may be a sub-path (`frames/<name>`). 404 unless the post's media dir sits directly under `<run>/media/` and the resolved file is inside it, so `..`, absolute paths and a post id of `..` never escape.
- Tests (`tests/api/`) drive the app in fake mode with `httpx.AsyncClient(ASGITransport)`; settings come from kwargs with `_env_file=None`. SSE tests read only streams that end (a run that reaches `done`); the `client` fixture waits for background tasks before the loop closes.

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

## explain/

Plans a run from a brief and explains a shortlist. One interface, three backends.

- Backends implement `ExplainBackend` (`explain/base.py`): `plan(brief, packs, platforms) -> Plan` and `explain(packet: ExplainPacket) -> Report`. `get_backend(settings, fixture_dir=None)` picks one from `clipsieve_explain_backend`: `fake` (needs `fixture_dir`, else `ExplainError`), `claude_cli` (`explain/claude_cli.py`), `claude_api` (stub; both methods raise `NotImplementedError`).
- Backends never know the run id. They return `Plan.run_id` / `Report.run_id` as they have them (`"FIXTURE"` for the fake, `"PENDING"` or model output for the CLI) and the caller overwrites both. `PlanRequest` carries no quantities, so the caller also sets `Plan.quantities` from the run; the plan prompt writes placeholder values.
- `cli_payload(mode, body)` returns JSON text: `body` dumped `mode="json", exclude_none=True` (optional means absent) plus a top-level `"mode": "plan" | "explain"`, the only key not in the body's model. `ensure_ascii=False` keeps CJK literal. A body with its own `mode` key raises `ExplainError`.
- A report may cite only ids in `packet.posts`. `validate_report_citations(report, known_post_ids)` returns the sorted, unique unknown ids cited in `patterns[].post_ids`, `clips[].post_id`, `gaps[].post_ids` and `concepts[].inspired_by_post_ids`.
- `prompts/plan.md` and `prompts/explain.md` are system prompts: task, output rules, citation rules. They never hold weights, thresholds or quotas (`test_prompts_exist_cite_only_given_posts_and_carry_no_policy` guards the words); policy stays in rubric YAML and `select/`. A `local` query is a folder or `.csv` path, not a search phrase.
- `FakeExplainBackend(fixture_dir)` reads `<fixture_dir>/explain/plan.json` and `report.json` on every call and appends `"plan"` / `"explain"` to `calls`. `plan` returns the fixture plan (`quantities` includes `local: 5`) with the given brief when it has a `topic`, else the fixture brief. `explain` re-points every citation at `packet.posts` (cycled, deduplicated), writes one clip per packet post in packet order, and returns no patterns, clips, gaps or concepts for an empty packet.
- Fixtures `tests/fixtures/explain/plan.json` and `report.json` are a valid `Plan` and `Report` with `run_id` `"FIXTURE"`, five `persona_fit_criteria`, citations only among `local:fx-001..005`, and no `null`s (a test compares each file to its `exclude_none` dump).
- `ClaudeCliBackend(bin, max_budget_usd, model="opus", effort="high", timeout_s=900)` runs one `subprocess.run` per attempt (`input=` the `cli_payload` JSON, `timeout=timeout_s`, `check=False`) with exactly this argv, pinned by `test_argv_is_exactly_the_contract`: `[bin, "-p", "--model", model, "--effort", effort, "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence", "--system-prompt-file", prompts/<mode>.md, "--output-format", "json", "--json-schema", <Plan or Report JSON Schema>, "--max-budget-usd", str(max_budget_usd), <task line>]`. Never `--bare`: it drops the user's OAuth login.
- Stdout is one JSON envelope; the backend returns its `structured_output` (else `result` parsed as JSON). A missing or unrunnable binary, a timeout, a non-zero exit, non-JSON or non-object stdout, `is_error: true` (message carries `result`, `errors` or `subtype`) or no structured output raise `ExplainError`; stderr is quoted as a tail of at most 500 characters. Logs `claude_cli_done` (mode, cost, duration) and `claude_cli_retry`; never the payload.
- Retry: a `Plan`/`Report` schema failure, or a report citing an id outside `packet.posts`, is retried exactly once with `PLAN_TASK`/`EXPLAIN_TASK` plus one sentence naming the problem (`loc: msg` errors without input values, or the unknown ids). A second failure raises `ExplainError` (`... failed schema validation ...` or `... unknown post ids ...`).
- The shim `tests/fixtures/claude-shim/claude` (bash, needs `python3`) ignores its arguments and answers `explain/plan.json` when stdin holds `"mode": "plan"`, else `explain/report.json`, as `{"is_error": false, "structured_output": ..., "total_cost_usd": 0.0}`. Env: `CLIPSIEVE_SHIM_STATE=<path>` writes the argv, one per line, to `<path>.argv` on every call; with `CLIPSIEVE_SHIM_BAD_FIRST=1` the first explain call (while `<path>` is absent) cites `local:does-not-exist` and creates `<path>`; `CLIPSIEVE_SHIM_FAIL=1` prints `{"is_error": true, "result": "shim failure", ...}`. Keep it committed executable.
- Tests never run the real `claude` binary or touch the network: they pass `bin=<shim path>`, or replace `subprocess.run` with a scripted fake for timeout and exit-code paths.
