# clipsieve v0.1 Plan 03: Judge, Select, Explain, Runner, API, CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn collected posts and evidence into Jev scores, a diverse shortlist, and a Claude report, exposed through a FastAPI server with server-sent events and a `sieve` CLI, all runnable end to end against fixtures with no network.

**Architecture:** `judge/` wraps TypeSafe behind a `Judge` protocol with a recorded fake. `select/` is pure functions over stored `JudgeResult`s. `explain/` wraps `claude -p` behind an `ExplainBackend` protocol with a fixture fake and a shim binary. `pipeline/runner.py` drives the stages, emitting typed `RunEvent`s to the JSONL log that `api/events.py` streams. `cli.py` reuses the same runner.

**Tech Stack:** Python 3.12, uv, Pydantic v2, `typesafe-sdk`, FastAPI, uvicorn, typer, PyYAML, structlog, pytest + pytest-asyncio (auto), httpx for API tests.

**Spec:** `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md`. Binding names: `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`. Read both before any task.

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

## Prerequisites from plans 01 and 02 (consumed, not re-created)

From plan 01: `clipsieve.models` (all eight schemas incl. `Question = ChoiceQuestion | ScoreQuestion | NoulQuestion`, `JudgeResult`, `JudgeAnswer`, `Counters`, `Run`, `Plan`, `Brief`, `Query`, `Report`, `Pattern`, `ClipExplanation`, `Gap`, `Concept`, `RubricPack`, `SelectionPolicy`, `RunEvent`, `RunEventType`, `Stage`), `clipsieve.config.Settings/get_settings`, `clipsieve.store.paths.RunPaths/safe_post_filename`, `clipsieve.store.db.get_engine/init_db`, `clipsieve.store.repo.RunRepository/RunNotFound`, `clipsieve.events.writer.EventWriter`, `clipsieve.events.reader.read_events/follow_events`, fixtures `tests/fixtures/posts/*.json` (ids `local:fx-001`..`local:fx-005`) and `tests/fixtures/raw/*.json`, `tests/conftest.py` with fixtures `tmp_data_dir`, `repo`, `fixture_posts: list[Post]`.

From plan 02: `clipsieve.adapters.base.Adapter/AdapterHealth/hash_creator`, `clipsieve.adapters.registry.load_adapters`, `LocalImportAdapter`, `YouTubeAdapter`, `clipsieve.evidence.asr.ASR/FakeASR`, `clipsieve.evidence.ocr.OCR/FakeOCR`, `clipsieve.evidence.frames.FrameExtractor/FakeFrames`, `clipsieve.evidence.packet.build_state/build_metadata_state/MAX_STATE_TOKENS`, `clipsieve.evidence.extract.extract_evidence`.

Also binding: Addendum A and Addendum B at the end of the overview. In particular: generated enums are `Enum` classes (compare with `.value`, pass plain strings on input); `Selection` already exists in `backend/clipsieve/select/select.py`; `RunPaths.selection_json` exists; event payload models live in `clipsieve.events.payloads`; adapters write raw payloads to `<data_dir>/incoming/<platform>/` and the Runner relocates them; `Evidence.truncated` is set by the Runner; `[project.scripts] sieve` is already declared.

If any of these names is missing when you start a task, stop and fix the earlier plan's output; do not fork a copy here.

## Review Focus

1. **Jev 429 on one post must not stall the others or fail the run** (overview item 2). Pinned by Task 2 `test_one_post_rate_limited_others_proceed` and Task 9 `test_judge_failed_post_excluded_run_completes`.
2. **Report citing an unknown post id is rejected, retried once, surfaced as an error** (overview item 4). Pinned by Task 7 `test_bad_citation_retried_once_then_ok` and `test_bad_citation_twice_raises`, Task 9 `test_explain_failure_marks_run_failed_with_shortlist_intact`.
3. **Reconnect with `after=<seq>` returns exactly the missed events** (overview item 3). Pinned by Task 10 `test_sse_after_returns_exact_tail`.
4. **Chinese text survives adapter → SQLite → JSONL → SSE byte-for-byte** (overview item 5). Pinned by Task 10 `test_chinese_caption_roundtrip`.
5. **A run killed mid-stage resumes without re-judging already judged posts** (spec §12 idempotency). Pinned by Task 9 `test_resume_after_crash_no_duplicate_judge_calls`.
6. **Pause between posts leaves the run resumable and the log consistent**. Pinned by Task 9 `test_pause_then_resume_completes`.
7. **A pack whose `persona_fit` criteria are replaced by the planner still has exactly five levels and the legend maps back to them**. Pinned by Task 1 `test_with_persona_criteria_requires_five`.

---

### Task 1: Rubric pack `creator-hooks-v1` and `judge/rubric.py`

**Files:**
- Create: `rubrics/creator-hooks-v1.yaml`
- Create: `rubrics/creator-hooks-v1.calibration.md`
- Create: `rubrics/AGENTS.md`
- Create: `backend/clipsieve/judge/__init__.py`
- Create: `backend/clipsieve/judge/rubric.py`
- Modify: `backend/pyproject.toml` (add `pyyaml`, `typesafe-sdk`)
- Modify: `AGENTS.md` (Child DOX Index: add `rubrics/`)
- Test: `backend/tests/judge/test_rubric.py`

**Interfaces:**
- Consumes: `clipsieve.models.RubricPack`, `ChoiceQuestion`, `ScoreQuestion`, `NoulQuestion`, `Question`, `JudgeAnswer`.
- Produces:
  - `load_pack(path: Path) -> RubricPack`
  - `find_pack(name: str, rubrics_dir: Path) -> RubricPack` (raises `PackNotFound`)
  - `questions_for_pass(pack: RubricPack, pass_name: str) -> dict[str, Question]`
  - `to_typesafe(question: Question) -> Choice | Score | Noul`
  - `from_typesafe(question_id: str, question: Question, response) -> JudgeAnswer`
  - `with_persona_criteria(pack: RubricPack, criteria: list[str]) -> RubricPack`
  - `class PackNotFound(Exception)`

- [x] **Step 1: Add dependencies**

```bash
cd backend && uv add pyyaml typesafe-sdk && uv add --dev types-PyYAML
```

Expected: `pyproject.toml` gains `pyyaml>=6` and `typesafe-sdk` under `[project] dependencies`; `uv.lock` updated.

- [x] **Step 2: Write the rubric pack in full**

`rubrics/creator-hooks-v1.yaml`:

```yaml
name: creator-hooks-v1
version: 1
jev_model: jev-1.13.0
language_mode: raw
metadata_pass:
  - niche_relevance
  - format_guess
pass_one_keep: 0.30
questions:
  hook_type:
    type: choice
    instructions: "Which opening hook does the first sentence or first on-screen text use? Judge from `transcript[0]` if present, otherwise from the first `ocr` item, otherwise from `post.text.caption`."
    criteria:
      curiosity_gap: "Withholds a key fact the viewer wants and promises to reveal it"
      bold_claim: "Asserts something surprising, contrarian or absolute"
      result_first: "Shows or states the outcome before the process or story"
      problem: "Names a pain, fear or frustration the viewer recognises"
      story: "Opens mid-scene or with a personal anchor such as a date, place or person"
      authority: "Leads with credentials, numbers achieved or proof of expertise"
      none: "No deliberate hook: greeting, logo, slow establishing context"
  hook_strength:
    type: score
    instructions: "How likely is the first three seconds (first transcript segment and first on-screen text) to keep the audience described in `brief.audience` watching?"
    criteria:
      - "No hook. Greeting, logo, or slow context."
      - "Topic stated, no reason to keep watching."
      - "Question or claim with some tension."
      - "Specific promise, surprising claim, or visible result in the first sentence."
      - "Immediate pattern interrupt plus a clear stake for this audience."
  format:
    type: choice
    instructions: "Dominant format of the post, judged from `post.kind`, `transcript`, `ocr` and `post.text.caption`."
    criteria:
      talking_head: "One person speaking to camera for most of the post"
      vlog_montage: "Cut sequence of real-life scenes, often with voiceover or music"
      screen_demo: "Screen recording or product walkthrough"
      ugc_testimonial: "Casual first-person review or reaction"
      image_carousel: "Multiple still images with text, typical of Xiaohongshu notes"
      meme: "Joke format, template, or trend sound"
      other: "None of the above"
  persona_fit:
    type: score
    instructions: "How closely does this creator's situation and voice match `brief.persona`? Judge from who is speaking, where they are, and how they describe themselves."
    criteria:
      - "Unrelated creator and situation"
      - "Adjacent niche or similar audience, different situation"
      - "Same niche and situation, clearly different voice"
      - "Close match in situation and voice"
      - "Could be the user's own channel"
  risky_claim:
    type: noul
    instructions: "Does the post make a health, financial, legal or regulated claim without support? Visa, tax, medical, investment and housing-law claims count. Personal anecdotes stated as personal experience do not."
  niche_relevance:
    type: score
    instructions: "Is this post about `brief.topic`, judging from `post.text.caption`, `post.text.hashtags` and `comments`?"
    criteria:
      - "Unrelated"
      - "Mentions in passing"
      - "Partly about it"
      - "Mainly about it"
      - "Entirely about it"
  format_guess:
    type: choice
    instructions: "Best guess at format from `post.kind`, `post.text.caption` and `post.text.hashtags` only. No transcript is available for this question."
    criteria:
      talking_head: "Caption suggests a person speaking to camera, explaining or advising"
      vlog_montage: "Caption suggests a day-in-the-life, trip or scene sequence"
      image_carousel: "Post is a multi-image note"
      unknown: "Not enough signal from caption and hashtags"
selection:
  weights:
    hook_strength: 0.4
    persona_fit: 0.4
    niche_relevance: 0.2
  hard_filters:
    risky_claim_max: 0.5
  review_confidence_below: 0.5
  shortlist_size: 40
  diversity:
    format:
      max_share: 0.4
    hook_type:
      max_share: 0.5
```

- [x] **Step 3: Write the calibration template and DOX docs**

`rubrics/creator-hooks-v1.calibration.md`:

```markdown
# creator-hooks-v1 calibration

Pack version: 1. Jev model: jev-1.13.0. Status: NOT CALIBRATED.

Filled by `sieve eval` (plan 05). Do not edit the tables by hand.

## English golden set (evals/golden/en-100.jsonl)

| question | n | agreement | mean confidence | notes |
|---|---|---|---|---|
| hook_type | | | | |
| hook_strength | | | | |
| format | | | | |
| persona_fit | | | | |
| risky_claim | | | | |
| niche_relevance | | | | |
| format_guess | | | | |

## Chinese golden set (evals/golden/zh-100.jsonl)

| mode | question | n | agreement | mean confidence |
|---|---|---|---|---|
| raw | | | | |
| translate | | | | |
| bilingual | | | | |

## Decision

language_mode: raw (default until a mode wins by at least 5 points of agreement on hook_type and hook_strength).
```

`rubrics/AGENTS.md`:

```markdown
# rubrics/ — AGENTS.md

Rubric packs are data, not code. One YAML per pack, validated against `packages/schema/schemas/rubric_pack.json` via `clipsieve.judge.rubric.load_pack`.

## Contracts

- Question shapes are Jev's real primitives: `choice` with a `criteria` map, `score` with 2 to 10 written level descriptions, `noul` with instructions only. Never a numeric scale.
- `metadata_pass` lists question ids answerable from caption, hashtags, comments and metrics alone. Every id must exist in `questions`.
- `selection.weights` may reference only `score` and `noul` questions. `diversity` may reference only `choice` questions.
- `persona_fit` must be a 5-level `score`; the planner replaces its criteria per run.
- `jev_model` is pinned. Bump `version` when any question text changes; thresholds tuned on one version do not transfer.
- Each pack has a `<name>.calibration.md` written by `sieve eval`. A pack is "calibrated" only when that file says so.

## Child DOX Index

None.
```

Root `AGENTS.md`: replace the Child DOX Index line for rubrics so the list reads `rubrics/` as present (keep the others as "when created").

- [x] **Step 4: Write the failing tests**

`backend/tests/judge/__init__.py` (empty) and `backend/tests/judge/test_rubric.py`:

```python
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipsieve.judge.rubric import (
    PackNotFound,
    find_pack,
    from_typesafe,
    load_pack,
    questions_for_pass,
    to_typesafe,
    with_persona_criteria,
)
from clipsieve.models import ChoiceQuestion, NoulQuestion, ScoreQuestion

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"


def test_load_pack_parses_real_yaml():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert pack.name == "creator-hooks-v1"
    assert pack.jev_model == "jev-1.13.0"
    assert set(pack.questions) == {
        "hook_type", "hook_strength", "format", "persona_fit",
        "risky_claim", "niche_relevance", "format_guess",
    }
    assert isinstance(pack.questions["hook_type"], ChoiceQuestion)
    assert isinstance(pack.questions["hook_strength"], ScoreQuestion)
    assert isinstance(pack.questions["risky_claim"], NoulQuestion)
    assert len(pack.questions["hook_strength"].criteria) == 5


def test_find_pack_by_name_and_missing():
    assert find_pack("creator-hooks-v1", RUBRICS).version == 1
    with pytest.raises(PackNotFound):
        find_pack("nope", RUBRICS)


def test_questions_for_pass():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert set(questions_for_pass(pack, "pass_one")) == {"niche_relevance", "format_guess"}
    assert set(questions_for_pass(pack, "pass_two")) == set(pack.questions)
    with pytest.raises(ValueError):
        questions_for_pass(pack, "pass_three")


def test_to_typesafe_shapes():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    choice = to_typesafe(pack.questions["hook_type"])
    score = to_typesafe(pack.questions["hook_strength"])
    noul = to_typesafe(pack.questions["risky_claim"])
    assert type(choice).__name__ == "Choice"
    assert type(score).__name__ == "Score"
    assert type(noul).__name__ == "Noul"
    assert "curiosity_gap" in choice.criteria
    assert len(score.criteria) == 5


def test_from_typesafe_maps_each_primitive():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    response = SimpleNamespace(
        choices={"hook_type": SimpleNamespace(choice="story", probabilities={"story": 0.7, "none": 0.3}, confidence=0.53)},
        scores={"hook_strength": SimpleNamespace(score=3.2, legend={"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"}, probabilities={"3": 0.8, "4": 0.2}, confidence=0.75)},
        nouls={"risky_claim": SimpleNamespace(noul=0.12)},
    )
    a = from_typesafe("hook_type", pack.questions["hook_type"], response)
    assert a.type.value == "choice" and a.value == "story" and a.confidence == 0.53
    b = from_typesafe("hook_strength", pack.questions["hook_strength"], response)
    assert b.type.value == "score" and b.value == 3.2 and b.legend["4"] == "e"
    c = from_typesafe("risky_claim", pack.questions["risky_claim"], response)
    assert c.type.value == "noul" and c.value == 0.12 and c.confidence is None


def test_with_persona_criteria_requires_five():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    new = with_persona_criteria(pack, ["a", "b", "c", "d", "e"])
    assert new.questions["persona_fit"].criteria == ["a", "b", "c", "d", "e"]
    assert pack.questions["persona_fit"].criteria[0] == "Unrelated creator and situation"  # original untouched
    with pytest.raises(ValueError):
        with_persona_criteria(pack, ["only", "four", "levels", "here"])
```

- [x] **Step 5: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/judge/test_rubric.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.judge'`.

- [x] **Step 6: Implement `judge/rubric.py`**

`backend/clipsieve/judge/__init__.py`: empty.

`backend/clipsieve/judge/rubric.py`:

```python
"""Load rubric packs and translate questions to and from TypeSafe primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from typesafe_sdk import Choice, Noul, Score

from clipsieve.models import (
    ChoiceQuestion,
    JudgeAnswer,
    NoulQuestion,
    Question,
    RubricPack,
    ScoreQuestion,
)

PASS_ONE = "pass_one"
PASS_TWO = "pass_two"
PERSONA_LEVELS = 5


class PackNotFound(Exception):
    pass


def load_pack(path: Path) -> RubricPack:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pack = RubricPack.model_validate(data)
    missing = [q for q in pack.metadata_pass if q not in pack.questions]
    if missing:
        raise ValueError(f"metadata_pass references unknown questions: {missing}")
    return pack


def find_pack(name: str, rubrics_dir: Path) -> RubricPack:
    path = rubrics_dir / f"{name}.yaml"
    if not path.exists():
        raise PackNotFound(f"no rubric pack named {name!r} in {rubrics_dir}")
    return load_pack(path)


def questions_for_pass(pack: RubricPack, pass_name: str) -> dict[str, Question]:
    if pass_name == PASS_ONE:
        return {q: pack.questions[q] for q in pack.metadata_pass}
    if pass_name == PASS_TWO:
        return dict(pack.questions)
    raise ValueError(f"unknown pass {pass_name!r}")


def to_typesafe(question: Question) -> Choice | Score | Noul:
    if isinstance(question, ChoiceQuestion):
        return Choice(instructions=question.instructions, criteria=dict(question.criteria))
    if isinstance(question, ScoreQuestion):
        return Score(instructions=question.instructions, criteria=list(question.criteria))
    if isinstance(question, NoulQuestion):
        return Noul(instructions=question.instructions)
    raise TypeError(f"unsupported question {type(question)!r}")


def from_typesafe(question_id: str, question: Question, response: Any) -> JudgeAnswer:
    if isinstance(question, ChoiceQuestion):
        a = response.choices[question_id]
        return JudgeAnswer(
            type="choice",
            value=str(a.choice),
            probabilities={str(k): float(v) for k, v in dict(a.probabilities).items()},
            confidence=float(a.confidence),
        )
    if isinstance(question, ScoreQuestion):
        s = response.scores[question_id]
        return JudgeAnswer(
            type="score",
            value=float(s.score),
            probabilities={str(k): float(v) for k, v in dict(s.probabilities).items()},
            confidence=float(s.confidence),
            legend={str(k): str(v) for k, v in dict(s.legend).items()},
        )
    if isinstance(question, NoulQuestion):
        n = response.nouls[question_id]
        return JudgeAnswer(type="noul", value=float(n.noul))
    raise TypeError(f"unsupported question {type(question)!r}")


def with_persona_criteria(pack: RubricPack, criteria: list[str]) -> RubricPack:
    if len(criteria) != PERSONA_LEVELS:
        raise ValueError(f"persona_fit needs exactly {PERSONA_LEVELS} levels, got {len(criteria)}")
    q = pack.questions["persona_fit"]
    if not isinstance(q, ScoreQuestion):
        raise ValueError("persona_fit must be a score question")
    new_q = q.model_copy(update={"criteria": list(criteria)})
    return pack.model_copy(update={"questions": {**pack.questions, "persona_fit": new_q}}, deep=True)
```

- [x] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/judge/test_rubric.py -q`
Expected: `6 passed`.

- [x] **Step 8: Commit**

```bash
git add rubrics backend/clipsieve/judge backend/tests/judge backend/pyproject.toml backend/uv.lock AGENTS.md
git commit -m "feat(judge): add creator-hooks-v1 rubric pack and rubric loader

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 2: `Judge` protocol and `TypeSafeJudge`

**Files:**
- Create: `backend/clipsieve/judge/base.py`
- Create: `backend/clipsieve/judge/typesafe_client.py`
- Test: `backend/tests/judge/test_typesafe_client.py`

**Interfaces:**
- Consumes: `clipsieve.models.JudgeResult`, `JudgeAnswer`, `Question`; `clipsieve.judge.rubric.to_typesafe`, `from_typesafe`.
- Produces:
  - `class Judge(Protocol): async def judge(self, post_id: str, pass_name: str, state: dict, questions: dict[str, Question], model: str) -> JudgeResult`
  - `JEV_USD_PER_MILLION_INPUT = 0.042`; `cost_usd(input_tokens: int) -> float`
  - `class JudgeFailed(Exception)` with attributes `post_id: str`, `attempts: int`
  - `class TypeSafeJudge(Judge)` with `__init__(self, api_key: str, concurrency: int = 16, max_retries: int = 5, client_factory: Callable[[], Any] | None = None, sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep)` and `async aclose()`

- [x] **Step 1: Write the failing tests**

`backend/tests/judge/test_typesafe_client.py`:

