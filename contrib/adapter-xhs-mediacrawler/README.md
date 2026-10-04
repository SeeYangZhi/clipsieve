# clipsieve-adapter-xhs

Community Xiaohongshu (小红书) adapter for [clipsieve](../../README.md). By default it calls Xiaohongshu's web API with the cookies of your own logged-in browser (`CLIPSIEVE_XHS_RUNNER=api`); the fallback runner (`mediacrawler`) drives a **local checkout of [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)** in CDP mode. Either way it maps the notes and comments it collects into clipsieve `Post` records.

## Read this first

MediaCrawler is distributed under the **NON-COMMERCIAL LEARNING LICENSE 1.1**. Its README states (Chinese original, our translation): "本项目仅供学习和参考之用，禁止用于商业用途" — "This project is for learning and reference only; commercial use is prohibited" — and that it must not be used for any illegal purpose. By using this adapter you accept those terms for your MediaCrawler checkout.

clipsieve itself is Apache-2.0, but **this adapter does not change MediaCrawler's licence**. This package never copies MediaCrawler code; the fallback runner runs your checkout as a subprocess, and the api runner only follows the public wire format.

**You are responsible for compliance with Xiaohongshu's terms of service and the laws that apply to you**, including personal-data law (PIPL, GDPR). clipsieve hashes creator identifiers and caps stored comments, and MediaCrawler already anonymises creators in its output, but collecting content you are not permitted to collect is on you, not on the tools.

## Setup

