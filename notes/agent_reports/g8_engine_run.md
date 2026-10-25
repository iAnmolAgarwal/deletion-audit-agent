# G8 engine run report (orch-redteam, high)

directed_by 2026-10-25T11:55:27+05:30 (T102). Engine: an export of commit 64e203f, replay-only. Brief: scratchpad `g8run_brief.md`. Saved verbatim from the agent's final message.

**Main's check:**
- **R04 reproduces** (`main-R04-check` on the export): case_93031 INCOMPLETE with 14 steps over 6 resources, against the expected 5 steps over `account_9303101`, `analytics_9303104` and `audit_record_9303106`. The extras are `account_9303103`, `search_9303102` and `analytics_9303105`.
- **Cause, confirmed in code:** `discovery/links.py` `link_observation` at 64e203f, lines 105-119, applies own-key precedence per observation. A line with no own key but with `resource_id` links through `lookup_identifiers` (`trace_lookup`), even when another line of the same trace and resource carries an own key.
- **Real-data impact, measured:** the agent's `trace_conflict.py` (read first; counts only) on the real dataset finds 2895 trace groups and 0 contradicted person-resource pairs. The approved run `g5-test-20261025T0530` has 0 `S1_SEVERAL_ACCOUNTS` flags.
- **R06** is behind the T101 ruling at 64e203f; the G7 wiring adds the dedicated rule.

---

I ran commit 64e203f, exported to scratch, replay-only on all 24 fixture folders. One settled row fails, and it is the worst kind: in **R04 case_93031**, one of the five custom eval cases, the engine tells us to delete the live account of a different person who has the same name. The validator and the coherence check both pass that row. R06 fails one small assertion. Everything else passes or waits for G7.

No model calls were made. I never read `.env`, `sample_output.csv` or any gold, and I wrote nothing to the repo except my `log.txt` entry. `check_log.py` passed with 0 blocking issues; it warned that my summary runs about 8 sentences (the format asks for 2–5).

## Results

All settled rows match `expected_output.csv` / `expected_partial.csv` exactly unless marked otherwise. Every row carries the `INTENT_FAILED_CLOSED` flag: in replay-only mode the engine gives every case the deletion path (T71 Q2). So the deletion-intent PASSes below still depend on G7 confirming that intent.

| Fixture | Case | Expected | Actual | Verdict |
|---|---|---|---|---|
| F01 | 90101 / 90102 / 90103 | NA [] | INCOMPLETE (10 / 7 / 10 steps) | WAITING-FOR-G7 (intent) |
| F02–F10 | 90201, 90301, 90401, 90501, 90601, 90701, 90801, 90901, 91001 | as file | identical | PASS |
| F11a | 91101 | FAILED_CLOSED, names evidence_11001 | same | PASS |
| F11b | 91201, 91205 | COMPLETE (2) | identical | PASS |
| F11b | 91202–91204 | FAILED_CLOSED MALFORMED_REQUEST, column named | same | PASS |
| R01 | 93001 | INCOMPLETE (5) | identical | PASS |
| R01 | 93002–93005, 93007 | NA [] | INCOMPLETE (4 / 6 / 6 / 3 / 6 steps) | WAITING-FOR-G7 (intent) |
| R01 | 93006 | COMPLETE (2) | identical | PASS |
| R02 | 93011, 93013, 93015 | INC (4) / COMPLETE (2) / INC (5) | identical | PASS |
| R02 | 93012, 93014, 93016 | NA [] | INCOMPLETE (6 / 6 / 3 steps) | WAITING-FOR-G7 (intent) |
| R03 | 93021, 93022 | INCOMPLETE (5) each | identical | PASS |
| **R04** | **93031** | **INCOMPLETE (5)** | **INCOMPLETE (14)** | **FAIL** |
| R05 | 93041 | INCOMPLETE (5) | identical | PASS |
| R06 | 93051 | FAILED_CLOSED, INCOMPLETE, never cites 930602, reason names search_9305102 | FAILED_CLOSED (`VALIDATOR_REFUSED`), INCOMPLETE, cites 930601 | **FAIL** (reason does not name the resource; all else passes) |
| R07 | 93061 | INCOMPLETE (4) | identical | PASS |
| R08 | 93071 | INCOMPLETE (7); account finding cites 930801, search finding cites 930802 | identical, citations as expected | PASS |
| R09 | 93081, 93082 | INCOMPLETE (8) / (5) | identical | PASS |
| R10 | 93091, 93092, 93093 | INC (5) / COMPLETE (3) / INC (5) | identical | PASS |
| R11 | 93101–93103 | FAILED_CLOSED; never COMPLETE or NA; only the allowed verify steps, with "" | same; the bad files are listed in `failed_dependencies` | PASS |
| R12 | 93111, 93112, 93114 | FAILED_CLOSED, reason names the problem, no cell values leaked | "expected 7 fields, found 8" / "duplicate case_id" (one row) / "reported_status not in the enum"; 0 leaks | PASS |
| R12 | 93113 | COMPLETE (2) | identical | PASS |

**What the WAITING-FOR-G7 rows wait for:** the model's intent answer. On those 11 rows I checked everything that doesn't depend on intent, and all of it passes:
- every step names only the requester's own resources;
- no step cites a file captured after `audit_at`;
- coherence finds no hard problem;
- in R01 93005, the sister's account (account_9300511) gets no step.

