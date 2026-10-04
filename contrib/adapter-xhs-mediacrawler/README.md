# clipsieve-adapter-xhs

Community Xiaohongshu (小红书) adapter for [clipsieve](../../README.md). It drives a **local checkout of [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)** in CDP mode against your own logged-in Chrome, then maps the notes and comments MediaCrawler writes into clipsieve `Post` records.

## Read this first

MediaCrawler is distributed under the **NON-COMMERCIAL LEARNING LICENSE 1.1**. Its README states (Chinese original, our translation): "本项目仅供学习和参考之用，禁止用于商业用途" — "This project is for learning and reference only; commercial use is prohibited" — and that it must not be used for any illegal purpose. By using this adapter you accept those terms for your MediaCrawler checkout.

clipsieve itself is Apache-2.0, but **this adapter does not change MediaCrawler's licence**. This package never copies MediaCrawler code; it runs your checkout as a subprocess.

**You are responsible for compliance with Xiaohongshu's terms of service and the laws that apply to you**, including personal-data law (PIPL, GDPR). clipsieve hashes creator identifiers and caps stored comments, and MediaCrawler already anonymises creators in its output, but collecting content you are not permitted to collect is on you, not on the tools.

## Setup

1. Clone MediaCrawler as a **sibling of the repo** (the default `CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler` is resolved against the clipsieve repo root, not your shell's cwd) and pin it to the commit this adapter was tested against:

   ```bash
   cd ..            # the directory that contains clipsieve/
   git clone https://github.com/NanmiCoder/MediaCrawler.git
   cd MediaCrawler && git checkout 380b426000aac3d612837ed72c99808347dc94c9
   uv sync && uv run playwright install
   ```

2. Start Chrome with remote debugging on the port clipsieve expects (default 9222) and log in to xiaohongshu.com in that Chrome:

   ```bash
   # macOS
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.clipsieve-chrome"
   ```

   On the first crawl MediaCrawler shows a QR code in that Chrome if you are not logged in. Scan it once; the session persists in that Chrome profile.

3. Point clipsieve at the checkout in the repo-root `.env` (the first two lines are the shipped defaults; the port is a core setting):

   ```text
   CLIPSIEVE_XHS_MEDIACRAWLER_DIR=../MediaCrawler
   CLIPSIEVE_XHS_CHROME_CDP_PORT=9222
   CLIPSIEVE_XHS_TIMEOUT_S=900
   ```

4. Install this adapter into the clipsieve backend environment so the core discovers it:

   ```bash
   cd backend && uv pip install -e ../contrib/adapter-xhs-mediacrawler
   ```

   `GET /api/adapters` then lists `xiaohongshu` with its health. If health is false, the message says which of Chrome, the checkout or the pinned commit is wrong.

## What it collects

Per note: title, caption (`desc`), hashtags (`tag_list`), likes, saves, comments count, shares, post time, image URLs or video URL, up to 50 top-level comments sorted by likes, and the untouched MediaCrawler record as `raw_ref`. `creator_hash` is clipsieve's salted hash of MediaCrawler's already-anonymised `creator_hash`. Nicknames are kept only as `creator_display`.

## Video-only runs

Set `CLIPSIEVE_XHS_NOTE_KINDS=video` to keep only video notes. The pinned MediaCrawler cannot ask Xiaohongshu for videos only, so image notes are discarded after the crawl and a video-only run needs more search pages per query. `CLIPSIEVE_XHS_MAX_PAGES` (default 5) bounds how many pages one query may crawl.

## Limits

- Search only (`--type search`). Creator and detail modes are out of scope.
- MediaCrawler decides how many notes a search page yields; the adapter stops once `limit` posts are mapped and discards the rest.
- Media download is done by the adapter with plain HTTP GETs on the URLs in the record. Some CDN URLs expire; a failed download is reported as a recoverable error for that post.
