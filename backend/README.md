# clipsieve backend

Python 3.12, FastAPI, uv.

    cd backend
    uv sync
    uv run pytest -q

## Module map

| Path | Role |
|---|---|
| `clipsieve/adapters/` | Platform adapters (`local`, `youtube`, fixture) behind one `Adapter` protocol |
| `clipsieve/evidence/` | ASR, OCR, frames and comments into text evidence and Jev state |
| `clipsieve/judge/` | Rubric packs to TypeSafe Jev requests; `TypeSafeJudge` and the `RecordedJudge` fake |
| `clipsieve/select/` | Pure scoring, diversity quotas, shortlist and pass-one keep |
| `clipsieve/explain/` | `ExplainBackend` (`claude -p`, API stub, fake): plan a brief, explain a shortlist |
| `clipsieve/planner/` | Brief to approvable `Plan` through an `ExplainBackend` |
| `clipsieve/pipeline/` | `Runner`: stage order, events, resume, pause, reselect |
| `clipsieve/api/` | FastAPI routes under `/api`, SSE event stream, `AppContext` |
| `clipsieve/cli.py` | `sieve` command: `run`, `replay`, `reselect`, `reindex`, `eval` stub |

See `AGENTS.md` for the contract of this directory.
