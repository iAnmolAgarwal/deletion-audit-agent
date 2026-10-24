# Build decisions (repo copy)

The full prep-era log (D1–D19) is in the kit at `../research/DECISIONS.md`. This file records the decisions taken **in the build session**, each tied to the developer turn in `log.txt` that made it, plus every organiser claim we adopt and why (`../CLAUDE.md` §0).

## Developer turn 2026-10-25T00:08:45+05:30

| # | Decision | Reason given / basis |
|---|---|---|
| T1 | **Secret scan (D19):** `.env.example` carries an empty `ANTHROPIC_API_KEY=` so nothing needs an exception. Every staged diff is scanned for `sk-ant-` + 20 key characters, `ANTHROPIC_API_KEY=` with a value, private-key headers, and the exact `.env` value (compared, never printed). Implemented as `scripts/secret_scan.sh`, run by the pre-commit hook. | Developer approved the narrower scan after the literal patterns hit the placeholder. |
| T2 | **Upstream:** the fast-forward to `0eddbbd` stands. If an upstream change removes or renames `AGENTS.md`, stop and tell the developer before merging. | The log hook finds the repo root through `AGENTS.md`. |
| T3 | **Timeline:** `TASKS.md` rebuilt to a 17:30 submission. G2 reconciles report 15 (1 h max); G3 is short; G4/G5 port the prototype. **09:00 rule redefined:** if the model parts (intent, the 11 screenshots, unparseable formats) have not started by 09:00, ship the engine with model intent only. *(09:00 rule withdrawn by T20.)* | Gate budgets as planned exceeded the time left. |
| T4 | **Primary-account rule, in this order:** (1) identifier link; (2) timed rule: the account delete row 75 to 44 min before `reported_at`, with `reported_result` matching the reported status; (3) a global one-to-one pass, unique assignments first, each removing its account from other cases' candidates; (4) the D17 fingerprint tie-break; (5) a D18 flagged pick. Measure the hand-built cases' pattern separately on DEV. **Not shipped:** the "appears in some evidence file" preference; the fallback to a delete row whose result doesn't match; per-case independent guesses. | `../research/verify/14_15_verify.md` (an independent re-run of reports 14 and 15). |
| T5 | **D17 (job timing fingerprint) shipped** for account tie-breaks and identifier-free analytics, only when the record goes to a single case, never anchored on a guessed account, with a fixture test that pins timestamp precision (±1 s changes 33 test cases). README describes it as a data-derived correlation, not a spec rule. | Developer: the data logs no job ID; a deletion run's writes sharing one timing signature is the available job-run correlation. Measured once on the holdout. |
| T6 | **D18:** true account ties (about 43) get a deterministic pick, flagged in run artifacts. The account step is never omitted. | Gold has an account step in every DEV case. |
| T7 | **Model inputs:** intent and the 11 screenshots come from cached model calls with code cross-checks. No per-row keyword tables, no hand-typed facts. | The verifier flagged both in the prototype under D3. |
| T8 | **Coverage gate at parser level, not case level:** a non-empty evidence file that parses to zero units is a parser failure; any case that depends on it fails closed, never COMPLETE. Every file family behind the 139 cases gets a parser test. | DEV case_01 and case_02 are COMPLETE with no user-linked evidence, so a case-level "no observations" gate would be wrong. |
| T9 | **Spec-only defaults, provisional until DEV or the rule text says otherwise:** follow `deletion_rules.csv` literally; a tombstone still holding personal data is a finding; the user's email or phone in support free text is exposed PII → redact; a legal hold is never deleted (the hold rule's operation applies); compliant records in INCOMPLETE cases get their verification steps, as DEV shows. Each gets a fixture from `../research/16` F1–F10, marked provisional, and is listed in G2's report for confirmation. | Developer defaults. |
| T10 | **Agent boundary:** the agent never changes a fact the engine has settled; tools on vs off is measured on DEV; the cost estimate is redone against $120. | Report 14 found no output upside for A+; the code score still needs a visible agent. |
| T11 | **Port, don't copy:** the prep prototype is rebuilt here as tested modules to pinned interfaces, and logged as a port. | Transcript and code score. |

