# Resume point (updated 2026-10-25 ~04:36 IST, after the resume)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status and the agent queue.
- `notes/DECISIONS.md`: T1–T74, every developer ruling.
- `notes/INTERFACES.md`: the pinned layout and interfaces.
- `notes/SYSTEM.md`: how the system works, with the precedence list.
- `notes/verify/g4_verify.md`: the G4 verifier report. `notes/verify/gp_verify.md`: the GP verifier, **PASS** (accepted by the developer).
- `notes/gold_forensics.md`: G2, all done.
- `log.txt`: the 03:27 pause entry quotes the developer's 03:22 and pause messages verbatim.

Scratchpad below means `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## State at pause
**Agents left running** (T44 cap: 2):
- **G3: finished during the pause.** It wrote `notes/ARCHITECTURE_## State (04:36)
**Done since the resume:**
- T64–T74 recorded.
- The checker fix is committed (`2b7efe2`), and GP is committed (`3163730`).
- INTERFACES has rule 8 and new sections §7 (G5) and §8 (GM).
- The upstream cron is re-created (`a94d194d`, every 2 h at :07); upstream is unchanged.
- The architecture is decided: A+ (T70).

**Running:** `orch-verifier` on the G4 fix round-2 diff (directed_by 2026-10-25T04:24:24+05:30; brief in scratchpad `g4fix2_verifier_brief.md`; it reports to `notes/verify/g4fix2_verify.md`). On PASS and the developer's reply: commit the G4 fix (`code/evaluation/**`, `notes/verify/g4fix*_verify.md`).

**Waiting on the developer:**
1. **Approval of GM and G5** (proposed together at 04:36).
2. **T73:** the `anthropic` version, 1.13.0 (meets the two-week rule; API version 2023-06-01) or an exception for 2.3.0.
3. **T74:** the hard-check reading for empty verifications in INCOMPLETE rows.
4. **T43:** the raw-check equality change. It reports 21 problems, which main diagnoses as `integrity_seal` hashes. The proposed fix counts a hash only when it is a known person's email hash. Expected signal: 21 → 0, with both over-attribution mutations caught. `code/tests/evidence/raw_check.py` is modified but not committed; the 21-problem report is in scratchpad `parser_raw_check.strict21.md`; the committed report is restored.

e headers go in backticks (T64).
- **Every subagent brief carries:**
  - a `directed_by: <ts>` line;
  - the literal header in backticks (T45, T64);
  - a summary of 2–5 sentences;
  - one heredoc for the append;
  - a `check_log` run afterwards.
- **Verifier briefs** prove lock bypasses with synthetic files only (T48).
- **Main's log entries:** the header from `TZ=Asia/Kolkata date -Iseconds`, a title ≤ 80 characters, a summary of 2–5 sentences, detail in Actions. Record the pushed commit hash.
- **Commits** stage only the gate's own paths plus `log.txt` and `TASKS.md`. Push to `github`, never to `origin`.
- **At any failure (T43):** give the hypothesis and the expected signal, then wait for the developer's confirm.
- **After any verifier, judge or code-review verdict:** stop for the developer's reply.
- **Holdout gold stays locked.** Never decode it.
