# clipsieve v0.1 Implementation Plans: Overview and Interface Contract

> **For agentic workers:** This file is the index and the shared contract for plans 01 to 05. Read it before any plan. Every name, path and signature below is binding across all plans. If a plan and this file disagree, this file wins; fix the plan.

**Spec:** `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md`

## Plan index and order

| # | File | Produces | Depends on |
|---|---|---|---|
| 01 | `2026-10-03-clipsieve-v0.1-01-foundation.md` | Monorepo, schema package with generators, config, store, event log, CI, DOX children | nothing |
| 02 | `2026-10-03-clipsieve-v0.1-02-adapters-evidence.md` | Adapter interface and registry, `local_import`, `youtube`, ASR/OCR/frames/comments with fakes, packet builder | 01 |
| 03 | `2026-10-03-clipsieve-v0.1-03-judge-select-explain-api.md` | Rubric loader and `creator-hooks-v1`, TypeSafe judge and recorded fake, selection, explain backends, pipeline runner, FastAPI with SSE, `sieve` CLI | 01, 02 |
| 04 | `2026-10-03-clipsieve-v0.1-04-frontend.md` | Next.js app: brief, plan, live dashboard, report, replay, i18n, Playwright flow | 01 (types), 03 (API) |
| 05 | `2026-10-03-clipsieve-v0.1-05-contrib-xhs-evals.md` | `contrib/adapter-xhs-mediacrawler`, evals golden format, `sieve eval`, calibration workflow | 02, 03 |

01 first. 02 and 04 can start in parallel once 01 is merged (04 builds against the fake backend and generated types until 03 lands). 03 after 02. 05 after 03.

## Global constraints (copied into every plan)

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

## Repository paths (binding)

```text
clipsieve/
  package.json                      bun workspaces: ["frontend", "packages/schema"]; root scripts
  biome.jsonc                       { "root": true, "extends": ["ultracite/biome/core"], ... }  (ultracite 7 has no bare "ultracite" export)
  .github/workflows/check.yml
  .env.example
  backend/
    AGENTS.md  pyproject.toml  README.md
    clipsieve/
      __init__.py  app.py  cli.py  config.py  models.py (GENERATED)
      store/__init__.py  store/paths.py  store/repo.py  store/db.py
      events/__init__.py  events/writer.py  events/reader.py
      planner/__init__.py  planner/plan.py
      adapters/__init__.py  adapters/base.py  adapters/registry.py  adapters/local_import.py  adapters/youtube.py
      evidence/__init__.py  evidence/asr.py  evidence/ocr.py  evidence/frames.py  evidence/comments.py  evidence/packet.py  evidence/extract.py
      judge/__init__.py  judge/base.py  judge/typesafe_client.py  judge/recorded.py  judge/rubric.py
      select/__init__.py  select/scoring.py  select/quotas.py  select/select.py
      explain/__init__.py  explain/base.py  explain/claude_cli.py  explain/claude_api.py  explain/fake.py  explain/prompts/plan.md  explain/prompts/explain.md
      pipeline/__init__.py  pipeline/runner.py
      api/__init__.py  api/runs.py  api/events.py  api/meta.py
    tests/
      conftest.py
      fixtures/posts/*.json
      fixtures/raw/*.json
      fixtures/judge/<post_id>.<pass_name>.json
      fixtures/explain/plan.json  fixtures/explain/report.json
      fixtures/claude-shim/claude            executable shell script
      fixtures/golden/sample-5.jsonl
  frontend/
    AGENTS.md  package.json  next.config.ts  biome.jsonc  tsconfig.json  components.json
    src/app/layout.tsx  src/app/page.tsx
    src/app/runs/[id]/plan/page.tsx  src/app/runs/[id]/page.tsx  src/app/runs/[id]/report/page.tsx  src/app/runs/[id]/replay/page.tsx
    src/components/brief/BriefForm.tsx
    src/components/plan/PlanEditor.tsx
    src/components/dashboard/Counters.tsx  PostGrid.tsx  CurrentItem.tsx  Aggregates.tsx  ReviewBucket.tsx  ReplayControls.tsx
    src/components/report/ReportView.tsx
    src/lib/types.ts (GENERATED)  src/lib/api.ts  src/lib/events.ts  src/lib/useRunEvents.ts  src/lib/i18n.ts  src/lib/i18n/en.ts  src/lib/i18n/zh.ts
    e2e/run-flow.spec.ts
  packages/schema/
    AGENTS.md  package.json
    schemas/post.json  evidence.json  run_event.json  rubric_pack.json  plan.json  report.json  judge_result.json  run.json
    generate.py       -> backend/clipsieve/models.py
    generate.ts       -> frontend/src/lib/types.ts
  rubrics/
    AGENTS.md  creator-hooks-v1.yaml  creator-hooks-v1.calibration.md
  contrib/adapter-xhs-mediacrawler/
    AGENTS.md  README.md  pyproject.toml
    clipsieve_xhs/__init__.py  adapter.py  mapping.py  runner.py
    tests/fixtures/mediacrawler-output/*.json
  evals/
    AGENTS.md  README.md  golden/en-100.jsonl  golden/zh-100.jsonl  score.py
  docs/superpowers/specs/  docs/superpowers/plans/
```

## Root scripts (`package.json`)

```json
{
  "name": "clipsieve",
  "private": true,
  "workspaces": ["frontend", "packages/schema"],
  "scripts": {
    "dev": "bun run --filter frontend dev & (cd backend && uv run uvicorn clipsieve.app:app --reload --port 8000); wait",
    "dev:api": "cd backend && uv run uvicorn clipsieve.app:app --reload --port 8000",
    "dev:web": "bun run --filter frontend dev",
    "schema": "cd backend && uv run python ../packages/schema/generate.py && bun run --filter @clipsieve/schema generate",
    "check:schema": "bun run schema && git diff --exit-code -- backend/clipsieve/models.py frontend/src/lib/types.ts",
    "lint": "bunx ultracite check && (cd backend && uv run ruff check . && uv run ruff format --check .)",
    "format": "bunx ultracite fix && (cd backend && uv run ruff format .)",
    "test": "(cd backend && uv run pytest -q) && bun run --filter frontend test",
    "typecheck": "bun run --filter frontend typecheck",
    "check": "bun run check:schema && bun run lint && bun run typecheck && bun run test"
  }
}
```

Frontend dev server on port 3000 proxies `/api/:path*` to `http://localhost:8000/api/:path*` via `next.config.ts` rewrites.

## Schema package: the eight schemas

JSON Schema draft 2020-12, one file each, `$id` of the form `https://clipsieve.dev/schema/<name>.json`. Field names are snake_case on the wire and in both generated languages. Enums are string enums. Generated Python uses Pydantic v2 `BaseModel` with `model_config = ConfigDict(extra="forbid")`. Generated TS uses `type` aliases and string-literal unions.

