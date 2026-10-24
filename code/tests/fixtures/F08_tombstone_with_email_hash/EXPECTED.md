# F08: account tombstone that still exposes the email hash

**Tests:** a tombstone whose name, email and phone are null but whose `email_hash` is still sha256(lower(email)), the person's own hash. The spec names the email hash as a direct identifier that must be removed. A rule learned from DEV's only (clean) tombstone, "a tombstone is always VERIFY_RECORD_REDACTED", gets this wrong. Test case_544, 546, 548 and 550 have this shape (`research/16` §4.5).

The request text also says "you may keep an internal reference number". That describes exactly what the tombstone may keep (`subject_reference`), and it does not cover the hash.

**Provisional:** yes. **SPEC-ONLY** (T9 default "a tombstone still holding personal data is a finding"; `notes/gold_forensics.md` Q6: no DEV evidence either way).
**G8 custom eval case:** yes.
**Parse:**
- `evidence_9801` OK (`snapshot_bundle`, 2 observations, 3 declared scopes, including the empty `account_service/customer_profiles`). The tombstone observation's identifiers are `email_hash` and `user_id: user_900801`;
- `evidence_9802` OK (`kv_log`, 2 observations).

Rule keys as in F02; `R15-P3` is `research/15`'s provisional tombstone rule.

## Inputs (all fictional)
- `case_90801`, `quill.ashdown@example.org`, `COMPLETE`; times as in F01.
- `user_900801`, Quill Ashdown; `email_hash` `96c26dda…a5ed` = sha256 of the email.
- `evidence_9801` (snapshot bundle, captured 11:40; all snapshots at 11:40):
  - `account_service/customer_profiles`: `[]`;
  - `identity_service/deleted_customer_references`: `tombstone_900810`, with `subject_reference user_900801`, name, email and phone null, `email_hash` = the person's hash, `account_status DELETED`;
  - `security_service/security_audit_events`: `audit_record_900812` (`user_900801`).
- `evidence_9802` (kv log, captured 11:30): `account_900811` 404, looked up by the email.

## Expected row: `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_EXPOSED_PII | identity_service | tombstone_900810 | PRESENT | evidence_9801 | rule_15 ACCOUNT_TOMBSTONE → REDACT, condition "only a stable internal user_id is needed"; PS:13 "direct identifiers such as name, email, phone, and **email hash** must be removed"; R15-P3. **SPEC-ONLY** |
| 2 | REMEDIATION | REDACT_RECORD | identity_service | tombstone_900810 | REDACTED | "" | R15-R9 mapping (EXPOSED_PII → REDACT) |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900811 | ABSENT | "" | 404 at 10:20 and an empty declared `account_service` scope at 11:40 (S1; R15-R6; T54); R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900812 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RECORD_REDACTED | identity_service | tombstone_900810 | REDACTED | "" | CD-F26; CD-F27 (system `identity_service`, DEV case_31) |

- **Hash recognition:** the hash is linked to the person by the identities file's own formula (T59). It sits on a record that also carries `user_900801` as its own subject.
- **Order:** CD-F11/F12. VERIFY_RECORD_ABSENT < VERIFY_RECORD_PRESENT < VERIFY_RECORD_REDACTED.
- **Citation:** the bundle is the latest linked pre-audit file and holds the tombstone (R15-R14; T66 rule 1).

## What a failure looks like
- "Tombstone → VERIFY_RECORD_REDACTED" learned from case_31 → COMPLETE with 3 steps: a status flip.
- The hash not recognised as an identifier, because only name, email and phone are checked → the same COMPLETE row.
- The tombstone deleted (rule_01-style) instead of redacted: the stable reference must stay (PS:13).

## Not settled by the rules
- Whether gold treats a hash-only tombstone as exposed rests on PS:13 alone. If DEV or the developer rules otherwise, the expected row becomes COMPLETE with `VERIFY_RECORD_ABSENT account_900811`, `VERIFY_RECORD_PRESENT audit_record_900812` and `VERIFY_RECORD_REDACTED tombstone_900810`, all citing `evidence_9801`.
