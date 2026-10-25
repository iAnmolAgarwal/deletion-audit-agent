# R10: tombstones holding a raw old phone or an old-email hash, another person's PII tombstone, and a clean one

**Attacks:** rule_15 (ACCOUNT_TOMBSTONE REDACT; "only a stable internal user_id is needed"). F08 had a tombstone holding the *current* email's hash. R10 pushes past it in four ways, all in one `identity_service/deleted_customer_references` collection:
- `tombstone_9309102` (case 93091) holds a raw phone, `+44 7700 900963`, which is Imelda's **old** phone (`audit_931001`). Everything else is null apart from `subject_reference`.
- `tombstone_9309302` (case 93093) holds only `email_hash` = sha256 of Leopold's **old** email (`audit_931002`/`931003`).
- `tombstone_9309109` belongs to Hester Rookwood (`user_930911`, no request). She shares Imelda's surname, and her tombstone holds her own name and raw email. It must produce **no** step for anyone.
- `tombstone_9309202` (case 93092) is clean: only `subject_reference`. It is the DEV-confirmed COMPLETE shape (case_31).

**Failure it catches:**
- a PII check against *current* identifiers only (93091, 93093 → COMPLETE);
- a check of name and email only (93091);
- surname or collection-level attribution (Hester's tombstone → a finding in 93091);
- "every tombstone is a finding" (93092 → INCOMPLETE).

**Provisional:**
- **93091 and 93093: yes.** A tombstone still holding personal data is a finding by the T9 default (R15-P3). No DEV tombstone holds PII (`notes/gold_forensics.md` Q6). The spec names phone and email hash explicitly (PS:13; AG:300 secondary). T86 (2) confirms that an email hash is personal data, and T59 puts old emails, their hashes and old phones in the identifier set. **SPEC-ONLY.**
- **93092: no** (CD-F27, DEV case_31).

**Custom eval case:** no. F08 already holds that role for this family.
**Parse:**
- `evidence_931001` OK (`snapshot_bundle`, 7 observations, 3 declared scopes). Record identifiers: tombstone_9309102 `+447700900963` and `user_930910`; tombstone_9309302 sha256(old email) and `user_930930`; tombstone_9309109 Hester's name, email and `user_930911`; tombstone_9309202 `user_930920` only;
- `evidence_931002` OK (`kv_log`, 6).

## Inputs (all fictional)
| case | person | identity history | account (kv log, 11:30) |
|---|---|---|---|
| 93091 | Imelda Rookwood `user_930910` | phone `+44 7700 900963` → `+44 7700 900962` (2026-03-01) | account_9309101 404 |
| 93092 | Casimir Wrenfield `user_930920` | none | account_9309201 404 |
| 93093 | Leopold Garnock `user_930930` | email `leo.garnock@example.org` → `leopold.garnock@example.com` (2026-03-01) | account_9309301 404 |

`evidence_931001` (snapshot bundle, captured 11:40; every snapshot at 11:40) holds:
- `account_service/customer_profiles` = `[]`, a declared-complete absence;
- the four tombstones;
- `security_service/security_audit_events` with audit_record_9309103, 9309203 and 9309303.

## Expected rows
### case_93091: INCOMPLETE, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_EXPOSED_PII | identity_service | tombstone_9309102 | PRESENT | evidence_931001 | rule_15; PS:13 ("phone … must be removed"); R15-P3; old phone in the identifier set (T59). **SPEC-ONLY** |
| 2 | REMEDIATION | REDACT_RECORD | identity_service | tombstone_9309102 | REDACTED | "" | R15-R9 mapping |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9309101 | ABSENT | "" | S1; empty declared scope at 11:40 (T54); R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9309103 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RECORD_REDACTED | identity_service | tombstone_9309102 | REDACTED | "" | CD-F26 |

### case_93092: COMPLETE, 3 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9309201 | ABSENT | evidence_931001 | S1; the file's declared `account_service` scope covers it (T66 rule 2); DEV case_31 (U6) |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9309203 | PRESENT | evidence_931001 | rule_12; R15-R10 |
| 3 | VERIFICATION | VERIFY_RECORD_REDACTED | identity_service | tombstone_9309202 | REDACTED | evidence_931001 | rule_15 satisfied; R15-R10; CD-F27 |

- **Citation:** the bundle is Casimir's latest linked file at or before audit (11:40 > the 11:30 kv log), as in DEV case_31 (R15-R14).

### case_93093: INCOMPLETE, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_EXPOSED_PII | identity_service | tombstone_9309302 | PRESENT | evidence_931001 | rule_15; PS:13 ("email hash"); T86 (2); hash of an old email (T59 (2)). **SPEC-ONLY** |
| 2 | REMEDIATION | REDACT_RECORD | identity_service | tombstone_9309302 | REDACTED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9309301 | ABSENT | "" | S1; T54 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9309303 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RECORD_REDACTED | identity_service | tombstone_9309302 | REDACTED | "" | CD-F26 |

- **No step anywhere for `tombstone_9309109`:** its identifiers belong to `user_930911`, who has no case (T49).

## What a failure looks like
- 93091 → COMPLETE with 3 steps: the old phone is not recognised.
- 93093 → COMPLETE with 3 steps: the old hash is not recognised, or only current-email hashes are computed.
- 93091 → a second finding on `tombstone_9309109` (surname match, or "any PII in the collection").
- 93092 → INCOMPLETE, or the tombstone DELETEd (the stable reference must stay, PS:13).

## Not settled by the rules
- 93091 and 93093 are ruled (T9, T86 (2)) but not DEV-confirmed. If the hidden key treated them as clean, each would become COMPLETE with 3 cited steps, the same shape as 93092.