```python
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipsieve.judge.base import JudgeFailed, cost_usd
from clipsieve.judge.rubric import load_pack, questions_for_pass
from clipsieve.judge.typesafe_client import TypeSafeJudge

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"


class RateLimited(Exception):
    status_code = 429


def make_response(question_ids):
    choices, scores, nouls = {}, {}, {}
    for qid in question_ids:
        if qid in ("hook_type", "format", "format_guess"):
            choices[qid] = SimpleNamespace(choice="story", probabilities={"story": 0.9}, confidence=0.9)
        elif qid == "risky_claim":
            nouls[qid] = SimpleNamespace(noul=0.1)
        else:
            scores[qid] = SimpleNamespace(
                score=3.0, legend={str(i): f"L{i}" for i in range(5)}, probabilities={"3": 1.0}, confidence=1.0
            )
    return SimpleNamespace(
        model="jev-1.13.0", choices=choices, scores=scores, nouls=nouls,
        usage=SimpleNamespace(input_tokens=1234, output_tokens=0),
    )


class FakeClient:
    """Mimics AsyncTypeSafeClient.system_one. `fail_plan` maps post marker -> list of exceptions to raise first."""

    def __init__(self, fail_plan=None):
        self.calls = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.fail_plan = dict(fail_plan or {})

    async def system_one(self, *, state, questions, model):
        marker = state["post"]["id"]
        self.calls.append(marker)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            pending = self.fail_plan.get(marker)
            if pending:
                raise pending.pop(0)
            return make_response(list(questions))
        finally:
            self.in_flight -= 1

    async def aclose(self):
        pass


def pack_questions(pass_name):
    return questions_for_pass(load_pack(RUBRICS / "creator-hooks-v1.yaml"), pass_name)


def state_for(post_id):
    return {"brief": {"topic": "x"}, "post": {"id": post_id, "text": {"caption": "你好 Shanghai"}}}


def test_cost_usd():
    assert cost_usd(1_000_000) == pytest.approx(0.042)
    assert cost_usd(0) == 0.0


async def test_judge_returns_result_with_usage_and_latency():
    client = FakeClient()
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client)
    result = await judge.judge("local:a", "pass_two", state_for("local:a"), pack_questions("pass_two"), "jev-1.13.0")
    assert result.post_id == "local:a"
    assert result.pass_name.value == "pass_two"
    assert result.model == "jev-1.13.0"
    assert result.input_tokens == 1234
    assert result.latency_ms >= 0
    assert set(result.answers) == set(pack_questions("pass_two"))
    assert result.answers["risky_claim"].value == 0.1
    assert client.calls == ["local:a"]  # one request, all questions batched


async def test_concurrency_is_bounded():
    client = FakeClient()
    judge = TypeSafeJudge(api_key="k", concurrency=4, client_factory=lambda: client)
    qs = pack_questions("pass_one")
    await asyncio.gather(*[
        judge.judge(f"local:{i}", "pass_one", state_for(f"local:{i}"), qs, "jev-1.13.0") for i in range(20)
    ])
    assert client.max_in_flight <= 4
    assert len(client.calls) == 20


async def test_one_post_rate_limited_others_proceed():
    slept = []

    async def sleeper(s):
        slept.append(s)

    client = FakeClient(fail_plan={"local:slow": [RateLimited(), RateLimited()]})
    judge = TypeSafeJudge(api_key="k", concurrency=16, client_factory=lambda: client, sleeper=sleeper)
    qs = pack_questions("pass_one")
    ids = ["local:slow"] + [f"local:{i}" for i in range(15)]
    results = await asyncio.gather(*[judge.judge(i, "pass_one", state_for(i), qs, "jev-1.13.0") for i in ids])
    assert [r.post_id for r in results] == ids
    assert client.calls.count("local:slow") == 3  # two 429s then success
    assert len(slept) == 2 and slept[0] < slept[1]  # exponential


async def test_gives_up_after_max_retries():
    client = FakeClient(fail_plan={"local:dead": [RateLimited() for _ in range(5)]})
    judge = TypeSafeJudge(api_key="k", max_retries=5, client_factory=lambda: client, sleeper=lambda s: asyncio.sleep(0))
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge("local:dead", "pass_one", state_for("local:dead"), pack_questions("pass_one"), "jev-1.13.0")
    assert ei.value.post_id == "local:dead" and ei.value.attempts == 5


async def test_non_retryable_error_raises_immediately():
    class Bad(Exception):
        status_code = 422

    client = FakeClient(fail_plan={"local:bad": [Bad()]})
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client)
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge("local:bad", "pass_one", state_for("local:bad"), pack_questions("pass_one"), "jev-1.13.0")
    assert ei.value.attempts == 1 and client.calls.count("local:bad") == 1
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/judge/test_typesafe_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.judge.base'`.

- [x] **Step 3: Implement `judge/base.py`**

```python
"""Judge protocol shared by the TypeSafe client and the recorded fake."""

from __future__ import annotations

from typing import Protocol

from clipsieve.models import JudgeResult, Question

JEV_USD_PER_MILLION_INPUT = 0.042


def cost_usd(input_tokens: int) -> float:
    return input_tokens / 1_000_000 * JEV_USD_PER_MILLION_INPUT


class JudgeFailed(Exception):
    def __init__(self, post_id: str, attempts: int, cause: BaseException | None = None) -> None:
        super().__init__(f"judge failed for {post_id} after {attempts} attempt(s): {cause!r}")
        self.post_id = post_id
        self.attempts = attempts
        self.cause = cause


class Judge(Protocol):
    async def judge(
        self,
        post_id: str,
        pass_name: str,
        state: dict,
        questions: dict[str, Question],
        model: str,
    ) -> JudgeResult: ...
```

- [x] **Step 4: Implement `judge/typesafe_client.py`**

```python
"""TypeSafe Jev judge: one batched system_one request per post, bounded concurrency, backoff."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from clipsieve.judge.base import Judge, JudgeFailed
from clipsieve.judge.rubric import from_typesafe, to_typesafe
from clipsieve.models import JudgeResult, Question

log = structlog.get_logger(__name__)

RETRYABLE_STATUS = {429, 529}
BASE_BACKOFF_S = 0.5
MAX_BACKOFF_S = 8.0


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in RETRYABLE_STATUS:
        return True
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "overloaded" in name


def _default_client_factory(api_key: str) -> Callable[[], Any]:
    def factory() -> Any:
        from typesafe_sdk import AsyncTypeSafeClient

        return AsyncTypeSafeClient(api_key=api_key)

    return factory


class TypeSafeJudge(Judge):
    def __init__(
        self,
        api_key: str,
        concurrency: int = 16,
        max_retries: int = 5,
        client_factory: Callable[[], Any] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._factory = client_factory or _default_client_factory(api_key)
        self._client: Any = None
        self._sem = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._sleep = sleeper

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "aclose"):
            await self._client.aclose()
        self._client = None

    async def judge(
        self,
        post_id: str,
        pass_name: str,
        state: dict,
        questions: dict[str, Question],
        model: str,
    ) -> JudgeResult:
        ts_questions = {qid: to_typesafe(q) for qid, q in questions.items()}
        attempts = 0
        async with self._sem:
            while True:
                attempts += 1
                started = time.perf_counter()
                try:
                    response = await self._get_client().system_one(state=state, questions=ts_questions, model=model)
                except Exception as exc:  # noqa: BLE001 - classified below
                    if _is_retryable(exc) and attempts < self._max_retries:
                        delay = min(MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** (attempts - 1))) + random.uniform(0, 0.1)
                        log.warning("jev_retry", post_id=post_id, attempt=attempts, delay_s=round(delay, 2))
                        await self._sleep(delay)
                        continue
                    raise JudgeFailed(post_id, attempts, exc) from exc
                latency_ms = int((time.perf_counter() - started) * 1000)
                answers = {qid: from_typesafe(qid, q, response) for qid, q in questions.items()}
                usage = getattr(response, "usage", None)
                return JudgeResult(
                    post_id=post_id,
                    pass_name=pass_name,
                    model=str(getattr(response, "model", model)),
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    latency_ms=latency_ms,
                    answers=answers,
                )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/judge/test_typesafe_client.py -q`
Expected: `6 passed`.

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/judge backend/tests/judge
git commit -m "feat(judge): add Judge protocol and TypeSafeJudge with bounded concurrency and backoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `RecordedJudge` and the ten judge fixtures

**Files:**
- Create: `backend/clipsieve/judge/recorded.py`
- Create: `backend/tests/fixtures/judge/make_fixtures.py`
- Create: `backend/tests/fixtures/judge/local__fx-00{1..5}.pass_one.json` and `.pass_two.json` (generated by the script, committed)
- Test: `backend/tests/judge/test_recorded.py`

**Interfaces:**
- Consumes: `clipsieve.store.paths.safe_post_filename`, `clipsieve.models.JudgeResult`.
- Produces: `class RecordedJudge(Judge)` with `__init__(self, fixture_dir: Path)`, `calls: list[tuple[str, str]]` (post_id, pass_name) for test assertions; `class FixtureMissing(FileNotFoundError)`.

- [x] **Step 1: Write the fixture generator**

`backend/tests/fixtures/judge/make_fixtures.py`. The table encodes the intended story: fx-001 and fx-004 are strong Shanghai-expat vlogs, fx-002 is a talking-head visa explainer with a risky claim, fx-003 is an off-topic food carousel, fx-005 is an on-topic image carousel with a weak hook and low confidence (lands in review).

```python
"""Deterministic judge fixtures for the five fixture posts. Run: uv run python tests/fixtures/judge/make_fixtures.py"""

import json
from pathlib import Path

HERE = Path(__file__).parent
LEGEND5 = {str(i): f"level {i}" for i in range(5)}

# post -> (niche_relevance, format_guess, hook_type, hook_strength, format, persona_fit, risky_claim, min_conf)
TABLE = {
    "local:fx-001": (3.8, "vlog_montage", "story", 3.6, "vlog_montage", 3.9, 0.05, 0.85),
    "local:fx-002": (3.2, "talking_head", "bold_claim", 2.9, "talking_head", 2.4, 0.82, 0.80),
    "local:fx-003": (0.6, "image_carousel", "result_first", 2.1, "image_carousel", 0.4, 0.03, 0.90),
    "local:fx-004": (3.9, "vlog_montage", "curiosity_gap", 3.9, "vlog_montage", 3.5, 0.08, 0.88),
    "local:fx-005": (3.4, "image_carousel", "problem", 1.6, "image_carousel", 2.8, 0.10, 0.35),
}


def choice(value, conf, labels):
    rest = (1 - conf) / max(1, len(labels) - 1)
    return {"type": "choice", "value": value, "confidence": conf,
            "probabilities": {l: (conf if l == value else rest) for l in labels}}


def score(value, conf):
    lo, hi = int(value), min(4, int(value) + 1)
    frac = value - lo
    probs = {str(i): 0.0 for i in range(5)}
    probs[str(lo)] = round(1 - frac, 3)
    probs[str(hi)] = round(frac, 3) if hi != lo else probs[str(lo)]
    return {"type": "score", "value": value, "confidence": conf, "probabilities": probs, "legend": LEGEND5}


def noul(p):
    return {"type": "noul", "value": p}


FORMAT_GUESS = ["talking_head", "vlog_montage", "image_carousel", "unknown"]
HOOK = ["curiosity_gap", "bold_claim", "result_first", "problem", "story", "authority", "none"]
FORMAT = ["talking_head", "vlog_montage", "screen_demo", "ugc_testimonial", "image_carousel", "meme", "other"]

for post_id, (nr, fg, ht, hs, fm, pf, rc, conf) in TABLE.items():
    safe = post_id.replace(":", "__")
    p1 = {"niche_relevance": score(nr, conf), "format_guess": choice(fg, conf, FORMAT_GUESS)}
    p2 = {**p1, "hook_type": choice(ht, conf, HOOK), "hook_strength": score(hs, conf),
          "format": choice(fm, conf, FORMAT), "persona_fit": score(pf, conf), "risky_claim": noul(rc)}
    for pass_name, answers, tokens in (("pass_one", p1, 640), ("pass_two", p2, 2900)):
        doc = {"post_id": post_id, "pass_name": pass_name, "model": "jev-1.13.0",
               "input_tokens": tokens, "latency_ms": 310, "answers": answers}
        (HERE / f"{safe}.{pass_name}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", len(TABLE) * 2, "fixtures")
```

Run: `cd backend && uv run python tests/fixtures/judge/make_fixtures.py`
Expected: `wrote 10 fixtures` and ten JSON files beside the script.

- [x] **Step 2: Write the failing tests**

`backend/tests/judge/test_recorded.py`:

```python
from pathlib import Path

import pytest

from clipsieve.judge.recorded import FixtureMissing, RecordedJudge
from clipsieve.judge.rubric import load_pack, questions_for_pass
from clipsieve.models import JudgeResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"


async def test_recorded_judge_replays_fixture_and_records_call():
    judge = RecordedJudge(FIXTURES)
    qs = questions_for_pass(load_pack(RUBRICS / "creator-hooks-v1.yaml"), "pass_two")
    result = await judge.judge("local:fx-001", "pass_two", {"any": "state"}, qs, "jev-1.13.0")
    assert isinstance(result, JudgeResult)
    assert result.answers["hook_type"].value == "story"
    assert set(result.answers) == set(qs)
    assert judge.calls == [("local:fx-001", "pass_two")]


async def test_all_ten_fixtures_validate():
    judge = RecordedJudge(FIXTURES)
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    for i in range(1, 6):
        for pass_name in ("pass_one", "pass_two"):
            r = await judge.judge(f"local:fx-00{i}", pass_name, {}, questions_for_pass(pack, pass_name), "jev-1.13.0")
            assert r.pass_name.value == pass_name


async def test_missing_fixture_raises():
    judge = RecordedJudge(FIXTURES)
    with pytest.raises(FixtureMissing):
        await judge.judge("local:nope", "pass_one", {}, {}, "jev-1.13.0")
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/judge/test_recorded.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.judge.recorded'`.

- [x] **Step 4: Implement `judge/recorded.py`**

```python
"""Judge fake that replays JudgeResult fixtures by post id and pass."""

from __future__ import annotations

import json
from pathlib import Path

from clipsieve.judge.base import Judge
from clipsieve.models import JudgeResult, Question
from clipsieve.store.paths import safe_post_filename


class FixtureMissing(FileNotFoundError):
    pass


class RecordedJudge(Judge):
    def __init__(self, fixture_dir: Path) -> None:
        self._dir = Path(fixture_dir) / "judge"
        self.calls: list[tuple[str, str]] = []

    async def judge(
        self, post_id: str, pass_name: str, state: dict, questions: dict[str, Question], model: str
    ) -> JudgeResult:
        self.calls.append((post_id, pass_name))
        path = self._dir / f"{safe_post_filename(post_id)}.{pass_name}.json"
        if not path.exists():
            raise FixtureMissing(str(path))
        result = JudgeResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
        # Only the questions asked are returned, so a pack with fewer questions still works.
        answers = {qid: a for qid, a in result.answers.items() if not questions or qid in questions}
        return result.model_copy(update={"answers": answers})
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/judge -q`
Expected: `15 passed`.

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/judge/recorded.py backend/tests/judge backend/tests/fixtures/judge
git commit -m "feat(judge): add RecordedJudge fake and ten judge fixtures

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 4: `select/scoring.py`

**Files:**
- Create: `backend/clipsieve/select/scoring.py`
- Modify: `backend/clipsieve/select/__init__.py` (exists from plan 01; add exports)
- Test: `backend/tests/select/__init__.py`, `backend/tests/select/test_scoring.py`

**Interfaces:**
- Consumes: `clipsieve.models.JudgeAnswer`, `JudgeResult`, `RubricPack`, `ScoreQuestion`, `NoulQuestion`.
- Produces:
  - `normalize_score(answer: JudgeAnswer, levels: int) -> float`
  - `answer_confidence(answer: JudgeAnswer) -> float` (choice/score: `confidence`; noul: `abs(2p - 1)`)
  - `composite(result: JudgeResult, pack: RubricPack, weights: dict[str, float] | None = None, question_ids: set[str] | None = None) -> float`
  - `passes_hard_filters(result: JudgeResult, pack: RubricPack) -> bool`
  - `needs_review(result: JudgeResult, pack: RubricPack, weights: dict[str, float] | None = None) -> bool`

Decision: when `legend` is absent, levels are assumed 0-indexed, matching the TypeSafe composite-scoring cookbook (`score / 4` for five levels). When present, the minimum integer key in `legend` is the first level.

- [x] **Step 1: Write the failing tests**

`backend/tests/select/test_scoring.py`:

```python
from pathlib import Path

import pytest

from clipsieve.judge.rubric import load_pack
from clipsieve.models import JudgeAnswer, JudgeResult
from clipsieve.select.scoring import (
    answer_confidence,
    composite,
    needs_review,
    normalize_score,
    passes_hard_filters,
)

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
LEG0 = {str(i): f"L{i}" for i in range(5)}
LEG1 = {str(i): f"L{i}" for i in range(1, 6)}


def sc(value, conf=0.9, legend=LEG0):
    return JudgeAnswer(type="score", value=value, confidence=conf, probabilities={}, legend=legend)


def ch(value, conf=0.9):
    return JudgeAnswer(type="choice", value=value, confidence=conf, probabilities={value: conf})


def nl(p):
    return JudgeAnswer(type="noul", value=p)


def result(answers, post_id="local:x"):
    return JudgeResult(post_id=post_id, pass_name="pass_two", model="jev", input_tokens=1, latency_ms=1, answers=answers)


@pytest.mark.parametrize("value,legend,expected", [
    (0.0, LEG0, 0.0), (4.0, LEG0, 1.0), (2.0, LEG0, 0.5),
    (1.0, LEG1, 0.0), (5.0, LEG1, 1.0), (3.0, LEG1, 0.5),
    (2.0, None, 0.5), (-1.0, LEG0, 0.0), (9.0, LEG0, 1.0),
])
def test_normalize_score(value, legend, expected):
    assert normalize_score(sc(value, legend=legend), 5) == pytest.approx(expected)


def test_answer_confidence():
    assert answer_confidence(ch("a", 0.7)) == 0.7
    assert answer_confidence(sc(2.0, conf=0.4)) == 0.4
    assert answer_confidence(nl(0.5)) == pytest.approx(0.0)
    assert answer_confidence(nl(0.9)) == pytest.approx(0.8)
    assert answer_confidence(nl(0.1)) == pytest.approx(0.8)


def test_composite_weights_and_renormalises_over_present_questions():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    r = result({"hook_strength": sc(4.0), "persona_fit": sc(2.0), "niche_relevance": sc(0.0)})
    # 0.4*1.0 + 0.4*0.5 + 0.2*0.0 = 0.6
    assert composite(r, pack) == pytest.approx(0.6)
    # missing niche_relevance: weights renormalise over hook_strength and persona_fit -> (0.4*1 + 0.4*0.5)/0.8 = 0.75
    r2 = result({"hook_strength": sc(4.0), "persona_fit": sc(2.0)})
    assert composite(r2, pack) == pytest.approx(0.75)
    # override weights
    assert composite(r, pack, weights={"hook_strength": 1.0}) == pytest.approx(1.0)
    # restrict to question ids (pass one): equal weights over metadata questions that are score/noul
    r3 = result({"niche_relevance": sc(4.0), "format_guess": ch("vlog_montage")})
    assert composite(r3, pack, question_ids={"niche_relevance", "format_guess"}) == pytest.approx(1.0)


def test_composite_with_noul_weight_uses_probability():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    r = result({"risky_claim": nl(0.25)})
    assert composite(r, pack, weights={"risky_claim": 1.0}) == pytest.approx(0.25)


def test_composite_no_scorable_answers_is_zero():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert composite(result({"hook_type": ch("story")}), pack) == 0.0


def test_hard_filters():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert passes_hard_filters(result({"risky_claim": nl(0.5)}), pack) is True
    assert passes_hard_filters(result({"risky_claim": nl(0.51)}), pack) is False
    assert passes_hard_filters(result({}), pack) is True  # no answer, no filter


def test_needs_review_only_over_weighted_questions():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    ok = result({"hook_strength": sc(3.0, 0.9), "persona_fit": sc(3.0, 0.6), "niche_relevance": sc(3.0, 0.5), "hook_type": ch("story", 0.1)})
    assert needs_review(ok, pack) is False  # hook_type is not weighted; 0.5 is not below 0.5
    low = result({"hook_strength": sc(3.0, 0.49), "persona_fit": sc(3.0, 0.9), "niche_relevance": sc(3.0, 0.9)})
    assert needs_review(low, pack) is True
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/select/test_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.select.scoring'`.

