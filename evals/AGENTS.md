# evals — AGENTS.md

Inherits root AGENTS.md.

- `score.py` is pure Python importable with the repo root on `sys.path`; `sieve eval` loads it that way. Keep it free of FastAPI and frontend imports.
- Never call TypeSafe or Claude in tests. Use `RecordedJudge` and `IdentityTranslator`; `ClaudeCliTranslator` is tested only through its `argv()` and a patched `subprocess.run`.
- Golden files hold text evidence only. No media, no raw payloads, no unhashed creator ids. `golden/en-100.jsonl` and `golden/zh-100.jsonl` are committed as header-only placeholders (no datasets in the repo).
- Agreement rules (choice exact, score within one level of a 0-indexed answer mapped to a 1-based level, noul side of 0.5) are documented in README.md; change both together.
- `score_pack` judges every item with `pass_two` and all pack questions. A `JudgeFailed` item is skipped and counted (`n_skipped`), never fatal. `ClaudeCliTranslator` always runs with a subprocess timeout.
- `bilingual` mode reads `rubrics/<pack>.zh-examples.yaml` (owned by `rubrics/AGENTS.md`); `translate` mode rewrites only `post.title`, `post.caption`, `transcript[].text`, `ocr[].text` and `comments.sample[]`.
- `evals/ruff.toml` extends the backend ruff config; lint from `backend/` with `uv run ruff check ../evals && uv run ruff format --check ../evals`.
- Tests live in `backend/tests/evals/`; the sample golden set is `backend/tests/fixtures/golden/sample-5.jsonl`.

## Child DOX Index

None.
