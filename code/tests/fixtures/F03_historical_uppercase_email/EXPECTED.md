# F03: request email that matches only a historical identifier, in upper case

**Tests:**
- the request email is the person's **old** email (only in `user_audit_log.csv`), written in upper case;
- every evidence line is keyed by that old email or by `user_id`, never by the current email;
- one evidence token is mixed-case (`N.Voss77@Example.NET`).

Test has 100 historical-email requests and 51 cases whose primary file links the person only by an old email; it has 20 uppercase request emails and 16 uppercase evidence tokens (`research/16` §2.1).

**Provisional:** no. Every step's rule is DEV-confirmed; the uppercase handling follows from case-insensitive email matching (R15-R1).
**G8 custom eval case:** no (a good candidate if a fourth case is wanted).
**Parse:** `evidence_9301` OK (`kv_log`, 6 observations; the mixed-case token is normalized to `n.voss77@example.net`).

Rule keys as in F02.

## Inputs (all fictional)
- `case_90301`, `N.VOSS77@EXAMPLE.NET`, `COMPLETE` (a claim: CD-F29); times as in F01.
- `user_900301`, Nadine Voss, current email `nadine.voss@example.org`.
- `user_audit_log.csv`, both at 2026-03-01T10:00:00Z:
  - `audit_90001`: email `n.voss77@example.net` → `nadine.voss@example.org`;
  - `audit_90002`: email_hash sha256(old) → sha256(new).
- `evidence_9301` (resource_lookup_trace kv log, captured 11:40):
  - `account_900310` 404, looked up by `lookup_key=n.voss77@example.net`;
  - `support_900311` `support_ticket_read_completed`, with `requester_email=N.Voss77@Example.NET` and every other requester field null;
  - `audit_record_900312`, `subject_reference=user_900301`, retention until 2033.

## Expected row: `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_EXPOSED_PII | support_platform | support_900311 | PRESENT | evidence_9301 | rule_05 → REDACT; R15-R9 (DEV support redact 4/4, including case_19's ticket-read log). The requester email is the person's old identifier (R15-R1; DEV case_30 is keyed by an old email) |
| 2 | REMEDIATION | REDACT_RECORD | support_platform | support_900311 | REDACTED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900310 | ABSENT | "" | 404 linked by the old email on the same trace (S1, T59); R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900312 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RECORD_REDACTED | support_platform | support_900311 | REDACTED | "" | CD-F26 |

- **Identity:** the request email resolves case-insensitively through `user_audit_log` to `user_900301` (R15-R1; PS:123 secondary). The person's identifier set includes the old email and its hash (T59).
- **Order:** CD-F11. VERIFY_RECORD_ABSENT < VERIFY_RECORD_PRESENT < VERIFY_RECORD_REDACTED, so `support_platform` comes last even though it sorts after `security_service` only by system.
- **Evidence:** as in F02 (R15-R14, R15-R15).
- **rule_05's condition** ("shared … context that must be retained") is not visible in a ticket-read line. Following `notes/gold_forensics.md` Q6, the action is mapped and the condition is not gated (DEV 4/4 REDACT, 3 of them without visible message text).

## What a failure looks like
- Evidence searched with the current email only: no support finding, so COMPLETE. With no identifier link for the account either, the account step depends on activity rows, which this fixture does not have.
- Case-sensitive matching: `N.VOSS77@EXAMPLE.NET` resolves to no one, so the row becomes an unresolved-identity row (T63).
- Support mapped to DELETE (rule_06) instead of REDACT: no attachment cue exists (R15-R12).

## Not settled by the rules
- None.