- [x] **Step 3: Implement `select/scoring.py`**

```python
"""Pure scoring helpers over JudgeResults. No I/O, no model calls."""

from __future__ import annotations

from clipsieve.models import JudgeAnswer, JudgeResult, NoulQuestion, RubricPack, ScoreQuestion


def _first_level(answer: JudgeAnswer) -> int:
    if answer.legend:
        keys = [int(k) for k in answer.legend if str(k).lstrip("-").isdigit()]
        if keys:
            return min(keys)
    return 0


def normalize_score(answer: JudgeAnswer, levels: int) -> float:
    if levels < 2:
        raise ValueError("a score needs at least two levels")
    pos = (float(answer.value) - _first_level(answer)) / (levels - 1)
    return min(1.0, max(0.0, pos))


def answer_confidence(answer: JudgeAnswer) -> float:
    if answer.type.value == "noul":
        return abs(2.0 * float(answer.value) - 1.0)
    return float(answer.confidence or 0.0)


def _scalar(answer: JudgeAnswer, pack: RubricPack, qid: str) -> float | None:
    question = pack.questions.get(qid)
    if isinstance(question, ScoreQuestion) and answer.type.value == "score":
        return normalize_score(answer, len(question.criteria))
    if isinstance(question, NoulQuestion) and answer.type.value == "noul":
        return float(answer.value)
    return None  # choice answers never contribute to the composite


def _effective_weights(pack: RubricPack, weights: dict[str, float] | None, question_ids: set[str] | None) -> dict[str, float]:
    if weights is not None:
        return dict(weights)
    base = dict(pack.selection.weights)
    if question_ids is None:
        return base
    restricted = {q: w for q, w in base.items() if q in question_ids}
    if restricted:
        return restricted
    return {q: 1.0 for q in question_ids}


def composite(
    result: JudgeResult,
    pack: RubricPack,
    weights: dict[str, float] | None = None,
    question_ids: set[str] | None = None,
) -> float:
    eff = _effective_weights(pack, weights, question_ids)
    total_w = 0.0
    acc = 0.0
    for qid, w in eff.items():
        answer = result.answers.get(qid)
        if answer is None:
            continue
        value = _scalar(answer, pack, qid)
        if value is None:
            continue
        acc += w * value
        total_w += w
    return acc / total_w if total_w > 0 else 0.0


def passes_hard_filters(result: JudgeResult, pack: RubricPack) -> bool:
    limit = pack.selection.hard_filters.risky_claim_max
    answer = result.answers.get("risky_claim")
    if limit is None or answer is None:
        return True
    return float(answer.value) <= limit


def needs_review(result: JudgeResult, pack: RubricPack, weights: dict[str, float] | None = None) -> bool:
    threshold = pack.selection.review_confidence_below
    for qid in (weights or pack.selection.weights):
        answer = result.answers.get(qid)
        if answer is not None and answer_confidence(answer) < threshold:
            return True
    return False
```

`backend/clipsieve/select/__init__.py`: keep plan 01's content and add

```python
from clipsieve.select.scoring import answer_confidence, composite, needs_review, normalize_score, passes_hard_filters  # noqa: F401
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/select/test_scoring.py -q`
Expected: `16 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/clipsieve/select backend/tests/select
git commit -m "feat(select): add pure scoring helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `select/quotas.py` and `select()` / `pass_one_keep()`

**Files:**
- Create: `backend/clipsieve/select/quotas.py`
- Modify: `backend/clipsieve/select/select.py` (plan 01 defined `Selection` here; append functions, do not redefine the class)
- Test: `backend/tests/select/test_select.py`

**Interfaces:**
- Consumes: `Selection` (plan 01), `scoring.*`, `clipsieve.models.ChoiceQuestion`.
- Produces:
  - `violates_quota(candidate: JudgeResult, chosen: list[JudgeResult], pack: RubricPack, shortlist_size: int) -> bool`
  - `select(results: list[JudgeResult], pack: RubricPack, weights_override: dict[str, float] | None = None) -> Selection`
  - `pass_one_keep(results: list[JudgeResult], pack: RubricPack) -> set[str]`
  - `dropped` reasons are exactly: `"hard_filter"`, `"quota"`, `"not_selected"`.

- [x] **Step 1: Write the failing tests**

Note (applied during execution): the quota rule is `cap = max(1, floor(max_share * shortlist_size + 1e-9))`; a candidate violates when its label already appears `cap` times among the chosen. The brief's `same + 1 > max_share * size` blocked every post when `max_share * size < 1` (its own tests 3-5 failed). The test helper `r()` derives default `format`/`hook_type` labels from `post_id` so quotas do not block the brief's expected shortlists (tests 1-2 failed with identical defaults).

`backend/tests/select/test_select.py`:

```python
import math
from pathlib import Path

from clipsieve.judge.rubric import load_pack
from clipsieve.models import JudgeAnswer, JudgeResult
from clipsieve.select.quotas import violates_quota
from clipsieve.select.select import Selection, pass_one_keep, select

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
LEG = {str(i): f"L{i}" for i in range(5)}


def sc(v, conf=0.9):
    return JudgeAnswer(type="score", value=v, confidence=conf, probabilities={}, legend=LEG)


def ch(v, conf=0.9):
    return JudgeAnswer(type="choice", value=v, confidence=conf, probabilities={v: conf})


def nl(p):
    return JudgeAnswer(type="noul", value=p)


def r(post_id, hook=3.0, persona=3.0, niche=3.0, fmt="vlog_montage", hook_type="story", risky=0.1, conf=0.9, pass_name="pass_two"):
    answers = {
        "hook_strength": sc(hook, conf), "persona_fit": sc(persona, conf), "niche_relevance": sc(niche, conf),
        "format": ch(fmt, conf), "hook_type": ch(hook_type, conf), "risky_claim": nl(risky),
        "format_guess": ch("unknown", conf),
    }
    return JudgeResult(post_id=post_id, pass_name=pass_name, model="jev", input_tokens=1, latency_ms=1, answers=answers)


def small_pack(shortlist_size=5):
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    return pack.model_copy(update={"selection": pack.selection.model_copy(update={"shortlist_size": shortlist_size})}, deep=True)


def test_violates_quota_counts_same_label_against_max_share():
    pack = small_pack(5)  # format max_share 0.4 -> at most 2 of 5 may share a format
    chosen = [r("a", fmt="talking_head"), r("b", fmt="talking_head")]
    assert violates_quota(r("c", fmt="talking_head"), chosen, pack, 5) is True
    assert violates_quota(r("d", fmt="vlog_montage"), chosen, pack, 5) is False
    # candidate missing the diversity question is never blocked by it
    cand = r("e", fmt="talking_head")
    del cand.answers["format"]
    assert violates_quota(cand, chosen, pack, 5) is False


def test_select_orders_by_composite_routes_review_and_filters():
    pack = small_pack(3)
    results = [
        r("low", hook=1, persona=1, niche=1),
        r("high", hook=4, persona=4, niche=4),
        r("mid", hook=2, persona=3, niche=3),
        r("risky", hook=4, persona=4, niche=4, risky=0.9),
        r("unsure", hook=4, persona=4, niche=4, conf=0.3),
    ]
    sel = select(results, pack)
    assert isinstance(sel, Selection)
    assert sel.shortlist == ["high", "mid", "low"]
    assert sel.review == ["unsure"]
    assert sel.dropped == {"risky": "hard_filter"}
    assert sel.scores["high"] > sel.scores["mid"] > sel.scores["low"]
    assert "unsure" in sel.scores and "risky" in sel.scores


def test_select_applies_quota_and_marks_overflow():
    pack = small_pack(2)  # hook_type max_share 0.5 -> 1 per hook type among 2
    results = [
        r("s1", hook=4, hook_type="story", fmt="vlog_montage"),
        r("s2", hook=3.5, hook_type="story", fmt="talking_head"),
        r("c1", hook=3, hook_type="curiosity_gap", fmt="screen_demo"),
        r("c2", hook=2, hook_type="curiosity_gap", fmt="meme"),
    ]
    sel = select(results, pack)
    assert sel.shortlist == ["s1", "c1"]
    assert sel.dropped["s2"] == "quota"
    assert sel.dropped["c2"] == "not_selected"


def test_select_is_deterministic_on_ties():
    pack = small_pack(2)
    results = [r("b"), r("a"), r("c")]
    assert select(results, pack).shortlist == ["a", "b"]


def test_select_with_weights_override_changes_order_without_judge():
    pack = small_pack(1)
    results = [r("hooky", hook=4, persona=0), r("fits", hook=0, persona=4)]
    assert select(results, pack).shortlist == ["fits"]  # equal composite on default weights; tie broken by post_id
    assert select(results, pack, weights_override={"hook_strength": 1.0}).shortlist == ["hooky"]


def test_pass_one_keep_keeps_top_fraction_min_one():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")  # pass_one_keep 0.30
    results = [
        JudgeResult(post_id=f"p{i}", pass_name="pass_one", model="jev", input_tokens=1, latency_ms=1,
                    answers={"niche_relevance": sc(float(i % 5)), "format_guess": ch("unknown")})
        for i in range(10)
    ]
    kept = pass_one_keep(results, pack)
    assert len(kept) == math.ceil(0.30 * 10) == 3
    assert kept == {"p3", "p4", "p9"}  # scores 4,4 then the 3s; tie among p3/p8 broken by post_id
    assert pass_one_keep(results[:1], pack) == {"p0"}
    assert pass_one_keep([], pack) == set()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/select/test_select.py -q`
Expected: FAIL with `ImportError: cannot import name 'select' from 'clipsieve.select.select'`.

- [x] **Step 3: Implement `select/quotas.py`**

```python
"""Diversity quotas over choice answers."""

from __future__ import annotations

from clipsieve.models import ChoiceQuestion, JudgeResult, RubricPack


def _label(result: JudgeResult, qid: str) -> str | None:
    answer = result.answers.get(qid)
    if answer is None or answer.type.value != "choice":
        return None
    return str(answer.value)


def violates_quota(candidate: JudgeResult, chosen: list[JudgeResult], pack: RubricPack, shortlist_size: int) -> bool:
    for qid, rule in pack.selection.diversity.items():
        if not isinstance(pack.questions.get(qid), ChoiceQuestion):
            continue
        label = _label(candidate, qid)
        if label is None:
            continue
        same = sum(1 for c in chosen if _label(c, qid) == label)
        if (same + 1) > rule.max_share * shortlist_size:
            return True
    return False
```

- [x] **Step 4: Append to `select/select.py`**

Keep plan 01's `Selection` class untouched and append:

```python
import math

from clipsieve.judge.rubric import PASS_ONE
from clipsieve.models import JudgeResult, RubricPack
from clipsieve.select.quotas import violates_quota
from clipsieve.select.scoring import composite, needs_review, passes_hard_filters

HARD_FILTER = "hard_filter"
QUOTA = "quota"
NOT_SELECTED = "not_selected"


def _ranked(results: list[JudgeResult], scores: dict[str, float]) -> list[JudgeResult]:
    return sorted(results, key=lambda r: (-scores[r.post_id], r.post_id))


def select(
    results: list[JudgeResult],
    pack: RubricPack,
    weights_override: dict[str, float] | None = None,
) -> Selection:
    scores = {r.post_id: composite(r, pack, weights=weights_override) for r in results}
    dropped: dict[str, str] = {}
    review: list[str] = []
    candidates: list[JudgeResult] = []
    for r in results:
        if not passes_hard_filters(r, pack):
            dropped[r.post_id] = HARD_FILTER
        elif needs_review(r, pack, weights=weights_override):
            review.append(r.post_id)
        else:
            candidates.append(r)
    review.sort(key=lambda pid: (-scores[pid], pid))

    size = pack.selection.shortlist_size
    chosen: list[JudgeResult] = []
    for r in _ranked(candidates, scores):
        if len(chosen) >= size:
            dropped[r.post_id] = NOT_SELECTED
        elif violates_quota(r, chosen, pack, size):
            dropped[r.post_id] = QUOTA
        else:
            chosen.append(r)
    return Selection(shortlist=[r.post_id for r in chosen], review=review, scores=scores, dropped=dropped)


def pass_one_keep(results: list[JudgeResult], pack: RubricPack) -> set[str]:
    if not results:
        return set()
    qids = set(pack.metadata_pass)
    scores = {r.post_id: composite(r, pack, question_ids=qids) for r in results}
    keep_n = max(1, math.ceil(pack.pass_one_keep * len(results)))
    return {r.post_id for r in _ranked(results, scores)[:keep_n]}
```

Note `PASS_ONE` is imported for callers' convenience; ruff will flag it unused, so either re-export it in `select/__init__.py` or drop the import. Drop it if unused.

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/select -q`
Expected: `22 passed`.

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/select backend/tests/select
git commit -m "feat(select): add diversity quotas, greedy selection and pass-one keep

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 6: Explain contract, prompts, fake backend, API stub, explain fixtures

**Files:**
- Create: `backend/clipsieve/explain/__init__.py`
- Create: `backend/clipsieve/explain/base.py`
- Create: `backend/clipsieve/explain/prompts/plan.md`
- Create: `backend/clipsieve/explain/prompts/explain.md`
- Create: `backend/clipsieve/explain/fake.py`
- Create: `backend/clipsieve/explain/claude_api.py`
- Create: `backend/tests/fixtures/explain/plan.json`
- Create: `backend/tests/fixtures/explain/report.json`
- Test: `backend/tests/explain/__init__.py`, `backend/tests/explain/test_base.py`, `backend/tests/explain/test_fake.py`, `backend/tests/explain/test_claude_api_stub.py`

**Interfaces:**
- Consumes: `clipsieve.models.Brief, Plan, Report, Post, Evidence, JudgeResult`; `clipsieve.config.Settings`.
- Produces (all in `explain/base.py` unless noted):
  - `class RubricPackSummary(BaseModel): name: str; description: str; question_ids: list[str]`
  - `class ExplainPacket(BaseModel): brief: Brief; posts: list[Post]; evidence: dict[str, Evidence]; judge: dict[str, JudgeResult]; aggregates: dict[str, dict[str, int]]; keyframes: dict[str, list[str]]`
  - `class PlanRequest(BaseModel): brief: Brief; packs: list[RubricPackSummary]; platforms: list[str]` (the serialised planner input)
  - `class ExplainBackend(Protocol): def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan; def explain(self, packet: ExplainPacket) -> Report`
  - `class ExplainError(Exception)`
  - `validate_report_citations(report: Report, known_post_ids: set[str]) -> list[str]`
  - `cli_payload(mode: Literal["plan", "explain"], body: BaseModel) -> str` (JSON with top-level `"mode"`, `ensure_ascii=False`)
  - `get_backend(settings: Settings, fixture_dir: Path | None = None) -> ExplainBackend`
  - `PROMPTS_DIR = Path(__file__).parent / "prompts"`
  - `explain/fake.py`: `class FakeExplainBackend(ExplainBackend)`, `__init__(self, fixture_dir: Path)`, attribute `calls: list[str]`
  - `explain/claude_api.py`: `class ClaudeApiBackend(ExplainBackend)` whose methods raise `NotImplementedError("claude_api backend is a v0.2 follow-up to plan 03; use claude_cli")`

Decision: backends return `Plan.run_id` and `Report.run_id` as whatever they have (`"FIXTURE"` for the fake, model output for the CLI); the caller overwrites `run_id`. Backends never know the run id.

- [x] **Step 1: Write the prompts in full**

`backend/clipsieve/explain/prompts/plan.md`:

```markdown
You are the planning step of clipsieve, a social media research tool. You receive a JSON object on stdin with `mode: "plan"`, a `brief` (free text plus any fields the user already filled), the available rubric `packs`, and the `platforms` the user ticked.

Produce a Plan object that matches the JSON schema you were given. Rules:

1. `brief.topic` is one noun phrase naming what the research is about. `brief.audience` names who watches this content. `brief.persona` describes the creator the user wants to become, in one or two sentences, in the user's own framing. Keep `brief.text` exactly as given. Keep `brief.language_hint` as given or null.
2. `queries`: two to four search queries per platform in `platforms`. Write Xiaohongshu and Douyin queries in Simplified Chinese with `lang: "zh"`. Write YouTube and local queries in the brief's language, default English with `lang: "en"`. Queries are what a user would type into that platform's search box, not sentences.
3. `quantities`: copy the platform quantities from the input unchanged.
4. `rubric_pack`: choose from `packs` by name. Prefer `creator-hooks-v1` unless a pack description matches the brief better.
5. `persona_fit_criteria`: exactly five short strings, ordered from "unrelated" to "could be the user's own channel", written for this persona. Level 1 is a creator with nothing in common; level 5 names the exact situation and voice in the brief.
6. `run_id`: copy from the input if present, otherwise the string "PENDING".
7. Output only the JSON object. No prose.
```

`backend/clipsieve/explain/prompts/explain.md`:

```markdown
You are the analysis step of clipsieve, a social media research tool. You receive a JSON object on stdin with `mode: "explain"`, the research `brief`, a shortlist of `posts` with their text and metrics, per-post `evidence` (transcript segments, on-screen text, comment summary), per-post `judge` results (typed rubric answers with probabilities and confidence), run-level `aggregates` (counts of each rubric label across every judged post, not only the shortlist), and `keyframes` paths.

Produce a Report object that matches the JSON schema you were given. Rules:

1. Use only the evidence provided. Do not invent transcript lines, numbers, creators or events. If the evidence for a post is thin or `truncated` is true, say so in `caveats`.
2. Separate observation from hypothesis. In each pattern, `observation` states what the evidence shows (quote hooks, cite counts from `aggregates`); `hypothesis` states why it might work for `brief.audience`, phrased as a testable guess.
3. Cite post ids. Every pattern, gap and concept lists the `post_ids` it draws on. Every id must appear in `posts`. A claim without a post id is not allowed; drop it or find its evidence.
4. `clips`: one entry per post in `posts`, in the same order. `hook_quote` is the opening line copied from `evidence.transcript[0].text` or the first `ocr` item or the caption, verbatim. `weaknesses` names at least one thing that holds the post back.
5. `gaps`: angles, formats or hooks the aggregates show as rare or absent that the persona in `brief.persona` could own.
6. `concepts`: eight to twelve testable ideas for the persona. Each has a `hook` (one sentence, ready to say or show), a `structure` (20 to 45 seconds, beat by beat), a `visual` treatment, a `proof` element, and a `cta`. `inspired_by_post_ids` names the shortlist posts it adapts; never copy a creator's hook verbatim.
7. `caveats`: sample size, language mix, anything the judge marked low confidence, and that engagement metrics are correlational.
8. `run_id`: copy from the input if present, otherwise the string "PENDING".
9. Write in the language of `brief.text`. Output only the JSON object. No prose outside it.
```

- [x] **Step 2: Write the explain fixtures**

`backend/tests/fixtures/explain/plan.json`:

```json
{
  "run_id": "FIXTURE",
  "brief": {
    "text": "I am planning to start social media accounts with the persona of a Singaporean moving to Shanghai, vlog style. Look for such videos and analyse hooks and styles.",
    "topic": "Singaporean expat life in Shanghai",
    "audience": "Singaporeans and Southeast Asians considering or starting a move to mainland China",
    "persona": "A Singaporean in their late twenties who has just moved to Shanghai, filming daily life, admin hurdles and cultural contrasts in a candid vlog voice mixing English and Mandarin.",
    "language_hint": null
  },
  "queries": [
    {"platform": "youtube", "query": "Singaporean moving to Shanghai vlog", "lang": "en"},
    {"platform": "youtube", "query": "expat life Shanghai first week", "lang": "en"},
    {"platform": "xiaohongshu", "query": "新加坡人 上海 生活 vlog", "lang": "zh"},
    {"platform": "xiaohongshu", "query": "新加坡 搬到上海 第一周", "lang": "zh"},
    {"platform": "local", "query": "./fixtures", "lang": "en"}
  ],
  "quantities": {"youtube": 500, "xiaohongshu": 500, "local": 5},
  "rubric_pack": "creator-hooks-v1",
  "persona_fit_criteria": [
    "Creator has no connection to Singapore, Shanghai or relocation",
    "Expat or relocation content, but a different country or city",
    "Singaporean in Shanghai, but a corporate, travel or food angle rather than daily-life vlog",
    "Singaporean recently moved to Shanghai, vlogging daily life in a candid voice",
    "Could be the user's own channel: Singaporean, just moved to Shanghai, mixed English and Mandarin vlog"
  ],
  "approved_at": null
}
```

