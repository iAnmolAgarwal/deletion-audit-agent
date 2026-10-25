# Resume point (updated 2026-10-25 ~07:00 IST, paused under T98)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status, the agent queue, the G9 list and the freeze checks.
- `notes/DECISIONS.md`: T1–T98, every developer ruling.
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
  | `g5_verify.md` | G5 | FIX (5 MAJOR, 0 BLOCKER); fix round 1 done and uncommitted; its verifier waits for resume |

- Agent reports in `notes/agent_reports/`: `g8_redteam.md`, `holdout_build.md`, `g5_fix1.md`.

Scratchpad below means `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

**PAUSED (T98) until the developer resumes at about 10:00.** No subagent is running, and no paid call has been made since the smoke call.

**Start here: `notes/HANDOFF.md`.** It has:
- the 25-line summary;
- each finished agent with main's checks;
- what is committed and uncommitted;
- the queue from resume with what each step needs;
- the spend;
- decisions A–F with recommendations.

**At resume, in order:**
0. Decision A: the agent-test patch.
1. The G5 fix-round verifier (T90; on its verdict, T93).
2. The G5 commit, with the §7.1 additions.
3. The pipeline unlock (main; Decision C).
4. The G7 wiring (`orch-builder-core`, high; a one-line OK).
5. The G7 verifier (T92).
6. Routing stage 1 plus vision (T97; Decision B).
7. Stage 2.
8. The mode-A run (Decision F first).
9. The G8 engine run (Decisions D and E).
10. The A+ full run (its cost).
11. G9.
12. G10.

**Last commits:** `73c2309` (the holdout build), `5f4d2f6` (the G8 fixtures), then the handoff commit.

**Spend:** $0.004964 (ledger).

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
