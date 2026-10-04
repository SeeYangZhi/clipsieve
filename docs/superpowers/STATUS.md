# clipsieve v0.1 — STATUS: DONE

## Post-v0.1 work (2026-10-04)

- **Plan 06 — Xiaohongshu api runner** merged into main at 8f05bda and **live-verified on 2026-10-04** after the account's `-104` restriction lifted: search-only probe 22 items; one page 20 videos in 20.5 s; three pages 60 videos in 61 s (59 per minute, no rate-limit code); a dashboard run (`run_943026e699d9`, quantity 30) collected 30 videos in 42 s with zero errors and proceeded to extraction. Plan 06 is complete (`docs/superpowers/plans/2026-10-04-clipsieve-v0.2-06-xhs-api-runner.md`, design note `docs/superpowers/specs/2026-10-04-xhs-api-runner-design.md`). Evidence extraction (Whisper/OCR, two posts at a time) is now the slow stage.
- Known follow-ups recorded in the plan 06 ledger (deferred minors): hard-coded `Sec-CH-UA`/platform headers (derive from CDP version info), `x-rap-param` unverified live, the runner fetches every detail on a page the adapter may abandon.
- Fixes on main since v0.1: yt-dlp[default] + deno for YouTube extraction; dev reload limited to `clipsieve/`; SSE `: connected` comment and 15 s keepalive; post dialog from tiles and the review list with local media and the original link; `Post.url` keeps the Xiaohongshu share token; XHS video-only filter and page cap; MediaCrawler run from its checkout with `--save_data_path`.


**DONE at commit 5a9d816** (merge of plan/05-contrib-xhs-evals into main, 2026-10-04T03:40:14Z). All five plans are merged into `main` and all seven definition-of-done checks in KICKOFF.md passed in this iteration on `main` at 5a9d816:

1. Every `- [ ]` in plans 01-05 is ticked (0 unticked boxes in each of the five plan files).
2. `bun run check` exit 0 (schema drift clean, ruff + Biome clean, typecheck clean, backend 421 passed / 1 xfailed, frontend 117 passed).
3. `cd frontend && bun run e2e` exit 0 (1 passed) against the backend in fake mode.
4. `CLIPSIEVE_EXPLAIN_BACKEND=fake sieve run --brief "新加坡人搬到上海的生活 vlog" --platforms local --limit 5 --pack creator-hooks-v1 --auto-approve --data-dir /tmp/clipsieve-smoke` exit 0, final stage `done`; `sieve replay <run_id>` printed 27 events, first `run_created`, last `done`.
5. AGENTS.md present in backend/, frontend/, packages/schema/, rubrics/, evals/, contrib/adapter-xhs-mediacrawler/; the root Child DOX Index lists all six; each plan's whole-branch review sampled the docs against the code.
6. `git status` clean, `git branch --no-merged main` empty, `main` pushed to origin (5a9d816).
7. This file.

Updated: 2026-10-04T09:45:51Z — v0.1 DONE at 5a9d816; post-v0.1 work below

## Plans
| Plan | Branch | Tasks done / total | Merged | Last commit |
|---|---|---|---|---|
| 01 foundation | plan/01-foundation (merged, branch deleted locally) | 8 / 8 | yes (574e57d) | d7b28e8 |
| 02 adapters-evidence | plan/02-adapters-evidence (merged, branch deleted locally) | 12 / 12 | yes (7c3beb5) | 44206fc |
| 03 judge-select-explain-api | merged into main (2616c2d) | 12 / 12 | yes | 2616c2d |
| 04 frontend | merged into main (3273b2f) | 12 / 12 | yes | 3273b2f |
| 05 contrib-xhs-evals | merged into main (5a9d816) | 7 / 7 | yes | 5a9d816 |

## Iteration 5 did
- Plan 04 fix wave (7 fixes: pause intent + bounded re-poll, failed-run alert with the error message, planner-failure alert with start-over link, replay-mode Dashboard without the connection badge, back-to-run link, PostDialog title fallback, `compress: false` after CONFIRMING Next gzip buffered the live SSE stream) + scoped re-review clean. Plan 04 merged into main with --no-ff (3273b2f): on main 397 pytest passed, `bun run check` exit 0, `cd frontend && bun run e2e` 1 passed. Worktree removed.
- Plan 05 Tasks 1-7 complete, each reviewed and ticked (contrib skeleton, runner, mapping, adapter with persistent media-URL cache and privacy stripping, evals scorer, sieve eval + calibration writer, root docs/CI/lint coverage). Controller fixed an order-sensitive plan 03 runner test that flaked once. Main merged into the branch (root AGENTS.md index and check.yml conflicts resolved by keeping both sides). On the merged branch: backend 419 passed 1 xfailed, contrib 47 passed, `bun run check` exit 0. Whole-branch final review dispatched.

