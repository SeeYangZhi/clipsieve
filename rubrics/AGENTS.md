# rubrics/ — AGENTS.md

Rubric packs are data, not code. A pack is a `<name>.yaml` here that loads with `clipsieve.judge.rubric.load_pack` (validated against `packages/schema/schemas/rubric_pack.json` plus the rules below). Other YAML in this folder, such as a `<pack>.zh-examples.yaml` sidecar, is not a pack: `pack_summaries` skips it (logs `rubric_pack_skipped`) and `find_pack` reports it as not a pack (`PackNotFound`).

## Contracts

- Question shapes are Jev's real primitives: `choice` with a `criteria` map, `score` with 2 to 10 written level descriptions, `noul` with instructions only. Never a numeric scale.
- `metadata_pass` lists question ids answerable from title, caption, hashtags, comments and metrics alone. Every id must exist in `questions`.
- Backticked paths in `instructions` and level text name real Jev state keys from `clipsieve.evidence.packet`: `brief.<field>`, the flat `post.<field>` (`post.title`, `post.caption`, `post.hashtags`, `post.kind`, `post.duration_s`, ...; never `post.text.*`), `transcript[i].text`, `ocr[i].text`, `comments`. `metadata_pass` questions may name only keys `build_metadata_state` produces (no `transcript`, no `ocr`). `tests/judge/test_rubric.py::test_rubric_paths_exist_in_jev_state` enforces this.
- `selection.weights` may reference only `score` and `noul` questions. `diversity` may reference only `choice` questions.
- `load_pack` rejects a pack that breaks the `metadata_pass`, `weights` or `diversity` rules above.
- `persona_fit` must be a 5-level `score`; the planner replaces its criteria per run.
- `jev_model` is pinned. Once a pack is calibrated, bump `version` when any question text changes; thresholds tuned on one version do not transfer.
- Each pack has a `<name>.calibration.md` written by `sieve eval`. A pack is "calibrated" only when that file says so.
- `sieve eval` writes only between the `<!-- results:start -->` / `<!-- results:end -->` markers, one `### <golden stem> <mode> (<date>)` section each; everything else in the file is hand-written.
- `<name>.zh-examples.yaml` (optional sidecar) holds Chinese examples that `evals/score.py` appends to the English criteria in `bilingual` mode: `question_id -> {label: phrase}` for choice, `question_id -> {1-based level: situation}` for score. Labels and levels not in the pack are ignored.

## Child DOX Index

None.
