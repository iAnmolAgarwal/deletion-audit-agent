# G5 fix round 1 report (orch-builder-core, high)

directed_by 2026-10-25T06:08:27+05:30 (T90). Brief: scratchpad `g5fix_brief.md`. Saved verbatim by main from the agent's final message. The G5 files stay **uncommitted** until the fix-round verifier runs after the developer resumes (T98).

**Main's check (T98):**
- **Scope:** no agent/ or evaluation/ file changed. Tracked changes are only the GM error-text fix and log.txt.
- **Tests:** `code/tests` runs 413 with 50 errors, all in `tests.agent` (G7a's `c_1`/`c_2` IDs, rejected by the new case-ID rule; the agent counted 412 and 53). `code/evaluation/tests` runs 252 OK.
- **The agent's patch** (scratchpad `agentpatch/agent_case_ids.patch`, 9 test files, case IDs and imports only), applied to a scratch copy, gives 413 OK. Not applied to the repo during the pause.
- **Hashes:**
  - DEV: `g5fix1-dev22-20261025T0653` output `641dbc8d…` = `g5-dev22-20261025T0530`, with COMPLETE 7 / INCOMPLETE 15.
  - Test: `g5fix1-test-20261025T0653` output `cf2a90b0…` = `g5-test-20261025T0530`, with 18 FAILED_CLOSED (9 NOTHING_FOUND, 9 UNPARSED_DEPENDENCY).
- **Lint:** mypy is clean on the G5 paths. Ruff finds 3 errors, all in `inputs/__init__.py` (UP035, B905, UP047). That is GP's committed file (160e017), untouched by this round: G9 list.
- **Repros on the fixed code:**
  - valprobe now fails on `COMPLETE_VERIFICATION_ONLY`.
  - p1 now has case_91201's row and no rows for `zzz` or `Robert.Tables`.
  - p2 is now INCOMPLETE, FAILED_CLOSED by `UNINTERPRETED_RECORD`.
- **Fixture tests** are named one by one, never globbed (the docstring in `tests/pipeline/test_fixtures.py`).

---

## Blocked on me

1. **G7a's agent tests break under the new case-ID rule (fix 4).** T87(5) makes a case ID readable only when it is exactly `case_<digits>`. The tests in `code/tests/agent/` use `"c_1"` and `"c_2"` (58 places), so 53 of them now fail in the repo. That folder is outside my scope, so I left it alone. I chose to apply the ruling and not weaken it to keep those tests green.
   - **Ready patch:** `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/agentpatch/agent_case_ids.patch`. Apply it from `code/tests` with `patch -p1`; the dry run is clean. The script that generated it, `apply.py`, is in the same folder.
   - **What it changes:** `"c_1"` becomes `C1` and `"c_2"` becomes `C2`, built at run time by a new `case()` helper, so no case ID is written in the source (the hygiene rule, T71 Q8).
   - **With it applied** in a scratch copy, all 412 tests pass and ruff is clean on `tests/agent`. Without it, the repo runs 412 tests with those 53 failing, all in `tests.agent`.
2. **Interface changes against §7.1, for you to record:**
   - `pipeline` adds `HoldoutRefused`, `holdout_ids()` and `refuse_holdout(cases)`. The `run()` signature is unchanged.
   - `FailedClosedReason` adds `UNINTERPRETED_RECORD`.
   - `CASE_ID_RE` changes to `case_[0-9]+`, matched in full.
   - The private helper `__main__._split` is replaced by `_dev_ids`.

## Changed

| Fix | Code | Tests (each failed on the pre-fix snapshot) |
|---|---|---|
| 1: tests that checked the code against itself | none | See the rows below this table |
| 2: COMPLETE row with a REMEDIATION | `validate/prewrite.py` adds the hard check `COMPLETE_VERIFICATION_ONLY`; `artifacts.py` counts it as a row rule | `test_complete_row_holds_verification_steps_only`, `test_complete_engine_row_with_a_remediation_added_fails` |
| 3: case in both request files | `inputs/requests.py`: the case is an issue in each file at its own line, and also when the test row is the malformed one | `test_clash_is_an_issue_in_each_file_at_its_line`, `test_clash_case_gets_a_malformed_request_row`, `test_malformed_test_row_never_answered_from_the_sample_file` |
| 4: case-ID shape | `CASE_ID_RE` is `case_[0-9]+`, full match, no trimming | `test_only_the_ruled_shape_is_readable`, `test_unreadable_ids_get_no_row_and_are_reported` |
| 5: record that exists but can't be interpreted | `engine.py`: new fail-closed reason `UNINTERPRETED_RECORD` | `test_unknown_system_record_fails_closed`, `test_known_system_record_with_no_readable_state_fails_closed` |
| 6: holdout guard | `pipeline.run` refuses a holdout case in an explicit list before reading any input, and again after resolving `"test"`. No unlock path. | `tests/pipeline/test_holdout_guard.py` |
| 7: `__main__` docstring | Rewritten to match the guard; the CLI turns the refusal into exit code 2 | covered by the guard tests |

- **Fix 1's tests:**
  - **Fixtures:** `tests/pipeline/test_fixtures.py`. F02–F10 are compared byte for byte with `expected_output.csv`. F11a and F11b check every assertion in their JSON files, including that coherence reports H03 as hard on the FAILED_CLOSED rows and on no others. F01 asserts its pre-G7 form and is marked to move into the exact-match list once G7 is wired.
  - **Step order:** the property test and a new 20-step sequence in `tests/steps/test_steps.py`, and a new ORDER test in the validator, now use orders written out by hand from the contract, not the production `step_sort_key`.
  - **Replica rule:** `tests/pipeline/test_engine_rules.py` tests it through the engine, with a non-replica control.
  - **Other surviving mutations:** I added tests for the five other mutations that had survived: the T26 window bounds, T27 email/phone keys, the lower-casing in the T59 hash formula, the T63 search by raw email, and NOT_APPLICABLE only from a model answer.
- **Fix 5 rule:** a record is uninterpreted when the engine gives it no step but it has observations at or before `audit_at`. When the row also has an unread dependency, UNPARSED_DEPENDENCY stays the reason and the flag is still counted.
- **T69 is kept:** `test_t69_hold_naming_no_resource_gives_no_step_and_row_stays_complete` and the R8 test pass both before and after the fix.
- **Updated tests:** `test_t86.py` and `test_pipeline.py` now build their case IDs with `case()`.

## Found

- **Tests:**
  - `code/evaluation/tests`: 252 OK.
  - `code/tests`: 412 tests, all passing except the 53 agent tests above.
  - Lint (ruff and mypy) is clean on every G5 path I touched.
- **Mutations** (my copies of the harnesses, run on scratchpad trees only, never the repo):
  - Before: 26 of 35 killed.
  - After: 35 of 35 killed.
- **Verifier repros on the fixed code:**
  - `valprobe` now reports `COMPLETE_VERIFICATION_ONLY`.
  - In probe `p1`, case_91201 now gets a MALFORMED_REQUEST row, and `zzz` and `Robert.Tables` get no row.
  - In probe `p2`, the case is now FAILED_CLOSED(UNINTERPRETED_RECORD).
- **DEV run `g5fix1-dev22-20261025T0653`:**
  - Status 22/22, row exact 19/22, step F1 0.9887.
  - Output sha256 `641dbc8d…` is identical to `g5-dev22-20261025T0530`, and there are no flips, right→wrong or wrong→right.
  - case_08 is still the known T26/T58 miss.
- **Test replay `g5fix1-test-20261025T0653`:**
  - 518 rows, 0 crashes.
  - FAILED_CLOSED 18: NOTHING_FOUND 9, UNPARSED_DEPENDENCY 9.
  - Output is byte-identical to `g5-test-20261025T0530`, so no row changed.
  - Coherence finds 58 hard H03 lines, all in exactly those 18 FAILED_CLOSED rows (the T87 target).
  - The only metric that moved is the validator's row-rules count, by one new check per COMPLETE row: +7 on DEV, +153 on test.
- **`UNINTERPRETED_RECORD` counts:** 0 on DEV and 0 on test, both as a reason and as a flag. The 3 test records that get no step have no observation at all and are already UNPARSED_DEPENDENCY.
- **Open UNEXPLAINED steps:** none new; case_08 stays on the list.
- **Log:** my entry is appended and `scripts/check_log.py` passes. It gives one warning on my entry: the summary is about 6 sentences against the 2–5 format.

Pre-fix snapshot and scratch copies are in `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/` (`prefix/`, `pnt/`, `post/`, `mutwork/`).
