# R04: look-alike and same-name decoys that share a trace with the requester's lookup key

**Attacks:** linking by trace instead of by a record's own key.

In F04 the decoy search hit was *looked up* by the look-alike email, so nothing tied it to the requester. In R04 every decoy sits on a trace whose **lookup key is the requester's own current email**. Only the record's own key shows whose record it is:
- `search_9303102`: looked up by `philippa.dunmore@example.com`. The hit's own `email` and `correlation_key` are `philippa.dunmore.jr@example.com`, a `.jr` look-alike that belongs to no user.
- `account_9303103`: looked up by the requester's email. The record's own `customer_reference` is `user_930311` and its `email` is `p.dunmore@example.org`. That is a **second, real person with the same name**, "Philippa Dunmore", who has no request.
- `analytics_9303105`: looked up by the requester's email. Its own `email_hash` is sha256 of the **look-alike** email.
- `analytics_9303104` is the opposite trap, a true link. Its only identifier, as both lookup key and own `email_hash`, is sha256 of the requester's **old** email `pip.dunmore@example.net` (`audit_930401`/`930402`). It must link (T59 (2)–(3)).

**Failure it catches:**
- a trace-join linker ("same trace as the person's lookup key → the person's record");
- name matching;
- an identifier set that leaves out hashes of old emails.

**Provisional:** no. T49 and T59 settle the link rules ("a look-alike … never links, even through a shared trace"; "a line's own key beats a trace lookup", compared against the complete identifier set). R15-R1 is DEV-confirmed (case_12's record is linked only by an old hash). The analytics mapping is DEV-confirmed (R15-R9 analytics 4/4).
**Custom eval case:** **yes.** *A correct system links a record only when the record's own key exactly matches one of the person's identifiers (old-email hashes included), so it never adopts a look-alike's or a namesake's record because they share the person's lookup trace.*
**Parse:** `evidence_930401` OK (`kv_log`, 12 observations). The parser keeps the two roles apart:
- `search_9303102` has record identifiers = the `.jr` email and lookup identifiers = the requester's email;
- `account_9303103` has record identifiers = `user_930311` and `p.dunmore@example.org`;
- `analytics_9303104` has record identifiers = sha256(old email).

## Inputs (all fictional)
- `case_93031`: `philippa.dunmore@example.com` (current), `COMPLETE`.
- `user_identities.csv`:
  - `user_930310` Philippa Dunmore, `philippa.dunmore@example.com`;
  - `user_930311` Philippa Dunmore, `p.dunmore@example.org`.
- `user_audit_log.csv`: user_930310's email changed `pip.dunmore@example.net` → current on 2026-03-01, with the matching email_hash row.
- `evidence_930401` (kv log, captured 11:40), one trace per resource:
  1. account_9303101 404 (lookup by the requester's email);
  2. search_9303102 (the `.jr` decoy on the requester's trace);
  3. account_9303103 200 (the namesake on the requester's trace);
  4. analytics_9303104 (the old-email hash);
  5. analytics_9303105 (the hash of the `.jr` email, on the requester's trace);
  6. audit_record_9303106 (`subject_reference user_930310`).

## Expected row: `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_EXPOSED_PII | analytics_platform | analytics_9303104 | PRESENT | evidence_930401 | rule_07 ANONYMIZE (still attributable via the hash); R15-R9; link by own key = hash of old email (T59; R15-R1) |
| 2 | REMEDIATION | ANONYMIZE_RECORD | analytics_platform | analytics_9303104 | ANONYMIZED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9303101 | ABSENT | "" | S1; R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9303106 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RECORD_ANONYMIZED | analytics_platform | analytics_9303104 | ANONYMIZED | "" | CD-F26 |

- **No step for `search_9303102`, `account_9303103` or `analytics_9303105`.** In each, the record's own key is not in user_930310's identifier set: `user_930310`, both emails, `+44 7700 900953`, and sha256 of both emails. The own key beats the shared lookup key (T49, T59 (3)).
- **Primary account:** account_9303101 is the only account whose link is not overruled by its own key. account_9303103's own `customer_reference` names another user, so it is excluded, even though its trace carries the requester's email (T29: one account per person).
- **Order:** CD-F11. VERIFY_RECORD_ABSENT < PRESENT < ANONYMIZED.

## What a failure looks like
- Trace-join linking → `REPORT_REMAINING_RECORD search_9303102`, `REPORT_REMAINING_RECORD account_9303103` (deleting the namesake's live account) and `REPORT_EXPOSED_PII analytics_9303105`.
- account_9303103 picked as the primary account (200 = "found") → the requester's real 404 account is dropped.
- Old-email hash missing from the identifier set → no analytics finding → COMPLETE with 2 steps.

## Not settled by the rules
- None. Whether a hash-only analytics record is "still attributable to a user" (rule_07's condition) follows from T86 (2): an email hash is personal data, a key back to the person.