## Iteration 4 did
- Plan 04 Tasks 11 (Playwright e2e vs fake backend: 1 passed, re-run by controller) and 12 (DOX closeout, CI opt-in e2e gated on vars.RUN_E2E) complete and ticked. Whole-branch review: mergeable after fixes — pause button uses pre-transition run; failed run shows no reason; planner failure leaves plan page spinning; replay page shows reconnecting badge; Next gzip may buffer live SSE (verify, compress:false). Fix wave dispatched.
- Plan 05 pre-flight scan: 13 rulings recorded in its ledger (persistent XHS media-URL cache instead of Media.url; MediaDownloadError from adapters.base; XhsSettings env_file/REPO_ROOT; 0-indexed predicted_level; eval_cmd edited in place; calibration keyed by golden stem+mode; contract test offline via respx; raw comment identifiers stripped; table rows in root index; test counts). Plan text + overview Addendum C (C.2, C.8, C.12 amended; C.15-C.18 added) patched in 9bcd7b2. Task 1 dispatched.
- Plan 03 whole-branch review: mergeable after fixes (empty shortlist fails before explain; pack_summaries skips non-pack YAML and surfaces load errors; explain packet drops comments and caps text at 4000 chars; two doc fixes). Fix wave + scoped re-review clean. Overview Addendum E.14 records the behaviour changes for plans 04/05.
- Plan 03 merged into main with --no-ff (2616c2d); on main: 397 pytest passed, `bun run check` exit 0, DoD smoke `sieve run ... --data-dir /tmp/clipsieve-smoke` exit 0 stage done, `sieve replay` 27 events run_created..done. Main pushed. Plan 03 worktree removed.
- Plan 04: main merged into plan/04-frontend (85f91d7; conflicts in .env.example and root AGENTS.md index resolved); backend suite and `bun run check` green there. Task 11 (Playwright e2e vs fake backend) dispatched.
- Plan 05: worktree created from main; pre-flight scan dispatched (B.10/Media.url for XHS, MediaDownloadError import, zh-examples sidecar, eval stub options, entry-point discovery, offline tests).

## Iteration 3 did (cut short by usage limit)
- Plan 03 Tasks 11 (sieve CLI; DoD smoke passes in fake mode: exit 0, stage done, replay 27 events) and 12 (DOX closeout) implemented, reviewed, ticked. All 12 tasks ticked; suite 384 passed, 1 xfailed; `bun run check` exit 0 on the branch. Branch pushed at 7ed007c.
- Whole-branch final review (opus) was dispatched on 7c3beb5..8398639 but its verdict was NOT received before the usage limit. Next iteration: check the reviewer output transcript is unavailable to a fresh session, so RE-DISPATCH the final review from the package at `.worktrees/plan-03-judge-select-explain-api/.superpowers/sdd/2026-10-03-clipsieve-v0.1-03-judge-select-explain-api/review-7c3beb5..8398639.diff` (regenerate with review-package for merge-base..HEAD), run ONE fix wave + scoped re-review, then `bun run check`, merge `--no-ff` into main, verify main, push, remove the worktree.
- Then plan 04: merge main into plan/04-frontend, run Tasks 11 (Playwright e2e vs fake backend) and 12, final review, merge. Then plan 05 (new worktree from main; first reconcile B.10 for XHS via Media.url or run-keyed cache; MediaDownloadError from adapters.base; pack_summaries must skip non-pack YAML such as *.zh-examples.yaml).

## Iteration 2 did
- Plan 03 tasks 1-10 complete (rubric pack + judge/rubric.py, TypeSafeJudge with retries, RecordedJudge + fixtures, scoring, quotas/select, explain contract + fake + prompts, claude -p backend + shim, planner, pipeline Runner + FixtureAdapter, FastAPI app + SSE). Fix rounds on tasks 1, 2, 10. Backend suite 367 passed, 1 xfailed; `bun run check` exit 0 on the plan 03 branch.
- Overview gained Addenda E.11-E.13 (Runner emits run_created; where: planner error; SSE Last-Event-ID precedence; 409 cases; context built once under a lock). Plan 03 text patched: Task 5 quota cap rule; Tasks 10/11 no explicit run_created emit.
- Task 11 (sieve CLI incl. the definition-of-done smoke command in fake mode) dispatched; Task 12 (DOX closeout) next, then whole-branch review and merge; then plan 04 resumes (tasks 11-12) and plan 05 starts.

