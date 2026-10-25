# Resume point (updated 2026-10-25 ~06:18 IST)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status, the agent queue, the G9 list and the freeze checks.
- `notes/DECISIONS.md`: T1–T97, every developer ruling.
- `notes/INTERFACES.md`:
  - §7 is G5's engine, amended by T68–T77; §7.1 holds its **as-built signatures**, accepted under T87.
  - §8 is GM's model client.
- `notes/SYSTEM.md`: how the system works.
- `notes/ARCHITECTURE_OPTIONS.md`: G3. A+ in text-first routing form was decided (T70).
- Verifier reports in `notes/verify/`:

  | Report | Gate | Verdict |
  |---|---|---|
  | `g4_verify.md`, `g4fix_verify.md`, `g4fix2_verify.md`, `g4fix3_verify.md` | G4 | FIX, FIX, FIX, then PASS |
  | `gp_verify.md` | GP | PASS |
  | `gm_verify.md`, `gm2_verify.md` | GM | FIX, then PASS |
  | `g5_verify.md` | G5 | FIX (5 MAJOR, 0 BLOCKER); fix round approved (T90) |

Scratchpad below means `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## State (06:18)
**Committed and pushed to `github`:** everything through `d58f22f`:
- `8bce1e1`: the log fix (T89) and the G5 verifier report;
- `d58f22f`: T90 and T91, and the smoke result.

**Uncommitted, waiting for review:**
- G5's engine and tests (the paths in TASKS.md). The fix round comes first (T90).
- G7b's files: `code/evaluation/{agent_report.py, freeze_check.py}` and `code/evaluation/tests/{run_dirs.py, test_agent_report.py, test_freeze_check.py}`. Checked by main: 187 tests OK.
- The GM error-text change: `model/{transport, policy, calllog, client}.py` and `tests/model/test_api_error_text.py`. Checked by main: model 81 and all 273 OK.
- `code/evaluation/NUMBERS.md`: the scorer-hash note (T92).
- Both G7b and the GM change wait for the G7 verifier.

**Running:**
- The G5 fix round: `orch-builder-core`, high, directed_by 2026-10-25T06:08:27+05:30, brief at scratchpad `g5fix_brief.md`, since about 06:52. On its verdict, T93 applies.
- The holdout run build: `orch-eval-engineer`, high, directed_by 2026-10-25T06:32:14+05:30, brief `holdout_run_brief.md` (T96). Afterwards, main adds `holdout_unlock` to `pipeline.py` with the engine-guard tests, after G5 commits.
- (Done: G7a, about 06:50, checked by main and uncommitted until the G7 verifier. Its wiring proposals and screenshot risks are on TASKS.md.)
- G8 red team: `orch-redteam`, high, directed_by 2026-10-25T06:18:59+05:30, brief at scratchpad `g8_redteam_brief.md`. On completion, check the fixtures, then commit `code/tests/fixtures/redteam/` before any engine run.
- (Done: the GP ruff cleanup, committed `447818a`, with all three baselines unchanged.)

**Order (T90/T92), each step after the one before:**
1. (Done.) G7a finished and was checked; its wiring proposals are on TASKS.md.
2. The G5 fix round (running since about 06:52): `orch-builder-core`, high, directed_by 2026-10-25T06:08:27+05:30. The brief is at scratchpad `g5fix_brief.md`, and the repros at `g5fix_repros/`. It keeps T69 and adds the new fail-closed rule for records that cannot be interpreted.
3. A fresh verifier on that diff. **T93:** if it returns PASS or only findings below BLOCKER, commit G5 without waiting and put those findings on the G9 list. A BLOCKER stops for the developer's reply.
4. G7a's wiring into `pipeline.py` and `artifacts.py`. `committed_key`/`final_key` must compare intent labels (T92). The `evaluation_report.md` generator embeds the tool histogram and the on vs off sections for the fixtures and differing test rows (T95 C2). G7a was sent T95 C4 (the code-side injection flag merged with the model's) and C1 (prompt files and tool descriptions) at 06:24.
5. The G7 verifier: `orch-verifier`, high, directed_by 2026-10-25T06:15:34+05:30. Scope: G7a, G7b, the GM change and G7b's four details.
6. The routing check and vision (approved, T97). Stage 1 is DEV and the fixtures, plus vision: $5 and 130 sends. Then stop and show the results, with a re-projection of the A+ full run from measured sizes; above $80, caching comes back for a ruling. Stage 2 is the 375 test texts, twice: $20 and 820 sends.
7. The mode-A run on all 518 test cases from cached replies (loop cap $3), written to `runs/` only, with its path and sha256 given to the developer.
8. The backup-screenshot rule (case_55's `backup_9287`; `evidence_32`, the only backup evidence before its audit_at), ruled when the readings are in.

**Paid calls so far:** smoke `smoke-t76-20261025T0612` passed on anthropic 1.13.0 (T91). It cost $0.004964, which is the ledger total. The earlier 400 was the key's scope; `.env` now holds a workspace-scoped key.

**Key numbers:**
- **G5 DEV** (`g5-dev22-20261025T0530`): 22/22 status, 19/22 exact.
- **G5 test** (`g5-test-20261025T0530`): 518 rows, 18 FAILED_CLOSED. The freeze check refuses it: 18 FAILED_CLOSED and 11 skips.
- **Scorer hash:** it changed when G7b added two modules (NUMBERS.md note).

**Environment:**
- `.venv/` (anthropic 1.13.0).
- Lint: `bash scripts/lint.sh <paths>`.
- The log guard lives in the kit at `../hooks/log_guard.py`, with its tests in `../hooks/test_log_guard.py`. It skips summarizer sessions (T89).
- Upstream cron `a94d194d`.

## Rules in force that are easy to forget
- **Before any spawn or message to an agent,** check the brief has no line starting with `## [`. Example headers go in backticks (T64).
- **Every subagent brief carries:**
  - a `directed_by: <ts>` line, taken from the `.claude/.log_guard_turn` mtime;
  - the header shape in backticks;
  - a summary of 2–5 sentences;
  - one heredoc for the append;
  - a `check_log` run afterwards.
- **Verifier briefs** prove lock bypasses with synthetic files only (T48).
- **Main's log entries:** the header from `TZ=Asia/Kolkata date -Iseconds`, a title ≤ 80 characters, **a summary of 2–5 sentences** (main went over on 05:16 and 05:34), detail in Actions. Record the pushed commit hash.
- **Commits** stage only the gate's own paths plus `log.txt` and `TASKS.md`. Push to `github`, never to `origin`.
- **Scripted edits:** chain each step with `&&`; take slice positions after every replacement, never before.
- **At any failure (T43):** give the hypothesis and the expected signal, then wait for the developer's confirm.
- **After any verifier, judge or code-review verdict:** stop for the developer's reply. Review rounds are capped at 3; after that, non-BLOCKER findings go to the G9 list.
- **Paid calls:** only with the developer's approval and a stated cost. Never print `.env`.
- **Holdout gold stays locked.** Never decode it.
- **Agent cap:** 3 at once (T79), never two of the same type.
