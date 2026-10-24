# F10: active legal hold, and a support attachment in text evidence

**Tests:**
- a `legal_hold_*` record (legal_service, `retained_order_records`, retained until 2033) for the person. Policy says retain it; it must **never** get a DELETE. Test has 8 cases; DEV has 0;
- a ticket attachment uploaded by the person (`storage_class: ticket_attachment`) in text evidence. It is rule_06 DELETE, not rule_05 REDACT, although its prefix is `support_`. Test has 20 cases; DEV has 1, via a PDF.

**Provisional:** yes. The legal-hold step (rule_13 RETAIN → `VERIFY_RECORD_PRESENT` on `legal_service`) is **SPEC-ONLY**: the T9 default "a legal hold is never deleted", CD A13 (UNSETTLED, leaning (a)), `notes/gold_forensics.md` Q6 "No DEV evidence". The attachment steps are DEV-confirmed (case_07's F/R/V shape).
**G8 custom eval case:** yes.
**Parse:**
- `evidence_10001` OK (`sql_replica_topology`, 6 observations; system IDs `legal_service`, `support_platform`, `security_service`);
- `evidence_10002` OK (`kv_log`, 2 observations).

Rule keys as in F02; `R15-P2` is `research/15`'s provisional legal-hold rule.

**Correction to `research/16` F10:** report 16 places `retained_order_records` and `ticket_attachments` in a "customer_data_inventory-style SQL with a `snapshot_scope` row". In the dataset those collections occur only in replica-topology SQL (read, regional, reporting) and in snapshot bundles. No inventory file has them. This fixture uses the read-replica layout.

## Inputs (all fictional)
- `case_91001`, `wen.halloran@example.com`, `COMPLETE`; times as in F01. Text: "… including any files I uploaded to support."
- `evidence_10001` (read replica SQL, captured 11:40), with the same rows in primary and replica:
  - `legal_hold_901010` (legal_service / retained_order_records): `subject_reference user_901001`, `order_reference ORD-901010`, `retention_reason payment_dispute_and_tax_record`, `retained_until 2033-12-31T23:59:59Z`;
  - `support_901011` (support_platform / ticket_attachments): `file_name delivery_photo_901011.pdf`, `uploaded_by` = the person's email, `storage_class ticket_attachment`;
  - `audit_record_901012`.
- `evidence_10002` (kv log, captured 11:30): `account_901013` 404, looked up by the email.

## Expected row: `INCOMPLETE`, 6 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | support_platform | support_901011 | PRESENT | evidence_10001 | rule_06 "belongs only to the deletion subject" (uploaded by the person) → DELETE; R15-R12 attachment cue `ticket_attachments` / `storage_class`; R15-R9 (DEV case_07) |
| 2 | REMEDIATION | DELETE_RECORD | support_platform | support_901011 | ABSENT | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_901013 | ABSENT | "" | S1; R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_ABSENT | support_platform | support_901011 | ABSENT | "" | CD-F26 |
| 5 | VERIFICATION | VERIFY_RECORD_PRESENT | legal_service | legal_hold_901010 | PRESENT | "" | rule_13 RETAIN, hold active (2033 > audit); PS:29 "records that must be retained remain available"; R15-P2. **SPEC-ONLY**. Listed in INCOMPLETE verification like the retained audit record (R15-R10; 12/12 DEV INCOMPLETE rows) |
| 6 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_901012 | PRESENT | "" | rule_12; R15-R10 |

- **Order:** CD-F11/F12. Within VERIFY_RECORD_ABSENT, `account_service` < `support_platform`. Within VERIFY_RECORD_PRESENT, `legal_service` < `security_service`.
- **No finding for the legal hold:** a retained record is never a finding (R15-R10 by analogy with rule_12; `notes/SYSTEM.md` "A legal hold is retained, never deleted").
- **Distinct from S9 / T69:** DEV's legal register PDF names no resource ID, so it creates no step. Here the hold is a record with its own `resource_id`, which is why it gets a step.

## What a failure looks like
- Unknown prefix treated as remaining → `REPORT_REMAINING_RECORD legal_hold_901010` → `DELETE_RECORD`: deletes data the policy says to keep (unsafe).
- S9 over-generalised ("legal → no step") → the step-5 PRESENT is missing.
- `support_` prefix → rule_05 → EXPOSED_PII / REDACT / REDACTED: three wrong operations.

## Not settled by the rules
- The legal hold's `system_id`. `legal_service` is the record's own origin and the activity `target_system` of the dataset's RETAIN rows, but no DEV gold shows it (A13).
- Whether gold lists a retained legal hold in an INCOMPLETE row's verification at all. If it does not, the expected row drops step 5 and has 5 steps.