Generation is deterministic: `datamodel-code-generator` for Python with `--output-model-type pydantic_v2.BaseModel --use-standard-collections --use-union-operator --field-constraints --snake-case-field --disable-timestamp`, and `json-schema-to-typescript` for TS with `bannerComment` set to a fixed string. Both outputs start with a line `// GENERATED by packages/schema; do not edit` (Python: `# GENERATED ...`).

### post.json

```text
Post { id: str, platform: "youtube"|"xiaohongshu"|"local", url: str, creator_hash: str,
       creator_display?: str, posted_at?: datetime, kind: "video"|"image_note",
       text: PostText, media: Media[], metrics: Metrics, comments: Comment[] (maxItems 50),
       lang?: str, raw_ref: str, collected_at: datetime }
PostText { title?: str, caption?: str, hashtags: str[] }
Media { type: "video"|"image", local_path?: str, duration_s?: number, index?: int, width?: int, height?: int }
Metrics { views?: int, likes?: int, comments?: int, shares?: int, saves?: int }
Comment { text: str, likes?: int }
```

### evidence.json

```text
Evidence { post_id: str, transcript: TranscriptSegment[], transcript_lang?: str, ocr: OcrItem[],
           keyframes: str[] (maxItems 8), comment_summary: CommentSummary, token_estimate: int, truncated: bool }
TranscriptSegment { start_s: number, end_s: number, text: str }
OcrItem { source: "keyframe"|"image", index: int, text: str }
CommentSummary { count: int, top_terms: str[], sample: str[] }
```

### run_event.json

```text
RunEvent { run_id: str, seq: int, ts: datetime, type: RunEventType, stage: Stage, payload: object }
RunEventType = "run_created"|"plan_ready"|"plan_approved"|"post_collected"|"pass_one_judged"|"evidence_ready"|"judged"|"selected"|"explained"|"error"|"stage_changed"|"done"
Stage = "planning"|"collecting"|"pass_one"|"extracting"|"pass_two"|"selecting"|"explaining"|"done"|"failed"
```

Payload shapes by type (documented in the schema `description`, validated in code by `events/writer.py`):

| type | payload |
|---|---|
| run_created | `{ brief: Brief, platforms: str[], quantities: {platform: int} }` |
| plan_ready | `{ plan: Plan }` |
| plan_approved | `{ plan: Plan }` |
| post_collected | `{ post: Post }` (media paths empty) |
| pass_one_judged | `{ judge: JudgeResult, kept: bool, composite: number }` |
| evidence_ready | `{ post_id: str, evidence: Evidence }` |
| judged | `{ judge: JudgeResult, composite: number }` |
| selected | `{ shortlist: str[], review: str[], scores: {post_id: number}, dropped: {post_id: str} }` |
| explained | `{ report: Report }` |
| error | `{ where: str, message: str, post_id?: str, recoverable: bool }` |
| stage_changed | `{ from: Stage, to: Stage }` |
| done | `{ counters: Counters }` |

```text
Counters { collected: int, pass_one_kept: int, judged: int, shortlisted: int, review: int, errors: int,
           jev_input_tokens: int, jev_cost_usd: number, elapsed_s: number }
```

### rubric_pack.json

```text
RubricPack { name: str, version: int, jev_model: str, language_mode: "raw"|"translate"|"bilingual",
             metadata_pass: str[], pass_one_keep: number (0..1), questions: {question_id: Question}, selection: SelectionPolicy }
Question = ChoiceQuestion | ScoreQuestion | NoulQuestion
ChoiceQuestion { type: "choice", instructions: str, criteria: {label: str} (minProperties 2, maxProperties 255) }
ScoreQuestion  { type: "score",  instructions: str, criteria: str[] (minItems 2, maxItems 10) }
NoulQuestion   { type: "noul",   instructions: str }
SelectionPolicy { weights: {question_id: number}, hard_filters: {risky_claim_max?: number},
                  review_confidence_below: number, shortlist_size: int, diversity: {question_id: {max_share: number}} }
```

### plan.json

```text
Plan { run_id: str, brief: Brief, queries: Query[], quantities: {platform: int}, rubric_pack: str,
       persona_fit_criteria: str[] (5 items), approved_at?: datetime }
Brief { text: str, topic: str, audience: str, persona: str, language_hint?: str }
Query { platform: str, query: str, lang: str }
```

### report.json

```text
Report { run_id: str, patterns: Pattern[], clips: ClipExplanation[], gaps: Gap[], concepts: Concept[], caveats: str[] }
Pattern { title: str, observation: str, hypothesis: str, post_ids: str[] }
ClipExplanation { post_id: str, why_it_works: str, hook_quote: str, weaknesses: str }
Gap { title: str, rationale: str, post_ids: str[] }
Concept { hook: str, structure: str, visual: str, proof: str, cta: str, inspired_by_post_ids: str[] }
```

### judge_result.json

```text
JudgeResult { post_id: str, pass_name: "pass_one"|"pass_two", model: str, input_tokens: int, latency_ms: int,
              answers: {question_id: JudgeAnswer} }
JudgeAnswer { type: "choice"|"score"|"noul", value: str|number, probabilities?: {label_or_level: number},
              confidence?: number, legend?: {level: str} }
```

`value` is the chosen label for choice, the fractional score for score, the probability for noul.

### run.json

```text
Run { id: str, created_at: datetime, stage: Stage, brief: Brief, platforms: str[], quantities: {platform: int},
      rubric_pack: str, counters: Counters, paused: bool, error?: str }
```

## Python interface contract (binding signatures)

All in `backend/clipsieve/`. Types come from `clipsieve.models` unless defined here.

