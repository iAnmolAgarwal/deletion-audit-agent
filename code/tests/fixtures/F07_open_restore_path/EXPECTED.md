# F07: open restore path, a false BLOCK claim, and a restore that happens after audit

**Tests:**
- a backup the evidence shows restorable at 11:20, before audit;
- a `BLOCK_RESTORE SUCCESS` claim the day before, which the evidence contradicts;
- a `CHECK_RESTORE_ACCESS` row that agrees with the evidence;
- a `RESTORE_BACKUP` on 2026-06-20, ten days after audit, that "repopulated" `search_900713`. That resource appears in no evidence.

**Provisional:** no. The restore risk follows R15-R9 (rule_14; DEV case_09 and 17). The post-audit rows follow R15-R5 and CD-F29.
**G8 custom eval case:** no.
**Parse:**
- `evidence_9701` OK (`service_resource_export`, 2 observations);
- `evidence_9702` OK (`kv_log`, 2 observations).

Rule keys as in F02.

## Inputs (all fictional)
- `case_90701`, `saoirse.lowe@example.com`, `COMPLETE`; times as in F01.
- `evidence_9701` (service_resource_export JSON, captured 11:40):
  - `backup_service.restore_entries`: `backup_900710`, `customer_email` = the person's email, `restore_allowed: true`, observed 11:20;
  - `security_service.audit_records`: `audit_record_900712`, `user_900701`, retention until 2033, observed 11:05.
- `evidence_9702` (kv log, captured 11:30): `account_900711` 404, looked up by the person's email at 10:12.
- Activity:
  - `activity_90701`, 2026-06-09T01:05: `BLOCK_RESTORE backup_900710 SUCCESS` (a claim);
  - `activity_90702`, 2026-06-10T10:00: `CHECK_RESTORE_ACCESS … can still be restored`;
  - `activity_90703`, 2026-06-20T09:00: `RESTORE_BACKUP backup_900710 → search_900713` (after audit).

## Expected row: `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_RESTORE_RISK | backup_service | backup_900710 | ACTIVE | evidence_9701 | rule_14; R15-R9 "restorable backup → BLOCK" (DEV 2/2); PS:27. `restore_allowed: true` at 11:20 postdates the BLOCK claim (R15-R6, CD-F29) |
| 2 | REMEDIATION | BLOCK_RESTORE | backup_service | backup_900710 | BLOCKED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900711 | ABSENT | "" | 404 linked by email (S1); R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900712 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RESTORE_BLOCKED | backup_service | backup_900710 | BLOCKED | "" | CD-F26 |

- **Citation:** the finding cites the latest linked pre-audit file, which is also the file holding the backup (R15-R14; T66 rule 1). `evidence_9702` (11:30) is earlier.
- **No step for `search_900713`:** it exists only in a post-audit activity row (R15-R5; A6 at activity level is UNSETTLED in CD, but no DEV gold resource ever comes from a post-audit row, and resources come from evidence).
- **rule_14 says RETAIN, but no `VERIFY_RECORD_PRESENT` for the backup:** DEV backups appear only as RESTORE_RISK → BLOCK → VERIFY_RESTORE_BLOCKED (CD invariant 15; CD-R10).

## What a failure looks like
- Trusting `activity_90701` → backup treated as blocked → COMPLETE while a restore path is open: the error `notes/SYSTEM.md` names first.
- Mapping RETAIN mechanically → `VERIFY_RECORD_PRESENT backup_900710`.
- Adding `REPORT_REMAINING_RECORD search_900713` from the post-audit restore.

## Not settled by the rules
- None.