1. Only for `CLIPSIEVE_XHS_RUNNER=mediacrawler`: clone MediaCrawler as a **sibling of the repo** (the default `CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler` is resolved against the clipsieve repo root, not your shell's cwd) and pin it to the commit this adapter was tested against:

   ```bash
   cd ..            # the directory that contains clipsieve/
   git clone https://github.com/NanmiCoder/MediaCrawler.git
   cd MediaCrawler && git checkout 380b426000aac3d612837ed72c99808347dc94c9
   uv sync && uv run playwright install
   ```

2. Required for both runners: start Chrome (or another Chromium) with remote debugging on the port clipsieve expects (default 9222) and log in to xiaohongshu.com in that Chrome:

   ```bash
   # macOS
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.clipsieve-chrome"
   ```

   The api runner reads the `a1` and `web_session` cookies from this browser over CDP; with the `mediacrawler` runner, on the first crawl MediaCrawler shows a QR code in that Chrome if you are not logged in. Scan it once; the session persists in that Chrome profile.

3. Optional settings in the repo-root `.env` (`CLIPSIEVE_XHS_RUNNER=api` is the default; the MediaCrawler lines apply only to the `mediacrawler` runner; the port is a core setting):

   ```text
   CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler
   CLIPSIEVE_XHS_CHROME_CDP_PORT=9222
   CLIPSIEVE_XHS_TIMEOUT_S=900
   ```

4. Install this adapter into the clipsieve backend environment so the core discovers it:

   ```bash
   cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler
   ```

   `GET /api/adapters` then lists `xiaohongshu` with its health. If health is false, the message says what is wrong: with the `api` runner, the browser on the CDP port or its xiaohongshu.com login; with `mediacrawler`, Chrome, the checkout or the pinned commit.

## How the api runner works

- Cookies come from your own logged-in Chromium through the Chrome DevTools Protocol on the configured port (`Storage.getCookies`). No credentials are stored; a missing `a1` or `web_session` cookie is a health failure telling you to log in to xiaohongshu.com in that browser.
- Requests go straight to `https://edith.xiaohongshu.com` over httpx, signed per request with [`xhshow`](https://github.com/cloxl/xhshow), with the `Origin`, `Referer` and `User-Agent` a browser tab sends.
- Search asks for `note_type=1` when `CLIPSIEVE_XHS_NOTE_KINDS=video` (server-side filter) and `CLIPSIEVE_XHS_PAGE_SIZE` notes (default 20). One search call is one page, so paging, dedupe, `limit` and `CLIPSIEVE_XHS_MAX_PAGES` behave as with the other runner. Each note needs one detail request for the video stream URL; comments are opt-in (`CLIPSIEVE_XHS_COMMENTS=1`) because they cost one more request per note.
- Records use the keys MediaCrawler writes, so the mapping, the raw-payload privacy stripping, the media-URL cache and media download are shared by both runners. Creator ids are hashed before they leave the runner; nicknames are not emitted.
- Requests are serial with a jittered interval (`CLIPSIEVE_XHS_REQUEST_INTERVAL_S`, default 1.0 s) and a short backoff on the platform's rate-limit codes. Login-expired, verification and exhausted-rate-limit responses end the run for this platform: the notes already collected on that page are kept, the dashboard shows `xiaohongshu search failed: xiaohongshu session halted: ...`, and no further request is sent. Open xiaohongshu.com in that browser, resolve the check, and start a new run; its health check reports the halt once and then clears it. Network errors (timeouts, connection failures) end the page with a recoverable error and are not retried.
- Every request carries the headers a browser tab sends (`Origin`, `Referer`, the browser's `User-Agent`, client hints, `Sec-Fetch-*`) and every header xhshow signs, including `x-rap-param`, which xhshow documents as required by the search and feed endpoints (not yet verified live).
- `code -104 您当前登录的账号没有权限访问` ("this account has no permission") is, per MediaCrawler's issue tracker, xiaohongshu's account-level risk control. On the one session observed so far it answered every request shape, including a byte-for-byte MediaCrawler replica, so it was not a signing problem there; it is reported to lift by itself after a while. The run stops for this platform with an error that says so (the notes already collected are kept); check that search works in the browser tab, then start a new run later. The smallest safe re-probe is `uv run python scripts/probe_api_runner.py "新加坡搬到上海" --search-only`: exactly one search request, no detail requests, counts only. Comments (`CLIPSIEVE_XHS_COMMENTS=1`) and the MediaCrawler runner (which always fetches comments) raise the request count per note and with it the chance of tripping it.

## Performance

Measured on 2026-10-04 with `scripts/probe_api_runner.py`, video-only (`CLIPSIEVE_XHS_NOTE_KINDS=video`), comments off, `CLIPSIEVE_XHS_REQUEST_INTERVAL_S=1.0`, Brave logged in on the CDP port, after the account's earlier `-104` restriction had lifted:

| Probe | Result |
|---|---|
| `--search-only` (1 request) | 22 items, `has_more` true |
| 1 page (`新加坡搬到上海`) | 20 notes, 20 videos, 0 errors, 20.5 s |
| 3 pages (`新加坡人 上海 vlog`) | 60 notes, 60 videos, 0 errors, 61 s (59 videos per minute); no rate-limit code |

Every note carried `video_url`, `note_url` with `xsec_token`, `title`, `desc`, `tag_list` and `time`, and mapped to a `Post` of kind `video`. Compared with the MediaCrawler runner on the same topic earlier that day (about 150 s per page of 20 notes, of which 2 to 7 were videos), that is roughly 20 times more videos per minute.

| | MediaCrawler runner | API runner (measured) |
|---|---|---|
| Requests per 20 videos | 1 browser crawl, all note types, ~150 s per page, 2 to 7 videos | 1 search + 20 detail calls, ~20 s |
| Video share per page | 30 to 50 % | 100 % |
| 60 videos collected | 25 to 50 min | 61 s |
| Comments | always | opt-in |

Evidence extraction (Whisper and OCR, two posts at a time) is now the slow stage: roughly one to two minutes per video on an Apple Silicon laptop.

The smallest safe re-probe after a restriction is `uv run python scripts/probe_api_runner.py "<keyword>" 1 --search-only` (one request), then one page without the flag.

## What it collects

Per note: title, caption (`desc`), hashtags (`tag_list`), likes, saves, comments count, shares, post time, image URLs or video URL, up to 50 top-level comments sorted by likes (api runner: only with `CLIPSIEVE_XHS_COMMENTS=1`), and the runner's record, in MediaCrawler's jsonl shape, as `raw_ref`. `creator_hash` is clipsieve's salted hash of the runner's creator hash (api runner: a SHA-256 of the user id; MediaCrawler: its already-anonymised `creator_hash`). The api runner emits no nicknames; MediaCrawler's are kept only as `creator_display`.

A cover thumbnail per collected post is fetched from the CDN at collection time.

## Video-only runs

Set `CLIPSIEVE_XHS_NOTE_KINDS=video` to keep only video notes. The api runner asks Xiaohongshu for video notes only; the pinned MediaCrawler cannot, so with `mediacrawler` image notes are discarded after the crawl and a video-only run needs more search pages per query. `CLIPSIEVE_XHS_MAX_PAGES` (default 10) bounds how many pages one query may crawl.

## Limits

- Search only (api runner: the search endpoint; MediaCrawler: `--type search`). Creator and detail modes are out of scope.
- The platform decides how many notes a search page yields (at most `CLIPSIEVE_XHS_PAGE_SIZE` with the api runner; MediaCrawler's own paging with the fallback); the adapter stops once `limit` posts are mapped and discards the rest.
- Media download is done by the adapter with plain HTTP GETs on the URLs in the record. Some CDN URLs expire; a failed download is reported as a recoverable error for that post.
