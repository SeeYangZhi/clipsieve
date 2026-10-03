# clipsieve v0.1 Design

Date: 2026-10-03
Status: approved in conversation, awaiting written review
Owner: Yang Zhi (SeeYangZhi)

## 1. Purpose

clipsieve turns a one-sentence research brief into a report on what works in a niche of short-form social content. It collects posts from the platforms the user ticks, converts each post into structured text evidence, scores every post against a typed rubric with Jev, keeps a small diverse shortlist, and has Claude explain the patterns and draft concepts the user can act on.

The motivating brief: "I am starting social accounts as a Singaporean moving to Shanghai, vlog style. Find such videos and analyse hooks and styles."

### 1.1 Users

1. The author, researching their own content persona. First and only user for v0.1.
2. Creators and marketers running the same loop on their niche. Served by the same flows, not by extra features.
3. Open-source contributors adding platform adapters and rubric packs. Served by the adapter interface, the schema package and the DOX docs.

### 1.2 Success criteria for v0.1

- One real brief, run against YouTube Shorts and Xiaohongshu with the default 500 posts per platform, produces a report the author acts on.
- Jev spend for that run is under USD 2. Claude spend is zero on the `claude -p` backend.
- A finished run replays in the dashboard at true speed with no network access.
- Every claim in the report cites post ids that exist in the run.
- A contributor can add an import-style adapter by implementing one interface and passing the adapter contract test, without touching core code.

### 1.3 Non-goals for v0.1

- Douyin, Bilibili, TikTok, Instagram, X, LinkedIn adapters.
- Vision-model captioning of frames.
- A Jev-driven browser navigator for unknown page states.
- Hosted mode, accounts, sharing, multi-user.
- A rubric pack registry or marketplace.
- Predicting virality. The tool explains what already worked.

## 2. Product flow

1. **Brief.** Home page. Free-text brief, platform checkboxes (YouTube, Xiaohongshu, Local import), per-platform quantity defaulting to 500, optional language hint, rubric pack selector defaulting to `creator-hooks-v1`. Submit creates a Run in state `planning`.
2. **Plan.** The explain backend turns the brief into a `Plan`: search queries per platform in the platform's language, the rubric pack to use, and a `persona_fit` Score question written from the brief. The plan page shows all of it editable. Confirming moves the run to `collecting`.
3. **Collect.** Each ticked adapter runs its queries up to the quantity. Each `Post` is persisted with its raw payload and emitted as a `post_collected` event. Media is not downloaded yet.
4. **Pass one.** Jev scores every post on the pack's `metadata_pass` questions using caption, hashtags, comments and metrics only. Posts below the pack's `pass_one_keep` threshold are marked `dropped_pass_one`. Default keeps roughly the top 30 percent.
5. **Extract.** For survivors only: download media, transcribe speech, OCR keyframes and note images, summarise comments. Emits `evidence_ready`.
6. **Pass two.** Jev scores survivors on the full pack. Emits `judged` with raw answers.
7. **Select.** Code computes composite scores, applies diversity quotas, routes low-confidence posts to the review bucket, emits `selected` for the shortlist.
8. **Explain.** The explain backend receives the shortlist evidence packet and returns a `Report`. Emits `explained`, then `done`.
9. **Report.** Report page shows patterns, per-clip explanations, gaps and concepts, each linked to the cited posts with their evidence.
10. **Replay.** Any finished or failed run replays from its event log at original timing.

A run can be paused and resumed at any stage boundary. Resume reads the event log, rebuilds state, and continues from the first incomplete stage.

## 3. Architecture

Python owns the pipeline. The frontend is a thin client over a REST API and a server-sent event stream.

```text
frontend (Next.js) --/api/* rewrite--> backend (FastAPI)
                                          |-- planner        -> Plan
                                          |-- adapters       -> Post
                                          |-- evidence       -> Evidence
                                          |-- judge (Jev)    -> JudgeResult
                                          |-- select         -> Shortlist
                                          |-- explain        -> Report
                                          |-- events (JSONL) -> SSE
                                          `-- store (SQLite + files)
