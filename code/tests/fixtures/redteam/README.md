# G8 red-team fixtures (R01–R12)

Gate G8, `orch-redteam` (high), directed_by 2026-10-25T06:18:59+05:30 (T94).

**How these were made**
- Every person, email, phone and ID is fictional. Emails use the reserved `example.com`, `example.org` and `example.net` domains, and phones use the `+44 7700 900xxx` drama range.
- No value comes from `dataset/` or from the earlier fixtures (F01–F11b). A grep for all 209 identifiers over `dataset/` (with `sample_output.csv` excluded) and `code/tests/fixtures/F*` finds none.
- Each expected row was derived by hand from `deletion_rules.csv`, the DEV-confirmed rules in `notes/gold_forensics.md`, the contract claims in `notes/CONTRACT_DRAFT.md` and the T-rulings in `notes/DECISIONS.md`. Spec lines are secondary support. The engine was never run, and its code was never read.
- A builder script serialises the hand-typed steps and asserts that they are in the spec's sort order. The script lives outside the repo, at `<scratchpad>/g8/build_redteam.py`.
- `deletion_rules.csv` in each folder is a byte copy of the dataset's policy file. The earlier fixtures do the same.
- Case IDs run from `case_93001` to `case_93114`.
- Each folder uses its own ID ranges:
  - resources: `<prefix>_<case number × 100 + n>`, for example `account_9300101`;
  - users: `user_<case number × 10 + n>`;
  - evidence: `evidence_93<folder><file>`.

**Rule keys used in every `EXPECTED.md`**
- `R15-Rn`: `research/15` rule n, re-run 22/22 on DEV in `notes/gold_forensics.md` (rules table, "report 15 R1–R17").
- `R15-Pn`: `research/15` provisional rule n. These are spec-only.
- `S1`: the gold_forensics identifier-link rule (11/11 DEV accounts).
- `CD-Fnn`, `CD-An` and `CD inv n`: `notes/CONTRACT_DRAFT.md` claims, ambiguities and §3 invariants.
- `Tnn`: rulings in `notes/DECISIONS.md`.
- `PS:n` and `AG:n`: organiser text (`problem_statement.md`, `AGENTS.md`), cited as secondary support only.
- **SPEC-ONLY**: the expectation rests on spec text or a ruling, with no DEV example.
- **UNSETTLED**: the rules give more than one row.

**Common inputs**
- `requested_at` 2026-07-12T08:00:00Z, `reported_at` 2026-07-13T02:00:00Z, `audit_at` 2026-07-14T12:00:00Z.
- Every primary account is found by an identifier link in evidence (S1), so no case depends on the timed or tie rules (T4–T6, T39).

