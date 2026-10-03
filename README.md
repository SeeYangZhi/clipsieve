# clipsieve

Sift thousands of social clips, reels, shorts and notes down to the few worth studying, then explain why they work.

clipsieve is a local-first research tool for creators and marketers. You describe what you are researching in a sentence. It turns that into search queries, collects posts from the platforms you tick, converts each one into text evidence (transcript, on-screen text, caption, comments, metrics), scores every post against a typed rubric with [Jev](https://typesafe.ai), keeps the top few percent with diversity across formats, and has Claude explain the patterns and draft concepts in your voice.

Status: plans 01 (schemas, run store, event log), 02 (adapters, evidence) and 03 (judge, select, explain, pipeline, API, CLI) are implemented; the frontend arrives with plan 04. See `docs/superpowers/specs/` for the v0.1 design and `docs/superpowers/plans/` for the implementation plans.

## Principles

- Local-first. Your data stays on your machine. Bring your own TypeSafe and Anthropic keys.
- Evidence first. Media becomes structured text with provenance before any model sees it.
- Typed judgments at scale, reasoning only on survivors. Jev answers fixed rubric questions on every post for cents; Claude reads only the shortlist.
- Policy in code. Weights, thresholds and selection are configuration you can change without re-running inference.
- Platform adapters behind one interface. Official-API and import adapters live here. Browser-session adapters live in `contrib/` with their own terms.

## Adapters

Built in: `local` (folder of media or a CSV export) and `youtube` (yt-dlp, Shorts under 180 s, auto-captions). Community adapters that drive a logged-in browser live in `contrib/` with their own terms. See `backend/AGENTS.md` for the adapter contract.

## Development

Requirements: Bun 1.3+, uv, Python 3.12 (uv installs it), ffmpeg.

    bun install && (cd backend && uv sync)   # once
    bun run dev                              # API on :8000, web on :3000
    bun run check                            # schema drift, lint, typecheck, tests


After editing anything in `packages/schema/schemas/`, run `bun run schema` and commit the regenerated `backend/clipsieve/models.py` and `frontend/src/lib/types.ts`.

## Running a fixture run (no keys, no network)

```bash
cd backend
CLIPSIEVE_EXPLAIN_BACKEND=fake uv run sieve run \
  --brief "Singaporean moving to Shanghai, vlog style" \
  --platforms local --limit 5 --pack creator-hooks-v1 \
  --data-dir /tmp/clipsieve-smoke --auto-approve
```

Fake mode wires every fake and reads fixtures from `backend/tests/fixtures`; set `CLIPSIEVE_FIXTURE_DIR` to point elsewhere. Then `uv run sieve replay <run_id> --speed 10 --data-dir /tmp/clipsieve-smoke` prints the event log at ten times speed. The dashboard reads runs only through the API, so it shows this run at `/runs/<run_id>/replay` (frontend from plan 04) only when the API uses the same data dir: start it with `CLIPSIEVE_DATA_DIR=/tmp/clipsieve-smoke bun run dev`, or leave out `--data-dir` above so the run lands in the default data dir.

To use real services, set `TYPESAFE_API_KEY` in `.env`, log in to Claude Code once (`claude` then `/login`), and run with `CLIPSIEVE_EXPLAIN_BACKEND=claude_cli`. The `claude_cli` backend is for your own Claude subscription; hosting clipsieve for others requires the API backend.

## Licence

Apache-2.0. See `LICENSE`.
