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
- Media URLs are cached by the adapter in `<data_dir>/adapter-cache/xiaohongshu/<safe_id>.media.json` (written by `search`, read by `fetch_media`); `fetch_media` never reads the raw payload because the Runner relocates it first. A missing entry raises `MediaDownloadError` (imported from `clipsieve.adapters.base`).
- Stored raw payloads drop comment `creator_hash`, `nickname`, `pictures` and the note's `xsec_token`.
- `map_note` maps only what core `Comment` defines (`text`, `likes`; top 50 top-level comments by likes). Media entries carry type and index only; URLs come from `image_urls`/`video_urls` for the adapter's media cache.
- Mapping is table-driven in `mapping.py::FIELD_MAP`. Unverified MediaCrawler details (date format in filenames, `tag_list` delimiter, `time` unit) are fixed there, not in logic.
- Tests never start MediaCrawler or Chrome. `FakeRunner` in `tests/conftest.py` replays `tests/fixtures/mediacrawler-output/`.

## Layout

- `clipsieve_xhs/settings.py` env settings (`CLIPSIEVE_XHS_*`).
- `clipsieve_xhs/runner.py` argv, subprocess, healthcheck, output discovery.
- `clipsieve_xhs/mapping.py` MediaCrawler record -> `Post`.
- `clipsieve_xhs/adapter.py` the `Adapter` implementation, raw payload writer and media-URL cache.
- `tests/fixtures/mediacrawler-output/` three realistic notes and their comments.