`backend/tests/fixtures/explain/report.json`:

```json
{
  "run_id": "FIXTURE",
  "patterns": [
    {
      "title": "Story-anchored openings",
      "observation": "Both top vlogs open mid-scene with a date and place before any explanation. Across all judged posts, story is the most common hook type.",
      "hypothesis": "A concrete time and place lets the audience place themselves in the move before being asked to care about details.",
      "post_ids": ["local:fx-001", "local:fx-004"]
    },
    {
      "title": "Admin hurdles outperform scenery",
      "observation": "The clip whose first line names a visa or housing problem has the highest comment count relative to views.",
      "hypothesis": "Practical pain points invite questions, and questions drive comments.",
      "post_ids": ["local:fx-002"]
    }
  ],
  "clips": [
    {"post_id": "local:fx-001", "why_it_works": "Opens on the first morning in the new flat, names the city, then cuts fast between three errands.", "hook_quote": "Day one in Shanghai and I already got lost in my own compound.", "weaknesses": "No on-screen text for the first six seconds."},
    {"post_id": "local:fx-004", "why_it_works": "Curiosity gap in the first sentence, resolved only at the end.", "hook_quote": "Nobody told me this about Shanghai supermarkets.", "weaknesses": "Payoff arrives late for a 45-second clip."}
  ],
  "gaps": [
    {"title": "Singlish and Mandarin code-switching", "rationale": "No shortlisted creator switches languages on camera, which the persona does naturally.", "post_ids": ["local:fx-001", "local:fx-002"]}
  ],
  "concepts": [
    {"hook": "I moved from Singapore to Shanghai with two suitcases. Here is what I bought on day one.", "structure": "0-3s hook at the door; 3-20s three purchases with prices; 20-35s one surprise; 35-40s invite questions.", "visual": "Handheld, receipts held to camera, price overlays.", "proof": "Real receipts and the app screen.", "cta": "Ask me what to pack.", "inspired_by_post_ids": ["local:fx-001"]},
    {"hook": "Three things my Singaporean brain refused to believe about Shanghai.", "structure": "0-3s list promise; 3-30s three items, each with a clip; 30-40s which one changed my mind.", "visual": "Jump cuts, numbered overlays in English and Chinese.", "proof": "Footage of each item.", "cta": "Tell me yours.", "inspired_by_post_ids": ["local:fx-004"]}
  ],
  "caveats": ["Two of five fixture posts shortlisted; sample is illustrative only.", "Engagement metrics are correlational."]
}
```

- [x] **Step 3: Write the failing tests**

`backend/tests/explain/test_base.py`:

```python
import json
from pathlib import Path

from clipsieve.explain.base import (
    ExplainPacket,
    PlanRequest,
    RubricPackSummary,
    cli_payload,
    validate_report_citations,
)
from clipsieve.models import Brief, Report

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_report():
    return Report.model_validate(json.loads((FIXTURES / "explain/report.json").read_text(encoding="utf-8")))


def test_validate_report_citations_finds_unknown_ids_sorted_unique():
    report = load_report()
    assert validate_report_citations(report, {f"local:fx-00{i}" for i in range(1, 6)}) == []
    unknown = validate_report_citations(report, {"local:fx-001"})
    assert unknown == ["local:fx-002", "local:fx-004"]


def test_cli_payload_has_mode_and_keeps_unicode():
    brief = Brief(text="新加坡人 in Shanghai", topic="t", audience="a", persona="p")
    body = PlanRequest(brief=brief, packs=[RubricPackSummary(name="x", description="d", question_ids=["q"])], platforms=["youtube"])
    raw = cli_payload("plan", body)
    data = json.loads(raw)
    assert data["mode"] == "plan"
    assert data["brief"]["text"] == "新加坡人 in Shanghai"
    assert "新加坡人" in raw  # ensure_ascii=False


def test_explain_packet_serialises(fixture_posts):
    packet = ExplainPacket(
        brief=Brief(text="x", topic="t", audience="a", persona="p"),
        posts=fixture_posts[:2], evidence={}, judge={}, aggregates={"hook_type": {"story": 2}}, keyframes={},
    )
    data = json.loads(cli_payload("explain", packet))
    assert data["mode"] == "explain" and len(data["posts"]) == 2
```

`backend/tests/explain/test_fake.py`:

```python
import json
from pathlib import Path

from clipsieve.explain.base import ExplainPacket, RubricPackSummary, validate_report_citations
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.models import Brief

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_fake_plan_returns_fixture_plan():
    backend = FakeExplainBackend(FIXTURES)
    plan = backend.plan(Brief(text="b", topic="", audience="", persona=""), [RubricPackSummary(name="creator-hooks-v1", description="", question_ids=[])], ["youtube"])
    assert plan.rubric_pack == "creator-hooks-v1"
    assert len(plan.persona_fit_criteria) == 5
    assert backend.calls == ["plan"]


def test_fake_explain_cites_only_packet_posts(fixture_posts):
    backend = FakeExplainBackend(FIXTURES)
    packet = ExplainPacket(brief=Brief(text="b", topic="", audience="", persona=""), posts=[fixture_posts[2], fixture_posts[4]],
                           evidence={}, judge={}, aggregates={}, keyframes={})
    report = backend.explain(packet)
    known = {p.id for p in packet.posts}
    assert validate_report_citations(report, known) == []
    assert [c.post_id for c in report.clips] == [p.id for p in packet.posts]
    assert backend.calls == ["explain"]
```

`backend/tests/explain/test_claude_api_stub.py`:

```python
import pytest

from clipsieve.explain.base import ExplainPacket
from clipsieve.explain.claude_api import ClaudeApiBackend
from clipsieve.models import Brief


@pytest.mark.xfail(reason="claude_api backend is a v0.2 follow-up; contract pinned here", raises=NotImplementedError, strict=True)
def test_claude_api_explain_contract(fixture_posts):
    backend = ClaudeApiBackend(api_key="unused")
    packet = ExplainPacket(brief=Brief(text="b", topic="", audience="", persona=""), posts=fixture_posts[:1],
                           evidence={}, judge={}, aggregates={}, keyframes={})
    report = backend.explain(packet)
    assert [c.post_id for c in report.clips] == [fixture_posts[0].id]
```

- [x] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/explain -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.explain'`.

- [x] **Step 5: Implement `explain/base.py`**

```python
"""Explain backend contract: planning a run and explaining a shortlist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from clipsieve.config import Settings
from clipsieve.models import Brief, Evidence, JudgeResult, Plan, Post, Report

PROMPTS_DIR = Path(__file__).parent / "prompts"


class RubricPackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    question_ids: list[str]


class ExplainPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: Brief
    posts: list[Post]
    evidence: dict[str, Evidence]
    judge: dict[str, JudgeResult]
    aggregates: dict[str, dict[str, int]]
    keyframes: dict[str, list[str]]


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: Brief
    packs: list[RubricPackSummary]
    platforms: list[str]


class ExplainError(Exception):
    pass


class ExplainBackend(Protocol):
    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan: ...
    def explain(self, packet: ExplainPacket) -> Report: ...


def validate_report_citations(report: Report, known_post_ids: set[str]) -> list[str]:
    cited: set[str] = set()
    for p in report.patterns:
        cited.update(p.post_ids)
    for c in report.clips:
        cited.add(c.post_id)
    for g in report.gaps:
        cited.update(g.post_ids)
    for k in report.concepts:
        cited.update(k.inspired_by_post_ids)
    return sorted(cited - known_post_ids)


def cli_payload(mode: Literal["plan", "explain"], body: BaseModel) -> str:
    data = {"mode": mode, **body.model_dump(mode="json")}
    return json.dumps(data, ensure_ascii=False)


def get_backend(settings: Settings, fixture_dir: Path | None = None) -> ExplainBackend:
    kind = settings.clipsieve_explain_backend
    if kind == "fake":
        from clipsieve.explain.fake import FakeExplainBackend

        if fixture_dir is None:
            raise ExplainError("fake explain backend needs fixture_dir")
        return FakeExplainBackend(fixture_dir)
    if kind == "claude_cli":
        from clipsieve.explain.claude_cli import ClaudeCliBackend

        return ClaudeCliBackend(bin=settings.clipsieve_claude_bin, max_budget_usd=settings.clipsieve_claude_max_budget_usd)
    if kind == "claude_api":
        from clipsieve.explain.claude_api import ClaudeApiBackend

        return ClaudeApiBackend(api_key=settings.anthropic_api_key)
    raise ExplainError(f"unknown explain backend {kind!r}")
```

- [x] **Step 6: Implement `explain/fake.py` and `explain/claude_api.py`**

`explain/fake.py`:

```python
"""Fixture-backed explain backend for tests and the Playwright flow."""

from __future__ import annotations

import json
from pathlib import Path

from clipsieve.explain.base import ExplainBackend, ExplainPacket, RubricPackSummary
from clipsieve.models import Brief, ClipExplanation, Plan, Report


class FakeExplainBackend(ExplainBackend):
    def __init__(self, fixture_dir: Path) -> None:
        self._dir = Path(fixture_dir) / "explain"
        self.calls: list[str] = []

    def _load(self, name: str) -> dict:
        return json.loads((self._dir / name).read_text(encoding="utf-8"))

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        self.calls.append("plan")
        plan = Plan.model_validate(self._load("plan.json"))
        return plan.model_copy(update={"brief": brief if brief.topic else plan.brief})

    def explain(self, packet: ExplainPacket) -> Report:
        self.calls.append("explain")
        report = Report.model_validate(self._load("report.json"))
        ids = [p.id for p in packet.posts]
        if not ids:
            return report.model_copy(update={"patterns": [], "clips": [], "gaps": [], "concepts": []})

        def remap(cited: list[str]) -> list[str]:
            out = [pid if pid in ids else ids[i % len(ids)] for i, pid in enumerate(cited)]
            return list(dict.fromkeys(out))

        template = report.clips[0] if report.clips else ClipExplanation(post_id="", why_it_works="", hook_quote="", weaknesses="")
        clips = [
            (report.clips[i] if i < len(report.clips) else template).model_copy(update={"post_id": pid})
            for i, pid in enumerate(ids)
        ]
        return report.model_copy(update={
            "patterns": [p.model_copy(update={"post_ids": remap(p.post_ids)}) for p in report.patterns],
            "clips": clips,
            "gaps": [g.model_copy(update={"post_ids": remap(g.post_ids)}) for g in report.gaps],
            "concepts": [c.model_copy(update={"inspired_by_post_ids": remap(c.inspired_by_post_ids)}) for c in report.concepts],
        })
```

`explain/claude_api.py`:

```python
"""Claude API explain backend. Stub in v0.1; the contract test in tests/explain pins the packet format."""

from __future__ import annotations

from clipsieve.explain.base import ExplainBackend, ExplainPacket, RubricPackSummary
from clipsieve.models import Brief, Plan, Report

MESSAGE = "claude_api backend is a v0.2 follow-up to plan 03; use claude_cli"


class ClaudeApiBackend(ExplainBackend):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        raise NotImplementedError(MESSAGE)

    def explain(self, packet: ExplainPacket) -> Report:
        raise NotImplementedError(MESSAGE)
```

`explain/__init__.py`: empty.

- [x] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/explain -q`
Expected: `5 passed, 1 xfailed`.

- [x] **Step 8: Commit**

```bash
git add backend/clipsieve/explain backend/tests/explain backend/tests/fixtures/explain
git commit -m "feat(explain): add backend contract, prompts, fixture fake and API stub

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 7: `ClaudeCliBackend` and the `claude` shim

**Files:**
- Create: `backend/clipsieve/explain/claude_cli.py`
- Create: `backend/tests/fixtures/claude-shim/claude` (executable, `chmod +x`)
- Test: `backend/tests/explain/test_claude_cli.py`

**Interfaces:**
- Consumes: `explain.base.*`, `clipsieve.models.Plan, Report`.
- Produces: `class ClaudeCliBackend(ExplainBackend)` with `__init__(self, bin: str, max_budget_usd: float, model: str = "opus", effort: str = "high", timeout_s: int = 900)`, `plan(...)`, `explain(...)`, and the module constants `PLAN_TASK = "Create the research plan for the brief in the JSON on stdin."`, `EXPLAIN_TASK = "Analyze the shortlisted posts in the JSON on stdin and return the report."`.
- Shim env contract (test only): `CLIPSIEVE_SHIM_STATE` (path to a counter file) and `CLIPSIEVE_SHIM_BAD_FIRST=1` make the shim return a report citing `local:does-not-exist` on the first explain call and the fixture report afterwards. `CLIPSIEVE_SHIM_FAIL=1` makes it print `{"is_error": true, "result": "shim failure"}`. The shim records every argv line to `$CLIPSIEVE_SHIM_STATE.argv` when that variable is set.

- [x] **Step 1: Write the shim**

`backend/tests/fixtures/claude-shim/claude`:

```bash
#!/usr/bin/env bash
# Fake `claude` binary for tests. Reads the packet on stdin, answers from fixtures/explain/*.json.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIX="$HERE/../explain"
if [[ -n "${CLIPSIEVE_SHIM_STATE:-}" ]]; then printf '%s\n' "$@" > "${CLIPSIEVE_SHIM_STATE}.argv"; fi
INPUT="$(cat)"
if [[ "${CLIPSIEVE_SHIM_FAIL:-}" == "1" ]]; then
  printf '{"is_error": true, "result": "shim failure", "total_cost_usd": 0.0}\n'; exit 0
fi
if grep -q '"mode": *"plan"' <<<"$INPUT"; then
  python3 -c 'import json,sys; print(json.dumps({"is_error": False, "structured_output": json.load(open(sys.argv[1])), "total_cost_usd": 0.0}, ensure_ascii=False))' "$FIX/plan.json"
  exit 0
fi
if [[ "${CLIPSIEVE_SHIM_BAD_FIRST:-}" == "1" && -n "${CLIPSIEVE_SHIM_STATE:-}" && ! -f "${CLIPSIEVE_SHIM_STATE}" ]]; then
  touch "${CLIPSIEVE_SHIM_STATE}"
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); r["patterns"][0]["post_ids"]=["local:does-not-exist"]; print(json.dumps({"is_error": False, "structured_output": r, "total_cost_usd": 0.0}, ensure_ascii=False))' "$FIX/report.json"
  exit 0
fi
python3 -c 'import json,sys; print(json.dumps({"is_error": False, "structured_output": json.load(open(sys.argv[1])), "total_cost_usd": 0.0}, ensure_ascii=False))' "$FIX/report.json"
```

Run: `chmod +x backend/tests/fixtures/claude-shim/claude && echo '{"mode": "plan"}' | backend/tests/fixtures/claude-shim/claude | head -c 80`
Expected: `{"is_error": false, "structured_output": {"run_id": "FIXTURE", ...`

- [x] **Step 2: Write the failing tests**

`backend/tests/explain/test_claude_cli.py`:

```python
import json
from pathlib import Path

import pytest

from clipsieve.explain.base import ExplainError, ExplainPacket, RubricPackSummary
from clipsieve.explain.claude_cli import EXPLAIN_TASK, ClaudeCliBackend
from clipsieve.models import Brief

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SHIM = str(FIXTURES / "claude-shim" / "claude")


@pytest.fixture
def packet(fixture_posts):
    return ExplainPacket(brief=Brief(text="b", topic="t", audience="a", persona="p"), posts=fixture_posts[:2],
                         evidence={}, judge={}, aggregates={}, keyframes={})


@pytest.fixture
def shim_env(monkeypatch, tmp_path):
    state = tmp_path / "shim.state"
    monkeypatch.setenv("CLIPSIEVE_SHIM_STATE", str(state))
    monkeypatch.delenv("CLIPSIEVE_SHIM_BAD_FIRST", raising=False)
    monkeypatch.delenv("CLIPSIEVE_SHIM_FAIL", raising=False)
    return state


def test_argv_is_exactly_the_contract(shim_env, packet):
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=2.5)
    backend.explain(packet)
    argv = Path(str(shim_env) + ".argv").read_text(encoding="utf-8").splitlines()
    assert argv[:12] == ["-p", "--model", "opus", "--effort", "high", "--tools", "", "--strict-mcp-config",
                         "--setting-sources", "", "--no-session-persistence", "--system-prompt-file"]
    assert argv[12].endswith("prompts/explain.md")
    assert argv[13:16] == ["--output-format", "json", "--json-schema"]
    assert json.loads(argv[16])["title"] == "Report"
    assert argv[17:19] == ["--max-budget-usd", "2.5"]
    assert argv[19] == EXPLAIN_TASK
    assert "--bare" not in argv


def test_plan_and_explain_roundtrip(shim_env, packet):
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    plan = backend.plan(packet.brief, [RubricPackSummary(name="creator-hooks-v1", description="", question_ids=[])], ["youtube"])
    assert plan.rubric_pack == "creator-hooks-v1"
    report = backend.explain(packet)
    assert report.patterns and report.run_id == "FIXTURE"


def test_bad_citation_retried_once_then_ok(shim_env, packet, monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_SHIM_BAD_FIRST", "1")
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    report = backend.explain(packet)
    assert "local:does-not-exist" not in {pid for p in report.patterns for pid in p.post_ids}
    argv = Path(str(shim_env) + ".argv").read_text(encoding="utf-8").splitlines()
    assert "local:does-not-exist" in argv[-1]  # retry task line names the unknown id


def test_bad_citation_twice_raises(shim_env, packet, monkeypatch):
    # Packet with no overlap with the fixture report -> every call cites unknown ids -> ExplainError after one retry.
    monkeypatch.setenv("CLIPSIEVE_SHIM_BAD_FIRST", "0")
    backend = ClaudeCliBackend(bin=SHIM, max_budget_usd=3)
    lonely = packet.model_copy(update={"posts": [packet.posts[0].model_copy(update={"id": "local:only"})]})
    with pytest.raises(ExplainError) as ei:
        backend.explain(lonely)
    assert "unknown post ids" in str(ei.value)


def test_is_error_envelope_raises(shim_env, packet, monkeypatch):
    monkeypatch.setenv("CLIPSIEVE_SHIM_FAIL", "1")
    with pytest.raises(ExplainError) as ei:
        ClaudeCliBackend(bin=SHIM, max_budget_usd=3).explain(packet)
    assert "shim failure" in str(ei.value)


def test_missing_binary_raises(packet):
    with pytest.raises(ExplainError):
        ClaudeCliBackend(bin="/definitely/not/claude", max_budget_usd=3).explain(packet)
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/explain/test_claude_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.explain.claude_cli'`.

- [x] **Step 4: Implement `explain/claude_cli.py`**