```python
# config.py
class Settings(BaseSettings):
    typesafe_api_key: str = ""
    clipsieve_explain_backend: Literal["claude_cli", "claude_api", "fake"] = "claude_cli"
    clipsieve_claude_bin: str = "claude"
    clipsieve_claude_max_budget_usd: float = 3.0
    anthropic_api_key: str = ""
    youtube_api_key: str = ""
    clipsieve_data_dir: Path = Path("./data")
    clipsieve_creator_salt: str = ""
    clipsieve_xhs_chrome_cdp_port: int = 9222
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
def get_settings() -> Settings  # lru_cache

# store/paths.py
class RunPaths:
    def __init__(self, data_dir: Path, run_id: str) -> None
    root: Path; run_json: Path; plan_json: Path; events_jsonl: Path; report_json: Path
    def post_json(self, post_id: str) -> Path
    def raw_path(self, post_id: str, ext: str) -> Path
    def media_dir(self, post_id: str) -> Path
    def evidence_json(self, post_id: str) -> Path
    def judge_json(self, post_id: str, pass_name: str) -> Path
    def ensure(self) -> None   # mkdir -p all dirs
def safe_post_filename(post_id: str) -> str   # "youtube:abc" -> "youtube__abc"

# store/db.py
def get_engine(data_dir: Path) -> Engine        # sqlite at data_dir / "clipsieve.db"
def init_db(engine: Engine) -> None

# store/repo.py
class RunRepository:
    def __init__(self, data_dir: Path, engine: Engine) -> None
    def create_run(self, brief: Brief, platforms: list[str], quantities: dict[str, int], rubric_pack: str) -> Run
    def get_run(self, run_id: str) -> Run                      # raises RunNotFound
    def list_runs(self) -> list[Run]
    def save_run(self, run: Run) -> None
    def save_plan(self, run_id: str, plan: Plan) -> None
    def get_plan(self, run_id: str) -> Plan | None
    def upsert_post(self, run_id: str, post: Post) -> None
    def get_post(self, run_id: str, post_id: str) -> Post
    def list_posts(self, run_id: str, offset: int = 0, limit: int = 100) -> list[Post]
    def count_posts(self, run_id: str) -> int
    def save_evidence(self, run_id: str, evidence: Evidence) -> None
    def get_evidence(self, run_id: str, post_id: str) -> Evidence | None
    def save_judge_result(self, run_id: str, result: JudgeResult) -> None
    def get_judge_result(self, run_id: str, post_id: str, pass_name: str) -> JudgeResult | None
    def list_judge_results(self, run_id: str, pass_name: str) -> list[JudgeResult]
    def save_selection(self, run_id: str, selection: "Selection") -> None
    def get_selection(self, run_id: str) -> "Selection | None"
    def save_report(self, run_id: str, report: Report) -> None
    def get_report(self, run_id: str) -> Report | None
    def reindex(self, run_id: str) -> None     # rebuild sqlite rows from files
class RunNotFound(Exception): ...

# events/writer.py
class EventWriter:
    def __init__(self, paths: RunPaths, run_id: str) -> None   # reads last seq from file if exists
    def emit(self, type: RunEventType, stage: Stage, payload: dict) -> RunEvent   # validates payload shape, appends JSON line, fsyncs
    @property
    def last_seq(self) -> int

# events/reader.py
def read_events(paths: RunPaths, after: int = 0) -> list[RunEvent]
async def follow_events(paths: RunPaths, after: int = 0, poll_s: float = 0.25) -> AsyncIterator[RunEvent]   # tails file until a "done" or stage "failed" event

# adapters/base.py
@dataclass
class AdapterHealth: ok: bool; message: str
class Adapter(Protocol):
    platform: str
    def search(self, queries: list[Query], limit: int) -> Iterator[Post]: ...
    def fetch_media(self, post: Post, dest: Path) -> Post: ...
    def healthcheck(self) -> AdapterHealth: ...
def hash_creator(platform_creator_id: str, salt: str) -> str   # sha256 hex of f"{salt}:{platform_creator_id}"

# adapters/registry.py
ENTRY_POINT_GROUP = "clipsieve.adapters"
def load_adapters(settings: Settings) -> dict[str, Adapter]   # built-ins + entry points; key = platform
# pyproject registers: local = "clipsieve.adapters.local_import:LocalImportAdapter", youtube = "clipsieve.adapters.youtube:YouTubeAdapter"

# evidence/asr.py
class ASR(Protocol):
    def transcribe(self, media: Path, lang_hint: str | None) -> tuple[list[TranscriptSegment], str | None]: ...
class WhisperASR(ASR)        # mlx-whisper if importable, else faster-whisper; model "large-v3"
class FakeASR(ASR)           # returns segments from a sidecar <media>.transcript.json if present, else []

# evidence/ocr.py
class OCR(Protocol):
    def read(self, image: Path, lang: str) -> list[str]: ...   # lang "ch" or "en"; drops conf < 0.6
class PaddleOCRBackend(OCR)
class FakeOCR(OCR)           # sidecar <image>.ocr.json

# evidence/frames.py
class FrameExtractor(Protocol):
    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]: ...
class FfmpegFrames(FrameExtractor)   # scene threshold 0.3 plus frame at 0.5s
class FakeFrames(FrameExtractor)     # copies fixture pngs

# evidence/comments.py
def summarize_comments(comments: list[Comment], lang: str | None) -> CommentSummary   # top 10 terms, 5 samples by likes

# evidence/packet.py
MAX_STATE_TOKENS = 28_000
def estimate_tokens(text: str) -> int                      # len(text) // 3
def build_state(brief: Brief, post: Post, evidence: Evidence | None) -> tuple[dict, bool]   # (state, truncated); truncation order: comments, ocr, transcript tail
def build_metadata_state(brief: Brief, post: Post) -> dict  # pass one: no evidence

# evidence/extract.py
def extract_evidence(post: Post, paths: RunPaths, asr: ASR, ocr: OCR, frames: FrameExtractor) -> Evidence

# judge/base.py
class Judge(Protocol):
    async def judge(self, post_id: str, pass_name: str, state: dict, questions: dict[str, Question], model: str) -> JudgeResult: ...
JEV_USD_PER_MILLION_INPUT = 0.042
def cost_usd(input_tokens: int) -> float

# judge/typesafe_client.py
class TypeSafeJudge(Judge):
    def __init__(self, api_key: str, concurrency: int = 16, max_retries: int = 5) -> None

# judge/recorded.py
class RecordedJudge(Judge):
    def __init__(self, fixture_dir: Path) -> None     # reads fixtures/judge/<safe_post_id>.<pass_name>.json; raises FixtureMissing

# judge/rubric.py
def load_pack(path: Path) -> RubricPack
def find_pack(name: str, rubrics_dir: Path) -> RubricPack
def questions_for_pass(pack: RubricPack, pass_name: str) -> dict[str, Question]   # pass_one -> metadata_pass ids; pass_two -> all
def to_typesafe(question: Question) -> "Choice | Score | Noul"
def from_typesafe(question_id: str, question: Question, response) -> JudgeAnswer
def with_persona_criteria(pack: RubricPack, criteria: list[str]) -> RubricPack   # replaces questions["persona_fit"].criteria

# select/scoring.py
def normalize_score(answer: JudgeAnswer, levels: int) -> float    # position among levels, 0..1, from value and legend
def composite(result: JudgeResult, pack: RubricPack) -> float
def passes_hard_filters(result: JudgeResult, pack: RubricPack) -> bool
def needs_review(result: JudgeResult, pack: RubricPack) -> bool

# select/quotas.py
def violates_quota(candidate: JudgeResult, chosen: list[JudgeResult], pack: RubricPack, shortlist_size: int) -> bool

# select/select.py
class Selection(BaseModel): shortlist: list[str]; review: list[str]; scores: dict[str, float]; dropped: dict[str, str]
def select(results: list[JudgeResult], pack: RubricPack, weights_override: dict[str, float] | None = None) -> Selection
def pass_one_keep(results: list[JudgeResult], pack: RubricPack) -> set[str]   # top pass_one_keep fraction by composite over metadata_pass questions

# explain/base.py
class RubricPackSummary(BaseModel): name: str; description: str; question_ids: list[str]
class ExplainPacket(BaseModel):
    brief: Brief; posts: list[Post]; evidence: dict[str, Evidence]; judge: dict[str, JudgeResult]
    aggregates: dict[str, dict[str, int]]; keyframes: dict[str, list[str]]
class ExplainBackend(Protocol):
    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan: ...
    def explain(self, packet: ExplainPacket) -> Report: ...
class ExplainError(Exception): ...
def validate_report_citations(report: Report, known_post_ids: set[str]) -> list[str]   # returns unknown ids
def get_backend(settings: Settings, fixture_dir: Path | None = None) -> ExplainBackend

# explain/claude_cli.py
class ClaudeCliBackend(ExplainBackend):
    def __init__(self, bin: str, max_budget_usd: float, model: str = "opus", effort: str = "high") -> None
    # argv exactly: [bin, "-p", "--model", model, "--effort", effort, "--tools", "", "--strict-mcp-config",
    #               "--setting-sources", "", "--no-session-persistence", "--system-prompt-file", <prompt path>,
    #               "--output-format", "json", "--json-schema", <schema json string>, "--max-budget-usd", str(max_budget_usd), <task line>]
    # stdin: packet JSON. Parses envelope; requires is_error is False; reads "structured_output".

# explain/fake.py
class FakeExplainBackend(ExplainBackend):
    def __init__(self, fixture_dir: Path) -> None   # fixtures/explain/plan.json and report.json; fills run_id and post_ids from packet

# explain/claude_api.py
class ClaudeApiBackend(ExplainBackend)   # raises NotImplementedError("see plan 03 follow-up")

# pipeline/runner.py
class Runner:
    def __init__(self, run_id: str, settings: Settings, repo: RunRepository, adapters: dict[str, Adapter],
                 judge: Judge, explain: ExplainBackend, asr: ASR, ocr: OCR, frames: FrameExtractor, rubrics_dir: Path) -> None
    async def plan(self) -> Plan                 # planning stage; emits plan_ready
    async def approve(self, plan: Plan) -> None  # saves plan, emits plan_approved
    async def run(self) -> None                  # runs remaining stages from current run.stage to done; idempotent per post
    def pause(self) -> None
    async def reselect(self, weights_override: dict[str, float]) -> Selection
STAGE_ORDER: list[Stage] = ["planning", "collecting", "pass_one", "extracting", "pass_two", "selecting", "explaining", "done"]

# app.py
app = FastAPI(title="clipsieve")
# includes api.runs.router, api.events.router, api.meta.router under prefix "/api"
# dependency get_context() -> AppContext(settings, repo, adapters, judge, explain, asr, ocr, frames, rubrics_dir)
# CLIPSIEVE_EXPLAIN_BACKEND=fake also swaps Judge -> RecordedJudge, ASR/OCR/Frames -> fakes (test mode)

# cli.py  (typer)
# sieve run --brief TEXT --platforms youtube,xiaohongshu --limit 500 --pack creator-hooks-v1 [--auto-approve] [--data-dir PATH]
# sieve replay RUN_ID [--speed 1.0]           prints events to stdout at original timing
# sieve reselect RUN_ID --weights hook_strength=0.5,persona_fit=0.5
# sieve eval --pack NAME --golden PATH [--mode raw|translate|bilingual]
# sieve reindex RUN_ID
```