```

### 3.1 Repository layout

```text
clipsieve/
  AGENTS.md  CLAUDE.md  README.md  LICENSE  package.json  biome.jsonc  .env.example
  backend/
    AGENTS.md  pyproject.toml
    clipsieve/
      app.py            FastAPI app, routers, SSE
      cli.py            `sieve` command: run, replay, eval
      config.py         Pydantic Settings
      store/            SQLite repositories, file layout
      events/           RunEvent writer and reader
      planner/          brief -> Plan via explain backend
      adapters/         base.py, local_import.py, youtube.py, registry.py
      evidence/         asr.py, ocr.py, frames.py, comments.py, packet.py
      judge/            typesafe_client.py, rubric.py, pass_one.py, pass_two.py
      select/           scoring.py, quotas.py, review.py
      explain/          base.py, claude_cli.py, claude_api.py (stub), schema.py
    tests/
  frontend/
    AGENTS.md  package.json  next.config.ts  biome.jsonc
    src/app/              routes: /, /runs/[id]/plan, /runs/[id], /runs/[id]/report, /runs/[id]/replay
    src/components/       dashboard regions, brief form, plan editor
    src/lib/              api client, SSE hook, generated types import
  packages/schema/
    AGENTS.md
    schemas/*.json        Post, Evidence, RunEvent, RubricPack, Plan, Report, JudgeResult, Run
    generate.py           -> backend/clipsieve/models.py
    generate.ts           -> frontend/src/lib/types.ts
  rubrics/
    AGENTS.md
    creator-hooks-v1.yaml
    creator-hooks-v1.calibration.md
  contrib/adapter-xhs-mediacrawler/
    AGENTS.md  README.md  pyproject.toml
    clipsieve_xhs/adapter.py, mapping.py
  evals/
    golden/en-100.jsonl  golden/zh-100.jsonl
    score.py
  docs/superpowers/specs/  docs/superpowers/plans/
```

### 3.2 Toolchain

| Concern | Choice | Reason |
|---|---|---|
| Python | 3.12 via uv | PaddleOCR and MediaCrawler do not support 3.13+ |
| JS | Bun 1.3, Next.js 16, React 19, Tailwind 4, shadcn, ultracite | Matches the author's other repos; newest stable versions |
| Store | SQLite via SQLModel, files under `data/runs/<run_id>/` | Local-first, zero setup |
| Logging | structlog | Repo convention |
| Lint | ruff, Biome via ultracite | Repo convention |
| Dev | root `bun run dev` starts both; `bun run check` runs lint, typecheck, tests, schema drift | One command for contributors |

### 3.3 Data on disk

```text
data/runs/<run_id>/
  run.json                 Run metadata and state
  plan.json                Approved Plan
  events.jsonl             Every RunEvent, append only
  posts/<post_id>.json     Normalised Post
  raw/<post_id>.<ext>      Untouched platform payload
  media/<post_id>/         Downloaded video, images, keyframes
  evidence/<post_id>.json  Evidence
  judge/<post_id>.json     JudgeResult per pass
  report.json              Report
```

SQLite holds an index over the same facts for queries. Files are canonical. Deleting the SQLite file and re-indexing from the run folder must produce the same state.

## 4. Data contracts

All eight schemas live in `packages/schema/schemas/` as JSON Schema draft 2020-12. Generation produces Pydantic v2 models and TypeScript types. CI fails if generated files differ from committed ones.

### 4.1 Post

| Field | Type | Notes |
|---|---|---|
| id | string | `<platform>:<platform_id>` |
| platform | enum | `youtube`, `xiaohongshu`, `local` |
| url | string | Canonical public URL, or `file://` for local |
| creator_hash | string | SHA-256 of platform creator id with a per-install salt |
| creator_display | string, optional | Display name only, no handle |
| posted_at | datetime, optional | |
| kind | enum | `video`, `image_note` |
| text | object | `title`, `caption`, `hashtags[]` |
| media | array | `{type: video or image, local_path, duration_s or index, width, height}` |
| metrics | object | `views`, `likes`, `comments`, `shares`, `saves`, each optional integer |
| comments | array | `{text, likes}`, capped at 50 by the adapter |
| lang | string, optional | BCP-47, detected or declared |
| raw_ref | string | Relative path to the raw payload |
| collected_at | datetime | |

### 4.2 Evidence

| Field | Type | Notes |
|---|---|---|
| post_id | string | |
| transcript | array | `{start_s, end_s, text}` segments, empty for image notes |
| transcript_lang | string, optional | |
| ocr | array | `{source: keyframe or image, index, text}` |
| keyframes | array | Relative paths, max 8 |
| comment_summary | object | `{count, top_terms[], sample[]}` built in code, no model |
| token_estimate | integer | Chars divided by 3, used for the 32k Jev cap |
| truncated | boolean | True if the packet was cut to fit |

### 4.3 RunEvent

| Field | Type | Notes |
|---|---|---|
| run_id | string | |
| seq | integer | Monotonic per run |
| ts | datetime | Wall clock at emit |
| type | enum | `run_created`, `plan_ready`, `plan_approved`, `post_collected`, `pass_one_judged`, `evidence_ready`, `judged`, `selected`, `explained`, `error`, `stage_changed`, `done` |
| stage | enum | `planning`, `collecting`, `pass_one`, `extracting`, `pass_two`, `selecting`, `explaining`, `done`, `failed` |
| payload | object | Type-specific. `judged` carries the full JudgeResult. `error` carries `{where, message, post_id?, recoverable}` |

### 4.4 RubricPack

```yaml
name: creator-hooks-v1
version: 1
jev_model: jev-1.13.0
language_mode: raw            # raw | translate | bilingual, decided by evals
metadata_pass:                # question ids available before media download
  - niche_relevance
  - format_guess
pass_one_keep: 0.30           # fraction kept, applied to composite of metadata_pass
questions:
  hook_type:
    type: choice
    instructions: "Which opening hook does the first sentence or first on-screen text use? See `transcript[0]` and `ocr`."
    criteria:
      curiosity_gap: "Withholds a key fact the viewer wants"
      bold_claim: "Asserts something surprising or contrarian"
      result_first: "Shows or states the outcome before the process"
      problem: "Names a pain the viewer recognises"
      story: "Opens mid-scene or with a personal anchor"
      authority: "Leads with credentials or proof"
      none: "No deliberate hook"
  hook_strength:
    type: score
    instructions: "How likely is the first three seconds to keep the audience described in `brief.audience` watching?"
    criteria:
      - "No hook. Greeting, logo, or slow context."
      - "Topic stated, no reason to keep watching."
      - "Question or claim with some tension."
      - "Specific promise, surprising claim, or visible result in the first sentence."
      - "Immediate pattern interrupt plus a clear stake for this audience."
  format:
    type: choice
    instructions: "Dominant format of the post."
    criteria:
      talking_head: "One person speaking to camera for most of the post"
      vlog_montage: "Cut sequence of real-life scenes, often with voiceover or music"
      screen_demo: "Screen recording or product walkthrough"
      ugc_testimonial: "Casual first-person review or reaction"
      image_carousel: "Multiple still images with text, typical of Xiaohongshu notes"
      meme: "Joke format, template, or trend sound"
      other: "None of the above"
  persona_fit:                 # criteria text is written by the planner from the brief
    type: score
    instructions: "How closely does this creator's situation and voice match `brief.persona`?"
    criteria: ["Unrelated", "Adjacent niche", "Same niche, different voice", "Close match", "Could be the user's own channel"]
  risky_claim:
    type: noul
    instructions: "Does the post make a health, financial, legal or regulated claim without support?"
  niche_relevance:
    type: score
    instructions: "Is this post about `brief.topic`, judging from caption, hashtags and comments?"
    criteria: ["Unrelated", "Mentions in passing", "Partly about it", "Mainly about it", "Entirely about it"]
  format_guess:
    type: choice
    instructions: "Best guess at format from caption and thumbnail text only."
    criteria:
      talking_head: "Caption or thumbnail text suggests a person speaking to camera"
      vlog_montage: "Caption suggests a day-in-the-life or scene sequence"
      image_carousel: "Post is a multi-image note"
      unknown: "Not enough signal from caption and thumbnail"
selection:
  weights: {hook_strength: 0.4, persona_fit: 0.4, niche_relevance: 0.2}
  hard_filters:
    risky_claim_max: 0.5
  review_confidence_below: 0.5
  shortlist_size: 40
  diversity:
    format: {max_share: 0.4}
    hook_type: {max_share: 0.5}
```

Score answers are normalised to 0 to 1 as the position among the pack's levels, first level 0 and last level 1, computed from the returned `score` and `legend` so the formula does not depend on whether the API indexes levels from 0 or 1. Noul answers are probabilities. Choice answers contribute only through diversity quotas and aggregates.

### 4.5 Plan

| Field | Type |
|---|---|
| run_id | string |
| brief | object: `text`, `topic`, `audience`, `persona`, `language_hint` |
| queries | array of `{platform, query, lang}` |
| quantities | object platform to integer |
| rubric_pack | string |
| persona_fit_criteria | array of 5 strings |
| approved_at | datetime, optional |

### 4.6 Report

| Field | Type |
|---|---|
| run_id | string |
| patterns | array of `{title, observation, hypothesis, post_ids[]}` |
| clips | array of `{post_id, why_it_works, hook_quote, weaknesses}` |
| gaps | array of `{title, rationale, post_ids[]}` |
| concepts | array of `{hook, structure, visual, proof, cta, inspired_by_post_ids[]}` |
| caveats | array of strings |

Every `post_ids` entry must exist in the run. The backend validates this and rejects a report that cites unknown ids, emitting an `error` event and retrying once with the invalid ids listed in the prompt.

### 4.7 JudgeResult

| Field | Type | Notes |
|---|---|---|
| post_id | string | |
| pass_name | enum | `pass_one`, `pass_two` |
| model | string | Jev model id as returned |
| input_tokens | integer | |
| latency_ms | integer | |
| answers | map question_id to JudgeAnswer | `{type, value, probabilities?, confidence?, legend?}`; `value` is the label for choice, the fractional score for score, the probability for noul |

### 4.8 Run

| Field | Type | Notes |
|---|---|---|
| id | string | |
| created_at | datetime | |
| stage | enum | Same values as RunEvent.stage |
| brief | Brief | |
| platforms | string[] | |
| quantities | map platform to integer | |
| rubric_pack | string | |
| counters | Counters | `collected, pass_one_kept, judged, shortlisted, review, errors, jev_input_tokens, jev_cost_usd, elapsed_s` |
| paused | boolean | |
| error | string, optional | Set when stage is `failed` |

Exact field shapes for all eight schemas, and the binding Python, HTTP and frontend signatures, are in `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`.

## 5. Adapters

### 5.1 Interface

```python
class Adapter(Protocol):
    platform: str
    def search(self, queries: list[Query], limit: int) -> Iterator[Post]: ...
    def fetch_media(self, post: Post, dest: Path) -> Post: ...
    def healthcheck(self) -> AdapterHealth: ...
```

`search` yields posts without media. `fetch_media` downloads into `dest` and returns the post with `media[].local_path` filled. Adapters are registered by Python entry point group `clipsieve.adapters`. The core discovers them at startup and shows only healthy ones in the brief form.

Adapter contract test, run against every adapter including contrib: a recorded fixture produces at least one valid `Post`, `raw_ref` resolves, `creator_hash` is not the raw id, comments are capped at 50, `fetch_media` is idempotent.

### 5.2 local_import

Reads a folder of video or image files, or a CSV with columns `url, title, caption, views, likes, comments`. Platform is `local`. No network.

### 5.3 youtube

yt-dlp for search (`ytsearchN:`), metadata, auto-captions and download. Captions, when present, seed the transcript and skip ASR. An optional YouTube Data API key improves search recall; without it, yt-dlp search is used. Respects `--max-filesize` of 200 MB and Shorts-only filtering by duration under 180 seconds unless the plan says otherwise.

### 5.4 xhs_mediacrawler (contrib)

A separate uv project in `contrib/adapter-xhs-mediacrawler/`. MediaCrawler is not installable as a package (its `pyproject.toml` has no build system), so the adapter runs a pinned sibling checkout at `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` and refuses to run if the checkout's commit differs from the pinned one. It invokes MediaCrawler as a subprocess in CDP mode against the user's own logged-in Chrome (`--platform xhs --type search --keywords <query> --get_comment --save_data_option jsonl`), with the working directory set to a per-run temp dir so output is isolated, then reads the JSONL output and maps notes and comments to `Post`. Image notes become `kind: image_note` with one `media` entry per image. Video notes get one `media` entry. The adapter downloads images and video itself with httpx.

MediaCrawler is released under its Non-Commercial Learning License 1.1. The contrib README and AGENTS.md quote that licence and its learning-only disclaimer, and state that the user is responsible for compliance with Xiaohongshu's terms and local law. The core repo never imports the adapter. It is listed in the root README as a community adapter.

Healthcheck verifies Chrome is reachable on the configured debugging port and the MediaCrawler checkout is at the pinned commit.

## 6. Evidence pipeline

- **ASR.** mlx-whisper on Apple Silicon, faster-whisper elsewhere, model `large-v3`, language auto-detect, word timestamps on. Skipped when the adapter supplied captions. Output is segments.
- **Keyframes.** ffmpeg scene-change detection, threshold 0.3, capped at 8 frames, plus frame at 0.5 seconds always included since hooks live there.
- **OCR.** PaddleOCR with `lang=ch` when the post language is Chinese, `en` otherwise, run on keyframes and on every image of an image note. Text below 0.6 confidence is dropped.
- **Comments.** Code only: count, top terms by frequency after stop-word removal in the post's language, five sample comments by likes.
- **Packet.** `evidence/packet.py` assembles the Jev state as a JSON object with named fields: `brief`, `post` (text, metrics, kind, lang), `transcript`, `ocr`, `comments`. It truncates in fixed order (comments, then OCR, then transcript tail) to stay under 28,000 estimated tokens, leaving room for the longest question, and sets `truncated`.

Behind interfaces with fakes: `ASR`, `OCR`, `FrameExtractor`.

## 7. Judge and select

### 7.1 Judge

`judge/typesafe_client.py` wraps `AsyncTypeSafeClient.system_one`. One request per post per pass with every question of that pass batched. Concurrency 16, backoff on 429 and 529. The `JudgeResult` stores, per question: the typed answer, the full `probabilities` map, `confidence`, plus request-level `model`, `input_tokens`, `latency_ms`. Cost is computed at USD 0.042 per million input tokens and accumulated on the run.

The client is behind a `Judge` interface with a `RecordedJudge` fake that replays fixture responses by post id.

### 7.2 Select

Pure functions in `select/`:

1. Drop posts failing hard filters.
2. Composite score from pack weights over normalised answers.
3. Mark posts with any weighted question's confidence below `review_confidence_below` as `review`; they are excluded from the shortlist and shown in the review bucket.
4. Greedy fill of the shortlist by composite score, skipping a post when adding it would push any diversity dimension above its `max_share`.
5. Emit `selected` with the ordered shortlist, the review list, and per-post composite scores.

Re-running selection with changed weights uses stored `JudgeResult`s and makes no Jev calls.

### 7.3 Chinese content

Jev's documentation states CJK input is accepted with lower accuracy. Before `creator-hooks-v1` is marked calibrated for Chinese, `evals/score.py` runs the pack over `golden/zh-100.jsonl` in three modes, `raw`, `translate` (state machine-translated to English by the explain backend, cost recorded), and `bilingual` (English criteria with Chinese examples), and reports agreement with human labels per question. The pack's `language_mode` is set to the winner and the numbers go in the calibration file.

## 8. Explain

### 8.1 Interface

```python
class ExplainBackend(Protocol):
    def plan(self, brief: Brief, packs: list[RubricPackSummary]) -> Plan: ...
    def explain(self, packet: ExplainPacket) -> Report: ...
```

`ExplainPacket` contains the brief, the shortlist posts' text and evidence, each post's JudgeResult, the run's aggregate distributions, and keyframe paths. Backends may attach keyframes as images.

### 8.2 claude_cli backend (default)

Invokes the `claude` binary as a subprocess:

```text
claude -p --model opus --effort high
  --tools "" --strict-mcp-config --setting-sources ""
  --no-session-persistence
  --system-prompt-file <prompts/explain.md>
  --output-format json
  --json-schema <Report schema>
  --max-budget-usd <config, default 3>
  "<task line>"
```

with the packet on stdin. Parses the result envelope, requires `is_error == false`, reads `structured_output`, validates against the Report schema and the post-id rule. Verified in this session: without `--strict-mcp-config --setting-sources ""` the prompt is about 65k tokens; with them about 1k, and the prompt cache survives across processes. `--bare` must not be used because it ignores subscription login.

Documented constraint: this backend is for individual use on the user's own Claude subscription. Anyone hosting clipsieve for others must use the API backend.

### 8.3 claude_api backend (stub in v0.1)

Same interface, implementation raises `NotImplemented` with a pointer to the plan. Its contract test is written and marked expected-fail so the packet format is pinned from day one.

### 8.4 Fake

`FakeExplainBackend` returns a canned Plan and Report from fixtures. Used by all frontend and pipeline tests and by the `claude` shim binary placed on PATH in CI.

## 9. Dashboard

### 9.1 Routes

| Route | Purpose |
|---|---|
| `/` | Brief form, recent runs |
| `/runs/[id]/plan` | Editable plan, approve button |
| `/runs/[id]` | Live dashboard |
| `/runs/[id]/report` | Report with citations |
| `/runs/[id]/replay` | Same dashboard driven by the stored log |

### 9.2 Live dashboard regions

1. **Counters.** Collected, pass-one survivors, judged, answers per second, elapsed, Jev cost so far. Answers per second is a client-side rolling window.
2. **Grid.** One tile per collected post, thumbnail when available, dimmed when dropped in pass one, highlighted when shortlisted, outlined when in review.
3. **Current item.** The latest `judged` post: thumbnail, caption, one row per question with the answer label and a bar for confidence (Choice, Score) or probability (Noul), plus composite score.
4. **Aggregates.** Running distributions of `hook_type`, `format`, and `persona_fit` levels, and the review bucket count with a link to a list.

### 9.3 Transport

`GET /api/runs/{id}/events?after=<seq>` streams SSE. The client reconnects with the last seen `seq`. Replay mode fetches the full log and a component re-emits events on `ts` deltas with a speed control. The regions consume one event stream type in both modes.

### 9.4 Internationalisation

All strings through a `t()` helper with `en` and `zh` dictionaries. Language picked from browser locale, switchable in the header.

## 10. API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/runs` | Create run from brief; returns run with state `planning` |
| GET | `/api/runs` | List runs |
| GET | `/api/runs/{id}` | Run, plan, counters |
| PUT | `/api/runs/{id}/plan` | Save edited plan |
| POST | `/api/runs/{id}/approve` | Approve plan, start pipeline |
| POST | `/api/runs/{id}/pause`, `/resume` | Stage-boundary control |
| GET | `/api/runs/{id}/events` | SSE, `after` query param |
| GET | `/api/runs/{id}/posts` | Paged posts with judge results and selection state |
| GET | `/api/runs/{id}/report` | Report |
| POST | `/api/runs/{id}/reselect` | Re-run selection with a weights override, no Jev calls |
| GET | `/api/adapters` | Registered adapters with health |
| GET | `/api/rubrics` | Available packs |

## 11. Configuration and secrets

`.env` only, loaded by Pydantic Settings:

```text
TYPESAFE_API_KEY=
CLIPSIEVE_EXPLAIN_BACKEND=claude_cli      # claude_cli | claude_api | fake
CLIPSIEVE_CLAUDE_BIN=claude
CLIPSIEVE_CLAUDE_MAX_BUDGET_USD=3
ANTHROPIC_API_KEY=                         # only for claude_api
YOUTUBE_API_KEY=                           # optional
CLIPSIEVE_DATA_DIR=./data
CLIPSIEVE_CREATOR_SALT=                    # generated on first run if empty
CLIPSIEVE_XHS_CHROME_CDP_PORT=9222         # contrib adapter
```

`.env.example` is committed with every key present and empty.

## 12. Error handling

- Adapter errors on one post emit `error` with `recoverable: true` and continue. An adapter that fails its healthcheck or errors on more than 20 percent of posts aborts its own collection but not the run.
- Jev 429 and 529 back off exponentially up to five tries, then the post is marked `judge_failed` and excluded from selection. Other 4xx on a post is recorded and skipped.
- Explain failures retry once with the error in the prompt. A second failure moves the run to `failed` with the shortlist still viewable.
- Evidence failures (ASR crash, OCR error) record empty evidence with an `error` event and let Jev judge on what remains.
- Any stage can be resumed from the log. The pipeline is idempotent per post: a post with an existing `judge/<post_id>.json` for a pass is not re-judged.

## 13. Testing and evaluation

- **Unit.** pytest for every pure function in `select/`, `evidence/packet.py`, event reader and writer, schema generation.
- **Contract.** Adapter contract test over fixtures; Judge contract test over `RecordedJudge`; ExplainBackend contract test over the fake and, expected-fail, the API stub.
- **Pipeline.** One end-to-end test with `local_import` on five fixture posts, `RecordedJudge`, `FakeExplainBackend`. Asserts the event log shape and the report citation rule.
- **Frontend.** Vitest for components with fixture events; one Playwright flow: create run, approve plan, watch the fixture run complete, open report, open replay.
- **Schema drift.** CI regenerates models and types and fails on diff.
- **Evals.** `sieve eval --pack creator-hooks-v1 --golden evals/golden/en-100.jsonl` prints per-question agreement and a calibration curve. Golden sets are hand-labelled by the author, 100 posts each in English and Chinese, stored as text evidence only, no media, with creator hashes.
- **CI.** GitHub Actions: `bun run check` on push, Python 3.12 and Bun pinned. No live network calls in CI; all external systems are faked.

## 14. Legal and privacy posture

- The core repo contains no scrapers and no data. Official-API and import adapters only.
- Browser-session adapters are community packages under `contrib/` with their own licence notices and disclaimers. The README states that users are responsible for compliance with each platform's terms and local law.
- Creator ids are hashed with a per-install salt at ingest. Display names are kept only for the dashboard. Comments are capped and stored as text with no author identifiers.
- Demo replays shipped with the repo use synthetic posts or Creative Commons content.
- The `claude_cli` backend documentation states the subscription-use constraint.

## 15. Decisions log

| Decision | Choice | Alternatives considered |
|---|---|---|
| First slice | YouTube Shorts and Xiaohongshu together | Local import only; YouTube only; Xiaohongshu only |
| Xiaohongshu access | Wrap a pinned MediaCrawler sibling checkout in contrib now, own CDP adapter with Jev navigator later | Own Playwright adapter; direct signed API via xhs/xhshow; browser extension capture; fork jev-ultrafast |
| Explain default | `claude -p` on subscription | Claude API first; both |
| Xiaohongshu items | Video and image notes | Video only |
| Pipeline owner | Python backend, Next.js thin client | CLI with static dashboard; Next.js orchestrating Python workers |
| Layout | `backend/` and `frontend/` matching the author's other repos | `apps/api` and `apps/web` |
| Python version | 3.12 | 3.13 (repo convention) rejected for PaddleOCR and MediaCrawler support |
| Store | SQLite and files | PostgreSQL (repo convention) rejected as local-first has no deployment |
| Name | clipsieve, CLI `sieve` | hookscope, viralens, scrollsieve, clipgrade, short clip-* names, all taken or colliding |
| Licence | Apache-2.0 | MIT |