```python
"""Explain backend that shells out to `claude -p` with structured output.

Individual-use backend: runs on the user's own Claude Code login. Never pass --bare (it drops OAuth).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import structlog
from pydantic import BaseModel, ValidationError

from clipsieve.explain.base import (
    PROMPTS_DIR,
    ExplainBackend,
    ExplainError,
    ExplainPacket,
    PlanRequest,
    RubricPackSummary,
    cli_payload,
    validate_report_citations,
)
from clipsieve.models import Brief, Plan, Report

log = structlog.get_logger(__name__)

PLAN_TASK = "Create the research plan for the brief in the JSON on stdin."
EXPLAIN_TASK = "Analyze the shortlisted posts in the JSON on stdin and return the report."


class ClaudeCliBackend(ExplainBackend):
    def __init__(self, bin: str, max_budget_usd: float, model: str = "opus", effort: str = "high", timeout_s: int = 900) -> None:
        self._bin = bin
        self._budget = max_budget_usd
        self._model = model
        self._effort = effort
        self._timeout = timeout_s

    def _argv(self, prompt_file: Path, schema: dict, task: str) -> list[str]:
        return [
            self._bin, "-p", "--model", self._model, "--effort", self._effort,
            "--tools", "", "--strict-mcp-config", "--setting-sources", "",
            "--no-session-persistence", "--system-prompt-file", str(prompt_file),
            "--output-format", "json", "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--max-budget-usd", str(self._budget), task,
        ]

    def _invoke(self, prompt_file: Path, schema_model: type[BaseModel], task: str, payload: str) -> dict:
        argv = self._argv(prompt_file, schema_model.model_json_schema(), task)
        try:
            proc = subprocess.run(argv, input=payload, capture_output=True, text=True, timeout=self._timeout, check=False)
        except FileNotFoundError as exc:
            raise ExplainError(f"claude binary not found: {self._bin}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ExplainError(f"claude -p timed out after {self._timeout}s") from exc
        if proc.returncode != 0 and not proc.stdout.strip():
            raise ExplainError(f"claude -p exited {proc.returncode}: {proc.stderr.strip()[:500]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ExplainError(f"claude -p returned non-JSON: {proc.stdout[:200]!r}") from exc
        if envelope.get("is_error"):
            raise ExplainError(f"claude -p error: {envelope.get('result')!r}")
        structured = envelope.get("structured_output")
        if structured is None:
            try:
                structured = json.loads(envelope.get("result") or "")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ExplainError("claude -p returned no structured_output") from exc
        log.info("claude_cli_done", cost_usd=envelope.get("total_cost_usd"), duration_ms=envelope.get("duration_ms"))
        return structured

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        body = PlanRequest(brief=brief, packs=packs, platforms=platforms)
        data = self._invoke(PROMPTS_DIR / "plan.md", Plan, PLAN_TASK, cli_payload("plan", body))
        try:
            return Plan.model_validate(data)
        except ValidationError as exc:
            raise ExplainError(f"plan failed schema validation: {exc.errors()[:3]}") from exc

    def explain(self, packet: ExplainPacket) -> Report:
        known = {p.id for p in packet.posts}
        payload = cli_payload("explain", packet)
        task = EXPLAIN_TASK
        for attempt in (1, 2):
            data = self._invoke(PROMPTS_DIR / "explain.md", Report, task, payload)
            try:
                report = Report.model_validate(data)
            except ValidationError as exc:
                if attempt == 2:
                    raise ExplainError(f"report failed schema validation: {exc.errors()[:3]}") from exc
                task = f"{EXPLAIN_TASK} The previous attempt failed schema validation: {exc.errors()[:3]}. Return a valid Report."
                continue
            unknown = validate_report_citations(report, known)
            if not unknown:
                return report
            if attempt == 2:
                raise ExplainError(f"report cites unknown post ids after retry: {unknown}")
            log.warning("claude_cli_bad_citations", unknown=unknown)
            task = (f"{EXPLAIN_TASK} The previous attempt cited unknown post ids: {', '.join(unknown)}. "
                    f"Cite only ids present in `posts`.")
        raise ExplainError("unreachable")
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/explain -q`
Expected: `11 passed, 1 xfailed`.

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/explain/claude_cli.py backend/tests/explain/test_claude_cli.py backend/tests/fixtures/claude-shim
git commit -m "feat(explain): add claude -p backend with structured output and citation retry

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Planner

**Files:**
- Create: `backend/clipsieve/planner/__init__.py`
- Create: `backend/clipsieve/planner/plan.py`
- Test: `backend/tests/planner/__init__.py`, `backend/tests/planner/test_plan.py`

**Interfaces:**
- Consumes: `ExplainBackend`, `RubricPackSummary`, `find_pack`, `clipsieve.models.Plan, Brief, Query, RubricPack`.
- Produces:
  - `build_plan(run_id: str, brief_text: str, platforms: list[str], quantities: dict[str, int], rubric_pack: str, language_hint: str | None, backend: ExplainBackend, rubrics_dir: Path) -> Plan`
  - `pack_summaries(rubrics_dir: Path) -> list[RubricPackSummary]`
  - `default_lang(platform: str, language_hint: str | None) -> str` (`xiaohongshu`, `douyin`, `bilibili` → `"zh"`; otherwise `language_hint or "en"`)

Decision: `run_id` is an argument (the overview signature omitted it); the planner, not the backend, owns `Plan.run_id`.

- [x] **Step 1: Write the failing tests**

`backend/tests/planner/test_plan.py`:

```python
from pathlib import Path

from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.models import Plan, Query
from clipsieve.planner.plan import build_plan, default_lang, pack_summaries

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
BRIEF = "Singaporean moving to Shanghai, vlog style; analyse hooks."


def test_default_lang():
    assert default_lang("xiaohongshu", None) == "zh"
    assert default_lang("youtube", None) == "en"
    assert default_lang("youtube", "zh") == "zh"
    assert default_lang("local", "ms") == "ms"


def test_pack_summaries_lists_real_packs():
    packs = pack_summaries(RUBRICS)
    assert [p.name for p in packs] == ["creator-hooks-v1"]
    assert "hook_type" in packs[0].question_ids


def test_build_plan_sets_run_id_quantities_and_one_query_per_platform():
    backend = FakeExplainBackend(FIXTURES)
    plan = build_plan("run_abc", BRIEF, ["youtube", "xiaohongshu", "local"], {"youtube": 10, "xiaohongshu": 20, "local": 5},
                      "creator-hooks-v1", None, backend, RUBRICS)
    assert isinstance(plan, Plan)
    assert plan.run_id == "run_abc"
    assert plan.quantities == {"youtube": 10, "xiaohongshu": 20, "local": 5}
    assert plan.rubric_pack == "creator-hooks-v1"
    assert plan.brief.text == BRIEF
    for platform in ("youtube", "xiaohongshu", "local"):
        assert any(q.platform == platform for q in plan.queries)
    assert all(q.lang == "zh" for q in plan.queries if q.platform == "xiaohongshu")
    assert len(plan.persona_fit_criteria) == 5
    assert plan.approved_at is None


def test_build_plan_fills_missing_platform_query_and_drops_unticked():
    class Narrow(FakeExplainBackend):
        def plan(self, brief, packs, platforms):
            p = super().plan(brief, packs, platforms)
            return p.model_copy(update={"queries": [Query(platform="youtube", query="x", lang="en")]})

    plan = build_plan("r", BRIEF, ["xiaohongshu"], {"xiaohongshu": 3}, "creator-hooks-v1", None, Narrow(FIXTURES), RUBRICS)
    assert [q.platform for q in plan.queries] == ["xiaohongshu"]
    assert plan.queries[0].lang == "zh" and plan.queries[0].query  # falls back to brief.topic


def test_build_plan_falls_back_to_pack_persona_criteria_when_not_five():
    class Short(FakeExplainBackend):
        def plan(self, brief, packs, platforms):
            return super().plan(brief, packs, platforms).model_copy(update={"persona_fit_criteria": ["a", "b"]})

    plan = build_plan("r", BRIEF, ["youtube"], {"youtube": 1}, "creator-hooks-v1", None, Short(FIXTURES), RUBRICS)
    assert plan.persona_fit_criteria[0] == "Unrelated creator and situation"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/planner -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.planner'`.

- [x] **Step 3: Implement `planner/plan.py`**

```python
"""Turn a brief into an approved-able Plan using the explain backend, then enforce invariants in code."""

from __future__ import annotations

from pathlib import Path

import structlog

from clipsieve.explain.base import ExplainBackend, RubricPackSummary
from clipsieve.judge.rubric import PERSONA_LEVELS, find_pack, load_pack
from clipsieve.models import Brief, Plan, Query, ScoreQuestion

log = structlog.get_logger(__name__)

ZH_PLATFORMS = {"xiaohongshu", "douyin", "bilibili"}


def default_lang(platform: str, language_hint: str | None) -> str:
    if platform in ZH_PLATFORMS:
        return "zh"
    return language_hint or "en"


def pack_summaries(rubrics_dir: Path) -> list[RubricPackSummary]:
    out: list[RubricPackSummary] = []
    for path in sorted(rubrics_dir.glob("*.yaml")):
        pack = load_pack(path)
        out.append(RubricPackSummary(name=pack.name, description=f"{pack.name} v{pack.version}", question_ids=list(pack.questions)))
    return out


def build_plan(
    run_id: str,
    brief_text: str,
    platforms: list[str],
    quantities: dict[str, int],
    rubric_pack: str,
    language_hint: str | None,
    backend: ExplainBackend,
    rubrics_dir: Path,
) -> Plan:
    seed = Brief(text=brief_text, topic="", audience="", persona="", language_hint=language_hint)
    packs = pack_summaries(rubrics_dir)
    draft = backend.plan(seed, packs, platforms)

    brief = draft.brief.model_copy(update={"text": brief_text, "language_hint": language_hint})
    queries = [q for q in draft.queries if q.platform in platforms]
    for platform in platforms:
        if not any(q.platform == platform for q in queries):
            queries.append(Query(platform=platform, query=brief.topic or brief_text, lang=default_lang(platform, language_hint)))
    queries = [q.model_copy(update={"lang": default_lang(q.platform, language_hint)}) if q.platform in ZH_PLATFORMS else q for q in queries]

    pack_name = draft.rubric_pack if any(p.name == draft.rubric_pack for p in packs) else rubric_pack
    pack = find_pack(pack_name, rubrics_dir)
    criteria = list(draft.persona_fit_criteria)
    if len(criteria) != PERSONA_LEVELS:
        persona_q = pack.questions["persona_fit"]
        criteria = list(persona_q.criteria) if isinstance(persona_q, ScoreQuestion) else criteria
        log.warning("plan_persona_criteria_fallback", got=len(draft.persona_fit_criteria))

    return Plan(
        run_id=run_id,
        brief=brief,
        queries=queries,
        quantities={p: int(quantities[p]) for p in platforms},
        rubric_pack=pack_name,
        persona_fit_criteria=criteria,
        approved_at=None,
    )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/planner -q`
Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/clipsieve/planner backend/tests/planner
git commit -m "feat(planner): build plan from brief with per-platform language and persona criteria

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 9: Pipeline `Runner` and the fixture adapter

**Files:**
- Create: `backend/clipsieve/adapters/fixture.py`
- Create: `backend/clipsieve/pipeline/__init__.py`
- Create: `backend/clipsieve/pipeline/state.py`
- Create: `backend/clipsieve/pipeline/runner.py`
- Modify: `backend/clipsieve/adapters/registry.py` (register `fixture` built-in only when `CLIPSIEVE_FIXTURE_DIR` is set; see Step 3)
- Modify: `backend/clipsieve/config.py` (add `clipsieve_fixture_dir: Path | None = None`)
- Modify: `.env.example` (add `CLIPSIEVE_FIXTURE_DIR=`)
- Test: `backend/tests/pipeline/__init__.py`, `backend/tests/pipeline/test_runner.py`

**Interfaces:**
- Consumes: everything from plans 01 and 02 listed in Prerequisites, plus Tasks 1 to 8 of this plan. Specifically `build_metadata_state`, `build_state`, `extract_evidence`, `pass_one_keep`, `select`, `composite`, `questions_for_pass`, `find_pack`, `with_persona_criteria`, `build_plan`, `cost_usd`, `JudgeFailed`, `ExplainError`, `EventWriter`, `RunRepository`, `RunPaths`, `incoming_dir` (plan 02 Addendum B.1).
- Produces:
  - `adapters/fixture.py`: `class FixtureAdapter(Adapter)` with `platform = "local"`, `__init__(self, fixture_dir: Path, data_dir: Path)`, `from_settings(settings)`; `search` yields the five fixture posts (ignores queries, honours `limit`) after copying each raw fixture into `incoming_dir(data_dir, "local")` and setting `raw_ref` to that path; `fetch_media` copies `fixtures/evidence/<safe id>/*` into `dest` when present and returns the post with `media[].local_path` set; `healthcheck` ok when the fixture dir exists.
  - `pipeline/state.py`: `class RunState(BaseModel): pass_one_kept: list[str] = []; pass_one_dropped: list[str] = []; judge_failed: list[str] = []; extracted: list[str] = []`; `load_state(paths: RunPaths) -> RunState`; `save_state(paths: RunPaths, state: RunState) -> None` (file `paths.root / "state.json"`).
  - `pipeline/runner.py`: `STAGE_ORDER`, `class Runner` per the overview signature with `plan()`, `approve(plan)`, `run()`, `pause()`, `reselect(weights_override)`, plus `class RunPaused(Exception)` and the module function `post_state(post_id, state: RunState, selection: Selection | None, judged_pass_two: set[str]) -> str` returning one of `collected | dropped_pass_one | judged | shortlisted | review | judge_failed` (used by the API in Task 10).

Decisions made here:
- Pass one judges every post concurrently, then computes the keep set, then emits `pass_one_judged` for every post with the correct `kept`. The grid is already populated by `post_collected`, so liveness is acceptable.
- Extraction runs in `asyncio.to_thread` with concurrency 2 (ASR is CPU-bound).
- `pause()` sets a flag checked between posts and between stages; `run()` raises `RunPaused` internally, saves state, sets `run.paused = True` and returns normally. `resume` is just `run()` again with `paused` cleared by the caller.
- `elapsed_s` is measured from `run.created_at` to now, in seconds, rounded to 1 decimal.
- Aggregates for the explain packet count `choice` labels over all `pass_two` results, keyed by question id.

- [x] **Step 1: Add the setting and env var**

In `config.py` add `clipsieve_fixture_dir: Path | None = None` to `Settings`. In `.env.example` append `CLIPSIEVE_FIXTURE_DIR=`.

- [x] **Step 2: Write the failing tests**

`backend/tests/pipeline/test_runner.py`:

```python
import asyncio
import json
from pathlib import Path

import pytest

from clipsieve.adapters.fixture import FixtureAdapter
from clipsieve.config import Settings
from clipsieve.events.reader import read_events
from clipsieve.evidence.asr import FakeASR
from clipsieve.evidence.frames import FakeFrames
from clipsieve.evidence.ocr import FakeOCR
from clipsieve.explain.base import ExplainError
from clipsieve.explain.fake import FakeExplainBackend
from clipsieve.judge.base import JudgeFailed
from clipsieve.judge.recorded import RecordedJudge
from clipsieve.models import Brief
from clipsieve.pipeline.runner import STAGE_ORDER, Runner, post_state
from clipsieve.pipeline.state import load_state
from clipsieve.store.db import get_engine, init_db
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import RunRepository

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
BRIEF = Brief(text="Singaporean moving to Shanghai vlog", topic="", audience="", persona="")


def make_runner(tmp_path, judge=None, explain=None, settings=None):
    settings = settings or Settings(clipsieve_data_dir=tmp_path, clipsieve_explain_backend="fake", clipsieve_fixture_dir=FIXTURES)
    engine = get_engine(tmp_path)
    init_db(engine)
    repo = RunRepository(tmp_path, engine)
    run = repo.create_run(BRIEF, ["local"], {"local": 5}, "creator-hooks-v1")
    runner = Runner(
        run_id=run.id, settings=settings, repo=repo,
        adapters={"local": FixtureAdapter(FIXTURES, tmp_path)},
        judge=judge or RecordedJudge(FIXTURES), explain=explain or FakeExplainBackend(FIXTURES),
        asr=FakeASR(), ocr=FakeOCR(), frames=FakeFrames(), rubrics_dir=RUBRICS,
    )
    return runner, repo, run.id


async def run_to_done(runner):
    plan = await runner.plan()
    await runner.approve(plan)
    await runner.run()


def event_types(tmp_path, run_id):
    return [e.type.value for e in read_events(RunPaths(tmp_path, run_id))]


def test_stage_order_is_the_contract():
    assert STAGE_ORDER == ["planning", "collecting", "pass_one", "extracting", "pass_two", "selecting", "explaining", "done"]


async def test_end_to_end_fixture_run(tmp_path):
    runner, repo, run_id = make_runner(tmp_path)
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "done" and run.paused is False
    types = event_types(tmp_path, run_id)
    assert types[0] == "run_created"
    assert types.index("plan_ready") < types.index("plan_approved") < types.index("post_collected")
    assert types.count("post_collected") == 5
    assert types.count("pass_one_judged") == 5
    kept = load_state(RunPaths(tmp_path, run_id)).pass_one_kept
    assert len(kept) == 2  # ceil(0.30 * 5)
    assert types.count("evidence_ready") == 2 and types.count("judged") == 2
    assert types[-3:] == ["selected", "explained", "done"]
    sel = repo.get_selection(run_id)
    assert sel is not None and set(sel.shortlist) | set(sel.review) <= set(kept)
    report = repo.get_report(run_id)
    assert report is not None and report.run_id == run_id
    assert {c.post_id for c in report.clips} == set(sel.shortlist)
    assert run.counters.collected == 5 and run.counters.judged == 2
    assert run.counters.jev_input_tokens == 5 * 640 + 2 * 2900
    assert run.counters.jev_cost_usd == pytest.approx((5 * 640 + 2 * 2900) / 1e6 * 0.042)
    # raw payload relocated into the run folder
    post = repo.get_post(run_id, "local:fx-001")
    assert post.raw_ref.startswith("raw/") and (RunPaths(tmp_path, run_id).root / post.raw_ref).exists()


async def test_resume_after_crash_no_duplicate_judge_calls(tmp_path):
    class CrashOnce(RecordedJudge):
        def __init__(self, d):
            super().__init__(d)
            self.crashed = False

        async def judge(self, post_id, pass_name, state, questions, model):
            if pass_name == "pass_two" and not self.crashed and len([c for c in self.calls if c[1] == "pass_two"]) == 1:
                self.crashed = True
                raise RuntimeError("simulated crash")
            return await super().judge(post_id, pass_name, state, questions, model)

    judge = CrashOnce(FIXTURES)
    runner, repo, run_id = make_runner(tmp_path, judge=judge)
    plan = await runner.plan()
    await runner.approve(plan)
    with pytest.raises(RuntimeError):
        await runner.run()
    assert repo.get_run(run_id).stage.value == "pass_two"
    pass_two_calls_before = [c for c in judge.calls if c[1] == "pass_two"]
    await runner.run()  # resume
    assert repo.get_run(run_id).stage.value == "done"
    pass_two_calls = [c for c in judge.calls if c[1] == "pass_two"]
    # exactly one extra successful call per not-yet-judged post; the already judged post is not re-judged
    assert len(pass_two_calls) == len(pass_two_calls_before) + 1
    assert event_types(tmp_path, run_id).count("judged") == 2


async def test_pause_then_resume_completes(tmp_path):
    runner, repo, run_id = make_runner(tmp_path)
    plan = await runner.plan()
    await runner.approve(plan)
    runner.pause()
    await runner.run()
    run = repo.get_run(run_id)
    assert run.paused is True and run.stage.value in ("collecting", "pass_one")
    run.paused = False
    repo.save_run(run)
    runner.resume_flag()
    await runner.run()
    assert repo.get_run(run_id).stage.value == "done"
    types = event_types(tmp_path, run_id)
    assert types.count("post_collected") == 5 and types.count("done") == 1


async def test_judge_failed_post_excluded_run_completes(tmp_path):
    class FailOne(RecordedJudge):
        async def judge(self, post_id, pass_name, state, questions, model):
            if post_id == "local:fx-001":
                raise JudgeFailed(post_id, 5, RuntimeError("429"))
            return await super().judge(post_id, pass_name, state, questions, model)

    runner, repo, run_id = make_runner(tmp_path, judge=FailOne(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "done"
    state = load_state(RunPaths(tmp_path, run_id))
    assert "local:fx-001" in state.judge_failed
    errors = [e for e in read_events(RunPaths(tmp_path, run_id)) if e.type.value == "error"]
    assert any(e.payload["post_id"] == "local:fx-001" and e.payload["recoverable"] for e in errors)
    assert run.counters.errors >= 1


async def test_explain_failure_marks_run_failed_with_shortlist_intact(tmp_path):
    class Broken(FakeExplainBackend):
        def explain(self, packet):
            raise ExplainError("report cites unknown post ids after retry: ['x']")

    runner, repo, run_id = make_runner(tmp_path, explain=Broken(FIXTURES))
    await run_to_done(runner)
    run = repo.get_run(run_id)
    assert run.stage.value == "failed" and "unknown post ids" in (run.error or "")
    assert repo.get_selection(run_id) is not None
    assert repo.get_report(run_id) is None
    assert event_types(tmp_path, run_id)[-1] == "error"


async def test_reselect_uses_stored_results_without_judge(tmp_path):
    runner, repo, run_id = make_runner(tmp_path)
    await run_to_done(runner)
    calls_before = len(runner.judge.calls)
    sel = await runner.reselect({"hook_strength": 1.0})
    assert set(sel.shortlist) | set(sel.review) <= set(load_state(RunPaths(tmp_path, run_id)).pass_one_kept)
    assert len(runner.judge.calls) == calls_before
    assert repo.get_selection(run_id) == sel


def test_post_state_mapping():
    from clipsieve.pipeline.state import RunState
    from clipsieve.select.select import Selection

    state = RunState(pass_one_kept=["a", "b", "c", "d"], pass_one_dropped=["z"], judge_failed=["d"])
    sel = Selection(shortlist=["a"], review=["b"], scores={}, dropped={"c": "not_selected"})
    assert post_state("z", state, sel, {"a", "b", "c"}) == "dropped_pass_one"
    assert post_state("d", state, sel, {"a", "b", "c"}) == "judge_failed"
    assert post_state("a", state, sel, {"a", "b", "c"}) == "shortlisted"
    assert post_state("b", state, sel, {"a", "b", "c"}) == "review"
    assert post_state("c", state, sel, {"a", "b", "c"}) == "judged"
    assert post_state("c", state, None, set()) == "collected"
```

