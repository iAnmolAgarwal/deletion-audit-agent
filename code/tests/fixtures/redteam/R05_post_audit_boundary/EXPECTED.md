# R05: evidence at the exact-second `audit_at` boundary, and a "clean" post-audit file

**Attacks:** the capture-time cutoff, from both sides. It is harder than F05, which used a file captured two days after audit:
- `evidence_930502` is captured at **exactly** `audit_at` (12:00:00). It shows `search_9304102` FOUND at 11:58. Equality is allowed: it is citable and it counts (CD-F21; DEV case_11, 16, 22, 31).
- `evidence_930503` is captured **one second later** (12:00:01). It is a snapshot bundle in which:
  - the `search_service` collection is empty, a declared scope that would "prove" the search entry gone;
  - the account is **recreated** ACTIVE with full PII.
- `activity_930501` (12:30, post-audit) claims `DELETE_RECORD search_9304102 SUCCESS`.

**Failure it catches:**
- an off-by-one or `<` vs `<=` cutoff, with either cost:
  - dropping the 12:00:00 file → COMPLETE while a search entry remains;
  - admitting the 12:00:01 file → COMPLETE plus an invented account finding;
- "latest wins" applied across the audit boundary;
- a post-audit activity claim treated as state.

**Provisional:** no. Each step rests on DEV-confirmed rules: CD-F21 equality, R15-R5 post-audit ignored, R15-R6 latest at or before audit, R15-R14 citation.
**Custom eval case:** **yes.** *A correct system judges state at `audit_at` inclusive to the second: it uses and cites the file captured at exactly `audit_at`, and ignores the file captured one second later, which falsely shows the record gone and the account recreated.*
**Parse:**
- `evidence_930501` OK (`kv_log`, 4);
- `evidence_930502` OK (`flat_record_list`, 1);
- `evidence_930503` OK (`snapshot_bundle`, 1 observation, 2 declared scopes).

## Inputs (all fictional)
- `case_93041`: Gideon Farrowby `user_930410`, `gideon.farrowby@example.com`, `COMPLETE`; `audit_at` 2026-07-14T12:00:00Z.
- `evidence_930501` (kv log, 11:30): account_9304101 404 at 10:05; audit_record_9304103 at 10:20.
- `evidence_930502` (flat record list, captured **12:00:00**): search_9304102 SEARCH_INDEX_ENTRY FOUND at 11:58 (his email).
- `evidence_930503` (snapshot bundle, captured **12:00:01**):
  - `search_service/customer_search_documents` = `[]`;
  - `account_service/customer_profiles` = account_9304101 ACTIVE (name, email, phone).
- `activity_930501`: 12:30 post-audit DELETE claim for search_9304102.

## Expected row: `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | search_service | search_9304102 | PRESENT | evidence_930502 | rule_03; R15-R9; FOUND at 11:58 is the latest observation at or before audit (R15-R6) |
| 2 | REMEDIATION | DELETE_RECORD | search_service | search_9304102 | ABSENT | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9304101 | ABSENT | "" | 404 at 10:05 (S1); the 12:00:01 recreation is post-audit (R15-R5, DEV case_27) |
| 4 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_9304102 | ABSENT | "" | CD-F26 |
| 5 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9304103 | PRESENT | "" | rule_12; R15-R10 |

- **Citation:** the latest linked file with `captured_at ≤ audit_at` is `evidence_930502`, at equality (R15-R14; CD-F21). It names the resource (T66 rule 1). `evidence_930503` is never cited.
- **The post-audit snapshot is ignored in full.** Its snapshot times are 12:00:01 too, so R15-R4 (pre-audit lines in a post-audit file) does not apply.

## What a failure looks like
- Strict `<` cutoff → no search observation → COMPLETE with account ABSENT and audit PRESENT, both citing `evidence_930501`. A ghost record, the error `notes/SYSTEM.md` names first.
- Cutoff off by one the other way, or "latest observation anywhere" → search ABSENT (empty scope at 12:00:01) and `REPORT_REMAINING_RECORD account_9304101` → wrong in both directions.
- `activity_930501` trusted → search ABSENT.

## Not settled by the rules
- None.