## Last iteration did (continued)
- Plan 02 complete: 12 tasks, fix rounds on tasks 3, 4, 5, 7, 12; whole-branch review found 1 Critical (local fetch_media read the relocated raw_ref) + 4 Important, all fixed in one wave and re-reviewed clean; merged --no-ff into main (7c3beb5); main `bun run check` exit 0 with 192 backend tests; pushed.
- Overview gained Addenda B.10-B.14 (fetch_media after raw relocation + contract helper relocates; shared MediaDownloadError in adapters/base; optional sidecar lang; Whisper hint normalisation + per-instance locks; state_json note).
- Plan 04: tasks 1-9 complete and ticked; task 10 (replay page) committed, review pending.
- Created plan 03 worktree from main 7c3beb5 with briefs for tasks 1-12.

## Last iteration did (earlier)
- Plan 01 complete: 8 tasks via fresh implementer + reviewer each, fix rounds on tasks 3, 6, 7; whole-branch review (opus) found 5 Important items, fixed in one wave and re-reviewed clean; merged --no-ff into main (574e57d); `bun run check` exit 0 on main (65 backend tests); pushed.
- Overview gained Addenda A.11-A.14 (repo-root .env/data_dir resolution, creator salt helper, optional-means-absent wire rule, shared test fixtures). Plan 03 failure path reordered (error first, stage_changed(failed) last).
- Created worktrees for plans 02 and 04 from main b349970; dispatched Task 1 implementers for both in parallel. Their reviews have NOT run yet.
- Plan 01 SDD ledger (all rulings and deferred minors) archived at the session scratchpad; summary below.

## Next iteration should
- For each of plan 02 and plan 04: check `git log` in the worktree for a Task 1 commit and the report at `.superpowers/sdd/<plan>/task-1-report.md`; dispatch the task reviewer (review-package b349970..HEAD), fix, tick, then continue tasks 2..12 sequentially per plan, running the two plans in parallel.
- Plan 03 running (task 1 dispatched). Plan 04 is paused after task 10: tasks 11 (Playwright vs fake backend) and 12 need plan 03 merged; then merge main into plan/04-frontend (expect small conflicts in root AGENTS.md index and README) and finish plan 04. Plan 05 after plan 03.
- Plan 05 note: the XHS fetch_media sketch reads the incoming raw file, which conflicts with B.10 (Runner relocates raw before fetch_media); Media has no url field. Reconcile before executing plan 05 (add Media.url to the schema or a run-keyed cache) and import MediaDownloadError from adapters.base (B.11).
- Plan 03 notes: call `ensure_creator_salt` in build_context and CLI (A.12); API routes use `response_model_exclude_none=True` (A.13); test near plan line 2435 must use `payload.get("post_id")`; explain failure emits error before stage_changed(failed).
- Plan 04 notes: biome.jsonc schema 2.5.15 and ultracite/biome/react + next presets; treat JSON null as absent defensively; `frontend/node_modules/next/dist/docs/` may be hoisted to root `node_modules/`.

## Deviations from plans
- Plan 01 Task 1: placeholder packages/schema/package.json (5c11bf4); biome.jsonc extends ultracite/biome/core, schema 2.5.15 (b5a3467).
- Plan 01 Task 3: named $defs.Question (plain union alias), --use-annotated, ignoreMinAndMaxItems; enums StrEnum; AwareDatetime (9fd80d1, de70f99).
- Plan 01 Task 6: index timestamps normalised to UTC; save_run/save_judge_result re-validate (63473a1).
- Plan 01 Task 7: readers parse bytes; writer repairs partial tail, truncates failed appends; follow_events checks terminal on filtered events (cad7a29).
- Plan 01 final review: config resolves .env/data_dir from repo root; ensure_creator_salt; exclude_none everywhere; shared conftest fixtures; autouse structlog reset (d7b28e8; overview A.11-A.14).
- Plan 03 text patched: explain-failure event order (f45ead1).
- Task 8 of plan 01 did not push to main directly; merge carried it.
- Deferred minors (not blocking v0.1): reindex rewrites files / ghost rows / shallow revalidate; shared .tmp name per path; no SQLite WAL; no reindex_all; CI permissions block; ruff does not lint packages/schema/*.py; test_get_settings_is_cached reads a real root .env if present; ~ not expanded in CLIPSIEVE_DATA_DIR; salt file O_TRUNC race.

## Blockers (human needed)
- none

## Definition-of-done checklist
- [ ] 1 all checkboxes ticked (plan 01: 67/67; plans 02-05: 0)
- [ ] 2 bun run check green on main (true at b349970, but plans 02-05 not yet merged)
- [ ] 3 e2e green on main
- [ ] 4 smoke run + replay OK
- [ ] 5 DOX complete
- [ ] 6 clean, merged, pushed
- [ ] 7 this file says DONE