Until G7 is wired, though, these rows are destructive plans for people who asked to keep their accounts.

## Failures, ranked by harm

**1. R04 case_93031: records of other people are linked through the requester's lookup.** The engine is wrong here; I checked the fixture's hashes.
- **Extra steps:** FINDING / DELETE / VERIFY on three records that belong to other people:
  - `account_9303103`, the live account (HTTP 200) of the same-name person, `user_930311`;
  - `search_9303102`, a search hit stored under the `.jr` look-alike email;
  - `analytics_9303105`, keyed by the hash of the look-alike email.
- **Fields that differ:** the step set and the row's step count (14 against 5). The 5 expected steps are all present.
- **Rules the expected row cites:** T49, T59 (3) ("a line's own key beats a trace lookup"), T29.
- **Cause:** `discovery/links.py` `link_observation` applies own-key precedence one log line at a time. In a kv log, the "started" line has only `lookup_key=<requester email>`. It names the resource, so it borrows the lookup key and links the record to the requester. The "completed" line, which carries the record's own key, is never compared against that link.
- **Why nothing caught it:** the engine raised `S1_SEVERAL_ACCOUNTS` but did not fail the row closed. Validator and coherence are both clean.
- **Effect on test rows:** probably none. On the dataset's evidence I counted 0 traces where a same-trace own key contradicts a lookup link (2,895 traces). The approved run `g5-test-20261025T0530` has 0 `S1_SEVERAL_ACCOUNTS` flags. Any fix still needs re-approval under T101 if it changes test output.
- **Repro:** `cd /private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8run/engine/code && python3 -c "from pathlib import Path; from deletion_audit import pipeline; pipeline.run(Path('tests/fixtures/redteam/R04_lookalike_sharing_trace'), run_id='g8-R04-repro', cases='test', runs_dir=Path('/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8run/runs'))"`. It is deterministic: the output is byte-identical to the first run.

**2. R06 case_93051: the fail-closed reason does not name the resource.** This one is low harm.
- **What happened:** the row fails closed only through the generic `HARD_CONTAINS` check on step 1. The reason is `VALIDATOR_REFUSED` with `step_no: 1`, so it never names `search_9305102`.
- **The written row looks normal:** its step 1 still cites `evidence_930601`, a file that does not contain the record. That is because `gate` blanks only failed `EVIDENCE_EXISTS` / `EVIDENCE_TIME` citations. Only the artifacts show that the row failed closed, and coherence finds nothing hard in it.
- **Double count:** the same failure is counted twice (hard: 2 checked, 2 failed, both on step 1), because the gate re-runs the check on the failed row and keeps both results.
- **Rule:** T101, which says the row fails closed with its own fixture test. Per T101's follow-through, the dedicated R06 engine rule and its test are in G7's wiring brief, so the engine at 64e203f is behind the ruling; the fixture is right.
- **Effect on test rows:** main measured 0 of 713 test FINDINGs with this shape, so probably none.
- **Repro:** the same command with `R06_preaudit_line_in_postaudit_file`, then read `failed_closed` and `checks_failed` in that run's `cases.jsonl`.

**Smaller observations (not FAILs):**
- R11 labels a SQL execution error and an unknown-family file as `MISSING_EVIDENCE_FILE`, which misdescribes them.
- None of the red-team fixtures R01–R12 is run by any committed test. `test_fixtures.py` names F01–F11b only.

## The five custom eval cases
| Case | Family | Result |
|---|---|---|
| 93021 | injection | PASS |
| 93031 | look-alike and same name | **FAIL** (failure 1) |
| 93041 | post-audit boundary | PASS |
| 93061 | replica after primary deletion | PASS |
| 93082 | sync path | PASS |

## Validator and coherence on these runs
- **FAILED_CLOSED rows: 11.**
  - `MISSING_EVIDENCE_FILE`: 4 (F11a 91101; R11 93101–93103).
  - `MALFORMED_REQUEST`: 6 (F11b 91202–91204; R12 93111, 93112, 93114).
  - `VALIDATOR_REFUSED`: 1 (R06 93051).
- **Validator, hard:** 2 failures, both the R06 `HARD_CONTAINS` above. Every other hard check passes in every run.
- **Validator, flags:** the `ABSENT_BRANCH` and other flag checks all pass. The only flags raised are the 11 `FAILED_CLOSED` flags.
- **Coherence, hard:** H03 only, 34 violations, all on the FAILED_CLOSED rows (F11a 4, F11b 12, R11 6, R12 12). R06's FAILED_CLOSED row has none, and neither does R04's wrong row.
- **Coherence, soft:** S13 ×7 (on the empty FAILED_CLOSED rows) and S11 ×1 (R08, which is expected to cite two files).
- The export's own `tests.pipeline.test_fixtures` passes: 4 tests OK.

## Files
- Per-fixture runs, run IDs `g8-F01` … `g8-R12`: `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8run/runs/`
- Run summary: `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8run/run_summary.json`
- My check scripts (`run_all.py`, `compare.py`, `coh.py`, `r04_obs.py`, `trace_conflict.py`): `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8run/scripts/`
- The code behind failure 1: `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/discovery/links.py`, lines 105–119 at 64e203f.