## HTTP API contract (binding)

Base path `/api`. JSON bodies are the schema models. Errors are `{ "detail": str }`.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/runs` | `{ brief: str, platforms: str[], quantities: {platform:int}, rubric_pack: str, language_hint?: str }` | `Run` (stage `planning`); planning starts in background |
| GET | `/runs` | | `Run[]` newest first |
| GET | `/runs/{id}` | | `{ run: Run, plan: Plan \| null }` |
| PUT | `/runs/{id}/plan` | `Plan` | `Plan` |
| POST | `/runs/{id}/approve` | | `Run` (stage `collecting`); pipeline starts in background |
| POST | `/runs/{id}/pause` | | `Run` |
| POST | `/runs/{id}/resume` | | `Run` |
| GET | `/runs/{id}/events?after=N` | | SSE. Each message: `id: <seq>`, `event: run_event`, `data: <RunEvent JSON>`. Ends after `done` or `failed`. |
| GET | `/runs/{id}/posts?offset=0&limit=100` | | `{ items: PostView[], total: int }` where `PostView { post: Post, judge: {pass_name: JudgeResult}, composite?: number, state: "collected"\|"dropped_pass_one"\|"judged"\|"shortlisted"\|"review"\|"judge_failed" }` |
| GET | `/runs/{id}/report` | | `Report` or 404 |
| POST | `/runs/{id}/reselect` | `{ weights: {question_id: number} }` | `Selection` |
| GET | `/adapters` | | `{ platform: str, healthy: bool, message: str }[]` |
| GET | `/rubrics` | | `RubricPackSummary[]` |
| GET | `/runs/{id}/media/{post_id}/{filename}` | | file bytes (thumbnails, keyframes) |

## Frontend contract (binding)

```ts
// src/lib/api.ts
export const api = {
  createRun(body: CreateRunBody): Promise<Run>,
  listRuns(): Promise<Run[]>,
  getRun(id: string): Promise<{ run: Run; plan: Plan | null }>,
  savePlan(id: string, plan: Plan): Promise<Plan>,
  approveRun(id: string): Promise<Run>,
  pauseRun(id: string): Promise<Run>, resumeRun(id: string): Promise<Run>,
  getPosts(id: string, offset?: number, limit?: number): Promise<{ items: PostView[]; total: number }>,
  getReport(id: string): Promise<Report>,
  reselect(id: string, weights: Record<string, number>): Promise<Selection>,
  listAdapters(): Promise<AdapterStatus[]>,
  listRubrics(): Promise<RubricPackSummary[]>,
};

// src/lib/events.ts
export type DashboardState = {
  stage: Stage; counters: Counters; posts: Record<string, PostTile>;
  latest: { post: Post; judge: JudgeResult; composite: number } | null;
  aggregates: Record<string, Record<string, number>>;   // question_id -> label -> count (pass_two only)
  shortlist: string[]; review: string[]; errors: RunEvent[]; done: boolean;
};
export type PostTile = { post: Post; state: "collected" | "dropped_pass_one" | "judged" | "shortlisted" | "review" | "judge_failed"; composite?: number };
export function initialState(): DashboardState;
export function reduceEvent(state: DashboardState, event: RunEvent): DashboardState;   // pure
export function answersPerSecond(events: RunEvent[], windowMs?: number): number;      // rolling window, default 5000

// src/lib/useRunEvents.ts
export function useRunEvents(runId: string, opts: { mode: "live" } | { mode: "replay"; speed: number; playing: boolean }):
  { state: DashboardState; events: RunEvent[]; connected: boolean; progress: number /* replay 0..1 */ };

