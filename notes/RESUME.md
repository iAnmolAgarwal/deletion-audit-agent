# Resume point (updated 2026-10-25 ~04:50 IST)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status and the agent queue.
- `notes/DECISIONS.md`: T1–T79, every developer ruling.
- `notes/INTERFACES.md`: the pinned layout and interfaces. §7 is G5 (amendments T68–T77), §8 is GM (T76).
- `notes/SYSTEM.md`: how the system works, with the precedence list.
- `notes/ARCHITECTURE_OPTIONS.md`: G3. A+ was decided (T70).
- Verifier reports, all in `notes/verify/`:
  - `g4_verify.md`: G4, FIX;
  - `gp_verify.md`: GP, PASS;
  - `g4fix_verify.md`: G4 fix round 1, FIX;
  - `g4fix2_verify.md`: G4 fix round 2, FIX, waiting on the developer.
- `notes/gold_forensics.md`: G2, all done.

Scratchpad below means `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## State (04:50)
**Running** (cap 3, T79; never two of the same type):
- **GM:** `orch-builder`, medium; brief at scratchpad `gm_brief.md`.
- **G5:** `orch-builder-core`, high; brief at scratchpad `g5_brief.md`.

Both have directed_by 2026-10-25T04:39:02+05:30, and both started at 04:47. If either is cut, relaunch it with the same brief under the same directed_by and log an `[auto]` entry.

**On completion, check the agent's evidence:**
- re-run both test suites with `.venv/bin/python`;
- G5: the DEV score and flips against `g4fix2-baseline-final-20261025T0429`, then the 518-input replay numbers (0 crashes, 0 coherence violations, validator counts by part, FAILED_CLOSED count, runtime);
- GM: the lint output and the list of SDK 1.13.0 differences;
- then report and stop for the developer.

**Waiting on the developer:**
- The G4 round-2 fix class, in `notes/verify/g4fix2_verify.md`:
  - M1: a non-UTF-8 byte crashes `read_output`;
  - M2: `--prev` bypasses the run-ID check.
  The fix goes to `orch-eval-engineer`, then a fresh `orch-verifier` on that diff. After that, commit the G4 fix (`code/evaluation/**`).
- **T76 smoke call:** propose it with its cost before G7's routing check. It covers structured output, effort, a tool call and the reply cache, on `claude-sonnet-5-5` with `anthropic` 1.13.0.

**Commits this session (all pushed to `github`):** `351928b` G2, `2b7efe2` checker, `3163730` GP, `ce88703` G3/T70–T74, `d9ac31e` raw check, deps and T75–T79. `ce88703` carried a corrupted copy of this file, fixed in the next commit.

**Uncommitted:** `code/evaluation/**` (the G4 fix, waiting on its verifier). GM and G5 are writing under `code/` now.

**Environment:** `.venv/` holds anthropic 1.13.0, pdfplumber 0.11.10, ruff 0.17.0 and mypy 2.4.0. It was installed with `--uploaded-prior-to 2026-10-11T00:00:00Z`; see `requirements.lock`. The upstream cron `a94d194d` runs every 2 h at :07 (baseline origin/main `0eddbbd`).

## Rules in force that are easy to forget
- **Before any spawn,** check the brief has no line starting with `## [`. Example headers go in backticks (T64).
- **Every subagent brief carries:**
  - a `directed_by: <ts>` line;
  - the header shape in backticks (T45, T64);
  - a summary of 2–5 sentences;
  - one heredoc for the append;
  - a `check_log` run afterwards.
- **Verifier briefs** prove lock bypasses with synthetic files only (T48).
- **Main's log entries:** the header from `TZ=Asia/Kolkata date -Iseconds`, a title ≤ 80 characters, a summary of 2–5 sentences, detail in Actions. Record the pushed commit hash.
- **Commits** stage only the gate's own paths plus `log.txt` and `TASKS.md`. Push to `github`, never to `origin`.
- **Scripted edits:** chain each step with `&&`, and compute any slice positions after every replacement, never before (the `ce88703` corruption).
- **At any failure (T43):** give the hypothesis and the expected signal, then wait for the developer's confirm.
- **After any verifier, judge or code-review verdict:** stop for the developer's reply.
- **Holdout gold stays locked.** Never decode it.
- **Agent cap:** 3 at once (T79).
