# clipsieve — Root AGENTS.md

clipsieve is a local-first social media research tool. A one-sentence brief becomes search queries, collected posts, text evidence, typed Jev scores on every post, a diverse shortlist, and a Claude report explaining why the shortlist works.

## DOX framework

This repo uses the [DOX](https://github.com/agent0ai/dox) AGENTS.md hierarchy.

- `AGENTS.md` files are binding contracts for their subtree.
- Read the chain from the root down to every path you touch BEFORE editing.
- Closer doc wins on local details; child docs must not weaken root rules.
- Every meaningful change requires a DOX pass: update the closest owning doc and any affected parents.

### Read Before Editing

1. Read this root AGENTS.md.
2. Walk from the repo root to each target path; read every AGENTS.md along the way.
3. Use the nearest AGENTS.md as the local contract; parent docs for repo-wide rules.
4. If docs conflict, the closer doc controls local details. No child doc may weaken the root.

### Update After Editing

Update the closest owning AGENTS.md when a change affects purpose, scope, ownership, durable structure, contracts, workflows, required inputs or outputs, constraints, or the AGENTS.md tree itself. Update parents when parent-level structure or the child index changes. Remove stale or contradictory text immediately.

### Style

Concise, current, operational. Document stable contracts, not diary entries. Broad rules in parents, concrete details in children. Delete stale notes instead of explaining history.

## Product North Star

One real brief produces a report the user acts on. Platform count, speed and cost are secondary to that.

Authoritative design: `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md`.
Implementation plan: `docs/superpowers/plans/`.

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLite via SQLModel, structlog, Pydantic Settings |
| Evidence | yt-dlp, ffmpeg, mlx-whisper (Apple Silicon) / faster-whisper, PaddleOCR |
| Judge | TypeSafe Jev via `typesafe-sdk`, model version pinned per rubric pack |
| Explain | `claude -p` (default), Claude API (later), behind one `ExplainBackend` interface |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4, shadcn/ui, lucide |
| Lint/format | ultracite (Biome) for TS, ruff for Python |
| Package mgrs | `uv` (Python), Bun (JS). Not pip, not npm, not pnpm |
| Contracts | `packages/schema/` JSON Schema -> generated Pydantic models and TS types |

## Coding Rules (repo-wide)

- `uv` for all Python dependency and command execution. Bun for all JS.
- `structlog` for backend logging. No `print()` in app code. The one exception is the `cli.py` output helpers `_say` and `_json`.
- Pydantic Settings for configuration. Secrets only in local `.env`. Keep `.env.example` current. Never commit keys.
- Every external system sits behind a small interface with a fake: adapters, Jev client, explain backend, ASR, OCR.
- Persist raw platform payloads before normalisation. Every `Post` carries a `raw_ref`.
- Every pipeline stage appends typed `RunEvent`s to the run's JSONL log. The log is the source of truth for live view, replay and resume.
- Jev questions use the real primitive shapes: Choice with a criteria map, Score with written level descriptions, Noul. Never a numeric scale. Batch every question for one post into one request.
- Policy (weights, thresholds, quotas) lives in rubric pack YAML and plain code, never in a model prompt.
- Core never imports browser-session adapters. They are discovered as plugins and live in `contrib/` with their own AGENTS.md and disclaimer.
- Hash creator identifiers at ingest. Store comment text only when a rubric question needs it. No datasets in the repo.

## Frontend Rules (repo-wide)

- Next.js 16 differs from training data. Check `frontend/node_modules/next/dist/docs/` before writing Next code.
- shadcn-first for UI primitives. lucide for icons. No nested cards.
- Frontend talks to the backend only through `/api/*` (Next rewrite to FastAPI) and the SSE event stream. It never reads run files directly.
- UI strings in English and Chinese from day one.

## Child DOX Index

| Path | Owns |
|---|---|
| `backend/AGENTS.md` | Python package `clipsieve`: config, logging, store, events (plan 01); adapters, evidence (plan 02); judge, select, explain, pipeline, API, CLI (plan 03) |
| `packages/schema/AGENTS.md` | JSON Schemas and the two generators |
| `rubrics/AGENTS.md` | Rubric pack YAML (`creator-hooks-v1`) and per-pack calibration notes |
| `frontend/AGENTS.md` | Next.js client: `/api/*` rewrite, SSE, shadcn UI, Vitest/Playwright, Next 16 notes (plan 04) |

`contrib/adapter-xhs-mediacrawler/` and `evals/` get their AGENTS.md when plan 05 creates them.