// src/lib/i18n.ts
export type Locale = "en" | "zh";
export function t(key: string, locale: Locale, vars?: Record<string, string | number>): string;
export function useLocale(): [Locale, (l: Locale) => void];   // localStorage "clipsieve.locale", default from navigator.language
```

## Fixture contract (binding)

- `backend/tests/fixtures/posts/`: five posts, ids `local:fx-001` to `local:fx-005`. Three `video`, two `image_note`. Two in English, three in Chinese. Each has a matching `raw/<safe id>.json`.
- `backend/tests/fixtures/judge/`: for each post, `<safe id>.pass_one.json` and `<safe id>.pass_two.json` as `JudgeResult`, answers covering every question in `creator-hooks-v1`.
- `backend/tests/fixtures/explain/plan.json` and `report.json`: valid `Plan` and `Report` with `run_id` `"FIXTURE"` and post ids drawn from the five fixtures.
- `backend/tests/fixtures/claude-shim/claude`: bash script that ignores arguments, reads stdin to detect `"mode": "plan"` or `"mode": "explain"` in the packet, and prints a result envelope `{"is_error": false, "structured_output": <plan.json or report.json contents>, "total_cost_usd": 0.0}`.
- The `ExplainPacket` and the planner input both carry a top-level `"mode"` field (`"plan"` or `"explain"`) when serialised for the CLI backend. This is the only field outside the schema models in the CLI payload.
- `backend/tests/fixtures/golden/sample-5.jsonl`: five lines `{ post_id, state: <Jev state dict>, labels: {question_id: expected_value} }`.

## Review Focus (shared, every plan adds the tests that pin its lines)

1. A post whose evidence exceeds the Jev state cap must be truncated in the documented order and judged, never skipped.
2. A Jev 429 on one post must not stall the other 15 in-flight posts or fail the run.
3. Reconnecting the dashboard mid-run with `after=<seq>` must replay exactly the missed events, no duplicates, no gaps.
4. A report citing a post id not in the run must be rejected, retried once, and surfaced as an error event, never shown with dangling links.
5. Chinese caption and comment text must survive the whole path byte-for-byte: adapter, SQLite, JSONL, SSE, dashboard.

## Addendum A: contract decisions made by plan 01 (binding for plans 02 to 05)

1. **Ninth schema file `common.json`** holds shared `$defs`: `Platform`, `Stage`, `RunEventType`, `Brief`, `Query`, `Counters`. Other schema files reference them as `"$ref": "common.json#/$defs/Name"`. `packages/schema/merge.py` and the same logic in `generate.ts` fold all files into one root schema before generation. `$def` names are unique across files.
2. **`Selection` model is defined in plan 01** at `backend/clipsieve/select/select.py` (fields `shortlist`, `review`, `scores`, `dropped`, extra forbid) so `RunRepository` can import it. Plan 03 appends `select()`, `pass_one_keep()` and helpers to that module and never redefines the class.
3. **`RunPaths.selection_json`** exists (`root / "selection.json"`).
4. **Event payload models live in `backend/clipsieve/events/payloads.py`** as `PAYLOAD_MODELS: dict[RunEventType, type[BaseModel]]`. The API layer and tests import from there. `StageChangedPayload` uses alias `from` for the `from_` field.
5. **`EventWriter.emit` raises `ValueError`** on a payload that fails its type's model. `follow_events` tracks a byte offset and ignores a trailing partial line until its newline arrives.
6. **Run ids** are `"run_" + uuid4().hex[:12]`. `RunRepository.get_post` raises `PostNotFound(KeyError)`. `list_runs` is newest first; `list_posts` orders by `collected_at` then `post_id`.
7. **Placeholder `frontend/package.json`** (name `frontend`, echo-only `dev`/`test`/`typecheck` scripts) and `frontend/src/lib/.gitkeep` exist after plan 01. Plan 04 deletes the placeholder before `create-next-app`. Root `biome.jsonc` already excludes `frontend/src/lib/types.ts` and `packages/schema/.build/`.
8. **Generated enums are `Enum` classes** (`--enum-field-as-literal none`, `--extra-fields forbid`). Code reads `run.stage.value`, `result.pass_name.value`; Pydantic accepts plain strings on input. `ruff` excludes `clipsieve/models.py`.
9. **`datamodel-code-generator>=0.26`** is pinned. `[project.scripts] sieve = "clipsieve.cli:app"` is declared in plan 01; plan 03 creates `cli.py` with a typer `app`.
10. **CI** pins Bun `1.3.11`, installs Python 3.12 via `astral-sh/setup-uv@v6`, runs `bun install --frozen-lockfile`, `uv sync --frozen`, `bun run check`.

11. **Repo-root resolution in `config.py`.** `REPO_ROOT = Path(__file__).resolve().parents[2]`. `Settings.model_config` uses `env_file=(REPO_ROOT / ".env", ".env")` so a `.env` copied from `.env.example` at the repo root is read even when commands `cd backend`. A relative `clipsieve_data_dir` is resolved against `REPO_ROOT` by a field validator; absolute paths (and `--data-dir`) are used as given.
12. **Creator salt.** `config.ensure_creator_salt(settings) -> str` returns `settings.clipsieve_creator_salt` if non-empty, else reads or creates `<data_dir>/creator_salt` (`secrets.token_hex(16)`, mode 0600) and returns it. Plan 03's `build_context` and the `sieve run` CLI call it before constructing adapters and pass the result as the `salt` for `hash_creator`. Nothing else generates salts.
13. **Optional means absent on the wire.** All JSON the backend writes or serves omits `None` fields: `RunRepository` dumps and `EventWriter` serialise with `exclude_none=True`, and plan 03's FastAPI routes use `response_model_exclude_none=True`. Files therefore validate against the JSON Schemas (no `null` for `type: string`), and TypeScript `field?: T` is never `null`. Frontend code may still defensively treat `null` as absent.
14. **Test fixtures shared from plan 01.** `backend/tests/conftest.py` provides `data_dir` (tmp), `tmp_data_dir` (alias), `engine`, `repo` (`RunRepository` on a fresh tmp db), `fixtures_dir`, and `fixture_posts: list[Post]` (the five fixture posts in id order). An autouse fixture resets structlog (`structlog.reset_defaults()`, `clear_contextvars()`) after every test so `configure_logging()` never leaks a captured stream into later tests.

## Addendum B: contract decisions made by plan 02 (binding for plans 03 to 05)

1. **Raw payload location.** Adapters write raw payloads to `<data_dir>/incoming/<platform>/<safe_post_id>.json` and set `raw_ref` to that absolute path. The Runner relocates the file to `RunPaths.raw_path(post.id, "json")` on `post_collected` and rewrites `raw_ref` to `raw/<safe_post_id>.json`. Helper `incoming_dir(data_dir, platform)` lives in `adapters/base.py`.
2. **Media paths.** `fetch_media` sets `Media.local_path` relative to `dest` (`video.mp4`, `img_00.jpg`). `extract_evidence` resolves via `paths.media_dir(post.id) / local_path`. `Evidence.keyframes` are run-relative `media/<safe_id>/frames/<name>`, hook frame first (`hook.jpg`, then `scene_NN.jpg`).
3. **`Evidence.truncated` is always `False` at extraction.** The Runner sets it from `build_state`'s return value and re-saves. `token_estimate` covers transcript, OCR and comment summary text only.
4. **`estimate_tokens` counts CJK characters as 1 token each** and other characters at `len // 3`. This supersedes the `len(text) // 3` note in the Python contract above; the signature is unchanged.
5. **Local import source is `Query.query`** (a folder or CSV path). `LocalImportAdapter` takes no path at construction.
6. **`from_settings(settings)` classmethod on every adapter.** `load_adapters` loads entry points first, then built-ins by import as fallback; a failing plugin is logged and skipped.
7. **Caption sidecar format** `<media>.transcript.json` is `{"lang": str, "segments": [{start_s, end_s, text}]}`. Both `FakeASR` and `WhisperASR` honour it and skip transcription when present.
8. **Additional modules:** `adapters/ytdlp_client.py` (`YtDlpClient` Protocol, `RealYtDlpClient`, `FakeYtDlpClient`), `adapters/vtt.py` (`parse_vtt`, `vtt_lang_from_filename`), fixtures under `backend/tests/fixtures/youtube/` and `backend/tests/fixtures/evidence/`.
9. **pyproject additions:** core deps `yt-dlp`, `httpx`; optional extras `asr` (mlx-whisper on darwin/arm64, faster-whisper otherwise) and `ocr` (paddleocr, paddlepaddle); entry points `local` and `youtube`.

