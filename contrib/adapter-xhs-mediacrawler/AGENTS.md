# contrib/adapter-xhs-mediacrawler — AGENTS.md

Community adapter. Inherits the root AGENTS.md; these rules are additive.

## Disclaimer

Browser-session adapter. It drives the user's own logged-in Chrome through a local MediaCrawler checkout (NON-COMMERCIAL LEARNING LICENSE 1.1). It is not part of core, is not covered by clipsieve's Apache-2.0 grant for MediaCrawler itself, and the user is responsible for platform terms and applicable law. See `README.md`.

## Contract

- Registers `xiaohongshu = "clipsieve_xhs.adapter:XhsMediaCrawlerAdapter"` in entry point group `clipsieve.adapters`.
- **The core package never imports `clipsieve_xhs`.** If you need something from here in `backend/`, it belongs in the `Adapter` protocol instead.
- Never vendor MediaCrawler files. Drive the checkout at `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` as a subprocess (`runner.py`) and parse what it writes.
- Pinned MediaCrawler commit lives in `settings.py::PINNED_COMMIT` and in README step 1. Bump both together after re-running the fixture-based mapping tests against a real output sample.
- Settings: `XhsSettings` reads `(REPO_ROOT/.env, .env)` with `extra="ignore"` and `env_ignore_empty=True`; a relative `CLIPSIEVE_XHS_MEDIACRAWLER_DIR` resolves against `REPO_ROOT`. The CDP port is owned by core `Settings.clipsieve_xhs_chrome_cdp_port`; do not re-declare it here.
- `XhsMediaCrawlerAdapter.from_settings(settings)` is what the registry calls; the constructor's `runner`, `http`, `raw_dir`, `cache_dir` and `now` arguments exist for tests. `healthcheck` delegates to the runner.
- `search` runs MediaCrawler once per page (`--start 1, 2, ...`) per query, until `limit` posts are yielded or a page adds no new note; notes are deduped by id across pages and queries, and queries for other platforms are skipped. Each page is a full MediaCrawler run, so `limit` is the real cost control.
- Raw payloads go to `incoming_dir(data_dir, "xiaohongshu")/<safe_id>.json` as `{"note", "comments", "query"}`; `Post.raw_ref` is that absolute path and the core Runner relocates the file (overview B.1/B.10). Stored payloads drop comment `creator_hash`, `nickname`, `pictures` and the note's `xsec_token`; `Post.url` is token-free (query and fragment stripped); the `Post` is still mapped from the unstripped records in memory.
- Media URLs are cached by the adapter in `<data_dir>/adapter-cache/xiaohongshu/<safe_id>.media.json` as `{"urls": [...]}` (written by `search`, read by `media_urls_for`: memory first, then disk). `fetch_media` never reads the raw payload or `raw_ref` because the Runner relocates it first, so a second process can fetch media after a restart. A missing entry raises `MediaDownloadError` (imported from `clipsieve.adapters.base`, never redefined) before `dest` is created.
- `fetch_media` downloads with the adapter's `httpx.Client` (30 s timeout, `Referer: https://www.xiaohongshu.com/`, streamed to `<name>.part` then renamed) into `dest` as `video.mp4` (first cached URL; the rest are lower-quality streams) or `img_00.jpg`, `img_01.jpg`, ... (always `.jpg`, overview B.2); `Media.local_path` is dest-relative. Existing non-empty files are not re-downloaded. A non-2xx response or network error raises `MediaDownloadError`.
- `map_note` maps only what core `Comment` defines (`text`, `likes`; top 50 top-level comments by likes). Media entries carry type and index only; URLs come from `image_urls`/`video_urls` for the adapter's media cache.
- Mapping is table-driven in `mapping.py::FIELD_MAP`, the single override point: `adapter.py` reads note ids and types only through `mapping.note_id`/`note_type`, so `Post.id`, the raw file name and the media-cache key stay consistent. Unverified MediaCrawler details (date format in filenames, `tag_list` delimiter, `time` unit) are fixed there, not in logic.
- Tests never start MediaCrawler, Chrome or the network. `FakeRunner` in `tests/conftest.py` replays `tests/fixtures/mediacrawler-output/`; media downloads are mocked with `respx`. `tests/test_adapter.py` also runs the shared `backend/tests/adapters/contract.py::run_adapter_contract`, loaded by file path because `tests` is this package's test module name too.

## Layout

- `clipsieve_xhs/settings.py` env settings (`CLIPSIEVE_XHS_*`).
- `clipsieve_xhs/runner.py` argv, subprocess, healthcheck, output discovery.
- `clipsieve_xhs/mapping.py` MediaCrawler record -> `Post`.
- `clipsieve_xhs/adapter.py` the `Adapter` implementation, raw payload writer and media-URL cache.
- `tests/fixtures/mediacrawler-output/` three realistic notes and their comments.
- Lint: `pyproject.toml` extends `../../backend/pyproject.toml` (ruff `E F I UP B T20`, line length 100); `clipsieve` and `clipsieve_xhs` are one isort group. Run `uv run ruff check . && uv run ruff format --check .` here.
