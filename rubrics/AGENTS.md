# rubrics/ — AGENTS.md

Rubric packs are data, not code. One YAML per pack, validated against `packages/schema/schemas/rubric_pack.json` via `clipsieve.judge.rubric.load_pack`.

## Contracts

- Question shapes are Jev's real primitives: `choice` with a `criteria` map, `score` with 2 to 10 written level descriptions, `noul` with instructions only. Never a numeric scale.
- `metadata_pass` lists question ids answerable from caption, hashtags, comments and metrics alone. Every id must exist in `questions`.
- `selection.weights` may reference only `score` and `noul` questions. `diversity` may reference only `choice` questions.
- `load_pack` rejects a pack that breaks the `metadata_pass`, `weights` or `diversity` rules above.
- `persona_fit` must be a 5-level `score`; the planner replaces its criteria per run.
- `jev_model` is pinned. Bump `version` when any question text changes; thresholds tuned on one version do not transfer.
- Each pack has a `<name>.calibration.md` written by `sieve eval`. A pack is "calibrated" only when that file says so.

## Child DOX Index

None.
