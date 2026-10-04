# Xiaohongshu API runner — design note (plan 06)

Status: accepted for implementation. Owner: contrib/adapter-xhs-mediacrawler.

## Problem

The v0.1 Xiaohongshu adapter drives a MediaCrawler checkout once per search page. Each page is a full
browser-driven crawl with built-in sleeps and per-note comment fetching: about 150 s for 20 notes, of
which only a third to a half are videos, and the pinned MediaCrawler always searches all note types.
A 20-video run spends 25 to 50 minutes collecting. The user wants many more videos, much faster.

## What exists (do not reinvent)

| Project | Author | Licence | Stars | What we take from it |
|---|---|---|---|---|
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | NanmiCoder | NON-COMMERCIAL LEARNING 1.1 | ~28k | The wire format of the web API (`/api/sns/web/v1/search/notes`, `/api/sns/web/v1/feed`, `/api/sns/web/v2/comment/page`), the record shape our mapping already consumes, and the fallback runner. Never copied, only referenced. |
| [xhshow](https://github.com/cloxl/xhshow) | Cloxl | MIT | — | Pure-Python `x-s` / `x-s-common` / `x-t` / `x-b3-traceid` signing. MediaCrawler at the pinned commit signs with it (`media_platform/xhs/playwright_sign.py`). We depend on it directly. |
| [xhs](https://github.com/ReaJason/xhs) | ReaJason | MIT | — | Endpoint catalogue and parameter names (`note_type` 0/1/2, `sort`, `page_size`). Not a runtime dependency: it expects a JS signer and brings more than we need. |
| [Spider_XHS](https://github.com/cv-cat/Spider_XHS) | cv-cat | see repo | — | Confirms search-by-type and the detail-call requirement for video URLs; its signing needs a local Node runtime, so it is reference only. |
| [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader) | JoeanAmier | GPL-3.0 | ~12k | Reference for watermark-free stream selection (`master_url` ranking by height and bitrate). |

Key fact: the web search API accepts `note_type=1` (video only). MediaCrawler's client supports the
parameter but its crawler never sets it, so the filter is one request field away once we call the API
ourselves.

## Decision

Add a second runner, `XhsApiRunner`, behind the existing `RunnerProtocol` in the contrib package.

- Cookies come from the user's own logged-in Chromium (Brave today) through the Chrome DevTools
  Protocol on the configured port (`Storage.getCookies`). No credentials are stored; a missing
  `a1`/`web_session` cookie is a health failure with a "log in to xiaohongshu.com in that browser"
  message.
- Requests go straight to `https://edith.xiaohongshu.com` over httpx, signed per request with
  `xhshow`, with the same `Origin`/`Referer`/`User-Agent` a browser tab sends.
- Search asks for `note_type=1` when `CLIPSIEVE_XHS_NOTE_KINDS=video` (server-side filter) and
  `page_size=20`. One `search()` call still means one page, so the adapter's paging, dedupe, `limit`
  and `max_pages` logic is unchanged.
- Each note needs one detail call (`/feed`) for the video stream URL, caption, tags and timestamps.
  Comments are opt-in (`CLIPSIEVE_XHS_COMMENTS=1`) because they cost one more request per note and the
  rubric only uses a comment summary.
- The runner emits records with the same keys MediaCrawler writes, so `mapping.py`, the raw-payload
  privacy stripping, the media-URL cache and `fetch_media` need no change. Creator ids are hashed
  before they leave the runner; nicknames are not emitted.
- Pacing is one request at a time with a jittered interval (default 1.0 s) and exponential backoff on
  the platform's rate-limit codes. Login-expired and verification responses stop the page with a
  recoverable error instead of hammering.
- `CLIPSIEVE_XHS_RUNNER=api|mediacrawler` selects the runner; `api` is the default. The MediaCrawler
  checkout becomes optional.

## Expected effect

| | MediaCrawler runner | API runner |
|---|---|---|
| Requests per 20 videos | 1 browser crawl, all note types, ~150 s | 1 search + 20 detail calls, ~25 to 35 s |
| Video share per page | 30 to 50 % | 100 % |
| 50 videos collected | 25 to 50 min | 2 to 3 min |
| Comments | always | opt-in |

Evidence extraction (Whisper and OCR, two posts at a time) then becomes the bottleneck: roughly one
to two minutes per video on this machine. That is out of scope here and is noted for a later plan.

## Risks

- The platform's signing and risk-control can change without notice. `xhshow` is the shared
  dependency the Chinese ecosystem tracks; pin a version and keep MediaCrawler as the fallback.
- A verification challenge (HTTP 461/471) or rate-limit code means the session is flagged. The runner
  surfaces it as a health or page error and never retries more than three times.
- Terms of service and personal-data law apply as before; the contrib README disclaimer covers both
  runners.

## Out of scope

Comments beyond the first page, creator or detail crawl modes, proxies, headless login, and faster
evidence extraction.
