# Resume point (updated 2026-10-25 ~03:12 IST)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status and the agent queue.
- `notes/DECISIONS.md`: T1–T61, every developer ruling.
- `notes/INTERFACES.md`: the pinned layout and interfaces.
- `notes/SYSTEM.md`: how the system works, with the precedence list (T49 and T50 added).
- `notes/verify/g4_verify.md`: the G4 verifier report.
- `notes/gold_forensics.md`: G2, "Follow-up 2" section at the end.

## Running (2 of 2 slots, T44 cap until 04:20)
- `orch-eval-engineer`, the G4 fix continuation (T51), directed_by 2026-10-25T03:08:01+05:30. On completion:
  - check that the output sha256 is `60234e8f…`, 0 flips, and evidence_18/27 are listed under the new state;
  - check that each fault mode is refused on its own fault;
  - re-run the tests;
  - then launch the queued `orch-verifier` on the G4 fix, once the GP verifier is done and a slot is free.
- `orch-verifier`, the GP review, directed_by 2026-10-25T03:08:01+05:30. On completion:
  - save its message verbatim to `notes/verify/gp_verify.md`;
  - check its repros;
  - stop for the developer's reply.

## Waiting on the developer
1. **G3 go** (`orch-architect`, xhigh), proposed 03:12; it queues for a slot.
2. **T53 reading:** only the band changes, and T5's guessed-anchor limit stays (101 test pairs, not 114). Confirm or rewrite.

## Uncommitted
- **GP rule changes** (T49/T50/T59: `interpret.py`, `families/collection_export.py`, `test_collection_export.py`, `test_field_roles.py`): commit after the GP verifier.
- **G4 fix** (`code/evaluation/**`): commit after its verifier.
- Committed at 03:12: the G2 boundary (`notes/gold_forensics.md`, `notes/forensics/`, notes, log, TASKS).

## Rules in force that are easy to forget
- **T44 cap until 04:20 IST:** at most 2 subagents at once; launch one at a time; queue the rest in gate order.
- **Every subagent brief carries:**
  - a `directed_by: <ts>` line;
  - the literal header with brackets (T45);
  - a summary of 2–5 sentences;
  - one heredoc for the append;
  - a `check_log` run afterwards.
- **Verifier briefs** prove lock bypasses with synthetic files only (T48).
- **Main's log entries:** the header from `TZ=Asia/Kolkata date -Iseconds`, a title ≤ 80 characters, a summary of 2–5 sentences, detail in Actions. Record the pushed commit hash.
- **Commits** stage only the gate's own paths plus `log.txt` and `TASKS.md`. Push to `github`, never to `origin`.
- **At any failure (T43):** give the hypothesis and the expected signal, then wait for the developer's confirm.
- **After any verifier, judge or code-review verdict:** stop for the developer's reply.
- **Holdout gold stays locked.** Never decode it.
- **Upstream:** the cron loop checks every 2 h. Baseline: origin/main 0eddbbd; AGENTS.md unchanged.
