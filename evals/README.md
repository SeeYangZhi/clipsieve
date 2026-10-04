# clipsieve evals

Measures how well a rubric pack's Jev answers agree with human labels, per question, in three language modes.

## Golden format

One JSON object per line in `evals/golden/<lang>-<n>.jsonl`:

- `post_id`: any stable id, usually `platform:id`.
- `state`: the Jev state in the shape `backend/clipsieve/evidence/packet.py::build_state` produces (`brief`, flat `post`, `transcript[].text`, `ocr[].text`, `comments`). It need not be byte-identical: the scorer reads only `post.title`, `post.caption` and the `text` fields (translate mode) and forwards the rest to the judge. Text evidence only, no media paths, creator ids already hashed.
- `labels`: `question_id -> label`. Choice: the label key. Score: 1-based level integer. Noul: `true`/`false`.

Lines starting with `#` are ignored.

## Labelling protocol

1. Pull 100 posts per language from a real run with `sieve export-golden RUN_ID --n 100 --lang zh` (plan 03 follow-up; until then copy `state` from `data/runs/<id>/evidence/` and `posts/`).
2. Two people label independently with the pack's criteria text in front of them. Disagreements are resolved by discussion; unresolved items are dropped.
3. Record the labelling date and the pack version in the file's first comment line.
4. Never commit media or raw platform payloads. States are text evidence only.

## Running

```bash
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode raw
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode translate
cd backend && uv run sieve eval --pack creator-hooks-v1 --golden ../evals/golden/zh-100.jsonl --mode bilingual
```

Each run prints a markdown table and rewrites its `### <golden stem> <mode> (<date>)` section inside the results block of `rubrics/<pack>.calibration.md` (other golden sets and modes are kept). A post whose judge call fails after retries is skipped and counted as `Skipped`. Agreement rules: choice exact match; score within one level (Jev score answers are 0-indexed; the predicted level is the argmax probability key, else the rounded value, minus the first legend key, plus one); noul correct when the probability is on the labelled side of 0.5.

## Modes

- `raw`: state sent as-is.
- `translate`: text fields translated to English with `claude -p` (cost reported separately). Tests the hypothesis that Jev's lower CJK accuracy is the bottleneck.
- `bilingual`: English criteria with Chinese examples from `rubrics/<pack>.zh-examples.yaml` appended. Tests whether grounding the rubric is enough without translating evidence.

Pick the winner per pack and set `language_mode` in the pack YAML.
