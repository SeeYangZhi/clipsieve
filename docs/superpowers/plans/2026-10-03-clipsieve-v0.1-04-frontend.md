# clipsieve Frontend (Plan 04) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md` first; it is the binding interface contract and wins over this file on any conflict.

**Goal:** Build the Next.js 16 frontend for clipsieve: brief form, editable plan, live four-region dashboard over SSE, report with citations, replay player, bilingual UI, and one Playwright flow against the fake backend.

**Architecture:** A thin client. All state comes from the REST API and the `RunEvent` SSE stream under `/api/*`, proxied by a Next rewrite to FastAPI on port 8000. A pure reducer (`src/lib/events.ts`) turns the event stream into `DashboardState`; one hook (`useRunEvents`) feeds that reducer from either a live `EventSource` or a replayed log at original timing. Components are shadcn primitives with Tailwind 4 and every string through `t()`.

**Tech Stack:** Bun 1.3, Next.js 16 (App Router, `src/`), React 19, TypeScript strict, Tailwind 4, shadcn/ui, lucide-react, Biome via ultracite 7, Vitest + Testing Library + jsdom, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md` (§9 Dashboard, §10 API) and `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md` (Frontend contract, HTTP API contract, Fixture contract).

## Global Constraints

- Python 3.12 exactly (`requires-python = ">=3.12,<3.13"`). Managed by `uv`. Never pip.
- Bun 1.3+ for all JS. Never npm, yarn or pnpm. Next.js 16, React 19, Tailwind 4, shadcn, ultracite 7 (Biome).
- Backend package name `clipsieve`, import root `backend/clipsieve/`. CLI command `sieve`.
- `structlog` only for logging. No `print()` in `backend/clipsieve/`.
- Pydantic v2 everywhere. Settings via `pydantic-settings` reading `.env`.
- Every external system behind a Protocol with a fake: `Adapter`, `ASR`, `OCR`, `FrameExtractor`, `Judge`, `ExplainBackend`.
- Tests: `pytest` with `pytest-asyncio` (mode `auto`) in `backend/tests/`; Vitest in `frontend/`; one Playwright flow in `frontend/e2e/`. No live network in tests. CI uses fakes only.
- Commit after every task with a conventional-commit message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Every new directory with code gets an `AGENTS.md` (DOX child) in the same task that creates it, and the root `AGENTS.md` Child DOX Index is updated in that task.
- No file in the repo may contain a real API key. `.env.example` lists every variable with an empty value.
- Chinese and English UI strings from the first component.

Plan-04 specific:

- The frontend never reads run files. Only `/api/*` and SSE.
- Frontend package name is `frontend` (root scripts use `bun run --filter frontend ...`). Scripts required: `dev`, `build`, `typecheck`, `test`, `e2e`.
- No eslint, no prettier. `frontend/biome.jsonc` is `{ "extends": ["//"] }` and relies on the root `biome.jsonc` from plan 01 having `"root": true`.
- SSE via the browser `EventSource` only. No SSE libraries.
- Post ids contain `:`; always `encodeURIComponent` them in URLs.

## Review Focus

1. **Reconnect mid-run (shared RF 3).** Dropping the SSE connection after seq N and reopening with `after=N` must produce byte-identical `DashboardState` to an uninterrupted stream. Pinned in Task 4 (`reduceEvent` ignores `seq <= lastSeq`, split-stream test) and Task 5 (fake EventSource error then reconnect test).
2. **Chinese text end to end (shared RF 5).** Captions like `新加坡人在上海的第一周` must render unchanged in tiles, current item and report. Pinned in Task 4 fixture, Task 8 PostGrid test, Task 11 e2e assertion.
3. **Failed judge on one post.** An `error` event with `where: "judge"` and a `post_id` must mark exactly that tile `judge_failed` and increment `errors`, leaving other tiles untouched. Pinned in Task 4.
4. **Replay timing and speed change.** Replay at 4x must emit the same events in the same order with quarter delays, and changing speed mid-replay must not skip or duplicate an event. Pinned in Task 5.
5. **Report with a post the posts endpoint does not know.** If a report cites an id that `getPosts` did not return (backend RF 4 should prevent this), the link must render disabled with a tooltip, never a broken dialog. Pinned in Task 9.

---

### Task 1: Scaffold the Next.js app, shadcn, Biome, Vitest

**Files:**
- Create: `frontend/` via create-next-app, then `frontend/biome.jsonc`, `frontend/next.config.ts`, `frontend/vitest.config.ts`, `frontend/vitest.setup.ts`, `frontend/AGENTS.md`, `frontend/src/lib/smoke.test.ts`
- Modify: `frontend/package.json`, `frontend/tsconfig.json`, root `AGENTS.md` (Child DOX Index)

**Interfaces:**
- Consumes: root `biome.jsonc` with `"root": true` (plan 01); root `package.json` workspaces including `frontend` (plan 01).
- Produces: a `frontend` workspace package with scripts `dev`, `build`, `typecheck`, `test`, `e2e`; shadcn components under `src/components/ui/`; `@/` alias to `src/`.

- [x] **Step 1: Create the app**

Run from repo root:

```bash
bunx --bun create-next-app@latest frontend --ts --tailwind --app --src-dir --use-bun --import-alias "@/*" --no-eslint --yes
```

If the CLI prompts for a linter, choose **Biome**. If it prompts for Turbopack, accept. Expected: `frontend/` exists with `src/app/layout.tsx`, `src/app/page.tsx`, `next.config.ts`, `tsconfig.json`.

- [x] **Step 2: Read the Next 16 docs that ship with the package and note the facts**

```bash
ls frontend/node_modules/next/dist/docs/
grep -ril "rewrites" frontend/node_modules/next/dist/docs/ | head -5
grep -ril "useParams" frontend/node_modules/next/dist/docs/ | head -3
```

Open the files found and confirm three things, then write them into `frontend/AGENTS.md` in Step 8: the `rewrites()` signature in `next.config.ts`; that `params` in server page components is a `Promise` in Next 16 and client pages should use `useParams()`; how `"use client"` route files are declared. If any Step below contradicts the shipped docs, the docs win: adjust the code and record the difference in `frontend/AGENTS.md`.

- [x] **Step 3: Remove any eslint remnants and set Biome**

```bash
cd frontend && rm -f eslint.config.mjs .eslintrc.json && bun remove eslint eslint-config-next 2>/dev/null; cd ..
```

Create `frontend/biome.jsonc`:

```jsonc
{
  "$schema": "https://biomejs.dev/schemas/2.3.0/schema.json",
  "extends": ["//"]
}
```

- [x] **Step 4: Configure the API rewrite**

Replace `frontend/next.config.ts`:

```ts
import type { NextConfig } from "next";

const API_ORIGIN = process.env.CLIPSIEVE_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
```

- [x] **Step 5: Install test tooling and shadcn**

```bash
cd frontend
bun add -d vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test
bunx --bun shadcn@latest init -d
bunx --bun shadcn@latest add button card input textarea checkbox select badge progress table tabs slider dialog sonner tooltip
bun add lucide-react
cd ..
```

Expected: `frontend/components.json` exists; `frontend/src/components/ui/button.tsx` and the others exist.

- [x] **Step 6: Scripts and Vitest config**

Edit `frontend/package.json` so `name` is `"frontend"` and `scripts` is exactly:

```json
{
  "dev": "next dev --port 3000",
  "build": "next build",
  "start": "next start --port 3000",
  "typecheck": "tsc --noEmit",
  "test": "vitest run",
  "test:watch": "vitest",
  "e2e": "playwright test"
}
```

Create `frontend/vitest.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**"],
    globals: false,
  },
});
```

Create `frontend/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

In `frontend/tsconfig.json`, ensure `"strict": true` and add `"vitest.setup.ts"` to `include`. Add `"types": ["vitest/globals"]` only if a later step needs it (it does not; tests import from `vitest`).

- [x] **Step 7: Write the first test and watch it fail**

Create `frontend/src/lib/smoke.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { version } from "./version";

describe("smoke", () => {
  it("exposes the app version", () => {
    expect(version).toBe("0.1.0");
  });
});
```

Run: `cd frontend && bun run test`
Expected: FAIL with `Cannot find module './version'`.

Create `frontend/src/lib/version.ts`:

```ts
export const version = "0.1.0";
```

Run: `cd frontend && bun run test`
Expected: `1 passed`.

Run: `cd frontend && bun run typecheck && bunx ultracite check`
Expected: no errors. If ultracite flags generated shadcn files, add `"files": { "includes": ["**", "!src/components/ui/**"] }` to `frontend/biome.jsonc` and note it in `frontend/AGENTS.md`.

- [x] **Step 8: DOX child and root index**

Create `frontend/AGENTS.md`:

```markdown
# frontend — AGENTS.md

Next.js 16 App Router client for clipsieve. Thin: all state from `/api/*` (Next rewrite to FastAPI :8000) and the `RunEvent` SSE stream.

## Contracts
- Package name `frontend`; scripts `dev`, `build`, `typecheck`, `test`, `e2e`.
- `src/lib/types.ts` is GENERATED by `packages/schema`; never edit.
- `src/lib/api.ts` is the only place that calls `fetch` against the API. `src/lib/useRunEvents.ts` is the only place that opens an `EventSource`.
- `src/lib/events.ts` is a pure reducer; components never derive state from raw events.
- Every user-visible string goes through `t(key, locale)` from `src/lib/i18n.ts`; keys live in `src/lib/i18n/en.ts` and `zh.ts`. Adding a key means adding it to both.
- Post ids contain `:`; `encodeURIComponent` them in every URL.

## Next 16 notes (verified against node_modules/next/dist/docs on scaffold)
- `next.config.ts` `rewrites()` returns `{ source, destination }[]`.
- Server page `params` is a Promise; client pages use `useParams()` from `next/navigation`.
- (record any other difference found in Task 1 Step 2 here)

## Tooling
- Biome via ultracite; `biome.jsonc` extends the root (`"//"`). No eslint, no prettier.
- shadcn components in `src/components/ui/` are generated; re-add with `bunx --bun shadcn@latest add <name>` instead of hand-editing.
- Vitest + Testing Library + jsdom for unit tests; Playwright for `e2e/run-flow.spec.ts`.

## Child DOX Index
None.
```

Edit root `AGENTS.md` Child DOX Index: replace `None yet. ...` list so it includes a line `- frontend/ — Next.js client; see frontend/AGENTS.md`.

- [x] **Step 9: Commit**

```bash
git add frontend package.json bun.lock AGENTS.md
git commit -m "feat(frontend): scaffold Next.js 16 app with shadcn, Biome, Vitest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: i18n with `en` and `zh` dictionaries

**Files:**
- Create: `frontend/src/lib/i18n.ts`, `frontend/src/lib/i18n/en.ts`, `frontend/src/lib/i18n/zh.ts`, `frontend/src/components/LocaleSwitch.tsx`
- Test: `frontend/src/lib/i18n.test.ts`

**Interfaces:**
- Produces: `type Locale = "en" | "zh"`; `t(key, locale, vars?)`; `tOr(key, fallback, locale)`; `useLocale(): [Locale, (l: Locale) => void]`; `STORAGE_KEY = "clipsieve.locale"`; `detectLocale(language)`.

- [x] **Step 1: Failing tests**

Create `frontend/src/lib/i18n.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { detectLocale, t, tOr } from "./i18n";
import { en } from "./i18n/en";
import { zh } from "./i18n/zh";

describe("t", () => {
  it("returns the zh string when present", () => {
    expect(t("brief.submit", "zh")).toBe("开始研究");
  });
  it("falls back to en when zh lacks a key", () => {
    expect(t("__only_en_test__", "zh")).toBe("__only_en_test__");
  });
  it("interpolates variables", () => {
    expect(t("grid.progress", "en", { done: 3, total: 10 })).toBe("3 / 10");
  });
  it("leaves unknown placeholders visible", () => {
    expect(t("grid.progress", "en", { done: 3 })).toBe("3 / {total}");
  });
  it("tOr returns fallback for an unknown key", () => {
    expect(tOr("label.not_a_label", "not_a_label", "en")).toBe("not_a_label");
  });
});

describe("dictionaries", () => {
  it("zh has every en key", () => {
    const missing = Object.keys(en).filter((k) => !(k in zh));
    expect(missing).toEqual([]);
  });
  it("en has every zh key", () => {
    const missing = Object.keys(zh).filter((k) => !(k in en));
    expect(missing).toEqual([]);
  });
});

describe("detectLocale", () => {
  it("maps zh-CN to zh and everything else to en", () => {
    expect(detectLocale("zh-CN")).toBe("zh");
    expect(detectLocale("zh-Hans-SG")).toBe("zh");
    expect(detectLocale("en-SG")).toBe("en");
    expect(detectLocale(undefined)).toBe("en");
  });
});
```

Run: `cd frontend && bun run test`
Expected: FAIL, cannot find `./i18n`.

- [x] **Step 2: Dictionaries**

Create `frontend/src/lib/i18n/en.ts` with every key used by later tasks:

```ts
export const en: Record<string, string> = {
  "app.title": "clipsieve",
  "app.tagline": "Sift thousands of clips down to the few worth studying",
  "locale.en": "English",
  "locale.zh": "中文",
  "common.loading": "Loading…",
  "common.error": "Something went wrong",
  "common.retry": "Retry",
  "common.close": "Close",
  "common.back": "Back",
  "common.save": "Save",

  "brief.title": "What are you researching?",
  "brief.text.label": "Brief",
  "brief.text.placeholder": "I am starting social accounts as a Singaporean moving to Shanghai, vlog style. Find such videos and analyse hooks and styles.",
  "brief.platforms": "Platforms",
  "brief.quantity": "Posts per platform",
  "brief.rubric": "Rubric pack",
  "brief.language_hint": "Language hint (optional)",
  "brief.language_hint.placeholder": "e.g. zh, en",
  "brief.submit": "Start research",
  "brief.submitting": "Creating run…",
  "brief.recent_runs": "Recent runs",
  "brief.no_runs": "No runs yet",
  "brief.adapter.healthy": "ready",
  "brief.adapter.unhealthy": "unavailable",
  "brief.validation.text": "Write a brief first",
  "brief.validation.platforms": "Tick at least one platform",

  "plan.title": "Review the plan",
  "plan.pending": "Claude is turning your brief into a plan…",
  "plan.topic": "Topic",
  "plan.audience": "Audience",
  "plan.persona": "Persona",
  "plan.queries": "Search queries",
  "plan.query.platform": "Platform",
  "plan.query.text": "Query",
  "plan.query.lang": "Language",
  "plan.query.add": "Add query",
  "plan.query.remove": "Remove",
  "plan.quantities": "Quantities",
  "plan.persona_criteria": "Persona fit levels",
  "plan.persona_criteria.help": "Five levels from unrelated to could-be-your-own-channel. Jev scores every post against these.",
  "plan.save": "Save plan",
  "plan.saved": "Plan saved",
  "plan.approve": "Approve and run",
  "plan.approving": "Starting…",

  "run.title": "Run",
  "run.stage.planning": "Planning",
  "run.stage.collecting": "Collecting",
  "run.stage.pass_one": "Pass one",
  "run.stage.extracting": "Extracting evidence",
  "run.stage.pass_two": "Pass two",
  "run.stage.selecting": "Selecting",
  "run.stage.explaining": "Explaining",
  "run.stage.done": "Done",
  "run.stage.failed": "Failed",
  "run.pause": "Pause",
  "run.resume": "Resume",
  "run.view_report": "View report",
  "run.view_replay": "Replay",
  "run.connected": "live",
  "run.disconnected": "reconnecting…",

  "counters.collected": "Collected",
  "counters.pass_one_kept": "Kept after pass one",
  "counters.judged": "Judged",
  "counters.answers_per_sec": "Answers / sec",
  "counters.elapsed": "Elapsed",
  "counters.cost": "Jev cost",
  "counters.shortlisted": "Shortlisted",
  "counters.review": "Too close to call",

  "grid.title": "Posts",
  "grid.progress": "{done} / {total}",
  "grid.state.collected": "collected",
  "grid.state.dropped_pass_one": "dropped in pass one",
  "grid.state.judged": "judged",
  "grid.state.shortlisted": "shortlisted",
  "grid.state.review": "needs review",
  "grid.state.judge_failed": "judge failed",

  "current.title": "Now answered",
  "current.empty": "Waiting for the first judged post…",
  "current.composite": "Composite",
  "current.confidence": "confidence",
  "current.probability": "probability",
  "current.score": "{value} / {levels}",
  "current.tokens": "{tokens} tokens · {ms} ms",

  "aggregates.title": "The category so far",
  "aggregates.hook_type": "Opening hook",
  "aggregates.format": "Format",
  "aggregates.persona_fit": "Persona fit",
  "aggregates.empty": "No pass-two results yet",

  "review.title": "Too close to call",
  "review.count": "{count} posts",
  "review.help": "Posts where Jev's confidence on a weighted question was under the pack threshold. These go to a person, not into the report.",
  "review.open": "Open list",
  "review.empty": "Nothing in review",

  "report.title": "Report",
  "report.loading": "Loading report…",
  "report.not_ready": "The report is not ready yet",
  "report.patterns": "Patterns",
  "report.clips": "Why each clip works",
  "report.gaps": "Gaps and underused angles",
  "report.concepts": "Concepts to test",
  "report.caveats": "Caveats",
  "report.observation": "Observed",
  "report.hypothesis": "Hypothesis",
  "report.why_it_works": "Why it works",
  "report.hook_quote": "Hook",
  "report.weaknesses": "Weaknesses",
  "report.concept.hook": "Hook",
  "report.concept.structure": "Structure",
  "report.concept.visual": "Visual",
  "report.concept.proof": "Proof",
  "report.concept.cta": "CTA",
  "report.cited": "Cited posts",
  "report.unknown_post": "Post not found in this run",
  "report.post.caption": "Caption",
  "report.post.transcript": "Transcript",
  "report.post.answers": "Jev answers",

  "replay.title": "Replay",
  "replay.loading": "Loading run log…",
  "replay.play": "Play",
  "replay.pause": "Pause",
  "replay.speed": "Speed",
  "replay.progress": "{done} / {total} events",

  "question.hook_type": "Hook type",
  "question.hook_strength": "Hook strength",
  "question.format": "Format",
  "question.persona_fit": "Persona fit",
  "question.risky_claim": "Risky claim",
  "question.niche_relevance": "Niche relevance",
  "question.format_guess": "Format guess",

  "label.curiosity_gap": "Curiosity gap",
  "label.bold_claim": "Bold claim",
  "label.result_first": "Result first",
  "label.problem": "Problem",
  "label.story": "Story",
  "label.authority": "Authority",
  "label.none": "No hook",
  "label.talking_head": "Talking head",
  "label.vlog_montage": "Vlog montage",
  "label.screen_demo": "Screen demo",
  "label.ugc_testimonial": "UGC testimonial",
  "label.image_carousel": "Image carousel",
  "label.meme": "Meme",
  "label.other": "Other",
  "label.unknown": "Unknown",
};
```

Create `frontend/src/lib/i18n/zh.ts` with the same keys, Chinese values. Required exact values used by tests: `"brief.submit": "开始研究"`, `"grid.progress": "{done} / {total}"`. Translate every other key; for example `"app.tagline": "从成千上万条内容中筛出值得研究的几条"`, `"brief.title": "你在研究什么？"`, `"plan.approve": "批准并运行"`, `"run.stage.collecting": "采集中"`, `"counters.cost": "Jev 花费"`, `"review.title": "难以判断"`, `"report.concepts": "待测试的内容概念"`, `"replay.play": "播放"`, `"label.curiosity_gap": "好奇缺口"`. The dictionary-parity tests enforce completeness.

- [x] **Step 3: i18n module**

Create `frontend/src/lib/i18n.ts`:

```ts
"use client";

import { useSyncExternalStore } from "react";
import { en } from "./i18n/en";
import { zh } from "./i18n/zh";

export type Locale = "en" | "zh";
export const STORAGE_KEY = "clipsieve.locale";

const dictionaries: Record<Locale, Record<string, string>> = { en, zh };

export function detectLocale(language: string | undefined): Locale {
  return language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function t(key: string, locale: Locale, vars?: Record<string, string | number>): string {
  const template = dictionaries[locale][key] ?? dictionaries.en[key] ?? key;
  if (!vars) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

export function tOr(key: string, fallback: string, locale: Locale): string {
  return dictionaries[locale][key] ?? dictionaries.en[key] ?? fallback;
}

let current: Locale | null = null;
const listeners = new Set<() => void>();

function readLocale(): Locale {
  if (current) {
    return current;
  }
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    stored = null;
  }
  current = stored === "zh" || stored === "en" ? stored : detectLocale(navigator.language);
  return current;
}

export function setLocale(locale: Locale): void {
  current = locale;
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // storage unavailable; keep in memory
  }
  for (const fn of listeners) {
    fn();
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useLocale(): [Locale, (l: Locale) => void] {
  const locale = useSyncExternalStore(subscribe, readLocale, () => "en" as Locale);
  return [locale, setLocale];
}
```

Create `frontend/src/components/LocaleSwitch.tsx`:

```tsx
"use client";

import { Button } from "@/components/ui/button";
import { type Locale, t, useLocale } from "@/lib/i18n";

export function LocaleSwitch() {
  const [locale, setLocale] = useLocale();
  const next: Locale = locale === "en" ? "zh" : "en";
  return (
    <Button variant="ghost" size="sm" onClick={() => setLocale(next)} aria-label={t(`locale.${next}`, locale)}>
      {t(`locale.${next}`, locale)}
    </Button>
  );
}
```

Run: `cd frontend && bun run test`
Expected: all i18n tests pass. Fix any parity failures by adding the missing key to the other dictionary.

- [x] **Step 4: Commit**

```bash
git add frontend/src/lib/i18n.ts frontend/src/lib/i18n frontend/src/lib/i18n.test.ts frontend/src/components/LocaleSwitch.tsx
git commit -m "feat(frontend): add en/zh i18n with locale store

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Typed API client

**Files:**
- Create: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Consumes: generated `frontend/src/lib/types.ts` exporting `Post, Plan, Run, Report, JudgeResult, RunEvent, Stage, Counters` (plan 01).
- Produces: `api` object per the overview Frontend contract; `ApiError`; types `CreateRunBody, PostState, PostView, Selection, AdapterStatus, RubricPackSummary`; helpers `mediaUrl(runId, postId, filename)`, `eventsUrl(runId, after)`.

- [x] **Step 1: Failing tests**

Create `frontend/src/lib/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, eventsUrl, mediaUrl } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 404 ? "Not Found" : "OK",
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("posts a run body to /api/runs", async () => {
    const fn = mockFetch(200, { id: "r1", stage: "planning" });
    const run = await api.createRun({
      brief: "新加坡人搬到上海",
      platforms: ["local"],
      quantities: { local: 5 },
      rubric_pack: "creator-hooks-v1",
    });
    expect(run.id).toBe("r1");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body)).brief).toBe("新加坡人搬到上海");
  });

  it("throws ApiError with the server detail", async () => {
    mockFetch(404, { detail: "run not found" });
    await expect(api.getReport("nope")).rejects.toMatchObject<Partial<ApiError>>({
      status: 404,
      detail: "run not found",
    });
  });

  it("encodes post ids in media urls", () => {
    expect(mediaUrl("r1", "local:fx-001", "thumb.jpg")).toBe("/api/runs/r1/media/local%3Afx-001/thumb.jpg");
  });

  it("builds the events url with after", () => {
    expect(eventsUrl("r1", 42)).toBe("/api/runs/r1/events?after=42");
  });

  it("passes paging to getPosts", async () => {
    const fn = mockFetch(200, { items: [], total: 0 });
    await api.getPosts("r1", 100, 50);
    expect((fn.mock.calls[0] as unknown as [string])[0]).toBe("/api/runs/r1/posts?offset=100&limit=50");
  });
});
```

Run: `cd frontend && bun run test src/lib/api.test.ts`
Expected: FAIL, cannot find `./api`.

- [x] **Step 2: Implement**

Create `frontend/src/lib/api.ts`:

```ts
import type { JudgeResult, Plan, Post, Report, Run } from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type CreateRunBody = {
  brief: string;
  platforms: string[];
  quantities: Record<string, number>;
  rubric_pack: string;
  language_hint?: string;
};

export type PostState = "collected" | "dropped_pass_one" | "judged" | "shortlisted" | "review" | "judge_failed";

export type PostView = {
  post: Post;
  judge: Record<string, JudgeResult>;
  composite?: number;
  state: PostState;
};

export type Selection = {
  shortlist: string[];
  review: string[];
  scores: Record<string, number>;
  dropped: Record<string, string>;
};

export type AdapterStatus = { platform: string; healthy: boolean; message: string };
export type RubricPackSummary = { name: string; description: string; question_ids: string[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  createRun: (body: CreateRunBody) => request<Run>("/runs", { method: "POST", body: JSON.stringify(body) }),
  listRuns: () => request<Run[]>("/runs"),
  getRun: (id: string) => request<{ run: Run; plan: Plan | null }>(`/runs/${enc(id)}`),
  savePlan: (id: string, plan: Plan) =>
    request<Plan>(`/runs/${enc(id)}/plan`, { method: "PUT", body: JSON.stringify(plan) }),
  approveRun: (id: string) => request<Run>(`/runs/${enc(id)}/approve`, { method: "POST" }),
  pauseRun: (id: string) => request<Run>(`/runs/${enc(id)}/pause`, { method: "POST" }),
  resumeRun: (id: string) => request<Run>(`/runs/${enc(id)}/resume`, { method: "POST" }),
  getPosts: (id: string, offset = 0, limit = 100) =>
    request<{ items: PostView[]; total: number }>(`/runs/${enc(id)}/posts?offset=${offset}&limit=${limit}`),
  getReport: (id: string) => request<Report>(`/runs/${enc(id)}/report`),
  reselect: (id: string, weights: Record<string, number>) =>
    request<Selection>(`/runs/${enc(id)}/reselect`, { method: "POST", body: JSON.stringify({ weights }) }),
  listAdapters: () => request<AdapterStatus[]>("/adapters"),
  listRubrics: () => request<RubricPackSummary[]>("/rubrics"),
};

export function mediaUrl(runId: string, postId: string, filename: string): string {
  return `${API_BASE}/runs/${enc(runId)}/media/${enc(postId)}/${enc(filename)}`;
}

export function eventsUrl(runId: string, after: number): string {
  return `${API_BASE}/runs/${enc(runId)}/events?after=${after}`;
}
```

Run: `cd frontend && bun run test src/lib/api.test.ts`
Expected: 5 passed.

- [x] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(frontend): typed API client with ApiError and url helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pure event reducer and fixture event log

**Files:**
- Create: `frontend/src/lib/events.ts`, `frontend/src/lib/__fixtures__/posts.ts`, `frontend/src/lib/__fixtures__/run-events.ts`, `frontend/scripts/write-fixture-events.ts`, `frontend/src/lib/__fixtures__/run-events.json` (generated by the script)
- Test: `frontend/src/lib/events.test.ts`

**Interfaces:**
- Consumes: `RunEvent, Post, JudgeResult, Counters, Stage` from `@/lib/types`.
- Produces: `DashboardState` (contract fields plus `lastSeq: number` and `startedAt: string | null`), `PostTile`, `initialState()`, `reduceEvent(state, event)`, `reduceAll(events)`, `answersPerSecond(events, windowMs = 5000)`, `emptyCounters()`, `JEV_USD_PER_MILLION_INPUT = 0.042`; fixture exports `fixturePosts: Post[]` and `fixtureEvents: RunEvent[]` (about 40 events, run id `FIXTURE`).

- [x] **Step 1: Fixture posts**

Create `frontend/src/lib/__fixtures__/posts.ts`:

```ts
import type { Post } from "@/lib/types";

const base = { collected_at: "2026-10-03T10:00:00Z", media: [], metrics: { views: 1000, likes: 100, comments: 10 } };

export const fixturePosts: Post[] = [
  {
    ...base,
    id: "local:fx-001",
    platform: "local",
    url: "file:///fx/001.mp4",
    creator_hash: "a1",
    creator_display: "Mei",
    kind: "video",
    text: { title: "First week in Shanghai", caption: "Stop scrolling. I moved from Singapore to Shanghai with two suitcases.", hashtags: ["shanghai", "expat"] },
    comments: [{ text: "relatable!", likes: 12 }],
    lang: "en",
    raw_ref: "raw/local__fx-001.json",
  },
  {
    ...base,
    id: "local:fx-002",
    platform: "local",
    url: "file:///fx/002.mp4",
    creator_hash: "a2",
    creator_display: "阿杰",
    kind: "video",
    text: { title: "新加坡人在上海的第一周", caption: "从新加坡搬到上海的第一周，租房踩了三个坑。", hashtags: ["上海生活", "新加坡人"] },
    comments: [{ text: "太真实了", likes: 40 }, { text: "求租房攻略", likes: 8 }],
    lang: "zh",
    raw_ref: "raw/local__fx-002.json",
  },
  {
    ...base,
    id: "local:fx-003",
    platform: "local",
    url: "file:///fx/003.mp4",
    creator_hash: "a3",
    kind: "video",
    text: { caption: "上海地铁早高峰 vlog｜一个新加坡人的日常", hashtags: ["vlog"] },
    comments: [],
    lang: "zh",
    raw_ref: "raw/local__fx-003.json",
  },
  {
    ...base,
    id: "local:fx-004",
    platform: "local",
    url: "file:///fx/004",
    creator_hash: "a4",
    kind: "image_note",
    text: { title: "Shanghai apartment hunting checklist", caption: "7 things I wish I knew before signing.", hashtags: ["shanghai", "checklist"] },
    comments: [{ text: "saving this", likes: 3 }],
    lang: "en",
    raw_ref: "raw/local__fx-004.json",
  },
  {
    ...base,
    id: "local:fx-005",
    platform: "local",
    url: "file:///fx/005",
    creator_hash: "a5",
    kind: "image_note",
    text: { title: "在上海办银行卡全攻略", caption: "新加坡护照办卡需要的材料清单。", hashtags: ["上海", "攻略"] },
    comments: [{ text: "有用", likes: 5 }],
    lang: "zh",
    raw_ref: "raw/local__fx-005.json",
  },
];
```

- [x] **Step 2: Fixture event builder**

Create `frontend/src/lib/__fixtures__/run-events.ts`:

```ts
import type { JudgeResult, RunEvent, Stage } from "@/lib/types";
import { fixturePosts } from "./posts";

const RUN_ID = "FIXTURE";
const T0 = Date.parse("2026-10-03T10:00:00Z");

let seq = 0;
function ev(offsetMs: number, type: RunEvent["type"], stage: Stage, payload: Record<string, unknown>): RunEvent {
  seq += 1;
  return { run_id: RUN_ID, seq, ts: new Date(T0 + offsetMs).toISOString(), type, stage, payload };
}

const hookTypes = ["bold_claim", "problem", "story", "result_first", "none"];
const formats = ["talking_head", "vlog_montage", "vlog_montage", "image_carousel", "image_carousel"];

function passOne(postId: string, i: number): JudgeResult {
  return {
    post_id: postId,
    pass_name: "pass_one",
    model: "jev-1.13.0",
    input_tokens: 900 + i * 10,
    latency_ms: 120,
    answers: {
      niche_relevance: { type: "score", value: 3.2 + (i % 2) * 0.6, probabilities: { "1": 0, "2": 0.1, "3": 0.3, "4": 0.5, "5": 0.1 }, confidence: 0.7, legend: { "1": "Unrelated", "2": "Mentions in passing", "3": "Partly about it", "4": "Mainly about it", "5": "Entirely about it" } },
      format_guess: { type: "choice", value: formats[i] === "image_carousel" ? "image_carousel" : "vlog_montage", probabilities: { vlog_montage: 0.6, image_carousel: 0.3, talking_head: 0.1 }, confidence: 0.5 },
    },
  };
}

function passTwo(postId: string, i: number): JudgeResult {
  return {
    post_id: postId,
    pass_name: "pass_two",
    model: "jev-1.13.0",
    input_tokens: 2400 + i * 50,
    latency_ms: 380,
    answers: {
      hook_type: { type: "choice", value: hookTypes[i], probabilities: { [hookTypes[i]]: 0.75, none: 0.25 }, confidence: 0.75 },
      hook_strength: { type: "score", value: 2.0 + i * 0.5, probabilities: { "3": 0.6, "4": 0.4 }, confidence: 0.8, legend: { "1": "No hook", "2": "Weak", "3": "Moderate", "4": "Strong", "5": "Exceptional" } },
      format: { type: "choice", value: formats[i], probabilities: { [formats[i]]: 0.9 }, confidence: 0.9 },
      persona_fit: { type: "score", value: i === 4 ? 1.4 : 3.6 + (i % 2) * 0.3, probabilities: { "3": 0.3, "4": 0.7 }, confidence: i === 2 ? 0.3 : 0.8, legend: { "1": "Unrelated", "2": "Adjacent niche", "3": "Same niche, different voice", "4": "Close match", "5": "Could be the user's own channel" } },
      risky_claim: { type: "noul", value: 0.05 },
      niche_relevance: passOne(postId, i).answers.niche_relevance,
      format_guess: passOne(postId, i).answers.format_guess,
    },
  };
}

export function buildFixtureEvents(): RunEvent[] {
  seq = 0;
  const brief = { text: "Singaporean moving to Shanghai, vlog style", topic: "moving to Shanghai", audience: "Singaporeans relocating", persona: "friendly expat vlogger" };
  const plan = { run_id: RUN_ID, brief, queries: [{ platform: "local", query: "shanghai", lang: "en" }], quantities: { local: 5 }, rubric_pack: "creator-hooks-v1", persona_fit_criteria: ["Unrelated", "Adjacent niche", "Same niche, different voice", "Close match", "Could be the user's own channel"] };
  const out: RunEvent[] = [];
  out.push(ev(0, "run_created", "planning", { brief, platforms: ["local"], quantities: { local: 5 } }));
  out.push(ev(500, "plan_ready", "planning", { plan }));
  out.push(ev(1500, "plan_approved", "planning", { plan }));
  out.push(ev(1600, "stage_changed", "collecting", { from: "planning", to: "collecting" }));
  fixturePosts.forEach((post, i) => out.push(ev(2000 + i * 200, "post_collected", "collecting", { post })));
  out.push(ev(3200, "stage_changed", "pass_one", { from: "collecting", to: "pass_one" }));
  fixturePosts.forEach((post, i) => {
    const kept = i !== 4;
    out.push(ev(3400 + i * 150, "pass_one_judged", "pass_one", { judge: passOne(post.id, i), kept, composite: kept ? 0.7 : 0.2 }));
  });
  out.push(ev(4300, "stage_changed", "extracting", { from: "pass_one", to: "extracting" }));
  fixturePosts.slice(0, 4).forEach((post, i) =>
    out.push(ev(4500 + i * 400, "evidence_ready", "extracting", { post_id: post.id, evidence: { post_id: post.id, transcript: [{ start_s: 0, end_s: 2.5, text: post.text.caption ?? "" }], ocr: [], keyframes: [], comment_summary: { count: post.comments.length, top_terms: [], sample: post.comments.map((c) => c.text) }, token_estimate: 400, truncated: false } })),
  );
  out.push(ev(6200, "stage_changed", "pass_two", { from: "extracting", to: "pass_two" }));
  fixturePosts.slice(0, 4).forEach((post, i) =>
    out.push(ev(6400 + i * 300, "judged", "pass_two", { judge: passTwo(post.id, i), composite: 0.55 + i * 0.1 })),
  );
  out.push(ev(7700, "error", "pass_two", { where: "judge", message: "429 after 5 retries", post_id: "local:fx-004", recoverable: true }));
  out.push(ev(7800, "stage_changed", "selecting", { from: "pass_two", to: "selecting" }));
  out.push(ev(7900, "selected", "selecting", { shortlist: ["local:fx-001", "local:fx-002"], review: ["local:fx-003"], scores: { "local:fx-001": 0.55, "local:fx-002": 0.65, "local:fx-003": 0.75 }, dropped: { "local:fx-005": "pass_one", "local:fx-004": "judge_failed" } }));
  out.push(ev(8000, "stage_changed", "explaining", { from: "selecting", to: "explaining" }));
  out.push(ev(12000, "explained", "explaining", { report: { run_id: RUN_ID, patterns: [{ title: "Problem-first openings", observation: "Both shortlisted clips open on a concrete pain.", hypothesis: "Specific friction signals authenticity.", post_ids: ["local:fx-001", "local:fx-002"] }], clips: [{ post_id: "local:fx-002", why_it_works: "Three concrete mistakes promised in the first line.", hook_quote: "租房踩了三个坑", weaknesses: "No visual hook." }], gaps: [], concepts: [{ hook: "I signed a Shanghai lease without reading this", structure: "problem, three mistakes, fix", visual: "walk-through", proof: "contract screenshot", cta: "save for later", inspired_by_post_ids: ["local:fx-002"] }], caveats: ["Only five posts in this fixture run."] } }));
  out.push(ev(12100, "stage_changed", "done", { from: "explaining", to: "done" }));
  out.push(ev(12200, "done", "done", { counters: { collected: 5, pass_one_kept: 4, judged: 4, shortlisted: 2, review: 1, errors: 1, jev_input_tokens: 14500, jev_cost_usd: 0.000609, elapsed_s: 12.2 } }));
  return out;
}

export const fixtureEvents: RunEvent[] = buildFixtureEvents();
```

Create `frontend/scripts/write-fixture-events.ts`:

```ts
import { writeFileSync } from "node:fs";
import { buildFixtureEvents } from "../src/lib/__fixtures__/run-events";

writeFileSync(new URL("../src/lib/__fixtures__/run-events.json", import.meta.url), `${JSON.stringify(buildFixtureEvents(), null, 2)}\n`);
console.log("wrote run-events.json");
```

Run: `cd frontend && bun run scripts/write-fixture-events.ts`
Expected: `wrote run-events.json`; the file has 30 or more events. If `@/` alias fails under `bun run`, change the import to a relative path.

- [x] **Step 3: Failing reducer tests**

Create `frontend/src/lib/events.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { fixtureEvents } from "./__fixtures__/run-events";
import { answersPerSecond, initialState, reduceAll, reduceEvent } from "./events";

describe("reduceEvent", () => {
  it("tracks collected posts and stage", () => {
    const upToCollect = fixtureEvents.filter((e) => e.seq <= 9);
    const s = reduceAll(upToCollect);
    expect(s.counters.collected).toBe(5);
    expect(Object.keys(s.posts)).toHaveLength(5);
    expect(s.stage).toBe("collecting");
    expect(s.posts["local:fx-002"].post.text.title).toBe("新加坡人在上海的第一周");
  });

  it("marks pass-one drops and keeps counts", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 15));
    expect(s.posts["local:fx-005"].state).toBe("dropped_pass_one");
    expect(s.posts["local:fx-001"].state).toBe("collected");
    expect(s.counters.pass_one_kept).toBe(4);
    expect(s.counters.jev_input_tokens).toBeGreaterThan(0);
  });

  it("sets latest and aggregates on judged", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.type !== "done" && e.seq <= 24));
    expect(s.latest?.post.id).toBe("local:fx-004");
    expect(s.aggregates.hook_type.bold_claim).toBe(1);
    expect(s.aggregates.format.vlog_montage).toBe(2);
    expect(s.aggregates.persona_fit["4"]).toBeGreaterThanOrEqual(1);
    expect(s.counters.judged).toBe(4);
  });

  it("marks judge_failed on a judge error with post_id and counts errors", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 25));
    expect(s.posts["local:fx-004"].state).toBe("judge_failed");
    expect(s.posts["local:fx-003"].state).toBe("judged");
    expect(s.counters.errors).toBe(1);
    expect(s.errors).toHaveLength(1);
  });

  it("applies selection", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 27));
    expect(s.shortlist).toEqual(["local:fx-001", "local:fx-002"]);
    expect(s.posts["local:fx-001"].state).toBe("shortlisted");
    expect(s.posts["local:fx-003"].state).toBe("review");
    expect(s.counters.shortlisted).toBe(2);
    expect(s.counters.review).toBe(1);
  });

  it("takes counters from done and marks done", () => {
    const s = reduceAll(fixtureEvents);
    expect(s.done).toBe(true);
    expect(s.stage).toBe("done");
    expect(s.counters.elapsed_s).toBe(12.2);
    expect(s.counters.jev_cost_usd).toBeCloseTo(0.000609, 6);
  });

  it("computes cost from tokens before done", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 15));
    expect(s.counters.jev_cost_usd).toBeCloseTo((s.counters.jev_input_tokens * 0.042) / 1_000_000, 9);
  });

  it("ignores duplicate or older events (reconnect safety)", () => {
    const all = reduceAll(fixtureEvents);
    const first = fixtureEvents.filter((e) => e.seq <= 12);
    const rest = fixtureEvents.filter((e) => e.seq > 12);
    const resumed = [...rest, ...fixtureEvents.filter((e) => e.seq <= 12)].reduce(reduceEvent, reduceAll(first));
    expect(resumed).toEqual(all);
  });

  it("is pure", () => {
    const s0 = initialState();
    const s1 = reduceEvent(s0, fixtureEvents[0]);
    expect(s0).toEqual(initialState());
    expect(s1).not.toBe(s0);
  });
});

describe("answersPerSecond", () => {
  it("counts answers in the trailing window", () => {
    const judged = fixtureEvents.filter((e) => e.type === "judged");
    const rate = answersPerSecond(judged, 5000);
    expect(rate).toBeCloseTo((4 * 7) / 5, 3);
  });
  it("returns 0 with no events", () => {
    expect(answersPerSecond([])).toBe(0);
  });
});
```

Run: `cd frontend && bun run test src/lib/events.test.ts`
Expected: FAIL, cannot find `./events`.

- [x] **Step 4: Implement the reducer**

Create `frontend/src/lib/events.ts`:

```ts
import type { Counters, JudgeResult, Post, RunEvent, Stage } from "./types";

export const JEV_USD_PER_MILLION_INPUT = 0.042;

export type PostTileState = "collected" | "dropped_pass_one" | "judged" | "shortlisted" | "review" | "judge_failed";
export type PostTile = { post: Post; state: PostTileState; composite?: number };

export type DashboardState = {
  stage: Stage;
  counters: Counters;
  posts: Record<string, PostTile>;
  latest: { post: Post; judge: JudgeResult; composite: number } | null;
  aggregates: Record<string, Record<string, number>>;
  shortlist: string[];
  review: string[];
  errors: RunEvent[];
  done: boolean;
  lastSeq: number;
  startedAt: string | null;
};

export function emptyCounters(): Counters {
  return { collected: 0, pass_one_kept: 0, judged: 0, shortlisted: 0, review: 0, errors: 0, jev_input_tokens: 0, jev_cost_usd: 0, elapsed_s: 0 };
}

export function initialState(): DashboardState {
  return { stage: "planning", counters: emptyCounters(), posts: {}, latest: null, aggregates: {}, shortlist: [], review: [], errors: [], done: false, lastSeq: 0, startedAt: null };
}

function bump(agg: Record<string, Record<string, number>>, qid: string, label: string): Record<string, Record<string, number>> {
  const row = { ...(agg[qid] ?? {}) };
  row[label] = (row[label] ?? 0) + 1;
  return { ...agg, [qid]: row };
}

function setTile(posts: Record<string, PostTile>, id: string, patch: Partial<PostTile>): Record<string, PostTile> {
  const tile = posts[id];
  if (!tile) {
    return posts;
  }
  return { ...posts, [id]: { ...tile, ...patch } };
}

export function reduceEvent(state: DashboardState, event: RunEvent): DashboardState {
  if (event.seq <= state.lastSeq) {
    return state;
  }
  const startedAt = state.startedAt ?? event.ts;
  const counters: Counters = { ...state.counters, elapsed_s: (Date.parse(event.ts) - Date.parse(startedAt)) / 1000 };
  const next: DashboardState = { ...state, counters, lastSeq: event.seq, stage: event.stage, startedAt };
  const p = event.payload as Record<string, unknown>;

  switch (event.type) {
    case "post_collected": {
      const post = p.post as Post;
      next.posts = { ...state.posts, [post.id]: { post, state: "collected" } };
      counters.collected += 1;
      break;
    }
    case "pass_one_judged": {
      const judge = p.judge as JudgeResult;
      const kept = Boolean(p.kept);
      next.posts = setTile(state.posts, judge.post_id, { state: kept ? "collected" : "dropped_pass_one", composite: Number(p.composite) });
      counters.pass_one_kept += kept ? 1 : 0;
      counters.jev_input_tokens += judge.input_tokens;
      break;
    }
    case "judged": {
      const judge = p.judge as JudgeResult;
      const composite = Number(p.composite);
      next.posts = setTile(state.posts, judge.post_id, { state: "judged", composite });
      const tile = next.posts[judge.post_id];
      next.latest = tile ? { post: tile.post, judge, composite } : state.latest;
      let agg = state.aggregates;
      for (const [qid, a] of Object.entries(judge.answers)) {
        if (a.type === "choice") {
          agg = bump(agg, qid, String(a.value));
        } else if (qid === "persona_fit" && a.type === "score") {
          agg = bump(agg, qid, String(Math.round(Number(a.value))));
        }
      }
      next.aggregates = agg;
      counters.judged += 1;
      counters.jev_input_tokens += judge.input_tokens;
      break;
    }
    case "selected": {
      const shortlist = p.shortlist as string[];
      const review = p.review as string[];
      let posts = state.posts;
      for (const id of shortlist) {
        posts = setTile(posts, id, { state: "shortlisted" });
      }
      for (const id of review) {
        posts = setTile(posts, id, { state: "review" });
      }
      next.posts = posts;
      next.shortlist = shortlist;
      next.review = review;
      counters.shortlisted = shortlist.length;
      counters.review = review.length;
      break;
    }
    case "error": {
      next.errors = [...state.errors, event];
      counters.errors += 1;
      const postId = typeof p.post_id === "string" ? p.post_id : null;
      if (postId && String(p.where).startsWith("judge")) {
        next.posts = setTile(state.posts, postId, { state: "judge_failed" });
      }
      break;
    }
    case "stage_changed": {
      next.stage = p.to as Stage;
      break;
    }
    case "done": {
      next.done = true;
      next.counters = { ...(p.counters as Counters) };
      return next;
    }
    default:
      break;
  }
  counters.jev_cost_usd = (counters.jev_input_tokens * JEV_USD_PER_MILLION_INPUT) / 1_000_000;
  return next;
}

export function reduceAll(events: RunEvent[]): DashboardState {
  return events.reduce(reduceEvent, initialState());
}

export function answersPerSecond(events: RunEvent[], windowMs = 5000): number {
  if (events.length === 0) {
    return 0;
  }
  const end = Date.parse(events[events.length - 1].ts);
  let answers = 0;
  for (const e of events) {
    if (e.type !== "judged" && e.type !== "pass_one_judged") {
      continue;
    }
    const ts = Date.parse(e.ts);
    if (end - ts <= windowMs) {
      const judge = (e.payload as { judge: JudgeResult }).judge;
      answers += Object.keys(judge.answers).length;
    }
  }
  return answers / (windowMs / 1000);
}
```

Run: `cd frontend && bun run test src/lib/events.test.ts`
Expected: 11 passed. If `aggregates.persona_fit["4"]` fails, check `Math.round(3.6)` is 4; adjust the fixture, not the reducer.

- [x] **Step 5: Commit**

```bash
git add frontend/src/lib/events.ts frontend/src/lib/events.test.ts frontend/src/lib/__fixtures__ frontend/scripts/write-fixture-events.ts
git commit -m "feat(frontend): pure RunEvent reducer with fixture event log

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `useRunEvents` hook (live and replay)

**Files:**
- Create: `frontend/src/lib/useRunEvents.ts`
- Test: `frontend/src/lib/useRunEvents.test.tsx`

**Interfaces:**
- Consumes: `eventsUrl` (Task 3), `reduceEvent`, `initialState`, `DashboardState` (Task 4).
- Produces: `useRunEvents(runId, opts, factory?)` returning `{ state, events, connected, progress }`; `type RunEventsOptions`; `type EventSourceLike`; `type EventSourceFactory = (url: string) => EventSourceLike`.

- [x] **Step 1: Failing tests with a fake EventSource**

Create `frontend/src/lib/useRunEvents.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fixtureEvents } from "./__fixtures__/run-events";
import { reduceAll } from "./events";
import type { RunEvent } from "./types";
import { type EventSourceLike, useRunEvents } from "./useRunEvents";

class FakeES implements EventSourceLike {
  static instances: FakeES[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
  onopen: ((e: Event) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeES.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.(new Event("open"));
  }
  send(ev: RunEvent) {
    for (const fn of this.listeners.run_event ?? []) {
      fn(new MessageEvent("run_event", { data: JSON.stringify(ev), lastEventId: String(ev.seq) }));
    }
  }
  fail() {
    this.onerror?.(new Event("error"));
  }
}

const factory = (url: string) => new FakeES(url);

beforeEach(() => {
  FakeES.instances = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("useRunEvents live", () => {
  it("reduces events and reconnects with after=lastSeq", () => {
    const { result } = renderHook(() => useRunEvents("FIXTURE", { mode: "live" }, factory));
    const es = FakeES.instances[0];
    expect(es.url).toBe("/api/runs/FIXTURE/events?after=0");
    act(() => es.open());
    expect(result.current.connected).toBe(true);
    act(() => {
      for (const e of fixtureEvents.slice(0, 12)) {
        es.send(e);
      }
    });
    expect(result.current.state.counters.collected).toBe(5);
    act(() => es.fail());
    expect(result.current.connected).toBe(false);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const es2 = FakeES.instances[1];
    expect(es2.url).toBe("/api/runs/FIXTURE/events?after=12");
    act(() => {
      es2.open();
      for (const e of fixtureEvents) {
        es2.send(e);
      }
    });
    expect(result.current.state).toEqual(reduceAll(fixtureEvents));
    expect(result.current.state.done).toBe(true);
    expect(es2.closed).toBe(true);
  });
});

describe("useRunEvents replay", () => {
  it("loads the log then plays at speed with correct progress", () => {
    const { result, rerender } = renderHook((props: { speed: number; playing: boolean }) => useRunEvents("FIXTURE", { mode: "replay", ...props }, factory), { initialProps: { speed: 1, playing: false } });
    const es = FakeES.instances[0];
    act(() => {
      es.open();
      for (const e of fixtureEvents) {
        es.send(e);
      }
    });
    expect(es.closed).toBe(true);
    expect(result.current.progress).toBe(0);
    expect(result.current.state.counters.collected).toBe(0);
    rerender({ speed: 4, playing: true });
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current.events).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(125);
    });
    expect(result.current.events).toHaveLength(2);
    rerender({ speed: 1, playing: true });
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(result.current.events).toHaveLength(fixtureEvents.length);
    expect(result.current.progress).toBe(1);
    expect(result.current.state).toEqual(reduceAll(fixtureEvents));
  });

  it("pauses without losing position", () => {
    const { result, rerender } = renderHook((props: { speed: number; playing: boolean }) => useRunEvents("FIXTURE", { mode: "replay", ...props }, factory), { initialProps: { speed: 16, playing: true } });
    const es = FakeES.instances[0];
    act(() => {
      es.open();
      for (const e of fixtureEvents) {
        es.send(e);
      }
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    const n = result.current.events.length;
    expect(n).toBeGreaterThan(1);
    rerender({ speed: 16, playing: false });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.events).toHaveLength(n);
    rerender({ speed: 16, playing: true });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.events).toHaveLength(fixtureEvents.length);
  });
});
```

Run: `cd frontend && bun run test src/lib/useRunEvents.test.tsx`
Expected: FAIL, cannot find `./useRunEvents`.

- [x] **Step 2: Implement**

Create `frontend/src/lib/useRunEvents.ts`:

```ts
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { eventsUrl } from "./api";
import { type DashboardState, initialState, reduceEvent } from "./events";
import type { RunEvent } from "./types";

export type RunEventsOptions = { mode: "live" } | { mode: "replay"; speed: number; playing: boolean };

export type EventSourceLike = {
  addEventListener(type: "run_event", fn: (e: MessageEvent) => void): void;
  onerror: ((e: Event) => void) | null;
  onopen: ((e: Event) => void) | null;
  close(): void;
};
export type EventSourceFactory = (url: string) => EventSourceLike;

const defaultFactory: EventSourceFactory = (url) => new EventSource(url) as unknown as EventSourceLike;
const RECONNECT_MS = 1000;

function isTerminal(e: RunEvent): boolean {
  return e.type === "done" || e.stage === "failed";
}

export function useRunEvents(runId: string, opts: RunEventsOptions, factory: EventSourceFactory = defaultFactory) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<DashboardState>(initialState);
  const [connected, setConnected] = useState(false);
  const [log, setLog] = useState<RunEvent[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const lastSeqRef = useRef(0);
  const doneRef = useRef(false);

  // Live mode: stream, reduce, reconnect with after=lastSeq.
  useEffect(() => {
    if (opts.mode !== "live") {
      return;
    }
    let es: EventSourceLike | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled || doneRef.current) {
        return;
      }
      es = factory(eventsUrl(runId, lastSeqRef.current));
      es.onopen = () => setConnected(true);
      es.addEventListener("run_event", (msg) => {
        const ev = JSON.parse(msg.data as string) as RunEvent;
        if (ev.seq <= lastSeqRef.current) {
          return;
        }
        lastSeqRef.current = ev.seq;
        setEvents((prev) => [...prev, ev]);
        setState((prev) => reduceEvent(prev, ev));
        if (isTerminal(ev)) {
          doneRef.current = true;
          es?.close();
        }
      });
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!cancelled && !doneRef.current) {
          timer = setTimeout(connect, RECONNECT_MS);
        }
      };
    };
    connect();
    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
      es?.close();
    };
  }, [runId, opts.mode, factory]);

  // Replay mode, phase 1: load the whole log once.
  useEffect(() => {
    if (opts.mode !== "replay" || log !== null) {
      return;
    }
    const buffer: RunEvent[] = [];
    const es = factory(eventsUrl(runId, 0));
    es.onopen = () => setConnected(true);
    es.addEventListener("run_event", (msg) => {
      const ev = JSON.parse(msg.data as string) as RunEvent;
      buffer.push(ev);
      if (isTerminal(ev)) {
        es.close();
        setLog([...buffer]);
      }
    });
    es.onerror = () => {
      es.close();
      setLog([...buffer]);
    };
    return () => es.close();
  }, [runId, opts.mode, factory, log]);

  // Replay mode, phase 2: schedule the next event from the cursor.
  const playing = opts.mode === "replay" ? opts.playing : false;
  const speed = opts.mode === "replay" ? opts.speed : 1;
  useEffect(() => {
    if (opts.mode !== "replay" || !log || !playing || cursor >= log.length) {
      return;
    }
    const prevTs = cursor === 0 ? Date.parse(log[0].ts) : Date.parse(log[cursor - 1].ts);
    const delay = Math.max(0, (Date.parse(log[cursor].ts) - prevTs) / speed);
    const timer = setTimeout(() => {
      const ev = log[cursor];
      setEvents((prev) => [...prev, ev]);
      setState((prev) => reduceEvent(prev, ev));
      setCursor((c) => c + 1);
    }, delay);
    return () => clearTimeout(timer);
  }, [opts.mode, log, playing, speed, cursor]);

  const progress = useMemo(() => {
    if (opts.mode === "live") {
      return state.done ? 1 : 0;
    }
    return log && log.length > 0 ? cursor / log.length : 0;
  }, [opts.mode, state.done, log, cursor]);

  return { state, events, connected, progress };
}
```

Run: `cd frontend && bun run test src/lib/useRunEvents.test.tsx`
Expected: 3 passed. If the replay first-event assertion fails because the first delay is computed against itself, confirm `cursor === 0` yields `delay 0` as written.

- [x] **Step 3: Commit**

```bash
git add frontend/src/lib/useRunEvents.ts frontend/src/lib/useRunEvents.test.tsx
git commit -m "feat(frontend): useRunEvents hook with live reconnect and timed replay

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Brief page

**Files:**
- Create: `frontend/src/components/brief/BriefForm.tsx`, `frontend/src/components/brief/RecentRuns.tsx`, `frontend/src/components/AppHeader.tsx`
- Modify: `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`
- Test: `frontend/src/components/brief/BriefForm.test.tsx`

**Interfaces:**
- Consumes: `api.listAdapters`, `api.listRubrics`, `api.createRun`, `api.listRuns`, `CreateRunBody`, `AdapterStatus`, `RubricPackSummary`; `t`, `useLocale`.
- Produces: `BriefForm({ adapters, rubrics, onSubmit, busy })`, `RecentRuns({ runs })`, `AppHeader()`.

- [x] **Step 1: Failing test**

Create `frontend/src/components/brief/BriefForm.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BriefForm } from "./BriefForm";

const adapters = [
  { platform: "youtube", healthy: true, message: "ok" },
  { platform: "xiaohongshu", healthy: false, message: "Chrome CDP port 9222 unreachable" },
  { platform: "local", healthy: true, message: "ok" },
];
const rubrics = [{ name: "creator-hooks-v1", description: "Hooks, format, persona fit", question_ids: ["hook_type"] }];

describe("BriefForm", () => {
  it("submits brief, ticked platforms with quantities, and rubric", async () => {
    const onSubmit = vi.fn();
    render(<BriefForm adapters={adapters} rubrics={rubrics} onSubmit={onSubmit} busy={false} />);
    await userEvent.type(screen.getByLabelText("Brief"), "新加坡人搬到上海 vlog");
    await userEvent.click(screen.getByLabelText("youtube"));
    const qty = screen.getByLabelText("Posts per platform: youtube");
    await userEvent.clear(qty);
    await userEvent.type(qty, "200");
    await userEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(onSubmit).toHaveBeenCalledWith({
      brief: "新加坡人搬到上海 vlog",
      platforms: ["youtube"],
      quantities: { youtube: 200 },
      rubric_pack: "creator-hooks-v1",
      language_hint: undefined,
    });
  });

  it("disables unhealthy adapters and shows their message", () => {
    render(<BriefForm adapters={adapters} rubrics={rubrics} onSubmit={vi.fn()} busy={false} />);
    expect(screen.getByLabelText("xiaohongshu")).toBeDisabled();
    expect(screen.getByText("Chrome CDP port 9222 unreachable")).toBeInTheDocument();
  });

  it("blocks submit without a brief or platform", async () => {
    const onSubmit = vi.fn();
    render(<BriefForm adapters={adapters} rubrics={rubrics} onSubmit={onSubmit} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Write a brief first")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && bun run test src/components/brief`
Expected: FAIL, cannot find `./BriefForm`.

- [x] **Step 2: Implement BriefForm**

Create `frontend/src/components/brief/BriefForm.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { AdapterStatus, CreateRunBody, RubricPackSummary } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";

export const DEFAULT_QUANTITY = 500;

type Props = { adapters: AdapterStatus[]; rubrics: RubricPackSummary[]; onSubmit: (body: CreateRunBody) => void; busy: boolean };

export function BriefForm({ adapters, rubrics, onSubmit, busy }: Props) {
  const [locale] = useLocale();
  const [brief, setBrief] = useState("");
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [rubric, setRubric] = useState(rubrics[0]?.name ?? "");
  const [languageHint, setLanguageHint] = useState("");
  const [error, setError] = useState<string | null>(null);

  const platforms = adapters.filter((a) => ticked[a.platform]).map((a) => a.platform);

  const submit = () => {
    if (!brief.trim()) {
      setError(t("brief.validation.text", locale));
      return;
    }
    if (platforms.length === 0) {
      setError(t("brief.validation.platforms", locale));
      return;
    }
    setError(null);
    onSubmit({
      brief: brief.trim(),
      platforms,
      quantities: Object.fromEntries(platforms.map((p) => [p, quantities[p] ?? DEFAULT_QUANTITY])),
      rubric_pack: rubric,
      language_hint: languageHint.trim() || undefined,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("brief.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <label htmlFor="brief-text" className="text-sm font-medium">{t("brief.text.label", locale)}</label>
          <Textarea id="brief-text" rows={4} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder={t("brief.text.placeholder", locale)} />
        </div>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-sm font-medium">{t("brief.platforms", locale)}</legend>
          {adapters.map((a) => (
            <div key={a.platform} className="flex flex-wrap items-center gap-3">
              <Checkbox id={`platform-${a.platform}`} checked={Boolean(ticked[a.platform])} disabled={!a.healthy} onCheckedChange={(v) => setTicked((s) => ({ ...s, [a.platform]: v === true }))} aria-label={a.platform} />
              <label htmlFor={`platform-${a.platform}`} className="min-w-28 text-sm">{a.platform}</label>
              <Badge variant={a.healthy ? "secondary" : "destructive"}>{t(a.healthy ? "brief.adapter.healthy" : "brief.adapter.unhealthy", locale)}</Badge>
              {!a.healthy && <span className="text-xs text-muted-foreground">{a.message}</span>}
              {ticked[a.platform] && (
                <Input type="number" min={1} max={5000} className="w-28" aria-label={`${t("brief.quantity", locale)}: ${a.platform}`} value={quantities[a.platform] ?? DEFAULT_QUANTITY} onChange={(e) => setQuantities((q) => ({ ...q, [a.platform]: Number(e.target.value) || DEFAULT_QUANTITY }))} />
              )}
            </div>
          ))}
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <label htmlFor="rubric" className="text-sm font-medium">{t("brief.rubric", locale)}</label>
            <select id="rubric" className="h-9 rounded-md border bg-background px-3 text-sm" value={rubric} onChange={(e) => setRubric(e.target.value)}>
              {rubrics.map((r) => (
                <option key={r.name} value={r.name}>{r.name}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="language-hint" className="text-sm font-medium">{t("brief.language_hint", locale)}</label>
            <Input id="language-hint" value={languageHint} onChange={(e) => setLanguageHint(e.target.value)} placeholder={t("brief.language_hint.placeholder", locale)} />
          </div>
        </div>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button onClick={submit} disabled={busy}>{busy ? t("brief.submitting", locale) : t("brief.submit", locale)}</Button>
      </CardContent>
    </Card>
  );
}
```

A native `<select>` is used for the rubric because the shadcn `Select` renders in a portal that jsdom cannot drive with `userEvent.selectOptions`; record this in `frontend/AGENTS.md` in Task 12.

- [x] **Step 3: RecentRuns, AppHeader, layout, page**

Create `frontend/src/components/brief/RecentRuns.tsx`:

```tsx
"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { t, useLocale } from "@/lib/i18n";
import type { Run } from "@/lib/types";

export function RecentRuns({ runs }: { runs: Run[] }) {
  const [locale] = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("brief.recent_runs", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("brief.no_runs", locale)}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {runs.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 text-sm">
                <Link href={r.stage === "planning" ? `/runs/${r.id}/plan` : `/runs/${r.id}`} className="truncate underline-offset-2 hover:underline">{r.brief.text}</Link>
                <Badge variant="outline">{t(`run.stage.${r.stage}`, locale)}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
```

Create `frontend/src/components/AppHeader.tsx`:

```tsx
"use client";

import Link from "next/link";
import { LocaleSwitch } from "@/components/LocaleSwitch";
import { t, useLocale } from "@/lib/i18n";

export function AppHeader() {
  const [locale] = useLocale();
  return (
    <header className="flex items-center justify-between border-b px-6 py-3">
      <Link href="/" className="font-semibold tracking-tight">{t("app.title", locale)}</Link>
      <LocaleSwitch />
    </header>
  );
}
```

Replace `frontend/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = { title: "clipsieve", description: "Sift thousands of clips down to the few worth studying" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background text-foreground antialiased">
        <AppHeader />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <Toaster />
      </body>
    </html>
  );
}
```

Replace `frontend/src/app/page.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { BriefForm } from "@/components/brief/BriefForm";
import { RecentRuns } from "@/components/brief/RecentRuns";
import { type AdapterStatus, ApiError, type CreateRunBody, type RubricPackSummary, api } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Run } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const [locale] = useLocale();
  const [adapters, setAdapters] = useState<AdapterStatus[]>([]);
  const [rubrics, setRubrics] = useState<RubricPackSummary[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api.listAdapters(), api.listRubrics(), api.listRuns()])
      .then(([a, r, rs]) => {
        setAdapters(a);
        setRubrics(r);
        setRuns(rs);
      })
      .catch((e: unknown) => toast.error(e instanceof ApiError ? e.detail : t("common.error", locale)));
  }, [locale]);

  const onSubmit = async (body: CreateRunBody) => {
    setBusy(true);
    try {
      const run = await api.createRun(body);
      router.push(`/runs/${run.id}/plan`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <BriefForm adapters={adapters} rubrics={rubrics} onSubmit={onSubmit} busy={busy} />
      <RecentRuns runs={runs} />
    </div>
  );
}
```

Run: `cd frontend && bun run test src/components/brief && bun run typecheck`
Expected: 3 passed, typecheck clean.

- [x] **Step 4: Commit**

```bash
git add frontend/src/components frontend/src/app/layout.tsx frontend/src/app/page.tsx
git commit -m "feat(frontend): brief form, recent runs, app header

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Plan page

**Files:**
- Create: `frontend/src/components/plan/PlanEditor.tsx`, `frontend/src/app/runs/[id]/plan/page.tsx`
- Test: `frontend/src/components/plan/PlanEditor.test.tsx`

**Interfaces:**
- Consumes: `Plan, Query` types; `api.getRun`, `api.savePlan`, `api.approveRun`; `useRunEvents` (to notice `plan_ready` while planning).
- Produces: `PlanEditor({ plan, onSave, onApprove, busy })`.

- [x] **Step 1: Failing test**

Create `frontend/src/components/plan/PlanEditor.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Plan } from "@/lib/types";
import { PlanEditor } from "./PlanEditor";

const plan: Plan = {
  run_id: "r1",
  brief: { text: "Singaporean in Shanghai vlog", topic: "moving to Shanghai", audience: "Singaporeans relocating", persona: "friendly expat vlogger" },
  queries: [
    { platform: "youtube", query: "Singaporean in Shanghai vlog", lang: "en" },
    { platform: "xiaohongshu", query: "新加坡人 上海 生活 vlog", lang: "zh" },
  ],
  quantities: { youtube: 500, xiaohongshu: 500 },
  rubric_pack: "creator-hooks-v1",
  persona_fit_criteria: ["Unrelated", "Adjacent niche", "Same niche, different voice", "Close match", "Could be the user's own channel"],
};

describe("PlanEditor", () => {
  it("edits a query and saves", async () => {
    const onSave = vi.fn();
    render(<PlanEditor plan={plan} onSave={onSave} onApprove={vi.fn()} busy={false} />);
    const input = screen.getByDisplayValue("新加坡人 上海 生活 vlog");
    await userEvent.clear(input);
    await userEvent.type(input, "新加坡人 搬到上海");
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].queries[1].query).toBe("新加坡人 搬到上海");
  });

  it("adds and removes queries", async () => {
    const onSave = vi.fn();
    render(<PlanEditor plan={plan} onSave={onSave} onApprove={vi.fn()} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Add query" }));
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(3);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[0][0].queries).toHaveLength(2);
  });

  it("approves with the current edits", async () => {
    const onApprove = vi.fn();
    render(<PlanEditor plan={plan} onSave={vi.fn()} onApprove={onApprove} busy={false} />);
    const crit = screen.getByDisplayValue("Close match");
    await userEvent.clear(crit);
    await userEvent.type(crit, "Very close match");
    await userEvent.click(screen.getByRole("button", { name: "Approve and run" }));
    expect(onApprove.mock.calls[0][0].persona_fit_criteria[3]).toBe("Very close match");
  });
});
```

Run: `cd frontend && bun run test src/components/plan`
Expected: FAIL, cannot find `./PlanEditor`.

- [x] **Step 2: Implement PlanEditor**

Create `frontend/src/components/plan/PlanEditor.tsx`:

```tsx
"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { t, useLocale } from "@/lib/i18n";
import type { Plan, Query } from "@/lib/types";

type Props = { plan: Plan; onSave: (plan: Plan) => void; onApprove: (plan: Plan) => void; busy: boolean };

export function PlanEditor({ plan, onSave, onApprove, busy }: Props) {
  const [locale] = useLocale();
  const [draft, setDraft] = useState<Plan>(plan);

  const setQuery = (i: number, patch: Partial<Query>) =>
    setDraft((d) => ({ ...d, queries: d.queries.map((q, j) => (j === i ? { ...q, ...patch } : q)) }));
  const addQuery = () => setDraft((d) => ({ ...d, queries: [...d.queries, { platform: Object.keys(d.quantities)[0] ?? "local", query: "", lang: "en" }] }));
  const removeQuery = (i: number) => setDraft((d) => ({ ...d, queries: d.queries.filter((_, j) => j !== i) }));
  const setCriterion = (i: number, value: string) =>
    setDraft((d) => ({ ...d, persona_fit_criteria: d.persona_fit_criteria.map((c, j) => (j === i ? value : c)) }));

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("plan.title", locale)}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm sm:grid-cols-3">
          <div><span className="text-muted-foreground">{t("plan.topic", locale)}: </span>{draft.brief.topic}</div>
          <div><span className="text-muted-foreground">{t("plan.audience", locale)}: </span>{draft.brief.audience}</div>
          <div><span className="text-muted-foreground">{t("plan.persona", locale)}: </span>{draft.brief.persona}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.queries", locale)}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("plan.query.platform", locale)}</TableHead>
                <TableHead>{t("plan.query.text", locale)}</TableHead>
                <TableHead>{t("plan.query.lang", locale)}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {draft.queries.map((q, i) => (
                <TableRow key={`${i}-${q.platform}`}>
                  <TableCell><Input value={q.platform} onChange={(e) => setQuery(i, { platform: e.target.value })} className="w-32" /></TableCell>
                  <TableCell><Input value={q.query} onChange={(e) => setQuery(i, { query: e.target.value })} /></TableCell>
                  <TableCell><Input value={q.lang} onChange={(e) => setQuery(i, { lang: e.target.value })} className="w-20" /></TableCell>
                  <TableCell><Button variant="ghost" size="sm" onClick={() => removeQuery(i)} aria-label={t("plan.query.remove", locale)}><Trash2 className="size-4" /></Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Button variant="outline" size="sm" onClick={addQuery} className="self-start"><Plus className="mr-1 size-4" />{t("plan.query.add", locale)}</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.quantities", locale)}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          {Object.entries(draft.quantities).map(([platform, n]) => (
            <label key={platform} className="flex items-center gap-2 text-sm">
              {platform}
              <Input type="number" min={1} className="w-28" value={n} onChange={(e) => setDraft((d) => ({ ...d, quantities: { ...d.quantities, [platform]: Number(e.target.value) || 1 } }))} />
            </label>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.persona_criteria", locale)}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("plan.persona_criteria.help", locale)}</p>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {draft.persona_fit_criteria.map((c, i) => (
            <div key={`crit-${i}`} className="flex items-center gap-3">
              <span className="w-6 text-sm text-muted-foreground">{i + 1}</span>
              <Input value={c} onChange={(e) => setCriterion(i, e.target.value)} />
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button variant="outline" onClick={() => onSave(draft)} disabled={busy}>{t("plan.save", locale)}</Button>
        <Button onClick={() => onApprove(draft)} disabled={busy}>{busy ? t("plan.approving", locale) : t("plan.approve", locale)}</Button>
      </div>
    </div>
  );
}
```

- [x] **Step 3: Plan page**

Create `frontend/src/app/runs/[id]/plan/page.tsx`:

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PlanEditor } from "@/components/plan/PlanEditor";
import { ApiError, api } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Plan } from "@/lib/types";
import { useRunEvents } from "@/lib/useRunEvents";

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [locale] = useLocale();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const { events } = useRunEvents(id, { mode: "live" });

  useEffect(() => {
    api.getRun(id).then(({ plan: p }) => setPlan(p)).catch(() => toast.error(t("common.error", locale)));
  }, [id, locale]);

  useEffect(() => {
    const ready = [...events].reverse().find((e) => e.type === "plan_ready");
    if (ready && !plan) {
      setPlan((ready.payload as { plan: Plan }).plan);
    }
  }, [events, plan]);

  const onSave = async (p: Plan) => {
    try {
      setPlan(await api.savePlan(id, p));
      toast.success(t("plan.saved", locale));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
    }
  };

  const onApprove = async (p: Plan) => {
    setBusy(true);
    try {
      await api.savePlan(id, p);
      await api.approveRun(id);
      router.push(`/runs/${id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
      setBusy(false);
    }
  };

  if (!plan) {
    return <p className="text-sm text-muted-foreground">{t("plan.pending", locale)}</p>;
  }
  return <PlanEditor key={plan.approved_at ?? plan.queries.length} plan={plan} onSave={onSave} onApprove={onApprove} busy={busy} />;
}
```

Run: `cd frontend && bun run test src/components/plan && bun run typecheck`
Expected: 3 passed, typecheck clean.

- [x] **Step 4: Commit**

```bash
git add frontend/src/components/plan frontend/src/app/runs
git commit -m "feat(frontend): editable plan page with approve

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Live dashboard

**Files:**
- Create: `frontend/src/components/dashboard/Counters.tsx`, `PostGrid.tsx`, `CurrentItem.tsx`, `Aggregates.tsx`, `ReviewBucket.tsx`, `Dashboard.tsx`, `frontend/src/app/runs/[id]/page.tsx`
- Test: `frontend/src/components/dashboard/dashboard.test.tsx`

**Interfaces:**
- Consumes: `DashboardState, PostTile`, `answersPerSecond`, `reduceAll`, fixture events; `mediaUrl`; `api.pauseRun/resumeRun`; `t, tOr`.
- Produces: `Counters({ counters, rate })`, `PostGrid({ runId, posts, total })`, `CurrentItem({ latest })`, `Aggregates({ aggregates })`, `ReviewBucket({ review, posts })`, `Dashboard({ runId, state, events, connected, controls? })`.

- [x] **Step 1: Failing tests**

Create `frontend/src/components/dashboard/dashboard.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import { reduceAll } from "@/lib/events";
import { Aggregates } from "./Aggregates";
import { Counters } from "./Counters";
import { CurrentItem } from "./CurrentItem";
import { PostGrid } from "./PostGrid";
import { ReviewBucket } from "./ReviewBucket";

const done = reduceAll(fixtureEvents);
const midRun = reduceAll(fixtureEvents.filter((e) => e.seq <= 22));

describe("Counters", () => {
  it("renders six tiles with values", () => {
    render(<Counters counters={done.counters} rate={12.5} />);
    expect(screen.getByText("Collected").nextSibling).toHaveTextContent("5");
    expect(screen.getByText("Answers / sec").nextSibling).toHaveTextContent("12.5");
    expect(screen.getByText("Jev cost").nextSibling).toHaveTextContent("$0.0006");
    expect(screen.getByText("Elapsed").nextSibling).toHaveTextContent("12.2s");
  });
});

describe("PostGrid", () => {
  it("renders one tile per post with state and Chinese titles intact", () => {
    render(<PostGrid runId="FIXTURE" posts={done.posts} total={5} />);
    const grid = screen.getByRole("list");
    expect(within(grid).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByTitle("新加坡人在上海的第一周")).toBeInTheDocument();
    expect(screen.getByTestId("tile-local:fx-001")).toHaveAttribute("data-state", "shortlisted");
    expect(screen.getByTestId("tile-local:fx-005")).toHaveAttribute("data-state", "dropped_pass_one");
    expect(screen.getByTestId("tile-local:fx-004")).toHaveAttribute("data-state", "judge_failed");
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });
});

describe("CurrentItem", () => {
  it("renders one row per answer with the right metric", () => {
    render(<CurrentItem latest={midRun.latest} />);
    expect(screen.getByText("Hook type")).toBeInTheDocument();
    expect(screen.getByText("Problem")).toBeInTheDocument();
    expect(screen.getByText("3 / 5")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar").length).toBeGreaterThanOrEqual(7);
  });
  it("shows the empty state", () => {
    render(<CurrentItem latest={null} />);
    expect(screen.getByText("Waiting for the first judged post…")).toBeInTheDocument();
  });
});

describe("Aggregates", () => {
  it("renders distributions with percentages", () => {
    render(<Aggregates aggregates={done.aggregates} />);
    expect(screen.getByText("Opening hook")).toBeInTheDocument();
    expect(screen.getByText("Vlog montage")).toBeInTheDocument();
    expect(screen.getAllByText("50%").length).toBeGreaterThanOrEqual(1);
  });
});

describe("ReviewBucket", () => {
  it("shows the count", () => {
    render(<ReviewBucket review={done.review} posts={done.posts} />);
    expect(screen.getByText("1 posts")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && bun run test src/components/dashboard`
Expected: FAIL, modules not found.

- [x] **Step 2: Counters and PostGrid**

Create `frontend/src/components/dashboard/Counters.tsx`:

```tsx
"use client";

import { Card, CardContent } from "@/components/ui/card";
import { t, useLocale } from "@/lib/i18n";
import type { Counters as CountersT } from "@/lib/types";

export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function Counters({ counters, rate }: { counters: CountersT; rate: number }) {
  const [locale] = useLocale();
  const tiles: [string, string][] = [
    ["counters.collected", String(counters.collected)],
    ["counters.pass_one_kept", String(counters.pass_one_kept)],
    ["counters.judged", String(counters.judged)],
    ["counters.answers_per_sec", rate.toFixed(1)],
    ["counters.elapsed", `${counters.elapsed_s.toFixed(1)}s`],
    ["counters.cost", formatCost(counters.jev_cost_usd)],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map(([key, value]) => (
        <Card key={key}>
          <CardContent className="flex flex-col gap-1 p-4">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">{t(key, locale)}</span>
            <span className="font-mono text-2xl tabular-nums">{value}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

Create `frontend/src/components/dashboard/PostGrid.tsx`:

```tsx
"use client";

import { Film, Images } from "lucide-react";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { mediaUrl } from "@/lib/api";
import type { PostTile } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";

export const MAX_TILES = 2000;

const stateClass: Record<PostTile["state"], string> = {
  collected: "opacity-80",
  dropped_pass_one: "opacity-25",
  judged: "opacity-100",
  shortlisted: "opacity-100 ring-2 ring-amber-500",
  review: "opacity-100 ring-2 ring-rose-500 ring-dashed",
  judge_failed: "opacity-40 ring-2 ring-zinc-500",
};

function Tile({ runId, tile }: { runId: string; tile: PostTile }) {
  const [locale] = useLocale();
  const [broken, setBroken] = useState(false);
  const title = tile.post.text.title ?? tile.post.text.caption ?? tile.post.id;
  const Icon = tile.post.kind === "video" ? Film : Images;
  return (
    <li data-testid={`tile-${tile.post.id}`} data-state={tile.state} title={title} aria-label={`${title} (${t(`grid.state.${tile.state}`, locale)})`} className={`relative aspect-square overflow-hidden rounded bg-muted ${stateClass[tile.state]}`}>
      {broken ? (
        <Icon className="absolute inset-0 m-auto size-5 text-muted-foreground" />
      ) : (
        // biome-ignore lint/performance/noImgElement: thumbnails come from the local API, not an optimizable remote
        <img src={mediaUrl(runId, tile.post.id, "thumb.jpg")} alt="" className="size-full object-cover" onError={() => setBroken(true)} />
      )}
    </li>
  );
}

export function PostGrid({ runId, posts, total }: { runId: string; posts: Record<string, PostTile>; total: number }) {
  const [locale] = useLocale();
  const tiles = Object.values(posts).slice(0, MAX_TILES);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{t("grid.title", locale)}</CardTitle>
        <span className="font-mono text-xs text-muted-foreground">{t("grid.progress", locale, { done: tiles.length, total })}</span>
      </CardHeader>
      <CardContent>
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(44px,1fr))] gap-1">
          {tiles.map((tile) => (
            <Tile key={tile.post.id} runId={runId} tile={tile} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
```

`total` is the sum of the plan's quantities when known, else the collected count; the page computes it.

- [x] **Step 3: CurrentItem, Aggregates, ReviewBucket**

Create `frontend/src/components/dashboard/CurrentItem.tsx`:

```tsx
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { DashboardState } from "@/lib/events";
import { type Locale, t, tOr, useLocale } from "@/lib/i18n";
import type { JudgeAnswer } from "@/lib/types";

export function answerLabel(qid: string, a: JudgeAnswer, locale: Locale): string {
  if (a.type === "choice") {
    return tOr(`label.${String(a.value)}`, String(a.value), locale);
  }
  if (a.type === "score") {
    const levels = a.legend ? Object.keys(a.legend).length : 5;
    return t("current.score", locale, { value: Number(a.value).toFixed(1), levels });
  }
  return `${Math.round(Number(a.value) * 100)}%`;
}

export function answerMetric(a: JudgeAnswer): { value: number; kind: "confidence" | "probability" } {
  if (a.type === "noul") {
    return { value: Number(a.value), kind: "probability" };
  }
  return { value: a.confidence ?? 0, kind: "confidence" };
}

export function CurrentItem({ latest }: { latest: DashboardState["latest"] }) {
  const [locale] = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("current.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {!latest ? (
          <p className="text-sm text-muted-foreground">{t("current.empty", locale)}</p>
        ) : (
          <div className="flex flex-col gap-3">
            <div>
              <p className="font-medium">{latest.post.text.title ?? latest.post.text.caption}</p>
              <p className="text-xs text-muted-foreground">{latest.post.platform} · {latest.post.kind} · {t("current.tokens", locale, { tokens: latest.judge.input_tokens, ms: latest.judge.latency_ms })}</p>
            </div>
            <dl className="grid grid-cols-[minmax(7rem,auto)_minmax(6rem,auto)_1fr_3rem] items-center gap-x-3 gap-y-2 text-sm">
              {Object.entries(latest.judge.answers).map(([qid, a]) => {
                const m = answerMetric(a);
                return (
                  <div key={qid} className="contents">
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">{tOr(`question.${qid}`, qid, locale)}</dt>
                    <dd>{answerLabel(qid, a, locale)}</dd>
                    <dd><Progress value={m.value * 100} aria-label={t(`current.${m.kind}`, locale)} /></dd>
                    <dd className="text-right font-mono text-xs tabular-nums">{Math.round(m.value * 100)}%</dd>
                  </div>
                );
              })}
            </dl>
            <p className="text-sm"><span className="text-muted-foreground">{t("current.composite", locale)}: </span><span className="font-mono">{latest.composite.toFixed(2)}</span></p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

Create `frontend/src/components/dashboard/Aggregates.tsx`:

```tsx
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { t, tOr, useLocale } from "@/lib/i18n";

const SHOWN = ["hook_type", "format", "persona_fit"] as const;

export function Aggregates({ aggregates }: { aggregates: Record<string, Record<string, number>> }) {
  const [locale] = useLocale();
  const empty = SHOWN.every((q) => !aggregates[q]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("aggregates.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="text-sm text-muted-foreground">{t("aggregates.empty", locale)}</p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-3">
            {SHOWN.map((qid) => {
              const row = aggregates[qid] ?? {};
              const total = Object.values(row).reduce((a, b) => a + b, 0) || 1;
              const entries = Object.entries(row).sort((a, b) => b[1] - a[1]);
              return (
                <div key={qid} className="flex flex-col gap-2">
                  <h3 className="text-xs uppercase tracking-wide text-muted-foreground">{t(`aggregates.${qid}`, locale)}</h3>
                  {entries.map(([label, n]) => (
                    <div key={label} className="flex flex-col gap-1 text-sm">
                      <div className="flex justify-between"><span>{tOr(`label.${label}`, label, locale)}</span><span className="font-mono text-xs">{Math.round((n / total) * 100)}%</span></div>
                      <div className="h-1.5 w-full rounded bg-muted"><div className="h-1.5 rounded bg-amber-500" style={{ width: `${(n / total) * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

Create `frontend/src/components/dashboard/ReviewBucket.tsx`:

```tsx
"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { PostTile } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";

export function ReviewBucket({ review, posts }: { review: string[]; posts: Record<string, PostTile> }) {
  const [locale] = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("review.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-3">
        <div>
          <p className="font-mono text-2xl text-rose-500">{t("review.count", locale, { count: review.length })}</p>
          <p className="text-xs text-muted-foreground">{t("review.help", locale)}</p>
        </div>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" disabled={review.length === 0}>{t("review.open", locale)}</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("review.title", locale)}</DialogTitle>
            </DialogHeader>
            {review.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("review.empty", locale)}</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {review.map((id) => (
                  <li key={id}>{posts[id]?.post.text.title ?? posts[id]?.post.text.caption ?? id}</li>
                ))}
              </ul>
            )}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
```

Run: `cd frontend && bun run test src/components/dashboard`
Expected: 7 passed. If `Progress` lacks `role="progressbar"` in the installed shadcn version, add `role="progressbar"` to the `Progress` usage in `CurrentItem.tsx`.

- [x] **Step 4: Dashboard composition and the run page**

Create `frontend/src/components/dashboard/Dashboard.tsx`:

```tsx
"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { answersPerSecond, type DashboardState } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";
import type { RunEvent } from "@/lib/types";
import { Aggregates } from "./Aggregates";
import { Counters } from "./Counters";
import { CurrentItem } from "./CurrentItem";
import { PostGrid } from "./PostGrid";
import { ReviewBucket } from "./ReviewBucket";

type Props = { runId: string; state: DashboardState; events: RunEvent[]; connected: boolean; total: number; controls?: ReactNode };

export function Dashboard({ runId, state, events, connected, total, controls }: Props) {
  const [locale] = useLocale();
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">{t("run.title", locale)}</h1>
          <Badge>{t(`run.stage.${state.stage}`, locale)}</Badge>
          <Badge variant={connected ? "secondary" : "destructive"}>{t(connected ? "run.connected" : "run.disconnected", locale)}</Badge>
        </div>
        <div className="flex items-center gap-2">
          {controls}
          {state.done && <Button asChild size="sm"><Link href={`/runs/${runId}/report`}>{t("run.view_report", locale)}</Link></Button>}
          <Button asChild variant="outline" size="sm"><Link href={`/runs/${runId}/replay`}>{t("run.view_replay", locale)}</Link></Button>
        </div>
      </div>
      <Counters counters={state.counters} rate={answersPerSecond(events)} />
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <PostGrid runId={runId} posts={state.posts} total={total} />
        <div className="flex flex-col gap-4">
          <CurrentItem latest={state.latest} />
          <Aggregates aggregates={state.aggregates} />
          <ReviewBucket review={state.review} posts={state.posts} />
        </div>
      </div>
    </div>
  );
}
```

Create `frontend/src/app/runs/[id]/page.tsx`:

```tsx
"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Run } from "@/lib/types";
import { useRunEvents } from "@/lib/useRunEvents";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [locale] = useLocale();
  const [run, setRun] = useState<Run | null>(null);
  const { state, events, connected } = useRunEvents(id, { mode: "live" });

  useEffect(() => {
    api.getRun(id).then(({ run: r }) => setRun(r)).catch(() => toast.error(t("common.error", locale)));
  }, [id, locale]);

  const total = run ? Math.max(Object.values(run.quantities).reduce((a, b) => a + b, 0), state.counters.collected) : state.counters.collected;

  const toggle = async () => {
    if (!run) {
      return;
    }
    try {
      setRun(run.paused ? await api.resumeRun(id) : await api.pauseRun(id));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
    }
  };

  const controls = run && !state.done ? (
    <Button variant="outline" size="sm" onClick={toggle}>{t(run.paused ? "run.resume" : "run.pause", locale)}</Button>
  ) : null;

  return <Dashboard runId={id} state={state} events={events} connected={connected} total={total} controls={controls} />;
}
```

Run: `cd frontend && bun run typecheck && bun run test`
Expected: clean, all tests pass.

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard "frontend/src/app/runs/[id]/page.tsx"
git commit -m "feat(frontend): live dashboard with counters, grid, current item, aggregates, review

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Report page

**Files:**
- Create: `frontend/src/components/report/ReportView.tsx`, `frontend/src/components/report/PostDialog.tsx`, `frontend/src/app/runs/[id]/report/page.tsx`
- Test: `frontend/src/components/report/ReportView.test.tsx`

**Interfaces:**
- Consumes: `Report`, `PostView`, `api.getReport`, `api.getPosts`, `answerLabel` (Task 8).
- Produces: `ReportView({ report, posts })` where `posts: Record<string, PostView>`; `PostDialog({ view, open, onOpenChange })`.

- [x] **Step 1: Failing test**

Create `frontend/src/components/report/ReportView.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import { fixturePosts } from "@/lib/__fixtures__/posts";
import type { PostView } from "@/lib/api";
import type { Report } from "@/lib/types";
import { ReportView } from "./ReportView";

const report = (fixtureEvents.find((e) => e.type === "explained")?.payload as { report: Report }).report;
const posts: Record<string, PostView> = Object.fromEntries(
  fixturePosts.slice(0, 2).map((p) => [p.id, { post: p, judge: {}, state: "shortlisted" as const }]),
);

describe("ReportView", () => {
  it("renders sections and opens a post dialog from a citation", async () => {
    render(<ReportView report={report} posts={posts} />);
    expect(screen.getByText("Patterns")).toBeInTheDocument();
    expect(screen.getByText("Problem-first openings")).toBeInTheDocument();
    expect(screen.getByText("租房踩了三个坑")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "local:fx-002" })[0]);
    expect(await screen.findByText("从新加坡搬到上海的第一周，租房踩了三个坑。")).toBeInTheDocument();
  });

  it("disables citations for posts not in the run", () => {
    const broken: Report = { ...report, gaps: [{ title: "Missing", rationale: "x", post_ids: ["local:fx-999"] }] };
    render(<ReportView report={broken} posts={posts} />);
    const btn = screen.getByRole("button", { name: "local:fx-999" });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", "Post not found in this run");
  });
});
```

Run: `cd frontend && bun run test src/components/report`
Expected: FAIL, modules not found.

- [x] **Step 2: Implement**

Create `frontend/src/components/report/PostDialog.tsx`:

```tsx
"use client";

import { answerLabel } from "@/components/dashboard/CurrentItem";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { PostView } from "@/lib/api";
import { t, tOr, useLocale } from "@/lib/i18n";

export function PostDialog({ view, open, onOpenChange }: { view: PostView | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [locale] = useLocale();
  const judge = view?.judge.pass_two ?? view?.judge.pass_one;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto">
        {view && (
          <>
            <DialogHeader>
              <DialogTitle>{view.post.text.title ?? view.post.id}</DialogTitle>
            </DialogHeader>
            <section className="flex flex-col gap-1 text-sm">
              <h4 className="text-xs uppercase text-muted-foreground">{t("report.post.caption", locale)}</h4>
              <p>{view.post.text.caption}</p>
            </section>
            {judge && (
              <section className="flex flex-col gap-1 text-sm">
                <h4 className="text-xs uppercase text-muted-foreground">{t("report.post.answers", locale)}</h4>
                <ul>
                  {Object.entries(judge.answers).map(([qid, a]) => (
                    <li key={qid} className="flex justify-between gap-3"><span className="text-muted-foreground">{tOr(`question.${qid}`, qid, locale)}</span><span>{answerLabel(qid, a, locale)}</span></li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

Create `frontend/src/components/report/ReportView.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PostView } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Report } from "@/lib/types";
import { PostDialog } from "./PostDialog";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

export function ReportView({ report, posts }: { report: Report; posts: Record<string, PostView> }) {
  const [locale] = useLocale();
  const [openId, setOpenId] = useState<string | null>(null);

  const Cites = ({ ids }: { ids: string[] }) => (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <span className="text-muted-foreground">{t("report.cited", locale)}:</span>
      {ids.map((id) => {
        const known = id in posts;
        return (
          <Button key={id} variant="outline" size="sm" className="h-6 px-2 font-mono text-xs" disabled={!known} title={known ? undefined : t("report.unknown_post", locale)} onClick={() => setOpenId(id)}>
            {id}
          </Button>
        );
      })}
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">{t("report.title", locale)}</h1>

      <Section title={t("report.patterns", locale)}>
        {report.patterns.map((p) => (
          <article key={p.title} className="flex flex-col gap-1 text-sm">
            <h3 className="font-medium">{p.title}</h3>
            <p><span className="text-muted-foreground">{t("report.observation", locale)}: </span>{p.observation}</p>
            <p><span className="text-muted-foreground">{t("report.hypothesis", locale)}: </span>{p.hypothesis}</p>
            <Cites ids={p.post_ids} />
          </article>
        ))}
      </Section>

      <Section title={t("report.clips", locale)}>
        {report.clips.map((c) => (
          <article key={c.post_id} className="flex flex-col gap-1 text-sm">
            <h3 className="font-medium">{posts[c.post_id]?.post.text.title ?? c.post_id}</h3>
            <p><span className="text-muted-foreground">{t("report.hook_quote", locale)}: </span>“{c.hook_quote}”</p>
            <p><span className="text-muted-foreground">{t("report.why_it_works", locale)}: </span>{c.why_it_works}</p>
            <p><span className="text-muted-foreground">{t("report.weaknesses", locale)}: </span>{c.weaknesses}</p>
            <Cites ids={[c.post_id]} />
          </article>
        ))}
      </Section>

      <Section title={t("report.gaps", locale)}>
        {report.gaps.map((g) => (
          <article key={g.title} className="flex flex-col gap-1 text-sm">
            <h3 className="font-medium">{g.title}</h3>
            <p>{g.rationale}</p>
            <Cites ids={g.post_ids} />
          </article>
        ))}
      </Section>

      <Section title={t("report.concepts", locale)}>
        {report.concepts.map((c) => (
          <article key={c.hook} className="grid gap-1 text-sm sm:grid-cols-[6rem_1fr]">
            <span className="text-muted-foreground">{t("report.concept.hook", locale)}</span><span className="font-medium">{c.hook}</span>
            <span className="text-muted-foreground">{t("report.concept.structure", locale)}</span><span>{c.structure}</span>
            <span className="text-muted-foreground">{t("report.concept.visual", locale)}</span><span>{c.visual}</span>
            <span className="text-muted-foreground">{t("report.concept.proof", locale)}</span><span>{c.proof}</span>
            <span className="text-muted-foreground">{t("report.concept.cta", locale)}</span><span>{c.cta}</span>
            <span className="sm:col-span-2"><Cites ids={c.inspired_by_post_ids} /></span>
          </article>
        ))}
      </Section>

      {report.caveats.length > 0 && (
        <Section title={t("report.caveats", locale)}>
          <ul className="list-disc pl-5 text-sm">{report.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </Section>
      )}

      <PostDialog view={openId ? (posts[openId] ?? null) : null} open={openId !== null} onOpenChange={(o) => !o && setOpenId(null)} />
    </div>
  );
}
```

Create `frontend/src/app/runs/[id]/report/page.tsx`:

```tsx
"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ReportView } from "@/components/report/ReportView";
import { ApiError, type PostView, api } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Report } from "@/lib/types";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [locale] = useLocale();
  const [report, setReport] = useState<Report | null>(null);
  const [posts, setPosts] = useState<Record<string, PostView>>({});
  const [status, setStatus] = useState<"loading" | "ready" | "not_ready" | "error">("loading");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.getReport(id);
        const all: PostView[] = [];
        let offset = 0;
        for (;;) {
          const page = await api.getPosts(id, offset, 500);
          all.push(...page.items);
          offset += page.items.length;
          if (offset >= page.total || page.items.length === 0) {
            break;
          }
        }
        setPosts(Object.fromEntries(all.map((v) => [v.post.id, v])));
        setReport(r);
        setStatus("ready");
      } catch (e) {
        setStatus(e instanceof ApiError && e.status === 404 ? "not_ready" : "error");
      }
    })();
  }, [id]);

  if (status === "loading") {
    return <p className="text-sm text-muted-foreground">{t("report.loading", locale)}</p>;
  }
  if (status === "not_ready") {
    return <p className="text-sm text-muted-foreground">{t("report.not_ready", locale)}</p>;
  }
  if (status === "error" || !report) {
    return <p className="text-sm text-destructive">{t("common.error", locale)}</p>;
  }
  return <ReportView report={report} posts={posts} />;
}
```

Run: `cd frontend && bun run test src/components/report && bun run typecheck`
Expected: 2 passed, clean.

- [x] **Step 3: Commit**

```bash
git add frontend/src/components/report "frontend/src/app/runs/[id]/report"
git commit -m "feat(frontend): report page with cited post dialogs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Replay page

**Files:**
- Create: `frontend/src/components/dashboard/ReplayControls.tsx`, `frontend/src/app/runs/[id]/replay/page.tsx`
- Test: `frontend/src/components/dashboard/ReplayControls.test.tsx`

**Interfaces:**
- Consumes: `Dashboard`, `useRunEvents` replay mode.
- Produces: `ReplayControls({ playing, speed, progress, done, total, onToggle, onSpeed })`; `SPEEDS = [1, 4, 16]`.

- [ ] **Step 1: Failing test**

Create `frontend/src/components/dashboard/ReplayControls.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReplayControls } from "./ReplayControls";

describe("ReplayControls", () => {
  it("toggles play and changes speed", async () => {
    const onToggle = vi.fn();
    const onSpeed = vi.fn();
    render(<ReplayControls playing={false} speed={1} progress={0.25} done={10} total={40} onToggle={onToggle} onSpeed={onSpeed} />);
    await userEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "4x" }));
    expect(onSpeed).toHaveBeenCalledWith(4);
    expect(screen.getByText("10 / 40 events")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });
});
```

Run: `cd frontend && bun run test src/components/dashboard/ReplayControls.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement**

Create `frontend/src/components/dashboard/ReplayControls.tsx`:

```tsx
"use client";

import { Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { t, useLocale } from "@/lib/i18n";

export const SPEEDS = [1, 4, 16] as const;

type Props = { playing: boolean; speed: number; progress: number; done: number; total: number; onToggle: () => void; onSpeed: (s: number) => void };

export function ReplayControls({ playing, speed, progress, done, total, onToggle, onSpeed }: Props) {
  const [locale] = useLocale();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button size="sm" onClick={onToggle} aria-label={t(playing ? "replay.pause" : "replay.play", locale)}>
        {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
      </Button>
      <span className="text-xs text-muted-foreground">{t("replay.speed", locale)}</span>
      {SPEEDS.map((s) => (
        <Button key={s} size="sm" variant={s === speed ? "default" : "outline"} onClick={() => onSpeed(s)}>{s}x</Button>
      ))}
      <div className="flex min-w-48 flex-1 items-center gap-2">
        <Progress value={progress * 100} role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100} />
        <span className="whitespace-nowrap font-mono text-xs">{t("replay.progress", locale, { done, total })}</span>
      </div>
    </div>
  );
}
```

Create `frontend/src/app/runs/[id]/replay/page.tsx`:

```tsx
"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { ReplayControls } from "@/components/dashboard/ReplayControls";
import { useRunEvents } from "@/lib/useRunEvents";

export default function ReplayPage() {
  const { id } = useParams<{ id: string }>();
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(4);
  const { state, events, connected, progress } = useRunEvents(id, { mode: "replay", speed, playing });
  const total = progress > 0 ? Math.round(events.length / progress) : 0;

  return (
    <Dashboard
      runId={id}
      state={state}
      events={events}
      connected={connected}
      total={Math.max(state.counters.collected, Object.keys(state.posts).length)}
      controls={<ReplayControls playing={playing} speed={speed} progress={progress} done={events.length} total={total} onToggle={() => setPlaying((p) => !p)} onSpeed={setSpeed} />}
    />
  );
}
```

Run: `cd frontend && bun run test && bun run typecheck`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/ReplayControls.tsx frontend/src/components/dashboard/ReplayControls.test.tsx "frontend/src/app/runs/[id]/replay"
git commit -m "feat(frontend): replay page with speed controls

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Playwright end-to-end flow against the fake backend

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/run-flow.spec.ts`
- Modify: `frontend/package.json` (add `"e2e": "playwright test"` if missing), `frontend/.gitignore` (add `test-results/`, `playwright-report/`)

**Interfaces:**
- Consumes: backend from plan 03 running with `CLIPSIEVE_EXPLAIN_BACKEND=fake` so that the `local` adapter serves `backend/tests/fixtures/posts`, `RecordedJudge` answers, and `FakeExplainBackend` plans and reports. A run completes in under 30 seconds in that mode.

- [ ] **Step 1: Install browsers and write the config**

```bash
cd frontend && bunx playwright install chromium && cd ..
```

Create `frontend/playwright.config.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const dataDir = mkdtempSync(join(tmpdir(), "clipsieve-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  webServer: [
    {
      command: "uv run uvicorn clipsieve.app:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/rubrics",
      reuseExistingServer: !process.env.CI,
      // fake mode defaults CLIPSIEVE_FIXTURE_DIR to backend/tests/fixtures (overview Addendum E.7); no other env needed
      env: { CLIPSIEVE_EXPLAIN_BACKEND: "fake", CLIPSIEVE_DATA_DIR: dataDir, TYPESAFE_API_KEY: "" },
      timeout: 120_000,
    },
    {
      command: "bun run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
```

- [ ] **Step 2: The flow**

Create `frontend/e2e/run-flow.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("brief -> plan -> live run -> report -> replay", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Brief").fill("我是一个要搬到上海的新加坡人，想做 vlog，分析这类视频的开头和风格。");
  await page.getByLabel("local", { exact: true }).check();
  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page).toHaveURL(/\/runs\/[^/]+\/plan$/);
  await expect(page.getByRole("button", { name: "Approve and run" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Approve and run" }).click();

  await expect(page).toHaveURL(/\/runs\/[^/]+$/);
  await expect(page.getByText("Done", { exact: true })).toBeVisible({ timeout: 60_000 });
  const collected = page.getByText("Collected").locator("xpath=following-sibling::*[1]");
  await expect(collected).toHaveText("5");
  await expect(page.getByTitle("新加坡人在上海的第一周")).toBeVisible();
  await expect(page.locator("[data-state='shortlisted']").first()).toBeVisible();

  await page.getByRole("link", { name: "View report" }).click();
  await expect(page).toHaveURL(/\/report$/);
  await expect(page.getByText("Patterns")).toBeVisible();
  const cite = page.getByRole("button", { name: /^local:fx-/ }).first();
  await cite.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(page.url().replace(/\/report$/, "/replay"));
  await page.getByRole("button", { name: "16x" }).click();
  await expect(page.locator("li[data-testid^='tile-']")).toHaveCount(5, { timeout: 30_000 });
  await expect(page.getByText(/5 \/ 5/)).toBeVisible();
});
```

Add to `frontend/.gitignore`:

```text
test-results/
playwright-report/
```

- [ ] **Step 3: Run it**

Run: `cd frontend && bun run e2e`
Expected: 1 passed. If the backend's fake mode exposes the `local` adapter under a different fixture path, fix the backend configuration (plan 03), not this test. If the "Done" badge text collides with another element, tighten the locator to `page.locator("header, h1 ~ *").getByText("Done")`.

- [ ] **Step 4: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e frontend/.gitignore frontend/package.json
git commit -m "test(frontend): Playwright flow from brief to replay against fake backend

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: DOX closeout and green `bun run check`

**Files:**
- Modify: `frontend/AGENTS.md`, root `AGENTS.md`, root `.github/workflows/check.yml` (plan 01) to run `bun run --filter frontend e2e` only when `RUN_E2E=1`

- [ ] **Step 1: Complete `frontend/AGENTS.md`**

Replace the file with the Task 1 content plus these sections:

```markdown
## Component map
- `src/app/page.tsx` → `brief/BriefForm` + `brief/RecentRuns`
- `src/app/runs/[id]/plan/page.tsx` → `plan/PlanEditor` (waits for `plan_ready` via `useRunEvents` live)
- `src/app/runs/[id]/page.tsx` → `dashboard/Dashboard` (live) with pause/resume controls
- `src/app/runs/[id]/report/page.tsx` → `report/ReportView` + `report/PostDialog`
- `src/app/runs/[id]/replay/page.tsx` → `dashboard/Dashboard` (replay) + `dashboard/ReplayControls`

## Data flow
`EventSource` (useRunEvents) → `reduceEvent` → `DashboardState` → components. Replay loads the full log over the same SSE endpoint (`after=0`, closes on `done`), then re-emits on `ts` deltas / speed. Reconnect uses `after=lastSeq`; the reducer drops `seq <= lastSeq`.

## Conventions
- Native `<select>` for form selects (shadcn Select portals do not drive under jsdom).
- Tiles request `/api/runs/{id}/media/{post_id}/thumb.jpg` and fall back to a kind icon on error.
- `data-testid="tile-<post_id>"` and `data-state` on grid tiles are part of the e2e contract.
- Fixture event log: `src/lib/__fixtures__/run-events.ts` (builder) and `run-events.json` (regenerate with `bun run scripts/write-fixture-events.ts`).
```

- [ ] **Step 2: Root index and CI**

In root `AGENTS.md` Child DOX Index ensure the `frontend/` line reads `- frontend/ — Next.js 16 client; contracts in frontend/AGENTS.md`.

In `.github/workflows/check.yml` add after the existing check step:

```yaml
      - name: Playwright e2e (opt-in)
        if: ${{ env.RUN_E2E == '1' }}
        run: cd frontend && bunx playwright install --with-deps chromium && bun run e2e
```

- [ ] **Step 3: Full check**

Run from repo root: `bun run check`
Expected: schema drift check passes (types.ts unchanged), ultracite and ruff clean, `tsc --noEmit` clean, pytest and vitest green.

- [ ] **Step 4: Commit**

```bash
git add frontend/AGENTS.md AGENTS.md .github/workflows/check.yml
git commit -m "docs(frontend): complete DOX child, wire opt-in e2e in CI

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §9.1 routes: Tasks 6, 7, 8, 9, 10. §9.2 four regions: Task 8 (Counters six tiles; grid with dimmed/highlighted/outlined states; current item with per-question bars; aggregates for hook_type, format, persona_fit plus review bucket count and list). §9.3 transport: Task 5 (SSE with `after` reconnect; replay re-emits on ts deltas with speed). §9.4 i18n: Task 2. §10 API: Task 3 covers every endpoint except the media route, which is consumed as a URL in Task 8. §13 frontend tests: Vitest per component, one Playwright flow (Task 11). Pause/resume: Task 8.

**Placeholder scan.** None. Every step has code or an exact command.

**Type consistency.** `DashboardState` extends the contract with `lastSeq` and `startedAt` (additive). `PostView.state` and `PostTile.state` share the same six literals. `answerLabel` is defined in Task 8 and imported in Task 9. `SPEEDS` in Task 10 matches the e2e button names `16x`.

**Review Focus.** RF1 pinned by Task 4 `ignores duplicate or older events` and Task 5 live reconnect test. RF2 by Task 4 fixture, Task 8 PostGrid title test, Task 11 `新加坡人在上海的第一周` assertion. RF3 by Task 4 `marks judge_failed`. RF4 by Task 5 replay speed-change and pause tests. RF5 by Task 9 disabled-citation test.

## Contract decisions made (propagate to plans 01, 02, 03)

1. **Thumbnails:** the frontend requests `GET /api/runs/{id}/media/{post_id}/thumb.jpg` for every tile and falls back to an icon on 404. Plan 02's `fetch_media` should write `thumb.jpg` (first keyframe or first image, 256px wide) into `media_dir(post_id)`; plan 03's media route serves it. Post ids are URL-encoded (`local%3Afx-001`), so the route must decode the path segment.
2. **Fake mode seeds the local adapter:** Task 11 assumes `CLIPSIEVE_EXPLAIN_BACKEND=fake` also makes the `local` adapter return the five posts in `backend/tests/fixtures/posts` regardless of the brief, and that the planner returns `quantities: {local: 5}`. Plan 03's `get_context()` must do this.
3. **`DashboardState` gains `lastSeq: number` and `startedAt: string | null`** (additive to the overview type). `elapsed_s` before `done` is computed client-side from the first event's `ts`.
4. **Error-to-tile rule:** an `error` event with a `post_id` and `where` starting with `"judge"` marks that tile `judge_failed`. Plan 03 should emit `where: "judge.pass_two"` or `"judge.pass_one"` for per-post judge failures.
5. **Aggregates:** every `choice` answer in pass two is aggregated by label; `persona_fit` is aggregated by rounded level. The UI shows `hook_type`, `format`, `persona_fit`.
6. **Replay source:** replay loads the log through the same SSE endpoint with `after=0` and stops on `done` or a `failed`-stage event. No separate JSON log endpoint is needed. The SSE endpoint must therefore replay a finished run from seq 1 and then close, which matches the overview.
7. **Generated type names assumed from `packages/schema`:** `Post, PostText, Media, Metrics, Comment, Evidence, TranscriptSegment, OcrItem, CommentSummary, RunEvent, RunEventType, Stage, RubricPack, Plan, Brief, Query, Report, Pattern, ClipExplanation, Gap, Concept, JudgeResult, JudgeAnswer, Run, Counters`. Plan 01's TS generator must emit `$defs` as named exports with these names.
8. **Biome in the frontend** uses Biome 2 nested-config syntax `"extends": ["//"]`, which requires the root `biome.jsonc` from plan 01 to set `"root": true`. If plan 01 chooses a different mechanism, change `frontend/biome.jsonc` accordingly.
9. **Frontend package name** is `frontend` so the root `--filter frontend` scripts resolve.
