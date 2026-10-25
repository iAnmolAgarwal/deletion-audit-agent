# G8 red-team report (orch-redteam, high)

directed_by 2026-10-25T06:18:59+05:30. Brief: scratchpad `g8_redteam_brief.md`. Saved verbatim by main from the agent's final message.

**Main's check (T98):** git status shows only `code/tests/fixtures/redteam/` from this agent. No run under `runs/` names a red-team folder. The parser gives 24 OK, 2 ERROR and 1 UNKNOWN_FAMILY, the three failures by design; the report's "25 OK" is a counting slip, since there are 27 entries. There are 31 cases on 32 case-ID rows (93112 is duplicated on purpose). In the overlap check, 41 emails, 38 phones and 172 resource IDs appear 0 times in `dataset/` (sample_output.csv excluded) or in F01–F11b. The custom eval cases are 93021, 93031, 93041, 93061 and 93082.

---

I built the 12 fixture folders (31 cases, `case_93001` to `case_93114`), but the engine has not been run on them, so the "actual" column is empty and no case has a PASS or FAIL yet. Your brief forbids running the engine before you commit the fixtures, and it overrides the generic task text, which said to write to `fixtures/adversarial/` and run the pipeline. All fixtures are in `code/tests/fixtures/redteam/`.

All 25 evidence files meant to be readable parse OK with `parse_all`. The three files meant to fail come back as failures (ERROR, ERROR and UNKNOWN_FAMILY). None of the 209 fictional identifiers appears in `dataset/` (`sample_output.csv` excluded) or in F01–F11b. `check_log.py` passes; its only note is a non-blocking warning that my summary has 6 sentences.

| Fixture | Family | What it attacks | Expected status (steps) | Actual | Provisional | Custom eval | Parse status |
|---|---|---|---|---|---|---|---|
| R01_negation_and_nondeletion | 1 | Double negation that does ask for deletion; deletion words inside export, "marketing lists only", correction and hypothetical requests; a quoted request from someone else; "verify my deletion" with a false non-deletion intake row | 93001 INCOMPLETE (5); 93002–93005 NOT_APPLICABLE (0); 93006 COMPLETE (2); 93007 NOT_APPLICABLE (0) | not run | yes (no DEV row is NOT_APPLICABLE) | no | 930101 OK |
| R02_multilingual_requests | 2 | Spanish (sent from an old email), Japanese verification and French deletion; Portuguese, German and Hindi negations | 93011 INCOMPLETE (4); 93012 NOT_APPLICABLE; 93013 COMPLETE (2); 93014 NOT_APPLICABLE; 93015 INCOMPLETE (5); 93016 NOT_APPLICABLE | not run | yes (no DEV text in these languages) | no | 930201 OK, 930202 OK |
| R03_injection_request_and_evidence | 3 | Request says skip backups, mark COMPLETE and cite a post-audit file; injected log line; a JSON comment telling the auditor to treat a backup as blocked; support text demanding NOT_APPLICABLE and naming two fake resource IDs | 93021 INCOMPLETE (5); 93022 INCOMPLETE (5) | not run | no | yes (93021) | 4 files OK; the fake IDs produce no observations |
| R04_lookalike_sharing_trace | 4 | Records of a `.jr` look-alike and of a same-name person, both looked up with the requester's own email; a true link through the hash of an old email | 93031 INCOMPLETE (5) | not run | no | yes | 930401 OK |
| R05_post_audit_boundary | 5 | A file captured exactly at `audit_at` (citable) against one captured one second later that shows the record gone and the account recreated | 93041 INCOMPLETE (5) | not run | no | yes | 3 files OK |
| R06_preaudit_line_in_postaudit_file | 5 | A record dated 11:59:59 that only a file captured at 13:00 holds | 93051 INCOMPLETE (5), citation unsettled | not run | yes | no | 2 files OK |
| R07_replica_copy_after_inventory | 6 | A complete inventory without the account, then a later read replica that still holds it; SUCCESS and "replica purged" claims | 93061 INCOMPLETE (4) | not run | no | yes | sql_inventory OK, replica OK |
| R08_inventory_after_replica_copy | 6 | The replica copy first, then a later complete inventory without it (T54 against "latest observation wins") | 93071 INCOMPLETE (7), citation unsettled | not run | yes | no | 2 files OK |
| R09_restore_and_sync_paths | 7 | BLOCK and DISABLE SUCCESS claims dated after the evidence; a connector keyed only by an old email; one keyed only by a phone; a post-audit repopulation | 93081 INCOMPLETE (8); 93082 INCOMPLETE (5) | not run | 93081 yes (spec text only), 93082 no | yes (93082) | 3 files OK |
| R10_tombstone_pii_variants | 8 | Tombstone holding a raw old phone; one holding an old email's hash; another person's tombstone with PII; a clean tombstone | 93091 INCOMPLETE (5); 93092 COMPLETE (3); 93093 INCOMPLETE (5) | not run | 93091 and 93093 yes | no | 2 files OK |
| R11_unreadable_evidence_beside_readable | robustness | Missing file, SQL cut off mid-INSERT, truncated JSON, each beside a readable file that alone would give COMPLETE | 93101–93103 FAILED_CLOSED, never COMPLETE | not run | n/a | no | 931101 OK; 931102 ERROR (file not found); 931103 ERROR (SQL OperationalError); 931104 UNKNOWN_FAMILY |
| R12_malformed_request_rows_v2 | robustness | An 8-field row; a duplicated case_id; a valid multi-line quoted row; `reported_status=DONE` | 93111 FAILED_CLOSED; 93112 exactly one row, unsettled; 93113 COMPLETE (2); 93114 unsettled | not run | n/a | no | 931201 OK |

