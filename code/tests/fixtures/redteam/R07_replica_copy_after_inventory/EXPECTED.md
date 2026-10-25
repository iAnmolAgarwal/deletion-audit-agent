# R07: a complete SQL inventory omits the account; a later read replica still holds it

**Attacks:** absence by omission (T50, T54), against a replica copy, across two files.
- `evidence_930701` is a `customer_data_inventory` SQL file with `snapshot_scope` rows for seven systems, `account_service` included, at 11:20. It has **no** `customer_profiles` row for the person. That is a declared-complete omission, the strongest absence evidence the dataset has (T50).
- `evidence_930702`, a read replica captured at 11:40, has the account **only** in `customer_data_read_replica`. Its `customer_data_primary` table lacks it.
- Activity claims pile on:
  - `DELETE_RECORD account_9306101 SUCCESS`, 60 min before `reported_at`, with the result matching the reported COMPLETE;
  - a replication `SYNC_RECORD` reading "replica copies of account_9306101 were purged".

F06 put the primary and replica tables in one file, with no complete-scope file at all. R07 adds a complete-scope file that says "absent".

**Failure it catches:**
- treating a declared complete inventory as proof that *every* copy is gone, against T54 ("a SQL inventory doesn't rule out replica copies");
- reading only primary tables;
- trusting the SUCCESS and "purged" claims.

**Provisional:** no.
- R15-R17 (replica-only profile = `account_service`, own `resource_id`; DEV case_05, 16);
- R15-R6 (the latest observation, 11:40, is PRESENT);
- T54 (the inventory does not cover replica copies);
- CD-F29 (claims are not proof).
**Custom eval case:** **yes.** *A correct system reports a profile still present in a read replica as a remaining `account_service` record, even when a complete primary inventory and the deletion and replication jobs all say it is gone.*
**Parse:**
- `evidence_930701` OK (`sql_inventory`, 1 observation, 7 declared scopes);
- `evidence_930702` OK (`sql_replica_topology`, 3 observations).

## Inputs (all fictional)
- `case_93061`: Saskia Brindlecombe `user_930610`, `saskia.brindlecombe@example.org`, `COMPLETE`.
- `evidence_930701` (inventory, captured 11:20): scopes for account_service, analytics_platform, export_service, integration_service, search_service, security_service and support_platform. The only row is `security_audit_records` audit_record_9306102 (`user_930610`).
- `evidence_930702` (read replica, captured 11:40):
  - primary table: audit_record_9306102;
  - replica table: audit_record_9306102, plus account_9306101 (`customer_profiles`, `customer_reference user_930610`, name, email, phone, ACTIVE).
- `activity_930701` (2026-07-13T01:00): `DELETE_RECORD account_9306101 SUCCESS`.
- `activity_930702` (01:20): `SYNC_RECORD … account_replication_cluster account_9306101 SUCCESS` ("replica copies … were purged").

## Expected row: `INCOMPLETE`, 4 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | account_service | account_9306101 | PRESENT | evidence_930702 | rule_01; R15-R17; the replica row at 11:40 is the latest observation (R15-R6); T54 |
| 2 | REMEDIATION | DELETE_RECORD | account_service | account_9306101 | ABSENT | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9306101 | ABSENT | "" | CD-F26 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9306102 | PRESENT | "" | rule_12; R15-R10 |

- **Citation:** `evidence_930702` is the latest linked file at or before audit, and it holds the account (R15-R14; T66 rule 1).
- **One finding,** though the record appears in one table only and the activity names it twice (CD inv 7).
- **`system_id`** is `account_service`, not `account_replication_cluster`: the activity target system is never the step system (CD-R12; R15-R17).

## What a failure looks like
- Declared scope treated as global → account ABSENT → COMPLETE with 2 steps. A live profile in a replica, the error `notes/SYSTEM.md` ranks first.
- Primary-table-only reading → the same COMPLETE row.
- The replication SYNC row read as an active data flow → a spurious `REPORT_ACTIVE_DATA_FLOW` (R15-R17: replication SYNC rows never become ACTIVE_DATA_FLOW).

## Not settled by the rules
- None. R08 is the reverse ordering, where the inventory is the later file, and is flagged there.
