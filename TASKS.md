# TASKS — gate tracker (submit Sun 25 Oct 17:30 IST; official deadline 19:00)

Rebuilt at the developer's direction (turn 2026-10-25T00:08:45+05:30). Updated and committed at every gate boundary. All times IST.

**Windows and budgets are estimates, not caps** (developer turn 2026-10-25T01:35:50+05:30, T19). A gate is done when its work is done properly and its evidence is checked. Scope, checks and options are never cut because of the schedule. If time looks like it should change a plan, main tells the developer, and the developer decides.

| Gate | Est. window | Est. time | Artifact (must exist before the next gate) | Agent (effort) | Status |
|---|---|---|---|---|---|
| G0 Setup | 23:59–00:10 | done | SESSION START, `.gitignore`, `.env.example`, upstream loop, private GitHub remote, secret scan | main | done |
| G1 Contract | 00:03–00:45 | 0:45 | `notes/CONTRACT_DRAFT.md` (claims checked on DEV) | `orch-contract-reader` (high) | **done 00:13**: 36 confirmed, 1 contradicted (AG:303 downstream-first), 9 untestable; 4 claims re-checked by main |
| G2 Forensics | 01:31– | ~1:00 | `notes/gold_forensics.md`: **reconcile** report 15 with `verify/14_15` (not a redo); the account-rule order and D17 limits on DEV; hand-built cases measured separately; UNEXPLAINED list; the provisional spec-only defaults listed for confirmation | `orch-gold-forensics` (xhigh) | **First run done 01:47** (directed_by 2026-10-25T01:29:52+05:30). Main reproduced its key account counts independently. **Follow-up run inside G2** (T21) for its NOT DONE items: B4, the system and phone-region tie signals, the trap counts, a one-to-one-aware S5, and two report corrections. The developer has ruled on the account findings (T26–T29). **Follow-up 1 done 02:14** (run g2f-0152; main spot-checked it). **Follow-up 2 running** since about 02:17 (six rule candidates, T31; directed_by 2026-10-25T01:58:39+05:30) → main checks it → the developer rules → G2 boundary commit → G3 proposed (T30). The 1 h cap is lifted (T21). Scope added by the developer: empty-candidate cases counted on DEV and the 518 test inputs, grouped by reason, case_08 traced, 2–3 options with DEV counts; tie signals |
| G3 Decide | 02:00–02:30 | 0:30 (short: D17, D18 decided) | `notes/ARCHITECTURE_OPTIONS.md`: A vs A+ under the agency contract; cost against **$120** | `orch-architect` (xhigh) | waits for the developer's turn |
| — | ~02:35 | — | Developer types the architecture decision | developer | — |
| G4 Eval first | 02:15– (parallel with G2, T34) | ~1:00 | **Port** the prep prototype's loader and scorer: `code/evaluation/split.py`, dev-filtered loader + test, scorer mirroring the published metrics (row accuracy included), coherence checks, baseline run of the prototype on DEV with a run ID, `code/evaluation/NUMBERS.md` started | `orch-eval-engineer` (high) | **running** since 02:15 (directed_by 2026-10-25T02:12:13+05:30). Gates G5's measurements |
| GP Evidence parsers | after the developer OKs the pinned interface (parallel, T35) | est. on proposal | Pulled forward from G5/G5b: one parser per file family feeding one interpretation point, to `notes/INTERFACES.md` §1–§3; failures per T8; a unit test per family; the T13 raw-file check (`notes/parser_raw_check.md`). Out of scope: account linking, state, policy | `orch-builder` (medium) | **running** since about 02:21 (directed_by 2026-10-25T02:19:57+05:30). Interface approved with changes (T38): package `deletion_audit`, declared-scope files with zero rows are OK, all-identifier raw check, the three CSV loaders, SQL step and row caps |
| GM Model client | after GP (T36) | est. on proposal | The model client (structured output, retry ladder, budget guard, reply cache), to an interface pinned before it starts | `orch-builder` (medium) | not started |
| G5 Spine | after G3 decision | est. | **Port** identity, discovery, account rule, state, policy, ordering and validator into tested modules to pinned interfaces, on top of GP's parsers; DEV end to end (3 cases, then 22) under `runs/` | `orch-builder-core` (high), `orch-builder` (medium) | not started |
| G5b Policy fixtures | after G5 | est. on proposal | Fixtures F1–F10, marked provisional (the parser tests and the T13 raw check moved to GP) | proposed to the developer when G5 is done | not started |
| G6 Build | after G5b | est. | `orch-verifier` review of GP and G5b; `orch-verifier` on each core diff; experiment log with flips | verifier | not started |
| G7 Model parts | after G6 | 2:00 | Intent (cached Sonnet calls + code cross-check), the 11 screenshots, unparseable formats, agent loop with read-only tools; tools on vs off on DEV; cost measured on 3 then 22 DEV cases | `orch-builder-core`, `orch-eval-engineer` | not started |
| Paid full run | submit ~11:00; back by 13:00 | — | Batch API run of 518 cases after the developer approves a stated cost; synchronous fallback for missing cases | main | not started |
| G8 Red team | 11:00–12:00 | 1:00 | Adversarial fixtures; ≥ 3 custom eval cases | `orch-redteam` (high) | not started |
| G9 Freeze | 12:00–14:30 | 2:30 | Clean-cache run → verifier → judge → fix → re-verify → freeze → HOLDOUT EVALUATION RUN (once) → reports | eval, verifier, `orch-judge` | not started |
| G10 Package | 14:30–15:15 | 0:45 | `code.zip`, `output.csv`, `log.txt`, README "How this was built" and "How it works" (from `notes/SYSTEM.md`, T33); trace dry-run | `orch-packager` (low) | not started |
| Submit | after G10 | — | Final checks, export both sessions, stage the trace, submit (T37: after G10 the next step is submission) | developer | — |

## Rules for this schedule
- **Time is not a factor (T19):** the developer makes sure we submit well before the deadline. Never cut scope, skip a check or pick a weaker option because of the schedule.
- The 09:00 Option C rule and G7's hard start are **withdrawn** (T20).
- **Paid calls:** none without the developer's approval and a stated cost. Budget $120.
- **Holdout:** locked until the developer says "HOLDOUT EVALUATION RUN", once, after freeze.
- **Parallel gates (T36):** gates that run side by side touch separate paths, with no shared files. Each gate's commit stages only its own paths, plus `log.txt` and `TASKS.md`. Two `orch-*` agents of the same type never run at once.
- **`NUMBERS.md` stays (T37):** `code/evaluation/NUMBERS.md`, started in G4, holds every number with its run ID (`../CLAUDE.md` §4); the reports draw on it.
- **Interview prep:** removed from the plan (T37). The developer will say how to prepare once the deliverables are ready.

## Open items
- Upstream watch: session cron every 2 h at :07; baseline `origin/main` = `0eddbbd`. If an upstream change removes or renames `AGENTS.md`, stop and tell the developer before merging (the log hook finds the repo through that file).
- Repo sync (D19): private remote `github`; `origin` push disabled; every commit runs `scripts/secret_scan.sh` from the pre-commit hook; push after each commit.
