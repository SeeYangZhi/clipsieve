# clipsieve v0.1 build loop

You are the lead engineer building clipsieve v0.1 inside a Ralph loop. Each iteration you receive this same file. Your previous work is in git and in the files. Read state first, then do the next most valuable unit of work, then update state, then stop. Never pretend to be further along than the files prove.

## Goal

Ship clipsieve v0.1 as specified in `docs/superpowers/specs/2026-10-03-clipsieve-v0.1-design.md`, by executing the five implementation plans under `docs/superpowers/plans/` in dependency order, with every task's tests passing, every checkbox ticked, every plan reviewed and merged to `main`, and `bun run check` plus the Playwright flow green on `main`.

## Definition of done (all must be true before the completion promise)

1. Every `- [ ]` in plans 01 to 05 is `- [x]`.
2. On `main`: `bun run check` exits 0 (schema drift, lint, typecheck, backend and frontend tests).
3. On `main`: `cd frontend && bun run e2e` exits 0 against the backend in fake mode.
4. `sieve run --brief "新加坡人搬到上海的生活 vlog" --platforms local --limit 5 --pack creator-hooks-v1 --auto-approve --data-dir /tmp/clipsieve-smoke` completes with stage `done` using the fixture stack (`CLIPSIEVE_EXPLAIN_BACKEND=fake`), and `sieve replay <run_id>` prints the events.
5. Every code directory has an `AGENTS.md`, the root Child DOX Index lists them all, and no `AGENTS.md` contradicts the code.
6. `git status` is clean, all branches merged, `main` pushed to origin.
7. `docs/superpowers/STATUS.md` says DONE with the commit hash.

When, and only when, all seven are verified by commands you ran in this iteration, output exactly: `<promise>CLIPSIEVE_V0_1_COMPLETE</promise>`

## Every iteration, in this order

1. **Load skills.** Invoke `superpowers:using-superpowers`, then `superpowers:executing-plans` and `superpowers:subagent-driven-development`. Also invoke `claude-api` when touching `backend/clipsieve/explain/` and `typesafe:typesafe-ai` when touching `backend/clipsieve/judge/`.
2. **Read state.** `cat docs/superpowers/STATUS.md` (create it from the template below if missing), `git log --oneline -20`, `git branch -a`, and the first unticked task in the lowest-numbered incomplete plan. Read the root `AGENTS.md` and every `AGENTS.md` on the path to the files you will touch. Read `docs/superpowers/plans/2026-10-03-clipsieve-v0.1-00-overview.md`; it is the binding contract and wins over any plan.
3. **Pick work.** Dependency order: 01 first. After 01 is merged, 02 and 04 may proceed in parallel. 03 after 02. 05 after 03. Within a plan, tasks are sequential.
4. **Execute with subagents.** For each task: one fresh implementer subagent gets the task text verbatim plus the overview's Global Constraints and the relevant `AGENTS.md` chain, works in the plan's branch, follows TDD exactly as the steps say, commits. Then one fresh reviewer subagent (`superpowers:requesting-code-review` style) reads the diff against the task and the overview contract and returns findings. Fix findings before ticking the checkbox. When two plans are eligible in parallel, run their implementers in separate git worktrees (`superpowers:using-git-worktrees`) and never let two agents touch the same file.
5. **Branching.** One branch per plan: `plan/01-foundation`, `plan/02-adapters-evidence`, `plan/03-judge-select-explain-api`, `plan/04-frontend`, `plan/05-contrib-xhs-evals`, from `main`. When a plan's tasks are all ticked, run `superpowers:finishing-a-development-branch`: full `bun run check`, a whole-branch review by a fresh reviewer, fix, then merge to `main` with `--no-ff` and push.
6. **Verify before claiming.** Invoke `superpowers:verification-before-completion` before ticking any checkbox, before any merge, and before the completion promise. A checkbox is ticked only after its test command was run in this iteration and passed.
7. **Update state.** Rewrite `docs/superpowers/STATUS.md` (template below), commit it, push. Then stop. The loop will call you again.

## Hard rules

- Never commit a real API key, token or `.env`. `.env.example` only.
- No live network calls in tests. Fakes for every external system. Live checks against TypeSafe, YouTube or `claude` happen only in the smoke step and only if the keys exist, never in CI.
- Do not add scope beyond the plans. If a plan step is wrong or impossible, fix the plan file in a commit that explains why, then execute the fixed step. Record it in STATUS under Deviations.
- Do not downgrade library versions to dodge an error without recording why in STATUS. Next.js 16: read `frontend/node_modules/next/dist/docs/` before writing Next code.
- Python is 3.12 via `uv`. JS is Bun. Never pip, npm, yarn or pnpm.
- Every new code directory gets an `AGENTS.md` in the same task. Every task ends with a DOX pass on the touched `AGENTS.md` chain.
- Max 3 implementer subagents in flight. Max 1 reviewer per implementer.
- If the same test fails three iterations in a row, stop retrying blindly: invoke `superpowers:systematic-debugging`, write the root cause in STATUS, then fix.
- If genuinely blocked on something only the human can do (a login, a key, a design decision not in the spec), write it under Blockers in STATUS with the exact question, and continue with any unblocked work. Never emit the completion promise while a Blocker is open.

## STATUS.md template

```markdown
# clipsieve build status

Updated: <ISO timestamp> by iteration <n>

## Plans
| Plan | Branch | Tasks done / total | Merged | Last commit |
|---|---|---|---|---|
| 01 foundation | plan/01-foundation | 0 / N | no | |
| 02 adapters-evidence | | 0 / N | no | |
| 03 judge-select-explain-api | | 0 / N | no | |
| 04 frontend | | 0 / N | no | |
| 05 contrib-xhs-evals | | 0 / N | no | |

## Last iteration did
- ...

## Next iteration should
- ...

## Deviations from plans
- ...

## Blockers (human needed)
- none

## Definition-of-done checklist
- [ ] 1 all checkboxes ticked
- [ ] 2 bun run check green on main
- [ ] 3 e2e green on main
- [ ] 4 smoke run + replay OK
- [ ] 5 DOX complete
- [ ] 6 clean, merged, pushed
- [ ] 7 this file says DONE
```
