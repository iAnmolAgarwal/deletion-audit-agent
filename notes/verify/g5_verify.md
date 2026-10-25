# G5 verifier report (orch-verifier, high)

directed_by 2026-10-25T05:38:42+05:30. Brief: scratchpad `g5_verifier_brief.md`. Saved verbatim by main from the agent's final message (2026-10-25, about 05:58 IST).

---

**Verdict: FIX.** 5 MAJOR findings, 0 BLOCKER. Nothing blocking, but all five should be fixed before G5 commits.

G5's numbers reproduce exactly, and the output is deterministic. None of the five findings changes a row on today's real data. They are gaps in the tests, the validator and the request loader.

| Q | Verdict | Basis |
|---|---|---|
| 1 Rulings | Implemented; 1 contradicted, some untested | T87(5) is contradicted (finding 4). T54's engine-level replica rule is untested (finding 1). Weaker gaps, where a mutation survived: the T26 ±10 min bound, T59's lower-casing in the hash formula, T27's email/phone-only restriction, T63's raw-email search, and the R15 finding-citation choice. Everything else on the list is killed by its named test. |
| 2 Fail-closed | Mostly holds | Structural failures make every case at or after their capture time depend on them. A missing file gives MISSING_EVIDENCE_FILE. The gate never drops a step. NOT_APPLICABLE needs `source ∈ {MODEL, MODEL_AFTER_TOOLS}`. An unread PNG is a dependency only for records known solely by a catalog row; that is allowed by T60 until freeze, and the zero-skip check at freeze is the backstop. Gaps: findings 2, 3 and 5. |
| 3 Rules by ID | Pass | Shuffling every row of the request, activity, identity and audit-log files gives byte-identical output. Renaming all case IDs by +7000 changes 0 of 518 rows. The only position-based rule is the documented tie-break on manifest order in `latest_file`. |
| 4 Holdout lock | Pass | The engine never reads `sample_output.csv`. The spy test passes and a grep of the engine source finds no reference. The sample file's 32 request inputs (DEV plus holdout) join the global stages, and the CLI refuses holdout IDs. Two non-blocking notes below. |
| 5 Reproduction | Pass | DEV: status 22/22, row exact 19/22, step F1 0.9887. The only flip is case_08 (row_exact and order_exact), which T26/T58 explain. Coherence: 0 hard, 1 soft. Test: 518 rows, 18 FAILED_CLOSED (9 NOTHING_FOUND, 9 UNPARSED_DEPENDENCY), 0 crashes. The 58 hard H03 lines fall in exactly those 18 FAILED_CLOSED cases and nowhere else, so T87's target is met. The sha256 values match G5's runs and are equal across two processes with different hash seeds. |
| 6 Fixtures | Pass | See the table below. |
| 7 Tests | Gaps | 268 tests pass. Of 35 mutations, 13 survive (finding 1). |
| 8 Interface | Pass | An AST walk of the current source matches the §7.1 block line for line. |

| Fixture | Expected | Got | Verdict |
|---|---|---|---|
| F01 | 3 × NOT_APPLICABLE `[]` | 3 × INCOMPLETE deletion-path rows, flagged INTENT_FAILED_CLOSED | Pre-G7 intent (T71 Q2), not a defect |
| F02–F10 | expected_output.csv | byte-identical | Match |
| F11a | FAILED_CLOSED, never COMPLETE, names evidence_11001, parse status ERROR | INCOMPLETE `[]`, reason MISSING_EVIDENCE_FILE, failed_dependencies=[evidence_11001] | Match |
| F11b | 5 rows; 91201 and 91205 equal the partial file; 91202, 91203, 91204 FAILED_CLOSED with the column named; empty case_id reported only | Same; reasons are "audit_at: unrecognized time", "empty required field email", "expected 7 fields, found 5" and "case_id not readable", with no cell values | Match |

## Findings

**1. MAJOR: the step-order tests check the code against itself, and no test runs the fixtures.**
- **Where:** `code/tests/steps/test_steps.py:101` checks order with the production `step_sort_key`, and the validator's ORDER check (`prewrite.py:125`) uses the same key. Nothing under `code/tests/` loads `fixtures/F*/expected_output.csv`. The replica test (`tests/state/test_state.py:128`) checks only the `is_replica_copy` predicate, not the engine's use of it at `engine.py:469`.
- **Reproduce:** `.venv/bin/python -B /tmp/verify-g5/mut.py /tmp/verify-g5/muts2.json` (and `muts1.json`), then `/tmp/verify-g5/fxmut.py /tmp/verify-g5/muts3.json` for the fixtures.
- **What survives all 268 tests:**
  - system sorted before operation: the fixtures catch it (F06, F07, F08, F10 differ);
  - resource sorted before system: F01 and F10 differ;
  - DELETE_RECORD moved ahead of DISABLE_DATA_FLOW in the operations table: F06 differs;
  - `replica = False`: no fixture except F01 differs, and DEV changes from 7 to 8 COMPLETE, so a case wrongly becomes COMPLETE.