10. **`fetch_media` runs after raw relocation.** The Runner rewrites `Post.raw_ref` to the run-relative `raw/<safe_post_id>.json` before `fetch_media` is called, so adapters must never read the incoming file or `raw_ref` inside `fetch_media`. Everything an adapter needs to fetch media must live on the `Post` itself (`url`, `media[]`, `id`); `LocalImportAdapter` derives the source path from `Post.url` (a `file://` URI). `tests/adapters/contract.py::run_adapter_contract` relocates the raw file and rewrites `raw_ref` before calling `fetch_media`, exactly as the Runner does, so every adapter (including plan 05's XHS adapter) is tested against this seam.
11. **`MediaDownloadError` lives in `adapters/base.py`** and is re-exported by `adapters/youtube.py`. Plan 05's XHS adapter imports it from `clipsieve.adapters.base` instead of defining its own; plan 03's Runner catches it by name.
12. **Caption sidecar `lang` is optional.** `<media>.transcript.json` is `{"lang"?: str, "segments": [...]}`; readers treat a missing or empty `lang` as `None` (refines B.7).
13. **Whisper language hints are normalised** to the lowercase primary subtag (`zh-Hans` → `zh`) and passed as `None` (auto-detect) when not a Whisper language. Shared `WhisperASR`/`PaddleOCRBackend` instances serialise model construction and inference with a per-instance lock because the Runner extracts with concurrency 2 via `asyncio.to_thread` (E.8).
14. **`packet.state_json(state)`** is the canonical compact serialisation the token estimate is measured on; plan 03 sends the dict to the TypeSafe SDK and must confirm the SDK does not escape non-ASCII (otherwise send `state_json`).

## Addendum C: contract decisions made by plan 05 (binding for plan 03 where noted)

1. **MediaCrawler is a pinned sibling checkout**, not a dependency: `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` (default `../MediaCrawler`, a relative value resolved against `config.REPO_ROOT`, never the cwd), `CLIPSIEVE_XHS_TIMEOUT_S` (900), and `XhsSettings.clipsieve_xhs_pinned_commit`. Its `pyproject.toml` has no build system, so it cannot be installed from git. Its licence is the Non-Commercial Learning License 1.1; the contrib README quotes it.
2. **Runner invocation:** `uv run --project <mc> python <mc>/main.py --platform xhs --lt qrcode --type search --keywords <q> --start <page> --get_comment yes --get_sub_comment no --get_media no --save_data_option jsonl --save_data_path <workdir> --headless no` (amended to the argv verified against the pinned commit: `--lt qrcode`, `--get_comment yes`, `--save_data_path`). cwd is the MediaCrawler checkout, because `main.py` opens `libs/*.js` relative to cwd and exits 1 otherwise; the per-run temp workdir is passed through `--save_data_path`, so MediaCrawler writes `<workdir>/xhs/{jsonl,...}` and nothing lands in the checkout. Output discovered by glob `<workdir>/xhs/jsonl/search_{contents,comments}_*.jsonl`.
3. **`creator_hash = hash_creator(<MediaCrawler creator_hash>, salt)`** because raw user ids are not present in its output.
4. **Video notes:** one `Media` entry with `index = 0`; `duration_s`, `width`, `height` left unset for `extract_evidence` to fill. The adapter downloads images and video itself with httpx; MediaCrawler's `--get_media` is not used.
5. **`Post.lang`** is `zh` when CJK characters are at least 30 percent of letters, else `en`.
6. **`MediaDownloadError`** raised from `fetch_media`; plan 03's Runner treats it as a recoverable per-post `error` event and continues.
7. **Golden label types:** Choice is the label string, Score is a 1-based integer level, Noul is a boolean. Lines starting with `#` are comments. The shipped `en-100.jsonl` and `zh-100.jsonl` are header-only until hand-labelled.
8. **Score agreement** is within one level of `predicted_level`, which follows E.3: index = argmax `probabilities` key (else `round(value)`), first = minimum integer legend key (else 0), level = index - first + 1 clamped to `1..levels`, compared with the 1-based golden label. Noul is correct when on the labelled side of 0.5.
9. **`Translator` protocol** in `evals/score.py` with `IdentityTranslator` and `ClaudeCliTranslator` (same `claude -p` flag set, model `sonnet`, effort `low`). `translate` mode rewrites `post.title`, `post.caption`, `transcript[].text`, `ocr[].text`, `comments.sample[]` only.
10. **Bilingual examples** file `rubrics/<pack>.zh-examples.yaml` maps `question_id -> {label or level: example}` and is appended to criteria text.
11. **`sieve eval`** takes `--rubrics-dir` and `--judge-fixtures`. `evals/` is imported by adding the repo root to `sys.path` via `clipsieve.calibration.repo_root()`; **plan 05 itself creates** `backend/clipsieve/calibration.py` with `repo_root() -> Path` and the marker-block writer (plan 03 does not).
12. **Calibration results** are written between `<!-- results:start -->` and `<!-- results:end -->` as one `### <golden stem> <mode> (<date>)` section per golden set and mode (for example `### zh-100 raw (2026-10-03)`); `write_results(path, stem, mode, table_md, when)` replaces only that section.
13. **Registry test hook:** the contrib discovery test monkeypatches `registry._iter_entry_points`; plan 02's `load_adapters` must obtain entry points through a module-level `_iter_entry_points()` function. `backend/tests/adapters/test_registry.py` already covers the monkeypatched discovery; plan 05 adds no second discovery test and verifies real discovery against the installed package (Task 4 Step 6, CI).
14. **Healthcheck** verifies CDP reachability on the configured port and the pinned MediaCrawler commit. There is no login-state file check, because in CDP mode the session lives in the user's Chrome.
15. **XHS media URLs are cached by the adapter** in `<data_dir>/adapter-cache/xiaohongshu/<safe_id>.media.json` (written by `search`, read by `fetch_media`, memory first then disk); no `Media.url`; a missing cache entry raises `MediaDownloadError`. `fetch_media` never reads the raw payload or `raw_ref`, because the Runner relocates it first (B.10). `MediaDownloadError` is imported from `clipsieve.adapters.base` (B.11), never redefined. Images are saved as `img_NN.jpg` (B.2).
16. **XHS settings resolution.** `XhsSettings` reads `(REPO_ROOT/.env, .env)` with `extra="ignore"` and `env_ignore_empty=True`; `.env.example` ships `CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler` and `CLIPSIEVE_XHS_TIMEOUT_S=900`. The CDP port is owned by core `Settings.clipsieve_xhs_chrome_cdp_port`; the adapter passes it to the runner and `XhsSettings` does not re-declare it. The root `lint` script also runs ruff over `evals/` and `contrib/`.
17. **Stored XHS raw payloads** drop comment `creator_hash`, `nickname` and `pictures` and the note's `xsec_token` (backend/AGENTS.md: comment author identifiers are stripped from raw); `Post.creator_hash` is still derived from the note's MediaCrawler `creator_hash` with `ensure_creator_salt(settings)` (A.12).
18. **Eval robustness.** `score_pack` skips an item whose judge call raises `JudgeFailed`, counts it in `EvalReport.n_skipped` and logs it; `ClaudeCliTranslator` runs `claude -p` with a subprocess timeout. The root `AGENTS.md` index rows for `contrib/adapter-xhs-mediacrawler/AGENTS.md` and `evals/AGENTS.md` are table rows.
19. **XHS api runner (plan 06).** `CLIPSIEVE_XHS_RUNNER=api` (default) collects through `https://edith.xiaohongshu.com` with cookies read from the user's browser over CDP and `xhshow` signatures; `note_type=1` when `CLIPSIEVE_XHS_NOTE_KINDS=video`; one `/feed` detail request per note for the stream URL; comments opt-in. Records keep the MediaCrawler jsonl keys, so `mapping.py`, raw-payload stripping (C.17), the media-URL cache (C.15) and `fetch_media` are unchanged. `mediacrawler` keeps C.2's invocation as the fallback.

## Addendum D: contract decisions made by plan 04 (binding for plans 01 to 03)

1. **Thumbnails.** Tiles request `GET /api/runs/{id}/media/{post_id}/thumb.jpg` with the post id URL-encoded (`local%3Afx-001`) and fall back to a kind icon on 404. Plan 02's `fetch_media` (or `extract_evidence`) writes `thumb.jpg`, 256px wide, from the first keyframe or first image into `media_dir(post_id)`. Plan 03's media route decodes the path segment.
2. **Fake mode seeds the local adapter.** With `CLIPSIEVE_EXPLAIN_BACKEND=fake`, `get_context()` wires a `local` adapter that returns the five fixture posts regardless of brief, and the fake planner returns `quantities: {local: 5}`. The e2e flow depends on this.
3. **`DashboardState` gains `lastSeq: number` and `startedAt: string | null`** (additive). Before `done`, `elapsed_s` is computed client-side from the first event's `ts`.
4. **Error-to-tile rule.** An `error` event with `post_id` and `where` starting with `"judge"` marks the tile `judge_failed`. Plan 03 emits `where: "judge.pass_one"` or `"judge.pass_two"` for per-post judge failures, and `"adapter.<platform>"`, `"evidence.<step>"`, `"explain"` elsewhere.
5. **Aggregates.** All pass-two `choice` answers aggregated by label; `persona_fit` by rounded level. The UI shows `hook_type`, `format`, `persona_fit`.
6. **Replay source.** Replay loads the log via the same SSE endpoint with `after=0`, stopping on `done` or a `failed`-stage event. Plan 03's SSE handler must serve a finished run from seq 1 and then close. No separate log endpoint.
7. **Generated TS type names** must be named exports: `Post, PostText, Media, Metrics, Comment, Evidence, TranscriptSegment, OcrItem, CommentSummary, RunEvent, RunEventType, Stage, RubricPack, Plan, Brief, Query, Report, Pattern, ClipExplanation, Gap, Concept, JudgeResult, JudgeAnswer, Run, Counters`. Plan 01's `generate.ts` emits every `$def` as a named export.
8. **Biome nesting.** `frontend/biome.jsonc` is `{ "extends": ["//"] }`; root `biome.jsonc` sets `"root": true`.
9. **Frontend package name** is `frontend`, so root `--filter frontend` scripts resolve.

## Addendum E: contract decisions made by plan 03 (binding for plans 04 and 05)

1. **`JudgeFailed(post_id, attempts, cause)`** lives in `judge/base.py`. `TypeSafeJudge.__init__` gains `client_factory` and `sleeper` kwargs for tests. Retryable = HTTP 429/529 or an exception class name containing "ratelimit" or "overloaded". Backoff `0.5s * 2^n`, capped at 8s, with jitter.
2. **`RecordedJudge`** exposes `calls: list[tuple[str, str]]` and raises `FixtureMissing(FileNotFoundError)`. Fixtures are generated by `backend/tests/fixtures/judge/make_fixtures.py`; the output is committed.
3. **Score normalisation:** 0-indexed levels when `legend` is absent; otherwise the minimum integer legend key is level 0. Noul confidence is `|2p - 1|`. `composite()` takes optional `weights` and `question_ids` kwargs and renormalises over the weighted questions present; choice answers never contribute. `Selection.dropped` reasons are `hard_filter`, `quota`, `not_selected`. Ties break by `post_id`.
4. **Backends never know `run_id`.** Callers overwrite `Plan.run_id` and `Report.run_id`. `PlanRequest` model and `cli_payload(mode, body)` live in `explain/base.py`; `"mode"` is the only non-schema key in CLI payloads. `ClaudeCliBackend` has constants `PLAN_TASK`, `EXPLAIN_TASK`, `timeout_s=900`, and one retry on bad citations or schema failure. Shim env contract: `CLIPSIEVE_SHIM_STATE`, `CLIPSIEVE_SHIM_BAD_FIRST`, `CLIPSIEVE_SHIM_FAIL`.
5. **`build_plan(run_id, brief_text, platforms, quantities, rubric_pack, language_hint, backend, rubrics_dir)`**. `default_lang` maps xiaohongshu, douyin and bilibili to `zh`. `pack_summaries(rubrics_dir)` exists in `planner/plan.py`.
6. **Additional modules:** `adapters/fixture.py` (`FixtureAdapter`, platform `local`, returns the five fixture posts regardless of query; used when `CLIPSIEVE_FIXTURE_DIR` is set), `pipeline/state.py` (`RunState` at `<run>/state.json` with `pass_one_kept`, `pass_one_dropped`, `judge_failed`, `extracted`), `api/context.py` (`AppContext`, `build_context`, `set_context`, `runner_for`). New setting `clipsieve_fixture_dir: Path | None` from env `CLIPSIEVE_FIXTURE_DIR`.
7. **Fake mode implies fixtures.** When `CLIPSIEVE_EXPLAIN_BACKEND=fake` and `CLIPSIEVE_FIXTURE_DIR` is unset, `build_context` sets the fixture dir to `backend/tests/fixtures` so the `local` adapter is the `FixtureAdapter`, the judge is `RecordedJudge`, and ASR/OCR/frames are fakes. This satisfies Addendum D.2 without a second switch.
8. **Runner:** pass one judges all posts concurrently, then emits `pass_one_judged` with `kept`. Extraction concurrency 2 via `asyncio.to_thread`. `pause()` is cooperative; `run()` returns normally when paused and sets `run.paused`; `resume_flag()` clears it. Explain failure moves the stage to `failed`: `error` (stage `explaining`, `recoverable: false`) first, then `stage_changed` to `failed` as the last event, because `follow_events` and the dashboard stop at the first failed-stage event. `post_state()` returns the six `PostView.state` values.
9. **API:** `create_app(ctx=None)` factory; extra `GET /api/health`; 201 on create, 409 on double approve or on editing an approved plan, 422 for unknown platforms.
10. **CLI exit codes:** 0 ok, 1 run failed or not found, 2 usage error or declined plan.

11. **Runner emits `run_created`.** The `Runner` constructor emits `run_created` when the run's event log is empty; `POST /runs` and `sieve run` do not emit it. **Planning failure** emits a recoverable `error` event with `where: "planner"` (stage `planning`); the plan page should surface it instead of waiting for `plan_ready` forever.
12. **SSE reconnect precedence.** `GET /runs/{id}/events` honours both `?after=N` and the `Last-Event-ID` header and streams events with `seq > max(after, Last-Event-ID)`. A 409 is returned for `PUT /plan` and `POST /approve` while the planner is still running, and for `POST /reselect` while the pipeline is busy or before a selection exists. `GET /posts` `limit` must be 1..1000. `GET /runs/{id}` returns `"plan": null` while planning (the one explicit null on the wire).
13. **App context is built once per process** under a lock (`api/context.py`); fake mode (E.7) never constructs `TypeSafeJudge`.

14. **Plan 03 final-review outcomes (binding for plans 04 and 05).** (a) A run whose shortlist is empty (nothing collected, every post judge-failed, filtered or sent to review) FAILS at `explaining` without calling the explain backend: `error {where: explain, recoverable: false}` then `stage_changed -> failed`; the frontend must render this state. (b) `ExplainPacket.posts` is `list[ExplainPost]` — a `Post` without `comments`; transcript and OCR text are capped at `EXPLAIN_TEXT_CAP = 4000` characters per post on a copy of the evidence (`truncated: true` on the copy; stored evidence untouched). (c) `pack_summaries` skips any `rubrics/*.yaml` that does not load as a pack (plan 05's `*.zh-examples.yaml` sidecar) and logs `rubric_pack_skipped` with the reason; `find_pack` raises `PackNotFound` for such files, surfaced as 422 / CLI exit 2 with the load error in the message. (d) The "already judged" check reads the SQLite judge row; `sieve reindex` rebuilds rows from `judge/*.json`.

## Addendum F: reconciliation of plans 01 to 05 (applied 2026-10-03)

Patches made so the five plans agree with this contract and with each other:

- plan 01 task 1: root `biome.jsonc` sets `"root": true` so `frontend/biome.jsonc` can extend `"//"` (D.8).
- plan 01 task 3: `generate.py` adds `--use-subclass-enum`; generated enums are `str` subclasses, so `post.kind == "video"` and `post.kind.value == "video"` are both true. This refines A.8: `.value` still works, and the plain-string comparisons in plans 02, 03 and 05 are valid as written.
- plan 01 task 3 and self-review: notes updated to describe the str-subclass enums.
- plan 02 task 2: `pillow>=10.4` added to core dependencies.
- plan 02 task 11: `extract_evidence` writes `media/<safe_id>/thumb.jpg` (256px wide, JPEG) from the first keyframe or first image via new `write_thumbnail(paths, post, source)`; idempotent; failures logged, never fatal (D.1). New test `test_thumbnail_written_256_wide_for_video_and_image_note`; missing-media test asserts no thumb; expected counts 9 to 10.
- plan 02 task 12: `backend/AGENTS.md` evidence section documents the thumbnail.
- plan 03 task 9: `build_context` defaults `clipsieve_fixture_dir` to `backend/tests/fixtures` (`DEFAULT_FIXTURE_DIR`) when the explain backend is `fake` and the dir is unset, instead of raising (D.2, E.7).
- plan 03 task 9: `Run.stage` is assigned `Stage(to)` and `Stage("failed")`, never a bare string; the implementation note is rewritten accordingly.
- plan 03 task 9: error `where` values are now `judge.<pass_name>`, `adapter.<platform>` (collect and fetch_media failures), `evidence.extract`, `explain` (D.4). `fetch_media` and `extract_evidence` have separate try blocks so a contrib `MediaDownloadError` is reported as an adapter error and extraction still runs on whatever media exists (C.6).
- plan 03 task 10: new API test `test_media_route_decodes_post_id_and_blocks_traversal` covering `local%3Afx-001/thumb.jpg` (200) and a `..%2F` path (404); expected count 10 to 11.
- plan 04 task 11: Playwright `webServer` comment records that fake mode needs no `CLIPSIEVE_FIXTURE_DIR`.

Verified without changes: plan 02 exposes `registry._iter_entry_points()` and plan 05 patches that name (C.13); plan 05 alone creates `backend/clipsieve/calibration.py` (C.11); plan 03's SSE endpoint serves a finished run from `after=0` to its terminal event then closes, and plan 04's replay consumes exactly that (D.6); `build_plan` has the E.5 signature in plan 03 and is not called by plan 05; `Selection` is defined only in plan 01; event payloads in plans 03 and 04 match `events/payloads.py` including the `from` alias; no plan assumes `len // 3` for tokens (B.4); each plan's final task adds exactly its own directories to the root Child DOX Index (01: `backend/`, `packages/schema/`; 03: `rubrics/`; 04: `frontend/`; 05: `contrib/adapter-xhs-mediacrawler/`, `evals/`); plan 01's `generate.ts` emits every `$def` and every file title as a named export (D.7). No placeholders found. Plan index and dependency order are unchanged.
