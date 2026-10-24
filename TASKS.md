# TASKS — gate tracker (submit Sun 25 Oct 17:30 IST; official deadline 19:00)

Rebuilt at the developer's direction (turn 2026-10-25T00:08:45+05:30). Updated and committed at every gate boundary. All times IST.

| Gate | Window | Budget | Artifact (must exist before the next gate) | Agent (effort) | Status |
|---|---|---|---|---|---|
| G0 Setup | 23:59–00:10 | done | SESSION START, `.gitignore`, `.env.example`, upstream loop, private GitHub remote, secret scan | main | done |
| G1 Contract | 00:03–00:45 | 0:45 | `notes/CONTRACT_DRAFT.md` (claims checked on DEV) | `orch-contract-reader` (high) | running |
| G2 Forensics | 00:55–01:55 | **1:00 max** | `notes/gold_forensics.md`: **reconcile** report 15 with `verify/14_15` (not a redo); the account-rule order and D17 limits on DEV; hand-built cases measured separately; UNEXPLAINED list; the provisional spec-only defaults listed for confirmation | `orch-gold-forensics` (xhigh) | waits for the developer's turn after G1 |
| G3 Decide | 02:00–02:30 | 0:30 (short: D17, D18 decided) | `notes/ARCHITECTURE_OPTIONS.md`: A vs A+ under the agency contract; cost against **$120** | `orch-architect` (xhigh) | waits for the developer's turn |
| — | ~02:35 | — | Developer types the architecture decision | developer | — |
| G4 Eval first | 02:35–03:35 | 1:00 | **Port** the prep prototype's loader and scorer: `code/evaluation/split.py`, dev-filtered loader + test, scorer, baseline with run ID | `orch-eval-engineer` (high) | not started |
| G5 Spine | 03:35–05:00 | 1:25 | **Port** extraction, identity, discovery, account rule, state, policy, ordering and validator into tested modules to pinned interfaces; DEV end to end (3 cases, then 22) under `runs/` | `orch-builder-core` (high), `orch-builder` (medium) | not started |
| Sleep | **developer to set** (proposed 05:00–08:30) | — | One pre-approved bounded background job, no paid calls: parser tests for every file family of the 139 cases, fixtures F1–F10 (provisional), explicit stop conditions, logs its own entries | `orch-builder-core` (one run) | needs the developer's window and approval |
| G6 Build | 08:30–09:00 | 0:30 | Review the overnight job; `orch-verifier` on each core diff; experiment log with flips | verifier | not started |
| G7 Model parts | **09:00 start (hard)**–11:00 | 2:00 | Intent (cached Sonnet calls + code cross-check), the 11 screenshots, unparseable formats, agent loop with read-only tools; tools on vs off on DEV; cost measured on 3 then 22 DEV cases | `orch-builder-core`, `orch-eval-engineer` | not started |
| Paid full run | submit ~11:00; back by 13:00 | — | Batch API run of 518 cases after the developer approves a stated cost; synchronous fallback for missing cases | main | not started |
| G8 Red team | 11:00–12:00 | 1:00 | Adversarial fixtures; ≥ 3 custom eval cases | `orch-redteam` (high) | not started |
| G9 Freeze | 12:00–14:30 | 2:30 | Clean-cache run → verifier → judge → fix → re-verify → freeze → HOLDOUT EVALUATION RUN (once) → reports | eval, verifier, `orch-judge` | not started |
| G10 Package | 14:30–15:15 | 0:45 | `code.zip`, `output.csv`, `log.txt`, README "How this was built"; trace dry-run | `orch-packager` (low) | not started |
| G11 Interview | 15:15–16:30 | 1:15 | `DEFENSE.md`, `NUMBERS.md`, two timed mocks | `orch-interview-coach` (high) | not started |
| Buffer | 16:30–17:30 | 1:00 | Final checks, export both sessions, stage the trace, **submit 17:30** | developer | — |

## Rules for this schedule
- **09:00 Option C rule (redefined by the developer):** if the model parts (intent, the 11 screenshots, unparseable formats) have not started by 09:00, ship the engine with model intent only.
- **Paid calls:** none without the developer's approval and a stated cost. Budget $120.
- **Holdout:** locked until the developer says "HOLDOUT EVALUATION RUN", once, after freeze.

## Open items
- Upstream watch: session cron every 2 h at :07; baseline `origin/main` = `0eddbbd`. If an upstream change removes or renames `AGENTS.md`, stop and tell the developer before merging (the log hook finds the repo through that file).
- Repo sync (D19): private remote `github`; `origin` push disabled; every commit runs `scripts/secret_scan.sh` from the pre-commit hook; push after each commit.
