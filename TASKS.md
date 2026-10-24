# TASKS — gate tracker (submit Sun 25 Oct 17:30 IST; official deadline 19:00)

Rebuilt at the developer's direction (turn 2026-10-25T00:08:45+05:30). Updated and committed at every gate boundary. All times IST.

**Windows and budgets are estimates, not caps** (developer turn 2026-10-25T01:35:50+05:30, T19). A gate is done when its work is done properly and its evidence is checked. Scope, checks and options are never cut because of the schedule. If time looks like it should change a plan, main tells the developer, and the developer decides.

| Gate | Est. window | Est. time | Artifact (must exist before the next gate) | Agent (effort) | Status |
|---|---|---|---|---|---|
| G0 Setup | 23:59–00:10 | done | SESSION START, `.gitignore`, `.env.example`, upstream loop, private GitHub remote, secret scan | main | done |
| G1 Contract | 00:03–00:45 | 0:45 | `notes/CONTRACT_DRAFT.md` (claims checked on DEV) | `orch-contract-reader` (high) | **done 00:13**: 36 confirmed, 1 contradicted (AG:303 downstream-first), 9 untestable; 4 claims re-checked by main |
| G2 Forensics | 01:31– | ~1:00 | `notes/gold_forensics.md`: **reconcile** report 15 with `verify/14_15` (not a redo); the account-rule order and D17 limits on DEV; hand-built cases measured separately; UNEXPLAINED list; the provisional spec-only defaults listed for confirmation | `orch-gold-forensics` (xhigh) | **First run done 01:47** (directed_by 2026-10-25T01:29:52+05:30). Main reproduced its key account counts independently. **Follow-up run inside G2** (T21) for its NOT DONE items: B4, the system and phone-region tie signals, the trap counts, a one-to-one-aware S5, and two report corrections. Then the developer rules on the empty-candidate options. The 1 h cap is lifted (T21). Scope added by the developer: empty-candidate cases counted on DEV and the 518 test inputs, grouped by reason, case_08 traced, 2–3 options with DEV counts; tie signals |
| G3 Decide | 02:00–02:30 | 0:30 (short: D17, D18 decided) | `notes/ARCHITECTURE_OPTIONS.md`: A vs A+ under the agency contract; cost against **$120** | `orch-architect` (xhigh) | waits for the developer's turn |
| — | ~02:35 | — | Developer types the architecture decision | developer | — |
| G4 Eval first | 02:35–03:35 | 1:00 | **Port** the prep prototype's loader and scorer: `code/evaluation/split.py`, dev-filtered loader + test, scorer, baseline with run ID | `orch-eval-engineer` (high) | not started |
| G5 Spine | 03:35–05:00 | 1:25 | **Port** extraction, identity, discovery, account rule, state, policy, ordering and validator into tested modules to pinned interfaces; DEV end to end (3 cases, then 22) under `runs/` | `orch-builder-core` (high), `orch-builder` (medium) | not started |
| G5b Parser coverage | after G5 | est. on proposal | A normal gate, run while the developer is here (T24): parser tests for every file family behind the 139 cases; fixtures F1–F10, marked provisional; for 3 test cases per unseen file family, a comparison of what the parser extracted against the raw file. No paid calls | proposed to the developer when G5 is done | not started |
| G6 Build | 08:30–09:00 | 0:30 | `orch-verifier` review of G5b; `orch-verifier` on each core diff; experiment log with flips | verifier | not started |
| G7 Model parts | 09:00–11:00 | 2:00 | Intent (cached Sonnet calls + code cross-check), the 11 screenshots, unparseable formats, agent loop with read-only tools; tools on vs off on DEV; cost measured on 3 then 22 DEV cases | `orch-builder-core`, `orch-eval-engineer` | not started |
| Paid full run | submit ~11:00; back by 13:00 | — | Batch API run of 518 cases after the developer approves a stated cost; synchronous fallback for missing cases | main | not started |
| G8 Red team | 11:00–12:00 | 1:00 | Adversarial fixtures; ≥ 3 custom eval cases | `orch-redteam` (high) | not started |
| G9 Freeze | 12:00–14:30 | 2:30 | Clean-cache run → verifier → judge → fix → re-verify → freeze → HOLDOUT EVALUATION RUN (once) → reports | eval, verifier, `orch-judge` | not started |
| G10 Package | 14:30–15:15 | 0:45 | `code.zip`, `output.csv`, `log.txt`, README "How this was built"; trace dry-run | `orch-packager` (low) | not started |
| G11 Interview | 15:15–16:30 | 1:15 | `DEFENSE.md`, `NUMBERS.md`, two timed mocks | `orch-interview-coach` (high) | not started |
| Buffer | 16:30–17:30 | 1:00 | Final checks, export both sessions, stage the trace, **submit 17:30** | developer | — |

## Rules for this schedule
- **Time is not a factor (T19):** the developer makes sure we submit well before the deadline. Never cut scope, skip a check or pick a weaker option because of the schedule.
- The 09:00 Option C rule and G7's hard start are **withdrawn** (T20).
- **Paid calls:** none without the developer's approval and a stated cost. Budget $120.
- **Holdout:** locked until the developer says "HOLDOUT EVALUATION RUN", once, after freeze.

## Open items
- Upstream watch: session cron every 2 h at :07; baseline `origin/main` = `0eddbbd`. If an upstream change removes or renames `AGENTS.md`, stop and tell the developer before merging (the log hook finds the repo through that file).
- Repo sync (D19): private remote `github`; `origin` push disabled; every commit runs `scripts/secret_scan.sh` from the pre-commit hook; push after each commit.