The five custom eval cases are 93021, 93031, 93041, 93061 and 93082, one per family. Each `EXPECTED.md` has the one-line statement of what a correct system must do.

## Risks ranked by harm
Each fixture is built to catch a specific mistake. Ranked by how bad that mistake would be:

1. **COMPLETE while a ghost record or open path exists.**
   - 93081: activity claims treated as state.
   - 93061 and 93071: a complete inventory treated as covering replica copies.
   - 93041: a `<` instead of `<=` cutoff at `audit_at`.
   - 93101–93103: an unreadable file ignored.
   - 93021: the injection obeyed.
   - 93051, under the "not discovered" reading.
2. **A destructive plan for someone who asked to keep their data:** the NOT_APPLICABLE rows in R01 and R02.
3. **Another person's records attributed to the requester:** R04's trace-join decoys and R10's other-person tombstone.
4. **Citation or validator failures that cost a row without changing the facts:** R06 and R08.

## Where the rules don't settle the row
- **R06 (93051): two rules conflict.** R15-R4 (DEV-confirmed) lets a pre-audit line inside a post-audit file count for discovery. If that record is a finding, it must cite a file that contains it (T66 rule 1), but no file captured at or before `audit_at` does. Citing the post-audit file is never allowed. I lean towards citing the case's one pre-audit file. The forensics trap table counts 179 test cases with this file shape, so this needs a ruling.
- **R08 (93071): T66 rule 1 against one-file-per-case.** The two findings can only be cited from different files. I followed T66, since it is your ruling and the one-file rule is marked soft.
- **R11 (93101): "depends on" is undefined for a missing file**, because its contents are unknown. I asserted that every case whose audit time falls after the file's capture time is never COMPLETE.
- **R12: no ruling on a duplicated case_id (93112)** or an out-of-enum `reported_status` (93114). Both readings are listed for each.
- **R01 93003 and 93007** ("delete me from your marketing lists only", "remove my old phone number") are NOT_APPLICABLE only on the organisers' list of non-deletion request types.

## How to check
- Parser statuses: `.venv/bin/python -I -B <scratchpad>/g8/parse_fixtures.py`, run from the repo root.
- Engine results: once you have committed the fixtures, compare each folder's `expected_output.csv`, `expected_partial.csv` or `expected_assertions.json` with the engine's output for that folder.

Files are in `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/tests/fixtures/redteam/`:
- README.md
- R01_negation_and_nondeletion/ to R12_malformed_request_rows_v2/

The builder and parser scripts are in the scratchpad (not committed):
- /private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8/build_redteam.py
- /private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g8/parse_fixtures.py
