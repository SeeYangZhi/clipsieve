# clipsieve

Sift thousands of social clips, reels, shorts and notes down to the few worth studying, then explain why they work.

clipsieve is a local-first research tool for creators and marketers. You describe what you are researching in a sentence. It turns that into search queries, collects posts from the platforms you tick, converts each one into text evidence (transcript, on-screen text, caption, comments, metrics), scores every post against a typed rubric with [Jev](https://typesafe.ai), keeps the top few percent with diversity across formats, and has Claude explain the patterns and draft concepts in your voice.

Status: design stage. See `docs/superpowers/specs/` for the v0.1 design and `docs/superpowers/plans/` for the implementation plan.

## Principles

- Local-first. Your data stays on your machine. Bring your own TypeSafe and Anthropic keys.
- Evidence first. Media becomes structured text with provenance before any model sees it.
- Typed judgments at scale, reasoning only on survivors. Jev answers fixed rubric questions on every post for cents; Claude reads only the shortlist.
- Policy in code. Weights, thresholds and selection are configuration you can change without re-running inference.
- Platform adapters behind one interface. Official-API and import adapters live here. Browser-session adapters live in `contrib/` with their own terms.

## Development

Requirements: Bun 1.3+, uv, Python 3.12 (uv installs it), ffmpeg.

    bun install && (cd backend && uv sync)   # once
    bun run dev                              # API on :8000, web on :3000
    bun run check                            # schema drift, lint, typecheck, tests

After editing anything in `packages/schema/schemas/`, run `bun run schema` and commit the regenerated `backend/clipsieve/models.py` and `frontend/src/lib/types.ts`.

## Licence

Apache-2.0. See `LICENSE`.
