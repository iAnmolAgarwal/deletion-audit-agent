# R09: restore and sync paths still open, with "fixed" claims dated after the evidence

**Attacks:**
- **case_93081: SUCCESS claims that postdate the evidence.**
  - The complete inventory at 11:00 shows `backup_9308102` with `restore_allowed = 1` and `data_flow_9308103` with `enabled = 1`.
  - Twenty minutes later, still before audit, two deletion-worker rows claim `BLOCK_RESTORE … SUCCESS` (11:20) and `DISABLE_DATA_FLOW … SUCCESS` (11:25).
  - No evidence captured after 11:00 shows either resource.
  - The connector is keyed **only by the person's old email** (`b.thistle@example.net`, `audit_930901`).
  - F06 and F07 had claims that *earlier* evidence contradicted. Here the claim is the latest thing on record.
- **case_93082: a connector keyed only by a phone.**
  - `data_flow_9308203` (`continuous_sync`, enabled) selects the subject by `+44 7700 900961`.
  - A `CHECK_DATA_FLOW` row agrees it "remains enabled".
  - A post-audit `SYNC_RECORD` claims the connector "repopulated downstream resource account_9308299", an ID that exists nowhere else.
  - A second trap: the 11:00 inventory declares `integration_service` and `security_service` complete *without* Peregrine's flow and audit record. The 11:40 replica file, the later observation, shows both present.

**Failure it catches:**
- "latest event wins" over activity rows (93081 → COMPLETE with open restore and sync paths, the first error in `notes/SYSTEM.md`);
- an identifier set without old emails or phones (both connectors missed);
- a post-audit repopulation turned into a finding;
- "any absence wins" across files (93082 → its flow lost).

**Provisional:**
- **case_93081: yes.** That a result claim never overrides evidence, even when the claim is later, is **SPEC-ONLY**: PS:124 "Reported workflow statuses and operation results are claims"; AG:298; CD-F29. DEV confirms claims only where later evidence contradicts them (verify-12 R14; DEV case_16, 24).
- **case_93082: no.** Connector → ACTIVE_DATA_FLOW is DEV 5/5 (R15-R9). Phone linking is T59. Latest-wins is R15-R6. The post-audit row is ignored (R15-R5).

**Custom eval case:** **yes, case_93082.** *A correct system finds a sync connector linked only by the person's phone, reports it active from the latest pre-audit evidence, and ignores a post-audit repopulation claim.* case_93081 would be a fifth eval candidate once its SPEC-ONLY basis is accepted.
**Parse:**
- `evidence_930901` OK (`kv_log`, 4);
- `evidence_930902` OK (`sql_inventory`, 3 observations, 7 scopes; data_flow_9308103 has record identifier `b.thistle@example.net`);
- `evidence_930903` OK (`sql_replica_topology`, 4; data_flow_9308203 has record identifier `+447700900961`).

## Inputs (all fictional)
- `case_93081`: Barnaby Thistlewood `user_930810`, current `barnaby.thistlewood@example.com`, old `b.thistle@example.net` (changed 2026-03-01).
- `case_93082`: Peregrine Ollerton `user_930820`, `peregrine.ollerton@example.org`, phone `+44 7700 900961`. Both `COMPLETE`.
- `evidence_930901` (kv log, captured 10:50): account_9308101 404 (Barnaby, 10:12); account_9308201 404 (Peregrine, 10:16).
- `evidence_930902` (inventory, captured 11:00, seven scopes):
  - `connector_subscriptions` data_flow_9308103: `customer_email` = **old** email, `enabled 1`;
  - `backup_restore_entries` backup_9308102: current email, `restore_allowed 1`;
  - `security_audit_records` audit_record_9308104 (`user_930810`).
- `evidence_930903` (read replica, captured 11:40; the same rows in both tables):
  - data_flow_9308203: `subject_selector` = Peregrine's phone, `enabled true`, `continuous_sync`;
  - audit_record_9308204.
- Activity, in time order:
  - `activity_930901` 10:30 `CHECK_DATA_FLOW data_flow_9308203` "remains enabled";
  - `activity_930902` 11:20 `BLOCK_RESTORE backup_9308102 SUCCESS`;
  - `activity_930903` 11:25 `DISABLE_DATA_FLOW data_flow_9308103 SUCCESS`;
  - `activity_930904` 2026-07-16 `SYNC_RECORD data_flow_9308203` "repopulated … account_9308299".

## Expected rows
### case_93081: INCOMPLETE, 8 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_ACTIVE_DATA_FLOW | integration_service | data_flow_9308103 | ACTIVE | evidence_930902 | R15-R9 enabled connector (DEV 5/5); PS:27; linked by old email (T59, R15-R1). The 11:25 DISABLE claim is not evidence (SPEC-ONLY) |
| 2 | FINDING | REPORT_RESTORE_RISK | backup_service | backup_9308102 | ACTIVE | evidence_930902 | rule_14; R15-R9 (DEV 2/2). The 11:20 BLOCK claim is not evidence (SPEC-ONLY) |
| 3 | REMEDIATION | DISABLE_DATA_FLOW | integration_service | data_flow_9308103 | DISABLED | "" | CD-F24 (disable first) |
| 4 | REMEDIATION | BLOCK_RESTORE | backup_service | backup_9308102 | BLOCKED | "" | R15-R9 |
| 5 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9308101 | ABSENT | "" | S1; R15-R7; the inventory's account_service scope agrees (T54) |
| 6 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9308104 | PRESENT | "" | rule_12; R15-R10 |
| 7 | VERIFICATION | VERIFY_DATA_FLOW_DISABLED | integration_service | data_flow_9308103 | DISABLED | "" | CD-F26 |
| 8 | VERIFICATION | VERIFY_RESTORE_BLOCKED | backup_service | backup_9308102 | BLOCKED | "" | CD-F26 |

- **Citation:** `evidence_930902` is Barnaby's latest linked pre-audit file, and it holds both findings (R15-R14; T66 rule 1). `evidence_930903` holds nothing of his.

### case_93082: INCOMPLETE, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_ACTIVE_DATA_FLOW | integration_service | data_flow_9308203 | ACTIVE | evidence_930903 | R15-R9 (DEV 5/5); linked by phone (T59); PRESENT at 11:40 beats the 11:00 scoped omission (R15-R6) |
| 2 | REMEDIATION | DISABLE_DATA_FLOW | integration_service | data_flow_9308203 | DISABLED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9308201 | ABSENT | "" | S1; R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9308204 | PRESENT | "" | rule_12; R15-R10; present at 11:40, after the 11:00 omission (R15-R6) |
| 5 | VERIFICATION | VERIFY_DATA_FLOW_DISABLED | integration_service | data_flow_9308203 | DISABLED | "" | CD-F26 |

- **No step for `account_9308299`:** it is named only in a post-audit activity row (R15-R5; resources come from evidence).

## What a failure looks like
- 93081 with activity rows treated as state → COMPLETE with account ABSENT and audit PRESENT, while a restore and a sync path are both open.
- 93081 connector missed (old email not in the identifier set) → 5 steps; restore only.
- 93082 connector missed (phone not linked) → COMPLETE with 2 steps.
- 93082 with "any absence wins" across files → the flow and the audit record are dropped.
- 93082 → `REPORT_REMAINING_RECORD account_9308299`.

## Not settled by the rules
- case_93081 rests on the SPEC-ONLY reading above. The alternative, "a later SUCCESS claim updates the state", has no ruling and would report COMPLETE while the evidence last showed both paths open. I flag it but do not consider it acceptable.