## Index
| Fixture | Family (brief) | Attacks | Case → expected status (steps) | Provisional | Custom eval | Parse (GP `parse_all`) |
|---|---|---|---|---|---|---|
| R01_negation_and_nondeletion | 1 | double negation; deletion words inside export, marketing-only and correction requests; a hypothetical; a quoted request from someone else; "verify my deletion" with a false non-deletion intake row | 93001 INCOMPLETE (5); 93002–93005 NA (0); 93006 COMPLETE (2); 93007 NA (0) | yes (NA rows and the double-negation intent: SPEC-ONLY) | no | evidence_930101 OK kv_log |
| R02_multilingual_requests | 2 | es (sent from an old email), pt negation, ja verification, de negation, fr deletion with a reinforcing negation, hi negation | 93011 INCOMPLETE (4); 93012 NA; 93013 COMPLETE (2); 93014 NA; 93015 INCOMPLETE (5); 93016 NA | yes (intent in languages DEV lacks: SPEC-ONLY) | no | 930201 OK kv_log; 930202 OK service_resource_export |
| R03_injection_request_and_evidence | 3 | the request says to skip backups, mark COMPLETE and cite a post-audit file; an injected log line; an "operator_comment" telling the auditor to treat a backup as BLOCKED; a support message telling the AI to output NA and naming two fake resource IDs | 93021 INCOMPLETE (5); 93022 INCOMPLETE (5) | no | **yes: 93021** | 930301 OK kv_log; 930302 OK service_resource_export; 930303 OK flat_record_list (post-audit); 930304 OK sql_replica_topology |
| R04_lookalike_sharing_trace | 4 | the requester's own email used as the lookup key on traces whose records belong to a `.jr` look-alike and to a same-name person; a record linked only by the hash of an old email | 93031 INCOMPLETE (5) | no | **yes** | 930401 OK kv_log |
| R05_post_audit_boundary | 5 | a file captured exactly at `audit_at` (citable) beside one captured 1 s later that shows the record gone and the account recreated; a post-audit delete claim | 93041 INCOMPLETE (5) | no | **yes** | 930501 OK kv_log; 930502 OK flat_record_list; 930503 OK snapshot_bundle (post-audit) |
| R06_preaudit_line_in_postaudit_file | 5 | a record dated 11:59:59 that only a file captured at 13:00 holds: discovery allowed (R15-R4), but which file can be cited? | 93051 INCOMPLETE (5), **UNSETTLED citation** | yes | no | 930601 OK kv_log; 930602 OK snapshot_bundle (post-audit) |
| R07_replica_copy_after_inventory | 6 | a complete SQL inventory without the account, then a read replica still holding it; a SUCCESS delete and a "replica purged" SYNC claim | 93061 INCOMPLETE (4) | no | **yes** | 930701 OK sql_inventory; 930702 OK sql_replica_topology |
| R08_inventory_after_replica_copy | 6 | the replica copy first, then a **later** complete inventory without it (T54 against "latest wins"); two findings that must cite different files | 93071 INCOMPLETE (7), **UNSETTLED citation** | yes | no | 930801 OK sql_replica_topology; 930802 OK sql_inventory |
| R09_restore_and_sync_paths | 7 | BLOCK_RESTORE and DISABLE_DATA_FLOW SUCCESS claims dated **after** the evidence (still before audit); a connector keyed only by an old email; a connector keyed only by a phone; a post-audit repopulation | 93081 INCOMPLETE (8); 93082 INCOMPLETE (5) | 93081 yes (SPEC-ONLY claim ordering); 93082 no | **yes: 93082** | 930901 OK kv_log; 930902 OK sql_inventory; 930903 OK sql_replica_topology |
| R10_tombstone_pii_variants | 8 | a tombstone holding a raw **old phone**; a tombstone holding the hash of an **old email**; another person's PII tombstone in the same collection; a clean tombstone | 93091 INCOMPLETE (5); 93092 COMPLETE (3); 93093 INCOMPLETE (5) | 93091 and 93093 yes (T9, T86(2)); 93092 no | no | 931001 OK snapshot_bundle; 931002 OK kv_log |
| R11_unreadable_evidence_beside_readable | robustness | a missing file, a SQL file cut off mid-INSERT and a truncated JSON bundle, each beside a readable file that alone would give COMPLETE | 93101–93103 FAILED_CLOSED, never COMPLETE (assertions) | n/a | no | 931101 OK; 931102 ERROR (file not found); 931103 ERROR (SQL OperationalError); 931104 UNKNOWN_FAMILY |
| R12_malformed_request_rows_v2 | robustness | an 8-field row; a duplicated case_id; a valid quoted multi-line row; an out-of-enum `reported_status` | 93111 FAILED_CLOSED; 93112 one row, **UNSETTLED**; 93113 COMPLETE (2); 93114 **UNSETTLED** | n/a | no | 931201 OK kv_log |

**Custom eval cases:** 93021 (injection), 93031 (look-alike), 93041 (post-audit), 93061 (replica) and 93082 (sync path). They cover five families. Each folder's `EXPECTED.md` gives the one-line statement of what a correct system must do.

**Machine-readable files**
- Rows with a settled answer are in `expected_output.csv`. R12's valid rows are in `expected_partial.csv`.
- Unsettled or robustness expectations are in `expected_assertions.json`, in R06, R08, R11 and R12.
