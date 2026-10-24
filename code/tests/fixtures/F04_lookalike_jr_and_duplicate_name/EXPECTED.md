# F04: `.jr` look-alike email and a second person with the same name (COMPLETE)

**Tests:** records are linked to the person only by an exact identifier match. Two traps sit in the same file:
- a search hit for `elin.sarrow.jr@example.com`, a look-alike of the requester's email that belongs to nobody. Test has 15 `.jr` tokens next to real users in 8 primaries and 6 companions;
- a second, real person with the **same name**, "Elin Sarrow" (`user_900402`, no request). She has a live account (`account_900420`, HTTP 200) and a support ticket with `requester_name="Elin Sarrow"`. Test has 3 duplicated-name cases.

A name-based or fuzzy match turns this COMPLETE case INCOMPLETE and schedules a delete of another person's account.

**Provisional:** no.
**G8 custom eval case:** no.
**Parse:** `evidence_9401` OK (`kv_log`, 10 observations). The decoy hit's record identifier is the `.jr` email only. The second Elin's lines carry her own email and `user_900402`; the name is extracted as `name: elin sarrow`.

Rule keys as in F02.

## Inputs (all fictional)
- `case_90401`, `elin.sarrow@example.com`, `COMPLETE`; times as in F01.
- `user_identities.csv`:
  - `user_900401`, Elin Sarrow, `elin.sarrow@example.com`;
  - `user_900402`, Elin Sarrow, `e.sarrow2@example.net`.
- `evidence_9401` (kv log, captured 11:40), one trace each:
  1. `account_900410` 404, `lookup_key=elin.sarrow@example.com`;
  2. `search_900412` hit, `lookup_key` and `email` both `elin.sarrow.jr@example.com`, `customer_reference=null`;
  3. `account_900420` 200, `email=e.sarrow2@example.net`, `customer_reference=user_900402`;
  4. `support_900413`, `requester_name="Elin Sarrow"`, `requester_email=e.sarrow2@example.net`, `customer_reference=user_900402`;
  5. `audit_record_900411`, `subject_reference=user_900401`, retention until 2033.

## Expected row: `COMPLETE`, 2 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900410 | ABSENT | evidence_9401 | 404 linked by the requester's own email (S1); R15-R7, R15-R10 |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900411 | PRESENT | evidence_9401 | rule_12; R15-R10 |

- **No step for `search_900412`, `account_900420` or `support_900413`.** None carries any of user_900401's identifiers: `user_id`, current or old email or phone, or email hash (T49, T59; `notes/SYSTEM.md` "An identifier links only on an exact match"). DEV agrees: the hand-built look-alikes in case_01 and case_02 create no step, and both stay COMPLETE (`research/verify/12_verify.md` extra #5).
- **Identity:** the request email resolves to exactly one user. The duplicate name never enters resolution, because resolution is by email (R15-R1).
- **Status:** no finding ⇒ COMPLETE (R15-R13). COMPLETE verifications cite the case's one file (R15-R14, R15-R15; CD-F17, CD-F20a). The cited file names both resources and is captured at or before audit (CD-F21; T66 rule 1).

## What a failure looks like
- Substring, edit-distance or model-judged matching links `search_900412` → REPORT_REMAINING_RECORD.
- Name-based linking pulls in `account_900420` and `support_900413` → REMAINING / EXPOSED_PII on someone else's data. That is wrong and unsafe.

## Not settled by the rules
- `research/16` proposed a two-file variant: the account named only in an earlier log, with the COMPLETE steps citing a later file that does not name it. **Not built.** DEV cannot separate "cite the latest linked file" from "cite the file that names the resource": `research/15` R14's per-resource ablation still scores 20/22. Its expected citation is therefore unsettled. This fixture keeps everything in one file so the citation is fixed.