## Developer turn 2026-10-25T01:29:52+05:30

| # | Decision | Reason given / basis |
|---|---|---|
| T12 | **G2 go:** `orch-gold-forensics` at xhigh, capped at 1 h *(cap lifted by T21)*, DEV only → `notes/gold_forensics.md`. It gates G3 and the rules G5 builds. | Developer approved the proposal as written. |
| T13 | **Overnight job addition:** for 3 test cases per unseen file family, compare what the parser extracted against the raw file. The job itself is approved separately before the developer goes. *(Superseded by T25: the job is now gate G5b.)* | Developer. The sleep window is still unset. |
| T14 | **Empty-candidate cases:** count them first, on DEV and on the 518 test inputs (no gold involved for test). Group them by why the timed rule finds nothing: no account delete row at all, delete row after `audit_at`, or result mismatch. For DEV case_08, show where its gold account resource appears in the inputs and what its account step cites. Then 2–3 options with DEV counts; the developer rules. | Developer; closes the gap main raised after G1. |
| T15 | **Secret-scan reading confirmed:** `ANTHROPIC_API_KEY=` "with a value" means a line-start assignment with any value, or a key-like value of 8+ characters anywhere. | Developer: "Your secret-scan reading is right. Keep it." |
| T16 | **Tie signals (if G2 has time):** look for any input signal that separates the ~43 true account ties (request text, phone fragments, system, region, timestamp seconds), each with counts. None ships without DEV support. | Developer. |
| T17 | **Independent second version:** the developer built one separately, with Codex and Claude on another laptop, and compares it against our prototype outside this session. The developer will bring back a list of disagreeing cases, with reasons, for G3/G5. None of its code comes into this repo and no row is copied from it. Each disagreement either points to a rule we fix with a test, or changes nothing. | Developer, recorded "so the log has it". |
| T18 | **Log timestamps use `+05:30`.** The 01:09:13 entry's header used `+0530`. Corrected by a note in the next entry rather than by rewriting `log.txt`, which stays append-only. | Developer's fix request; `../CLAUDE.md` §1 append-only rule. |

## Developer turn 2026-10-25T01:35:50+05:30

| # | Decision | Reason given / basis |
|---|---|---|
| T19 | **Time is not a factor from here on.** Gate time budgets in `TASKS.md` are estimates, not caps. A gate is done when its work is done properly and its evidence is checked. Never cut scope, skip a check or choose a weaker option because of where the schedule says we'll finish. If time looks like it should change a plan, main tells the developer, and the developer decides. | Developer: "I'll make sure we submit well before the deadline, so don't plan around the clock." |
| T20 | **Withdrawn:** the 09:00 Option C rule (T3) and G7's "hard" start. The schedule-slip question is removed; nothing needs to absorb it. | Developer; follows from T19. |
| T21 | **G2's 1-hour cap is lifted** (amends T12). If the run stops at its brief's 02:32 mark with scope left, the tie-signal search (T16) included, a follow-up run inside G2 finishes it. Nothing is dropped. | Developer. |
| T22 | **Sleep window:** the developer says when they go. Nothing is planned around it. *(Superseded by T24: no sleep window.)* | Developer. |
| T23 | **The 01:09:13 log line stays as it is.** Append-only is right, and the note in the 01:32:51 entry covers it (confirms T18). | Developer. |

## Developer turn 2026-10-25T01:40:42+05:30

| # | Decision | Reason given / basis |
|---|---|---|
| T24 | **No sleep window.** The Sleep row is dropped from `TASKS.md`. | Developer: "I'm not sleeping tonight." |
| T25 | **The overnight job becomes gate G5b, right after G5.** It runs while the developer is here and is reviewed like any other gate. Scope: parser tests for every file family behind the 139 cases; fixtures F1–F10, marked provisional; for 3 test cases per unseen file family, a comparison of what the parser extracted against the raw file. Main proposes it when G5 is done (agent, effort, goal, what it gates), and G6 reviews it with `orch-verifier`. Time is still not a factor (T19). | Developer. |

## Organiser claims adopted
(None yet. G1's `notes/CONTRACT_DRAFT.md` will propose them; each adoption is added here with its DEV evidence.)
