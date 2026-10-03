# backend/ — AGENTS.md

Python package `clipsieve`. Owns the whole pipeline: config, store, event log, adapters, evidence, judge, select, explain, API, CLI.

## Contract

- Python 3.12 only. `uv` for everything: `uv sync`, `uv run pytest`, `uv add`.
- `clipsieve/models.py` is GENERATED from `packages/schema/`. Never edit it. Run `bun run schema` at the repo root after changing a schema.
- Logging via `clipsieve.logging.get_logger(__name__)`. No `print()`.
- Config via `clipsieve.config.get_settings()`. Never read `os.environ` elsewhere.
- Files under `data/runs/<run_id>/` are canonical; SQLite is an index. Any write goes to the file first, then the row. `RunRepository.reindex` must be able to rebuild rows from files.
- Every stage emits `RunEvent`s through `clipsieve.events.writer.EventWriter`. Payload shapes are validated there; see the type table in `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`.
- `events.jsonl` is append-only, one writer per run. `EventWriter` terminates a partial last line left by a dead writer before appending (logs `events.repaired_partial_line`) and truncates a failed append. Readers parse bytes, hold back a trailing partial line silently, and log then skip corrupt complete lines (`events.skip_corrupt_line`). `follow_events` ends at the first terminal event (`done`, or stage `failed`) even when `after` filters it out.
- Tests in `tests/`, fixtures in `tests/fixtures/`. No network. Every external system has a fake.

## Layout

| Path | Owns |
|---|---|
| `clipsieve/config.py` | `Settings`, `get_settings()` |
| `clipsieve/logging.py` | structlog configuration |
| `clipsieve/models.py` | generated models (do not edit) |
| `clipsieve/store/` | `RunPaths`, SQLite engine and tables, `RunRepository` |
| `clipsieve/events/` | `EventWriter`, `read_events`, `follow_events` |
| `clipsieve/events/payloads.py` | `PAYLOAD_MODELS`, one Pydantic model per `RunEventType` |
| `clipsieve/select/select.py` | `Selection` model (plan 01); selection functions (plan 03) |

Later plans add `adapters/`, `evidence/`, `judge/`, `explain/`, `pipeline/`, `api/`, `cli.py` and extend this table.