Note: `test_pause_then_resume_completes` uses `runner.resume_flag()`, a method that clears the pause flag. Add it to `Runner` (it is not in the overview; it is a convenience used by the API's resume route).

- [x] **Step 3: Implement `adapters/fixture.py`**

```python
"""Adapter that serves the five fixture posts. Used by tests, `CLIPSIEVE_EXPLAIN_BACKEND=fake`, and the Playwright flow."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

from clipsieve.adapters.base import Adapter, AdapterHealth, incoming_dir
from clipsieve.config import Settings
from clipsieve.models import Post, Query
from clipsieve.store.paths import safe_post_filename


class FixtureAdapter(Adapter):
    platform = "local"

    def __init__(self, fixture_dir: Path, data_dir: Path) -> None:
        self._fixtures = Path(fixture_dir)
        self._data_dir = Path(data_dir)

    @classmethod
    def from_settings(cls, settings: Settings) -> FixtureAdapter:
        if settings.clipsieve_fixture_dir is None:
            raise ValueError("CLIPSIEVE_FIXTURE_DIR is not set")
        return cls(settings.clipsieve_fixture_dir, settings.clipsieve_data_dir)

    def healthcheck(self) -> AdapterHealth:
        ok = (self._fixtures / "posts").is_dir()
        return AdapterHealth(ok=ok, message="fixture posts present" if ok else f"missing {self._fixtures / 'posts'}")

    def search(self, queries: list[Query], limit: int) -> Iterator[Post]:
        incoming = incoming_dir(self._data_dir, self.platform)
        incoming.mkdir(parents=True, exist_ok=True)
        for path in sorted((self._fixtures / "posts").glob("*.json"))[:limit]:
            post = Post.model_validate(json.loads(path.read_text(encoding="utf-8")))
            raw_src = self._fixtures / "raw" / f"{safe_post_filename(post.id)}.json"
            raw_dst = incoming / f"{safe_post_filename(post.id)}.json"
            shutil.copyfile(raw_src, raw_dst)
            yield post.model_copy(update={"raw_ref": str(raw_dst), "media": [m.model_copy(update={"local_path": None}) for m in post.media]})

    def fetch_media(self, post: Post, dest: Path) -> Post:
        dest.mkdir(parents=True, exist_ok=True)
        src = self._fixtures / "evidence" / safe_post_filename(post.id)
        media = []
        for i, m in enumerate(post.media):
            name = "video.mp4" if m.type.value == "video" else f"img_{i:02d}.jpg"
            if (src / name).exists():
                shutil.copyfile(src / name, dest / name)
                for sidecar in src.glob(f"{name}.*.json"):
                    shutil.copyfile(sidecar, dest / sidecar.name)
            media.append(m.model_copy(update={"local_path": name}))
        return post.model_copy(update={"media": media})
```

In `adapters/registry.py`, after loading built-ins, add:

```python
    if settings.clipsieve_fixture_dir is not None:
        from clipsieve.adapters.fixture import FixtureAdapter

        adapters["local"] = FixtureAdapter.from_settings(settings)
```

so fake mode replaces `LocalImportAdapter` for the `local` platform.

- [x] **Step 4: Implement `pipeline/state.py`**

```python
from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from clipsieve.store.paths import RunPaths


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_one_kept: list[str] = []
    pass_one_dropped: list[str] = []
    judge_failed: list[str] = []
    extracted: list[str] = []


def _path(paths: RunPaths):
    return paths.root / "state.json"


def load_state(paths: RunPaths) -> RunState:
    p = _path(paths)
    if not p.exists():
        return RunState()
    return RunState.model_validate(json.loads(p.read_text(encoding="utf-8")))


def save_state(paths: RunPaths, state: RunState) -> None:
    tmp = _path(paths).with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(_path(paths))
```

- [x] **Step 5: Implement `pipeline/runner.py`**

```python
"""Drives a run through its stages, emitting RunEvents. Idempotent per post; resumable from the log."""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import structlog

from clipsieve.adapters.base import Adapter
from clipsieve.config import Settings
from clipsieve.events.writer import EventWriter
from clipsieve.evidence.asr import ASR
from clipsieve.evidence.extract import extract_evidence
from clipsieve.evidence.frames import FrameExtractor
from clipsieve.evidence.ocr import OCR
from clipsieve.evidence.packet import build_metadata_state, build_state
from clipsieve.explain.base import ExplainBackend, ExplainError, ExplainPacket
from clipsieve.judge.base import Judge, JudgeFailed, cost_usd
from clipsieve.judge.rubric import PASS_ONE, PASS_TWO, find_pack, questions_for_pass, with_persona_criteria
from clipsieve.models import Evidence, JudgeResult, Plan, Post, Run, RubricPack, Stage
from clipsieve.pipeline.state import RunState, load_state, save_state
from clipsieve.planner.plan import build_plan
from clipsieve.select.scoring import composite
from clipsieve.select.select import Selection, pass_one_keep, select
from clipsieve.store.paths import RunPaths, safe_post_filename
from clipsieve.store.repo import RunRepository

log = structlog.get_logger(__name__)

STAGE_ORDER: list[str] = ["planning", "collecting", "pass_one", "extracting", "pass_two", "selecting", "explaining", "done"]
EXTRACT_CONCURRENCY = 2
ADAPTER_ERROR_ABORT_RATIO = 0.20


class RunPaused(Exception):
    pass


def post_state(post_id: str, state: RunState, selection: Selection | None, judged_pass_two: set[str]) -> str:
    if post_id in state.judge_failed:
        return "judge_failed"
    if post_id in state.pass_one_dropped:
        return "dropped_pass_one"
    if selection is not None:
        if post_id in selection.shortlist:
            return "shortlisted"
        if post_id in selection.review:
            return "review"
    if post_id in judged_pass_two:
        return "judged"
    return "collected"


class Runner:
    def __init__(
        self,
        run_id: str,
        settings: Settings,
        repo: RunRepository,
        adapters: dict[str, Adapter],
        judge: Judge,
        explain: ExplainBackend,
        asr: ASR,
        ocr: OCR,
        frames: FrameExtractor,
        rubrics_dir: Path,
    ) -> None:
        self.run_id = run_id
        self.settings = settings
        self.repo = repo
        self.adapters = adapters
        self.judge = judge
        self.explain_backend = explain
        self.asr, self.ocr, self.frames = asr, ocr, frames
        self.rubrics_dir = rubrics_dir
        self.paths = RunPaths(settings.clipsieve_data_dir, run_id)
        self.paths.ensure()
        self.events = EventWriter(self.paths, run_id)
        self._pause = False

    # ---- control -----------------------------------------------------------------------------

    def pause(self) -> None:
        self._pause = True

    def resume_flag(self) -> None:
        self._pause = False

    def _check_pause(self) -> None:
        if self._pause:
            raise RunPaused()

    # ---- helpers -----------------------------------------------------------------------------

    def _run(self) -> Run:
        return self.repo.get_run(self.run_id)

    def _save_counters(self, run: Run) -> None:
        run.counters.elapsed_s = round((datetime.now(UTC) - run.created_at).total_seconds(), 1)
        self.repo.save_run(run)

    def _set_stage(self, run: Run, to: str) -> Run:
        frm = run.stage.value
        if frm != to:
            run.stage = Stage(to)  # assign the enum member; validate_assignment is off
            self.repo.save_run(run)
            self.events.emit("stage_changed", to, {"from": frm, "to": to})
        return run

    def _error(self, run: Run, where: str, message: str, post_id: str | None = None, recoverable: bool = True) -> None:
        run.counters.errors += 1
        self._save_counters(run)
        payload = {"where": where, "message": message[:1000], "recoverable": recoverable}
        if post_id is not None:
            payload["post_id"] = post_id
        self.events.emit("error", run.stage.value, payload)

    def _pack(self, plan: Plan) -> RubricPack:
        return with_persona_criteria(find_pack(plan.rubric_pack, self.rubrics_dir), plan.persona_fit_criteria)

    def _plan(self) -> Plan:
        plan = self.repo.get_plan(self.run_id)
        if plan is None:
            raise RuntimeError("run has no approved plan")
        return plan

    # ---- planning ----------------------------------------------------------------------------

    async def plan(self) -> Plan:
        run = self._run()
        plan = await asyncio.to_thread(
            build_plan, self.run_id, run.brief.text, run.platforms, run.quantities, run.rubric_pack,
            run.brief.language_hint, self.explain_backend, self.rubrics_dir,
        )
        self.repo.save_plan(self.run_id, plan)
        self.events.emit("plan_ready", "planning", {"plan": plan.model_dump(mode="json")})
        return plan

    async def approve(self, plan: Plan) -> None:
        plan = plan.model_copy(update={"run_id": self.run_id, "approved_at": datetime.now(UTC)})
        self.repo.save_plan(self.run_id, plan)
        run = self._run()
        run.brief = plan.brief
        run.rubric_pack = plan.rubric_pack
        self.repo.save_run(run)
        self.events.emit("plan_approved", "planning", {"plan": plan.model_dump(mode="json")})
        self._set_stage(run, "collecting")

    # ---- main loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        run = self._run()
        if run.stage.value in ("done", "failed"):
            return
        if run.stage.value == "planning":
            raise RuntimeError("plan must be approved before run()")
        stages = {
            "collecting": self._collect, "pass_one": self._pass_one, "extracting": self._extract,
            "pass_two": self._pass_two, "selecting": self._select, "explaining": self._explain,
        }
        try:
            idx = STAGE_ORDER.index(run.stage.value)
            for stage in STAGE_ORDER[idx:]:
                if stage == "done":
                    break
                run = self._set_stage(self._run(), stage)
                self._check_pause()
                await stages[stage](run)
            run = self._run()
            self._set_stage(run, "done")
            self._save_counters(run)
            self.events.emit("done", "done", {"counters": run.counters.model_dump(mode="json")})
        except RunPaused:
            run = self._run()
            run.paused = True
            self._save_counters(run)
            log.info("run_paused", run_id=self.run_id, stage=run.stage.value)
        except ExplainError as exc:
            run = self._run()
            # Emit the error first, while the stage is still "explaining": readers (plan 01
            # follow_events, plan 04 useRunEvents) stop at the first failed-stage event, so the
            # stage_changed to "failed" must be the last line in the log.
            self._error(run, "explain", str(exc), recoverable=False)
            run.error = str(exc)
            run.stage = Stage("failed")
            self.repo.save_run(run)
            self.events.emit("stage_changed", "failed", {"from": "explaining", "to": "failed"})

    # ---- stages ------------------------------------------------------------------------------

    async def _collect(self, run: Run) -> None:
        plan = self._plan()
        for platform in run.platforms:
            adapter = self.adapters.get(platform)
            if adapter is None:
                self._error(run, f"adapter.{platform}", f"no adapter registered for {platform}")
                continue
            health = adapter.healthcheck()
            if not health.ok:
                self._error(run, f"adapter.{platform}", f"{platform} adapter unhealthy: {health.message}")
                continue
            queries = [q for q in plan.queries if q.platform == platform]
            limit = run.quantities.get(platform, 0)
            seen, errors = 0, 0
            try:
                for post in await asyncio.to_thread(lambda: list(adapter.search(queries, limit))):
                    self._check_pause()
                    try:
                        post = self._relocate_raw(post)
                        self.repo.upsert_post(self.run_id, post)
                        run.counters.collected += 1
                        self.events.emit("post_collected", "collecting", {"post": post.model_dump(mode="json")})
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        self._error(run, f"adapter.{platform}", repr(exc), post_id=post.id)
                    seen += 1
                    if seen >= 10 and errors / seen > ADAPTER_ERROR_ABORT_RATIO:
                        self._error(run, f"adapter.{platform}", f"{platform} adapter aborted: error ratio {errors}/{seen}")
                        break
            except RunPaused:
                raise
            except Exception as exc:  # noqa: BLE001
                self._error(run, f"adapter.{platform}", f"{platform} search failed: {exc!r}")
            self._save_counters(run)

    def _relocate_raw(self, post: Post) -> Post:
        src = Path(post.raw_ref)
        if src.is_absolute() and src.exists():
            dst = self.paths.raw_path(post.id, "json")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return post.model_copy(update={"raw_ref": f"raw/{safe_post_filename(post.id)}.json"})
        return post

    async def _judge_one(self, run: Run, post: Post, pass_name: str, state_dict: dict, pack: RubricPack, rstate: RunState) -> JudgeResult | None:
        existing = self.repo.get_judge_result(self.run_id, post.id, pass_name)
        if existing is not None:
            return existing
        try:
            result = await self.judge.judge(post.id, pass_name, state_dict, questions_for_pass(pack, pass_name), pack.jev_model)
        except JudgeFailed as exc:
            if post.id not in rstate.judge_failed:
                rstate.judge_failed.append(post.id)
                save_state(self.paths, rstate)
            self._error(run, f"judge.{pass_name}", str(exc), post_id=post.id)
            return None
        self.repo.save_judge_result(self.run_id, result)
        run.counters.jev_input_tokens += result.input_tokens
        run.counters.jev_cost_usd = round(cost_usd(run.counters.jev_input_tokens), 6)
        return result

    async def _pass_one(self, run: Run) -> None:
        plan, pack, rstate = self._plan(), self._pack(self._plan()), load_state(self.paths)
        if rstate.pass_one_kept or rstate.pass_one_dropped:
            return  # already decided
        posts = self.repo.list_posts(self.run_id, 0, 1_000_000)
        results = await asyncio.gather(*[
            self._judge_one(run, p, PASS_ONE, build_metadata_state(plan.brief, p), pack, rstate) for p in posts
        ])
        ok = [r for r in results if r is not None]
        kept = pass_one_keep(ok, pack)
        rstate.pass_one_kept = sorted(kept)
        rstate.pass_one_dropped = sorted({r.post_id for r in ok} - kept)
        save_state(self.paths, rstate)
        run.counters.pass_one_kept = len(kept)
        self._save_counters(run)
        for r in ok:
            self.events.emit("pass_one_judged", "pass_one", {
                "judge": r.model_dump(mode="json"), "kept": r.post_id in kept,
                "composite": composite(r, pack, question_ids=set(pack.metadata_pass)),
            })

    async def _extract(self, run: Run) -> None:
        rstate = load_state(self.paths)
        sem = asyncio.Semaphore(EXTRACT_CONCURRENCY)

        async def one(post_id: str) -> None:
            if post_id in rstate.extracted:
                return
            self._check_pause()
            post = self.repo.get_post(self.run_id, post_id)
            adapter = self.adapters.get(post.platform.value)
            async with sem:
                if adapter is not None:
                    try:
                        post = await asyncio.to_thread(adapter.fetch_media, post, self.paths.media_dir(post.id))
                        self.repo.upsert_post(self.run_id, post)
                    except Exception as exc:  # noqa: BLE001 - covers contrib MediaDownloadError and any adapter failure
                        self._error(run, f"adapter.{post.platform.value}", repr(exc), post_id=post.id)
                try:
                    evidence = await asyncio.to_thread(extract_evidence, post, self.paths, self.asr, self.ocr, self.frames)
                except Exception as exc:  # noqa: BLE001
                    self._error(run, "evidence.extract", repr(exc), post_id=post.id)
                    evidence = Evidence(post_id=post.id, transcript=[], ocr=[], keyframes=[],
                                        comment_summary={"count": len(post.comments), "top_terms": [], "sample": []},
                                        token_estimate=0, truncated=False)
            self.repo.save_evidence(self.run_id, evidence)
            rstate.extracted.append(post_id)
            save_state(self.paths, rstate)
            self.events.emit("evidence_ready", "extracting", {"post_id": post_id, "evidence": evidence.model_dump(mode="json")})

        await asyncio.gather(*[one(pid) for pid in rstate.pass_one_kept if pid not in rstate.judge_failed])

    async def _pass_two(self, run: Run) -> None:
        plan, rstate = self._plan(), load_state(self.paths)
        pack = self._pack(plan)
        todo = [pid for pid in rstate.pass_one_kept if pid not in rstate.judge_failed]

        async def one(pid: str) -> None:
            self._check_pause()
            if self.repo.get_judge_result(self.run_id, pid, PASS_TWO) is not None:
                return
            post = self.repo.get_post(self.run_id, pid)
            evidence = self.repo.get_evidence(self.run_id, pid)
            state_dict, truncated = build_state(plan.brief, post, evidence)
            if evidence is not None and evidence.truncated != truncated:
                self.repo.save_evidence(self.run_id, evidence.model_copy(update={"truncated": truncated}))
            result = await self._judge_one(run, post, PASS_TWO, state_dict, pack, rstate)
            if result is None:
                return
            run.counters.judged += 1
            self._save_counters(run)
            self.events.emit("judged", "pass_two", {"judge": result.model_dump(mode="json"), "composite": composite(result, pack)})

        await asyncio.gather(*[one(pid) for pid in todo])

    def _pass_two_results(self) -> list[JudgeResult]:
        rstate = load_state(self.paths)
        return [r for r in self.repo.list_judge_results(self.run_id, PASS_TWO) if r.post_id not in rstate.judge_failed]

    async def _select(self, run: Run) -> None:
        pack = self._pack(self._plan())
        selection = select(self._pass_two_results(), pack)
        self.repo.save_selection(self.run_id, selection)
        run.counters.shortlisted = len(selection.shortlist)
        run.counters.review = len(selection.review)
        self._save_counters(run)
        self.events.emit("selected", "selecting", selection.model_dump(mode="json"))

    def _aggregates(self, results: list[JudgeResult]) -> dict[str, dict[str, int]]:
        agg: dict[str, dict[str, int]] = {}
        for r in results:
            for qid, a in r.answers.items():
                if a.type.value == "choice":
                    agg.setdefault(qid, {})
                    agg[qid][str(a.value)] = agg[qid].get(str(a.value), 0) + 1
        return agg

    async def _explain(self, run: Run) -> None:
        plan = self._plan()
        selection = self.repo.get_selection(self.run_id)
        if selection is None:
            raise ExplainError("no selection to explain")
        results = self._pass_two_results()
        by_id = {r.post_id: r for r in results}
        posts = [self.repo.get_post(self.run_id, pid) for pid in selection.shortlist]
        evidence = {pid: ev for pid in selection.shortlist if (ev := self.repo.get_evidence(self.run_id, pid)) is not None}
        packet = ExplainPacket(
            brief=plan.brief, posts=posts, evidence=evidence,
            judge={pid: by_id[pid] for pid in selection.shortlist if pid in by_id},
            aggregates=self._aggregates(results),
            keyframes={pid: list(ev.keyframes) for pid, ev in evidence.items()},
        )
        report = await asyncio.to_thread(self.explain_backend.explain, packet)
        report = report.model_copy(update={"run_id": self.run_id})
        self.repo.save_report(self.run_id, report)
        self.events.emit("explained", "explaining", {"report": report.model_dump(mode="json")})

    # ---- reselect ----------------------------------------------------------------------------

    async def reselect(self, weights_override: dict[str, float]) -> Selection:
        pack = self._pack(self._plan())
        selection = select(self._pass_two_results(), pack, weights_override=weights_override)
        self.repo.save_selection(self.run_id, selection)
        run = self._run()
        run.counters.shortlisted = len(selection.shortlist)
        run.counters.review = len(selection.review)
        self._save_counters(run)
        self.events.emit("selected", run.stage.value, selection.model_dump(mode="json"))
        return selection
```

`Run.stage` is always assigned an enum member (`Stage(to)`, `Stage("failed")`) because Pydantic's `validate_assignment` is off by default and `repo.save_run` reads `run.stage.value`. Plan 01 generates enums as `str` subclasses (`--use-subclass-enum`), so `run.stage == "failed"` also holds.

`pipeline/__init__.py`: empty.

- [x] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/pipeline -q`
Expected: `8 passed`. If `test_end_to_end_fixture_run` fails on `kept` size, check plan 02's fixture evidence folder names match `safe_post_filename`.

- [x] **Step 7: Commit**

```bash
git add backend/clipsieve/adapters/fixture.py backend/clipsieve/adapters/registry.py backend/clipsieve/config.py backend/clipsieve/pipeline backend/tests/pipeline .env.example
git commit -m "feat(pipeline): add resumable Runner with per-post idempotency and fixture adapter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 10: FastAPI app, SSE, posts view

**Files:**
- Create: `backend/clipsieve/api/__init__.py`
- Create: `backend/clipsieve/api/context.py`
- Create: `backend/clipsieve/api/runs.py`
- Create: `backend/clipsieve/api/events.py`
- Create: `backend/clipsieve/api/meta.py`
- Create: `backend/clipsieve/app.py`
- Modify: `backend/pyproject.toml` (add `fastapi`, `uvicorn[standard]`, `python-multipart`; dev `httpx` already present from plan 02)
- Test: `backend/tests/api/__init__.py`, `backend/tests/api/test_runs.py`, `backend/tests/api/test_events.py`

**Interfaces:**
- Consumes: `Runner`, `post_state`, `load_state`, `RunRepository`, `load_adapters`, `get_backend`, `pack_summaries`, `read_events`, `follow_events`, `RecordedJudge`, `TypeSafeJudge`, fakes.
- Produces:
  - `api/context.py`: `class AppContext(BaseModel, arbitrary_types_allowed)`: `settings, repo, adapters: dict[str, Adapter], judge: Judge, explain: ExplainBackend, asr, ocr, frames, rubrics_dir: Path, runners: dict[str, Runner], tasks: dict[str, asyncio.Task]`; `build_context(settings: Settings) -> AppContext`; `get_context() -> AppContext` FastAPI dependency; `RUBRICS_DIR_DEFAULT = Path(__file__).resolve().parents[3] / "rubrics"`.
  - `api/runs.py`: router with the routes from the HTTP contract except events/adapters/rubrics/media. Request models `CreateRunBody(brief: str, platforms: list[str], quantities: dict[str, int], rubric_pack: str = "creator-hooks-v1", language_hint: str | None = None)`, `ReselectBody(weights: dict[str, float])`, response model `PostView(post: Post, judge: dict[str, JudgeResult], composite: float | None, state: str)` and `PostsPage(items: list[PostView], total: int)`.
  - `api/events.py`: `GET /runs/{id}/events?after=N` SSE.
  - `api/meta.py`: `GET /adapters`, `GET /rubrics`, `GET /runs/{id}/media/{post_id}/{filename}`.
  - `app.py`: `create_app(ctx: AppContext | None = None) -> FastAPI`; module-level `app = create_app()`.

Decisions: fake mode is `settings.clipsieve_explain_backend == "fake"`; it requires `clipsieve_fixture_dir` and wires `RecordedJudge`, `FakeASR`, `FakeOCR`, `FakeFrames`, `FakeExplainBackend`, and the `FixtureAdapter` for `local`. Real mode wires `TypeSafeJudge(settings.typesafe_api_key)`, `WhisperASR`, `PaddleOCRBackend`, `FfmpegFrames` (imported lazily so missing optional extras fail at first use, not at import). Background work uses `asyncio.create_task`; a run's task handle lives in `ctx.tasks[run_id]`. SSE events are JSON with `ensure_ascii=False`.

- [x] **Step 1: Add dependencies**

```bash
cd backend && uv add fastapi "uvicorn[standard]" python-multipart
```

- [x] **Step 2: Write the failing tests**

`backend/tests/api/conftest.py`:

```python
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from clipsieve.api.context import build_context
from clipsieve.app import create_app
from clipsieve.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def ctx(tmp_path):
    settings = Settings(clipsieve_data_dir=tmp_path, clipsieve_explain_backend="fake", clipsieve_fixture_dir=FIXTURES)
    return build_context(settings)


@pytest.fixture
async def client(ctx):
    app = create_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def wait_for_stage(client, run_id, stage, timeout_s=10.0):
    import asyncio
    for _ in range(int(timeout_s / 0.05)):
        r = await client.get(f"/api/runs/{run_id}")
        if r.json()["run"]["stage"] == stage:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {stage}")


async def wait_for_plan(client, run_id, timeout_s=10.0):
    import asyncio
    for _ in range(int(timeout_s / 0.05)):
        data = (await client.get(f"/api/runs/{run_id}")).json()
        if data["plan"] is not None:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} never produced a plan")
```

`backend/tests/api/test_runs.py`:

```python
import asyncio

from tests.api.conftest import wait_for_plan, wait_for_stage

BODY = {"brief": "新加坡人搬到上海的 vlog，分析开头和风格", "platforms": ["local"], "quantities": {"local": 5}, "rubric_pack": "creator-hooks-v1"}


async def test_create_run_plans_in_background(client):
    r = await client.post("/api/runs", json=BODY)
    assert r.status_code == 201
    run = r.json()
    assert run["id"].startswith("run_") and run["stage"] == "planning"
    data = await wait_for_plan(client, run["id"])
    assert data["plan"]["rubric_pack"] == "creator-hooks-v1"
    assert data["run"]["brief"]["text"] == BODY["brief"]


async def test_list_runs_newest_first(client):
    a = (await client.post("/api/runs", json=BODY)).json()["id"]
    b = (await client.post("/api/runs", json=BODY)).json()["id"]
    ids = [r["id"] for r in (await client.get("/api/runs")).json()]
    assert ids.index(b) < ids.index(a)


async def test_unknown_run_is_404(client):
    assert (await client.get("/api/runs/run_nope")).status_code == 404
    assert (await client.get("/api/runs/run_nope/report")).status_code == 404


async def test_full_flow_approve_posts_report_reselect(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    plan = (await wait_for_plan(client, run_id))["plan"]
    plan["queries"][0]["query"] = "edited"
    r = await client.put(f"/api/runs/{run_id}/plan", json=plan)
    assert r.status_code == 200 and r.json()["queries"][0]["query"] == "edited"
    r = await client.post(f"/api/runs/{run_id}/approve")
    assert r.status_code == 200 and r.json()["stage"] == "collecting"
    await wait_for_stage(client, run_id, "done")

    page = (await client.get(f"/api/runs/{run_id}/posts?offset=0&limit=3")).json()
    assert page["total"] == 5 and len(page["items"]) == 3
    states = {i["post"]["id"]: i["state"] for i in (await client.get(f"/api/runs/{run_id}/posts?limit=100")).json()["items"]}
    assert set(states.values()) <= {"collected", "dropped_pass_one", "judged", "shortlisted", "review", "judge_failed"}
    assert list(states.values()).count("dropped_pass_one") == 3
    shortlisted = [pid for pid, s in states.items() if s == "shortlisted"]
    item = next(i for i in (await client.get(f"/api/runs/{run_id}/posts?limit=100")).json()["items"] if i["post"]["id"] == shortlisted[0])
    assert "pass_two" in item["judge"] and item["composite"] is not None

    report = (await client.get(f"/api/runs/{run_id}/report")).json()
    assert report["run_id"] == run_id and {c["post_id"] for c in report["clips"]} == set(shortlisted)

    sel = (await client.post(f"/api/runs/{run_id}/reselect", json={"weights": {"hook_strength": 1.0}})).json()
    assert set(sel["shortlist"]) | set(sel["review"]) <= set(states)


async def test_approve_twice_is_409(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    assert (await client.post(f"/api/runs/{run_id}/approve")).status_code == 200
    assert (await client.post(f"/api/runs/{run_id}/approve")).status_code == 409


async def test_pause_and_resume_routes(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    assert (await client.post(f"/api/runs/{run_id}/pause")).status_code == 200  # pause before approve is allowed and sticky
    await client.post(f"/api/runs/{run_id}/approve")
    for _ in range(100):
        run = (await client.get(f"/api/runs/{run_id}")).json()["run"]
        if run["paused"]:
            break
        await asyncio.sleep(0.05)
    assert run["paused"] is True
    r = await client.post(f"/api/runs/{run_id}/resume")
    assert r.status_code == 200 and r.json()["paused"] is False
    await wait_for_stage(client, run_id, "done")


async def test_meta_routes(client):
    adapters = (await client.get("/api/adapters")).json()
    assert any(a["platform"] == "local" and a["healthy"] for a in adapters)
    rubrics = (await client.get("/api/rubrics")).json()
    assert rubrics[0]["name"] == "creator-hooks-v1"


async def test_media_route_decodes_post_id_and_blocks_traversal(client, ctx):
    from clipsieve.store.paths import RunPaths

    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    media_dir = RunPaths(ctx.settings.clipsieve_data_dir, run_id).media_dir("local:fx-001")
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    r = await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/thumb.jpg")
    assert r.status_code == 200 and r.content == b"\xff\xd8\xff\xd9"
    assert (await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/missing.jpg")).status_code == 404
    assert (await client.get(f"/api/runs/{run_id}/media/local%3Afx-001/..%2F..%2Frun.json")).status_code == 404
```

`backend/tests/api/test_events.py`:

```python
import json

from tests.api.conftest import wait_for_plan, wait_for_stage

BODY = {"brief": "新加坡人搬到上海的 vlog", "platforms": ["local"], "quantities": {"local": 5}, "rubric_pack": "creator-hooks-v1"}


async def read_sse(client, url):
    events = []
    async with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        cur = {}
        async for line in resp.aiter_lines():
            if line.startswith("id:"):
                cur["id"] = int(line[3:].strip())
            elif line.startswith("event:"):
                cur["event"] = line[6:].strip()
            elif line.startswith("data:"):
                cur["data"] = json.loads(line[5:].strip())
            elif line == "" and cur:
                events.append(cur)
                cur = {}
    return events


async def approved_run(client):
    run_id = (await client.post("/api/runs", json=BODY)).json()["id"]
    await wait_for_plan(client, run_id)
    await client.post(f"/api/runs/{run_id}/approve")
    return run_id


async def test_stream_from_start_ends_at_done(client):
    run_id = await approved_run(client)
    events = await read_sse(client, f"/api/runs/{run_id}/events")
    seqs = [e["id"] for e in events]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))  # contiguous
    assert all(e["event"] == "run_event" for e in events)
    assert events[0]["data"]["type"] == "run_created"
    assert events[-1]["data"]["type"] == "done"


async def test_sse_after_returns_exact_tail(client):
    run_id = await approved_run(client)
    await wait_for_stage(client, run_id, "done")
    full = await read_sse(client, f"/api/runs/{run_id}/events")
    cut = full[len(full) // 2]["id"]
    tail = await read_sse(client, f"/api/runs/{run_id}/events?after={cut}")
    assert [e["id"] for e in tail] == [e["id"] for e in full if e["id"] > cut]
    assert tail[-1]["data"]["type"] == "done"
    assert await read_sse(client, f"/api/runs/{run_id}/events?after={full[-1]['id']}") == []


async def test_chinese_caption_roundtrip(client):
    run_id = await approved_run(client)
    events = await read_sse(client, f"/api/runs/{run_id}/events")
    collected = [e["data"] for e in events if e["data"]["type"] == "post_collected"]
    zh = [p for p in collected if any("一" <= ch <= "鿿" for ch in (p["payload"]["post"]["text"].get("caption") or ""))]
    assert zh, "fixtures must include a Chinese caption"
    post_id = zh[0]["payload"]["post"]["id"]
    caption_sse = zh[0]["payload"]["post"]["text"]["caption"]
    page = (await client.get(f"/api/runs/{run_id}/posts?limit=100")).json()
    caption_api = next(i["post"]["text"]["caption"] for i in page["items"] if i["post"]["id"] == post_id)
    assert caption_api == caption_sse
    run_brief = (await client.get(f"/api/runs/{run_id}")).json()["run"]["brief"]["text"]
    assert run_brief == BODY["brief"]
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/api -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.api'`.

- [x] **Step 4: Implement `api/context.py`**

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from clipsieve.adapters.base import Adapter
from clipsieve.adapters.registry import load_adapters
from clipsieve.config import Settings, get_settings
from clipsieve.evidence.asr import ASR, FakeASR
from clipsieve.evidence.frames import FakeFrames, FrameExtractor
from clipsieve.evidence.ocr import OCR, FakeOCR
from clipsieve.explain.base import ExplainBackend, get_backend
from clipsieve.judge.base import Judge
from clipsieve.pipeline.runner import Runner
from clipsieve.store.db import get_engine, init_db
from clipsieve.store.repo import RunRepository

RUBRICS_DIR_DEFAULT = Path(__file__).resolve().parents[3] / "rubrics"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"  # backend/tests/fixtures


class AppContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    settings: Settings
    repo: RunRepository
    adapters: dict[str, Adapter]
    judge: Judge
    explain: ExplainBackend
    asr: ASR
    ocr: OCR
    frames: FrameExtractor
    rubrics_dir: Path
    runners: dict[str, Runner] = {}
    tasks: dict[str, asyncio.Task] = {}

    def runner_for(self, run_id: str) -> Runner:
        if run_id not in self.runners:
            self.runners[run_id] = Runner(
                run_id=run_id, settings=self.settings, repo=self.repo, adapters=self.adapters, judge=self.judge,
                explain=self.explain, asr=self.asr, ocr=self.ocr, frames=self.frames, rubrics_dir=self.rubrics_dir,
            )
        return self.runners[run_id]


def build_context(settings: Settings) -> AppContext:
    engine = get_engine(settings.clipsieve_data_dir)
    init_db(engine)
    repo = RunRepository(settings.clipsieve_data_dir, engine)
    fake = settings.clipsieve_explain_backend == "fake"
    if fake:
        if settings.clipsieve_fixture_dir is None:
            # Addendum E.7 / D.2: fake mode implies the repo fixtures unless told otherwise.
            settings = settings.model_copy(update={"clipsieve_fixture_dir": DEFAULT_FIXTURE_DIR})
        from clipsieve.judge.recorded import RecordedJudge

        judge: Judge = RecordedJudge(settings.clipsieve_fixture_dir)
        asr: ASR = FakeASR()
        ocr: OCR = FakeOCR()
        frames: FrameExtractor = FakeFrames()
    else:
        from clipsieve.evidence.asr import WhisperASR
        from clipsieve.evidence.frames import FfmpegFrames
        from clipsieve.evidence.ocr import PaddleOCRBackend
        from clipsieve.judge.typesafe_client import TypeSafeJudge

        judge = TypeSafeJudge(settings.typesafe_api_key)
        asr, ocr, frames = WhisperASR(), PaddleOCRBackend(), FfmpegFrames()
    return AppContext(
        settings=settings, repo=repo, adapters=load_adapters(settings), judge=judge,
        explain=get_backend(settings, settings.clipsieve_fixture_dir), asr=asr, ocr=ocr, frames=frames,
        rubrics_dir=RUBRICS_DIR_DEFAULT,
    )


_CONTEXT: AppContext | None = None


def set_context(ctx: AppContext) -> None:
    global _CONTEXT
    _CONTEXT = ctx


def get_context() -> AppContext:
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = build_context(get_settings())
    return _CONTEXT
```

- [x] **Step 5: Implement `api/runs.py`**

```python
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from clipsieve.api.context import AppContext, get_context
from clipsieve.judge.rubric import PASS_ONE, PASS_TWO
from clipsieve.models import Brief, JudgeResult, Plan, Post, Report, Run
from clipsieve.pipeline.runner import post_state
from clipsieve.pipeline.state import load_state
from clipsieve.select.scoring import composite
from clipsieve.select.select import Selection
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import RunNotFound

log = structlog.get_logger(__name__)
router = APIRouter()


class CreateRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str
    platforms: list[str]
    quantities: dict[str, int]
    rubric_pack: str = "creator-hooks-v1"
    language_hint: str | None = None


class ReselectBody(BaseModel):
    weights: dict[str, float]


class PostView(BaseModel):
    post: Post
    judge: dict[str, JudgeResult]
    composite: float | None
    state: str


class PostsPage(BaseModel):
    items: list[PostView]
    total: int


class RunWithPlan(BaseModel):
    run: Run
    plan: Plan | None


def _get_run(ctx: AppContext, run_id: str) -> Run:
    try:
        return ctx.repo.get_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(404, f"run {run_id} not found") from exc


def _spawn(ctx: AppContext, run_id: str, coro) -> None:
    task = asyncio.create_task(coro)
    ctx.tasks[run_id] = task

    def _done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            log.error("run_task_failed", run_id=run_id, error=repr(t.exception()))

    task.add_done_callback(_done)


@router.post("/runs", response_model=Run, status_code=201)
async def create_run(body: CreateRunBody, ctx: AppContext = Depends(get_context)) -> Run:
    unknown = [p for p in body.platforms if p not in ctx.adapters]
    if unknown:
        raise HTTPException(422, f"no adapter for platforms: {unknown}")
    brief = Brief(text=body.brief, topic="", audience="", persona="", language_hint=body.language_hint)
    run = ctx.repo.create_run(brief, body.platforms, {p: body.quantities.get(p, 500) for p in body.platforms}, body.rubric_pack)
    runner = ctx.runner_for(run.id)  # the Runner constructor emits run_created when the log is empty (Task 9); do not emit it here
    _spawn(ctx, run.id, runner.plan())
    return run


@router.get("/runs", response_model=list[Run])
async def list_runs(ctx: AppContext = Depends(get_context)) -> list[Run]:
    return ctx.repo.list_runs()


@router.get("/runs/{run_id}", response_model=RunWithPlan)
async def get_run(run_id: str, ctx: AppContext = Depends(get_context)) -> RunWithPlan:
    run = _get_run(ctx, run_id)
    return RunWithPlan(run=run, plan=ctx.repo.get_plan(run_id))


@router.put("/runs/{run_id}/plan", response_model=Plan)
async def save_plan(run_id: str, plan: Plan, ctx: AppContext = Depends(get_context)) -> Plan:
    run = _get_run(ctx, run_id)
    if run.stage.value != "planning":
        raise HTTPException(409, "plan can only be edited before approval")
    plan = plan.model_copy(update={"run_id": run_id, "approved_at": None})
    ctx.repo.save_plan(run_id, plan)
    return plan


@router.post("/runs/{run_id}/approve", response_model=Run)
async def approve(run_id: str, ctx: AppContext = Depends(get_context)) -> Run:
    run = _get_run(ctx, run_id)
    if run.stage.value != "planning":
        raise HTTPException(409, f"run is already {run.stage.value}")
    plan = ctx.repo.get_plan(run_id)
    if plan is None:
        raise HTTPException(409, "plan is not ready yet")
    runner = ctx.runner_for(run_id)
    await runner.approve(plan)
    _spawn(ctx, run_id, runner.run())
    return _get_run(ctx, run_id)


@router.post("/runs/{run_id}/pause", response_model=Run)
async def pause(run_id: str, ctx: AppContext = Depends(get_context)) -> Run:
    _get_run(ctx, run_id)
    ctx.runner_for(run_id).pause()
    return _get_run(ctx, run_id)


@router.post("/runs/{run_id}/resume", response_model=Run)
async def resume(run_id: str, ctx: AppContext = Depends(get_context)) -> Run:
    run = _get_run(ctx, run_id)
    runner = ctx.runner_for(run_id)
    runner.resume_flag()
    if run.stage.value in ("done", "failed", "planning"):
        return run
    task = ctx.tasks.get(run_id)
    if task is not None and not task.done():
        return run  # still running; the flag alone is enough
    run.paused = False
    ctx.repo.save_run(run)
    _spawn(ctx, run_id, runner.run())
    return _get_run(ctx, run_id)


@router.get("/runs/{run_id}/posts", response_model=PostsPage)
async def posts(run_id: str, offset: int = 0, limit: int = 100, ctx: AppContext = Depends(get_context)) -> PostsPage:
    _get_run(ctx, run_id)
    plan = ctx.repo.get_plan(run_id)
    pack = None
    if plan is not None:
        from clipsieve.judge.rubric import find_pack, with_persona_criteria
        pack = with_persona_criteria(find_pack(plan.rubric_pack, ctx.rubrics_dir), plan.persona_fit_criteria)
    paths = RunPaths(ctx.settings.clipsieve_data_dir, run_id)
    state = load_state(paths)
    selection: Selection | None = ctx.repo.get_selection(run_id)
    judged_two = {r.post_id for r in ctx.repo.list_judge_results(run_id, PASS_TWO)}
    items: list[PostView] = []
    for post in ctx.repo.list_posts(run_id, offset, limit):
        judge: dict[str, JudgeResult] = {}
        for pass_name in (PASS_ONE, PASS_TWO):
            r = ctx.repo.get_judge_result(run_id, post.id, pass_name)
            if r is not None:
                judge[pass_name] = r
        comp = None
        if selection is not None and post.id in selection.scores:
            comp = selection.scores[post.id]
        elif PASS_TWO in judge and pack is not None:
            comp = composite(judge[PASS_TWO], pack)
        items.append(PostView(post=post, judge=judge, composite=comp, state=post_state(post.id, state, selection, judged_two)))
    return PostsPage(items=items, total=ctx.repo.count_posts(run_id))


@router.get("/runs/{run_id}/report", response_model=Report)
async def report(run_id: str, ctx: AppContext = Depends(get_context)) -> Report:
    _get_run(ctx, run_id)
    rep = ctx.repo.get_report(run_id)
    if rep is None:
        raise HTTPException(404, "no report yet")
    return rep


@router.post("/runs/{run_id}/reselect", response_model=Selection)
async def reselect(run_id: str, body: ReselectBody, ctx: AppContext = Depends(get_context)) -> Selection:
    run = _get_run(ctx, run_id)
    if ctx.repo.get_selection(run_id) is None and run.stage.value not in ("selecting", "explaining", "done", "failed"):
        raise HTTPException(409, "nothing judged yet")
    return await ctx.runner_for(run_id).reselect(body.weights)

```

- [x] **Step 6: Implement `api/events.py` and `api/meta.py`**

`api/events.py`:

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from clipsieve.api.context import AppContext, get_context
from clipsieve.api.runs import _get_run
from clipsieve.events.reader import follow_events, read_events
from clipsieve.store.paths import RunPaths

router = APIRouter()
TERMINAL = {"done", "failed"}


def _format(event) -> str:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    return f"id: {event.seq}\nevent: run_event\ndata: {data}\n\n"


def _finished(events) -> bool:
    return any(e.type.value == "done" or e.stage.value == "failed" for e in events)


@router.get("/runs/{run_id}/events")
async def events(run_id: str, after: int = 0, ctx: AppContext = Depends(get_context)) -> StreamingResponse:
    _get_run(ctx, run_id)
    paths = RunPaths(ctx.settings.clipsieve_data_dir, run_id)

    async def gen() -> AsyncIterator[str]:
        existing = read_events(paths, after)
        for e in existing:
            yield _format(e)
        if _finished(read_events(paths, 0)):
            return
        last = existing[-1].seq if existing else after
        async for e in follow_events(paths, after=last):
            yield _format(e)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`api/meta.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clipsieve.api.context import AppContext, get_context
from clipsieve.api.runs import _get_run
from clipsieve.explain.base import RubricPackSummary
from clipsieve.planner.plan import pack_summaries
from clipsieve.store.paths import RunPaths

router = APIRouter()


class AdapterStatus(BaseModel):
    platform: str
    healthy: bool
    message: str


@router.get("/adapters", response_model=list[AdapterStatus])
async def adapters(ctx: AppContext = Depends(get_context)) -> list[AdapterStatus]:
    out = []
    for platform, adapter in sorted(ctx.adapters.items()):
        h = adapter.healthcheck()
        out.append(AdapterStatus(platform=platform, healthy=h.ok, message=h.message))
    return out


@router.get("/rubrics", response_model=list[RubricPackSummary])
async def rubrics(ctx: AppContext = Depends(get_context)) -> list[RubricPackSummary]:
    return pack_summaries(ctx.rubrics_dir)


@router.get("/runs/{run_id}/media/{post_id}/{filename}")
async def media(run_id: str, post_id: str, filename: str, ctx: AppContext = Depends(get_context)) -> FileResponse:
    _get_run(ctx, run_id)
    base = RunPaths(ctx.settings.clipsieve_data_dir, run_id).media_dir(post_id).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(404, "no such media")
    return FileResponse(target)
```

- [x] **Step 7: Implement `app.py`**

```python
from __future__ import annotations

from fastapi import FastAPI

from clipsieve.api import events, meta, runs
from clipsieve.api.context import AppContext, get_context, set_context


def create_app(ctx: AppContext | None = None) -> FastAPI:
    if ctx is not None:
        set_context(ctx)
    app = FastAPI(title="clipsieve")
    app.include_router(runs.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "backend": get_context().settings.clipsieve_explain_backend}

    return app


app = create_app()
```

`api/__init__.py`: empty. Note `app = create_app()` at import time calls `get_context()` lazily only on the first request, so importing the module in tests does not build a real context.

- [x] **Step 8: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api -q`
Expected: `11 passed`. If `test_stream_from_start_ends_at_done` hangs, confirm plan 01's `follow_events` stops on `done` and that `_finished` sees the terminal event written by the Runner before the generator starts following.

- [x] **Step 9: Commit**

```bash
git add backend/clipsieve/api backend/clipsieve/app.py backend/tests/api backend/pyproject.toml backend/uv.lock
git commit -m "feat(api): add FastAPI app with run lifecycle, SSE events, posts view and meta routes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 11: `sieve` CLI

**Files:**
- Create: `backend/clipsieve/cli.py`
- Modify: `backend/pyproject.toml` (add `typer`; `[project.scripts] sieve = "clipsieve.cli:app"` already exists from plan 01)
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `build_context`, `Runner`, `read_events`, `RunPaths`, `Brief`.
- Produces: typer app `app` with commands `run`, `replay`, `reselect`, `reindex`, `eval` (stub). Exit codes: 0 success, 1 run failed, 2 usage or not implemented.
- `print` is permitted in this module only (output helpers `_say`, `_json`).

- [x] **Step 1: Add dependency**

```bash
cd backend && uv add typer
```

- [x] **Step 2: Write the failing tests**

`backend/tests/test_cli.py`:

```python
import json
import re
from pathlib import Path

from typer.testing import CliRunner

from clipsieve.cli import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
runner = CliRunner()


def env(tmp_path):
    return {
        "CLIPSIEVE_DATA_DIR": str(tmp_path),
        "CLIPSIEVE_EXPLAIN_BACKEND": "fake",
        "CLIPSIEVE_FIXTURE_DIR": str(FIXTURES),
    }


def test_run_auto_approve_completes_and_prints_summary(tmp_path):
    result = runner.invoke(app, ["run", "--brief", "新加坡人 Shanghai vlog", "--platforms", "local", "--limit", "5",
                                 "--pack", "creator-hooks-v1", "--auto-approve"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    m = re.search(r"run_id: (run_[0-9a-f]{12})", result.output)
    assert m
    assert "stage: done" in result.output
    assert "collected: 5" in result.output and "shortlisted:" in result.output
    assert "jev_cost_usd:" in result.output
    assert (tmp_path / "runs" / m.group(1) / "report.json").exists()


def test_run_without_auto_approve_declined_exits_2(tmp_path):
    result = runner.invoke(app, ["run", "--brief", "b", "--platforms", "local", "--limit", "5"], input="n\n", env=env(tmp_path))
    assert result.exit_code == 2
    assert "plan" in result.output.lower()


def test_replay_prints_events_in_order_fast(tmp_path):
    r = runner.invoke(app, ["run", "--brief", "b", "--platforms", "local", "--limit", "5", "--auto-approve"], env=env(tmp_path))
    run_id = re.search(r"run_id: (run_\w+)", r.output).group(1)
    result = runner.invoke(app, ["replay", run_id, "--speed", "1000"], env=env(tmp_path))
    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
    assert [e["seq"] for e in lines] == list(range(1, len(lines) + 1))
    assert lines[0]["type"] == "run_created" and lines[-1]["type"] == "done"


def test_reselect_and_reindex(tmp_path):
    r = runner.invoke(app, ["run", "--brief", "b", "--platforms", "local", "--limit", "5", "--auto-approve"], env=env(tmp_path))
    run_id = re.search(r"run_id: (run_\w+)", r.output).group(1)
    result = runner.invoke(app, ["reselect", run_id, "--weights", "hook_strength=1.0"], env=env(tmp_path))
    assert result.exit_code == 0 and "shortlist" in result.output
    result = runner.invoke(app, ["reindex", run_id], env=env(tmp_path))
    assert result.exit_code == 0 and "reindexed" in result.output


def test_eval_is_a_stub(tmp_path):
    result = runner.invoke(app, ["eval", "--pack", "creator-hooks-v1", "--golden", "x.jsonl"], env=env(tmp_path))
    assert result.exit_code == 2 and "plan 05" in result.output


def test_unknown_run_exits_1(tmp_path):
    result = runner.invoke(app, ["replay", "run_nope"], env=env(tmp_path))
    assert result.exit_code == 1 and "not found" in result.output
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clipsieve.cli'` (or an ImportError if plan 01 left a placeholder `cli.py`; replace it).

- [x] **Step 4: Implement `cli.py`**

```python
"""`sieve` command line. The only module in clipsieve/ allowed to print."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import typer

from clipsieve.api.context import build_context
from clipsieve.config import Settings
from clipsieve.events.reader import read_events
from clipsieve.models import Brief
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import RunNotFound

app = typer.Typer(no_args_is_help=True, add_completion=False, help="clipsieve: sift social clips, explain the winners.")


def _say(msg: str) -> None:
    print(msg)  # noqa: T201


def _json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False))  # noqa: T201


def _settings(data_dir: Path | None) -> Settings:
    settings = Settings()
    if data_dir is not None:
        settings = settings.model_copy(update={"clipsieve_data_dir": data_dir})
    return settings


def _parse_weights(spec: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        key, _, value = part.partition("=")
        if not key or not value:
            raise typer.BadParameter(f"weights must be key=value pairs, got {part!r}")
        out[key] = float(value)
    return out


@app.command()
def run(
    brief: str = typer.Option(..., "--brief", help="Research brief, one or two sentences."),
    platforms: str = typer.Option("youtube", "--platforms", help="Comma-separated platform ids."),
    limit: int = typer.Option(500, "--limit", help="Posts per platform."),
    pack: str = typer.Option("creator-hooks-v1", "--pack"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Skip the plan confirmation."),
    language_hint: str | None = typer.Option(None, "--language-hint"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    ctx = build_context(_settings(data_dir))
    plats = [p.strip() for p in platforms.split(",") if p.strip()]
    missing = [p for p in plats if p not in ctx.adapters]
    if missing:
        _say(f"no adapter for: {', '.join(missing)}")
        raise typer.Exit(2)
    brief_model = Brief(text=brief, topic="", audience="", persona="", language_hint=language_hint)
    run_obj = ctx.repo.create_run(brief_model, plats, {p: limit for p in plats}, pack)
    runner = ctx.runner_for(run_obj.id)  # the Runner constructor emits run_created when the log is empty (Task 9); do not emit it here
    _say(f"run_id: {run_obj.id}")

    plan = asyncio.run(runner.plan())
    _say("plan:")
    _json(plan.model_dump(mode="json"))
    if not auto_approve and not typer.confirm("Approve this plan and start the run?", default=False):
        _say("plan not approved; run left in planning. Approve later from the dashboard.")
        raise typer.Exit(2)

    async def go() -> None:
        await runner.approve(plan)
        await runner.run()

    asyncio.run(go())
    final = ctx.repo.get_run(run_obj.id)
    _say(f"stage: {final.stage.value}")
    for key, value in final.counters.model_dump().items():
        _say(f"{key}: {value}")
    if final.stage.value == "failed":
        _say(f"error: {final.error}")
        raise typer.Exit(1)


@app.command()
def replay(run_id: str, speed: float = typer.Option(1.0, "--speed"), data_dir: Path | None = typer.Option(None, "--data-dir")) -> None:
    settings = _settings(data_dir)
    paths = RunPaths(settings.clipsieve_data_dir, run_id)
    if not paths.events_jsonl.exists():
        _say(f"run {run_id} not found")
        raise typer.Exit(1)
    events = read_events(paths)
    prev = None
    for e in events:
        if prev is not None and speed > 0:
            delay = (e.ts - prev).total_seconds() / speed
            if delay > 0:
                time.sleep(min(delay, 5.0))
        prev = e.ts
        _json(e.model_dump(mode="json"))


@app.command()
def reselect(run_id: str, weights: str = typer.Option(..., "--weights", help="e.g. hook_strength=0.5,persona_fit=0.5"),
             data_dir: Path | None = typer.Option(None, "--data-dir")) -> None:
    ctx = build_context(_settings(data_dir))
    try:
        ctx.repo.get_run(run_id)
    except RunNotFound:
        _say(f"run {run_id} not found")
        raise typer.Exit(1) from None
    selection = asyncio.run(ctx.runner_for(run_id).reselect(_parse_weights(weights)))
    _json(selection.model_dump(mode="json"))


@app.command()
def reindex(run_id: str, data_dir: Path | None = typer.Option(None, "--data-dir")) -> None:
    ctx = build_context(_settings(data_dir))
    try:
        ctx.repo.reindex(run_id)
    except RunNotFound:
        _say(f"run {run_id} not found")
        raise typer.Exit(1) from None
    _say(f"reindexed {run_id}")


@app.command()
def eval(pack: str = typer.Option(..., "--pack"), golden: Path = typer.Option(..., "--golden"),
         mode: str = typer.Option("raw", "--mode")) -> None:
    _say("sieve eval arrives with plan 05 (contrib adapters and evals). Nothing was run.")
    raise typer.Exit(2)
```

If plan 01 generated `Settings` with `frozen=True`, replace the `model_copy` in `_settings` with `Settings(clipsieve_data_dir=data_dir)` plus `_env_file` defaults; the test passes `CLIPSIEVE_DATA_DIR` through the environment either way.

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli.py -q`
Expected: `6 passed`. Then `cd backend && uv run sieve --help` prints the five commands.

- [x] **Step 6: Commit**

```bash
git add backend/clipsieve/cli.py backend/tests/test_cli.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(cli): add sieve run, replay, reselect, reindex and eval stub

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: DOX docs, README, green `bun run check`

**Files:**
- Modify: `backend/AGENTS.md`
- Modify: `AGENTS.md` (root Child DOX Index: `rubrics/` present)
- Modify: `README.md` (add "Running a fixture run")
- Modify: `backend/README.md` (module map)

**Interfaces:** none new.

- [x] **Step 1: Update `backend/AGENTS.md`**

Append these sections (keep plan 01 and 02 content above them):

```markdown
## judge/

- `rubric.py` is the only module that imports `typesafe_sdk` primitives. Everything else sees `Question` and `JudgeAnswer`.
- One `system_one` request per post per pass, all questions batched. Never one request per question.
- `TypeSafeJudge` retries 429/529 with exponential backoff up to 5 tries, then raises `JudgeFailed`. Any other error is `JudgeFailed` after one attempt. Callers record the post in `RunState.judge_failed` and continue.
- `RecordedJudge` is the fake. Fixtures: `tests/fixtures/judge/<safe id>.<pass>.json`, regenerated by `tests/fixtures/judge/make_fixtures.py`.

## select/

- Pure functions. No I/O, no model calls, no settings.
- `Selection` is defined here (plan 01) and persisted by `RunRepository.save_selection`.
- Normalisation: score position among levels from `value` and `legend`, 0-indexed when no legend. Noul contributes its probability. Choice never contributes to composite; it drives quotas and aggregates.
- `dropped` reasons: `hard_filter`, `quota`, `not_selected`.

## explain/

- `ExplainBackend` has two methods, `plan` and `explain`. Backends never know the run id; callers overwrite `run_id`.
- `claude_cli` is the default and is for the user's own Claude login. Argv is fixed in `ClaudeCliBackend._argv`; never add `--bare`. Prompts live in `explain/prompts/` and are the system prompt files passed to `claude -p`.
- Citation rule: every cited post id must be in the packet. `claude_cli` retries once with the unknown ids in the task line, then raises `ExplainError`.
- `FakeExplainBackend` and `tests/fixtures/claude-shim/claude` answer from `tests/fixtures/explain/`.

## pipeline/

- `Runner` owns stage order and event emission. Stages are idempotent per post: an existing `judge/<id>.<pass>.json` is never re-judged; `RunState` (`state.json`) records pass-one decisions, extracted posts and judge failures.
- Pause is cooperative: checked between posts and stages. `run()` returns normally when paused.
- Explain failure moves the run to `failed` and keeps the selection viewable.

## api/

- Routers under `/api`. `AppContext` is built once per process; `CLIPSIEVE_EXPLAIN_BACKEND=fake` wires every fake and the `FixtureAdapter`.
- SSE: `id: <seq>`, `event: run_event`, `data: <RunEvent JSON>`; `?after=N` resumes exactly after `N`; the stream ends after `done` or `failed`.
- Background work is `asyncio.create_task`, handles in `ctx.tasks[run_id]`.

## cli.py

- The only module allowed to `print`. All commands build the same `AppContext` as the API.
```

- [x] **Step 2: README "Running a fixture run"**

Append to the root `README.md`:

````markdown
## Running a fixture run (no keys, no network)

```bash
cd backend
CLIPSIEVE_EXPLAIN_BACKEND=fake CLIPSIEVE_FIXTURE_DIR=$PWD/tests/fixtures \
  uv run sieve run --brief "Singaporean moving to Shanghai, vlog style" --platforms local --limit 5 --auto-approve
```

Then `uv run sieve replay <run_id> --speed 10` prints the event log at ten times speed. The same run is visible in the dashboard at `/runs/<run_id>/replay` once the frontend (plan 04) is running.

To use real services, set `TYPESAFE_API_KEY` in `.env`, log in to Claude Code once (`claude` then `/login`), and run with `CLIPSIEVE_EXPLAIN_BACKEND=claude_cli`. The `claude_cli` backend is for your own Claude subscription; hosting clipsieve for others requires the API backend.
````

`backend/README.md`: add a module map table listing `judge/`, `select/`, `explain/`, `pipeline/`, `api/`, `cli.py` with one line each, copied from the AGENTS.md section headers above.

- [x] **Step 3: Run the full check**

Run: `bun run check`
Expected: schema drift check passes (no generated file changed in this plan), ruff clean, Biome clean, `pytest` reports all tests from tasks 1 to 11 passing plus plan 01 and 02 tests, frontend placeholder scripts succeed.

If ruff flags `BLE001` on the broad `except Exception` lines in `pipeline/runner.py`, keep the `# noqa: BLE001` comments shown in Task 9; they are deliberate boundaries where one post's failure must not stop the run.

- [x] **Step 4: Commit**

```bash
git add AGENTS.md backend/AGENTS.md README.md backend/README.md
git commit -m "docs: document judge, select, explain, pipeline, api and cli contracts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

**Spec coverage.** §4.4 rubric → Task 1. §7.1 judge, concurrency 16, backoff, cost → Task 2. Recorded fake → Task 3. §7.2 steps 1 to 5 → Tasks 4 and 5. §8.1 to 8.4 → Tasks 6 and 7. Planning step of §2 → Task 8. §2 stages 3 to 10, §12 error handling, idempotency and resume → Task 9. §10 API surface and §9.3 transport → Task 10. CLI from the overview → Task 11. §13 fakes for every external system: `RecordedJudge`, `FakeExplainBackend`, claude shim, `FixtureAdapter`, plus plan 02's ASR/OCR/frames fakes. §7.3 Chinese eval and `sieve eval` are plan 05; the stub in Task 11 reserves the command.

**Type consistency.** `questions_for_pass(pack, pass_name)` returns `dict[str, Question]` and is passed straight into `Judge.judge`. `JudgeResult.pass_name` is compared with `.value`. `Selection` fields are `shortlist`, `review`, `scores`, `dropped` everywhere, including the `selected` event payload (`selection.model_dump()`), which matches the overview payload table. `post_state` returns exactly the six `PostView.state` strings in the HTTP contract. `ExplainBackend.plan` takes `(brief, packs, platforms)` in both backends and in `build_plan`.

**Review Focus coverage.** Item 1: Task 2 and Task 9 tests. Item 2: Task 7 and Task 9 tests. Item 3: Task 10 `test_sse_after_returns_exact_tail`. Item 4: Task 10 `test_chinese_caption_roundtrip`. Items 5 to 7: Task 9 resume and pause tests, Task 1 persona criteria test.

**Known seams to watch while executing.** Enum assignment on `Run.stage` (Task 9 note). `follow_events` termination relies on plan 01 behaviour. `FixtureAdapter.fetch_media` depends on plan 02's fixture evidence folder layout; if the sidecar names differ, adjust the glob in one place.