- **Expected vs actual:** each rule should have a test that fails when it breaks; all of these pass.
- **Bug class:** self-confirming tests, which T63 pin 5 forbids, and tests of a predicate only. Fix: add a fixture-equality test (F02–F10, plus the F11 assertions), and an engine-level replica test.

**2. MAJOR: the validator accepts a COMPLETE row that holds a REMEDIATION step.**
- **Where:** `validate/prewrite.py:135-136`. The finding/remediation/verification check runs only when the row is INCOMPLETE, and nothing checks that a COMPLETE row holds verifications only.
- **Reproduce:** `.venv/bin/python -B /tmp/verify-g5/valprobe.py`
  ```
  status COMPLETE hard failures: []
  ```
  This is F04's row with a DELETE_RECORD remediation added.
- **Expected vs actual:** a hard failure is expected (`../CLAUDE.md` §3: COMPLETE means VERIFICATION steps only); none is raised. `compile_steps` cannot produce such a row today.
- **Bug class:** a gap in the status↔steps invariant at the last safety net.

**3. MAJOR: a test case whose ID is also in the sample request file gets no output row.**
- **Where:** `inputs/requests.py:136-138` drops the case from both files and files the issue under `SAMPLE_FILE`. `pipeline.py:57` then keeps only issues from `deletion_requests.csv`, so the case is neither audited nor turned into a malformed-request row.
- **Reproduce:** `.venv/bin/python -B /tmp/verify-g5/run.py probe1 test /tmp/verify-g5/p1` (case_91201 copied into the sample file). The output has no case_91201 row; request_issues lists `case_91201 … case_id also in deletion_requests.csv`.
- **Expected vs actual:** a FAILED_CLOSED(MALFORMED_REQUEST) row is expected (T86 item 2); the row is missing. Real data has no such clash.
- **Bug class:** a row silently dropped on a loader error path.

**4. MAJOR: the loader's "readable case ID" pattern contradicts T87(5).**
- **Where:** `inputs/requests.py:50`, `CASE_ID_RE = [A-Za-z0-9][A-Za-z0-9_.-]*`. T87(5) says a readable case_id is shaped `case_<digits>`.
- **Reproduce:** the same probe1. A malformed row with case ID `zzz` gets a written FAILED_CLOSED row, and `Robert.Tables` gets a row that sorts first.
- **Expected vs actual:** these should be reported in the run artifacts only, with no row; both get rows.
- **Bug class:** the pattern differs from the ruling, and no test pins the ruling's shape.

**5. MAJOR: a linked record whose evidence cannot be interpreted gets no step and does not fail the row closed.**
- **Where:** `engine.py:505-506` only flags NO_STATE, and `engine.py:523` fails a row closed only when nothing at all is found. A record that is in scope and has observations at or before `audit_at`, but whose observations give no state or category (UNKNOWN category, `_resource_system` returning `"unknown_system"`), gets NO_STEP and the row can still be COMPLETE. R8's no-step rule covers records with no observation, not records with an unreadable one.
- **Reproduce:** `.venv/bin/python -B /tmp/verify-g5/run.py probe2 test /tmp/verify-g5/p2`. F04 plus a `crm_service` line holding the requester's exact email gives:
  ```
  COMPLETE ... ('crm_900499','unknown_system','UNKNOWN',None,'NO_STEP')
  ```
- **Expected vs actual:** expected FAILED_CLOSED (§3: a failed read is never "nothing found"); actual COMPLETE. On real data all 3 NO_STATE records sit in rows that are already FAILED_CLOSED, so this reaches real rows only when that dependency clears with the state still unread.
- **Bug class:** uninterpretable evidence treated as no evidence.

## Non-blocking notes
- **Pre-existing GP behaviour:** a manifest row that names `sample_output.csv` makes the parser open that file. Probe p3 (a synthetic gold file in a fixture copy) gave UNKNOWN_FAMILY, and the row then failed closed. The real manifest names no such file (grep count 0).
- **Holdout guard:** `pipeline.run` has no holdout guard of its own; only the CLI refuses holdout IDs. The `__main__` docstring says they are "refused everywhere", which overstates it.
- **Lint:** ruff's 11 findings are all in the GP files already on the G9 list. mypy is clean.

The log entry is appended and `python3 -I scripts/check_log.py` reports PASS, with nothing reported for this entry. No repo file was modified, no model call was made, and neither `.env` nor `dataset/sample_output.csv` was opened.

Files are in `/tmp/verify-g5/`:
- harnesses: `run.py`, `score.py`, `mut.py`, `fxmut.py`, `valprobe.py`, `asbuilt.py`;
- runs: `runs/`;
- probe datasets: `p1/`, `p2/`, `p3/`, `perm/`.
