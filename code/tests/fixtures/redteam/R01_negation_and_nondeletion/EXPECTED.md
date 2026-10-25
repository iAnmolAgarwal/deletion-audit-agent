# R01: negation and other non-deletion requests, harder than F01

**Attacks:** intent classification. Every person has live, identifier-linked records, so a misread in either direction produces a wrong row:
- reading a non-deletion request as deletion yields a destructive plan for an account the person wants kept;
- reading a deletion request as non-deletion yields `[]` while data remains.

F01 covered a marketing opt-out, an access request and a correction, each with the deletion word inside a plain negation. R01 adds:
- a double negation that *does* ask for deletion;
- an export request that mentions past deletions;
- "delete me from your marketing lists only";
- a hypothetical;
- a quoted deletion request from someone else;
- "verify my deletion is complete" with a false `CLASSIFY_REQUEST … non-deletion` intake row;
- a correction phrased with "remove".

**Failure it catches:**
- a keyword classifier (fires on "delete", "deletion", "remove");
- a negation counter that treats any "not" as a refusal (93001);
- trusting the intake row over the text (93006).

**Provisional:** yes for the five NA rows. 0 DEV rows are NA (CD-F04b, CD-F16, CD-F28), so they are **SPEC-ONLY**. Case 93001's intent is also SPEC-ONLY, since DEV has no double negation; its steps are DEV-confirmed. Case 93006 is not provisional (CD-A12, DEV case_21/26/27).
**Custom eval case:** no. F01 already serves that role for this family.
**Parse:** `evidence_930101` OK (`kv_log`, 30 observations).

## Inputs (all fictional)
One kv log, `evidence_930101` (captured 2026-07-14T11:40:00Z), holds every person's records.

| case | person | reported | text (summary) | records in evidence |
|---|---|---|---|---|
| 93001 | Corvin Ashgrove `user_930010` | PARTIALLY_COMPLETE | "It is **not** true that I want to keep this account. I would **not** object to you deleting it, and I **don't** want any of my personal data left behind." | account_9300101 404; search_9300102 hit (his email); audit_record_9300103 |
| 93002 | Dagny Wexford | NOT_STARTED | "Please **export** a copy … including the history of anything you **deleted** on my behalf … export request only; don't delete or change anything." | account_9300201 200; audit_record_9300202 |
| 93003 | Ferris Quillon | NOT_STARTED | "**Delete me from your marketing lists only.** Keep my account and my order history." | account_9300301 200; analytics_9300302 (his email) |
| 93004 | Ysolde Brannock | NOT_STARTED | "**If** I decided to close my account some day, would you also delete …? I am only asking … please don't do anything yet." | account_9300401 200; search_9300402 hit |
| 93005 | Tamsin Gorewell | NOT_STARTED | "My sister asked me to forward her message: '**Please delete my account and all my data.**' That is her request, not mine … I would just like to know which systems hold my details." | account_9300501 200. The sister, Briony Gorewell (`user_930051`, no request), has account_9300511 200 |
| 93006 | Bertil Hanscombe | COMPLETE | "Please **verify** that my deletion is complete …" | account_9300601 404; audit_record_9300602 |
| 93007 | Odalys Fenwright | NOT_STARTED | "Please **remove** my old phone number from my profile and replace it with +44 7700 900939. Keep my account …" | account_9300701 200; support_9300702 (her email) |

`activity_930101` (2026-07-12T09:15) is a `CLASSIFY_REQUEST` row: "Privacy intake classified request for account_9300601 as non-deletion". It belongs to case 93006 and **contradicts** its text.

## Expected rows
| case | status | steps |
|---|---|---|
| 93001 | INCOMPLETE | 5 (below) |
| 93002, 93003, 93004, 93005, 93007 | NOT_APPLICABLE | `[]` |
| 93006 | COMPLETE | 2 (below) |

### case_93001: INCOMPLETE, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | search_service | search_9300102 | PRESENT | evidence_930101 | rule_03 Always DELETE; R15-R9 (DEV search 8/8). The hit carries the requester's own email (S1, T49) |
| 2 | REMEDIATION | DELETE_RECORD | search_service | search_9300102 | ABSENT | "" | R15-R9; CD-F19 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9300101 | ABSENT | "" | 404 on a lookup by his email (S1); R15-R7, R15-R10; CD inv 13 |
| 4 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_9300102 | ABSENT | "" | CD-F26 |
| 5 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9300103 | PRESENT | "" | rule_12 RETAIN; R15-R10 (DEV 17/17 generated rows) |

- **Intent (SPEC-ONLY):** each negation is itself negated. "Not true that I want to keep", "would not object to deleting" and "don't want any … left behind" all ask for deletion.
  - R15-R2 says a request is deletion-authorized unless a negation **scopes the deletion away**. Here no negation does.
  - PS:19 is secondary support.
- **Order:** CD-F10, F11, F12. **Evidence:** R15-R14 and R15-R15, with one file, the latest linked file at or before audit. T77 rules 1 and 3.

### case_93006: COMPLETE, 2 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9300601 | ABSENT | evidence_930101 | S1, R15-R7; cited file names the resource (T66 rule 2) |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9300602 | PRESENT | evidence_930101 | rule_12; R15-R10; cited file names the resource (T66 rule 1) |

- **Intent:** a request to verify a deletion is a deletion request. This is CD-A12, settled (a) on DEV case_21, 26 and 27, and T63.
- **The intake row loses.** T71 Q10 makes the CLASSIFY_REQUEST rows a cross-check only, and T63 says the model's intent call decides. An engine that copies the intake label outputs `NOT_APPLICABLE, []`.

### The five NA rows
Each request authorizes no deletion, so the row is `NOT_APPLICABLE` with `[]` (PS:19, PS:91, PS:96; AG:296 lists "access, correction, export, marketing opt-out"; R15-P1; CD-F16). Every one is SPEC-ONLY.
- **93002 (export):** "deleted" names past events, and the request explicitly forbids deletion.
- **93003 (marketing opt-out):** the imperative "Delete me from your marketing lists" is scoped by "only" and followed by "Keep my account". Rule_10 (MARKETING_PROFILE DELETE) is not reached, because the request authorizes no deletion audit (AG:296: marketing opt-out is NA).
- **93004 (hypothetical):** a conditional question, and the person says they have not decided.
- **93005 (quoted request):** the deletion sentence is the sister's words. The requester is Tamsin (the email resolves to `user_930050`), and what Tamsin asks for is access. Briony's live account must get **no** step and no row of its own, because she has no case.
- **93007 (correction):** "remove my old phone number … replace it" is a correction (AG:296). Rule_02 SECONDARY_IDENTIFIER is not reached, for the same reason as 93003.

## What a failure looks like
- 93001 → `NOT_APPLICABLE, []`: a negation counter hides a live search entry.
- 93002, 93003, 93004, 93005, 93007 → any non-empty row: a destructive plan for a person who asked to keep their account. 93005 under a "quoted text is the requester's" bug would also make Briony's account a candidate.
- 93006 → `NOT_APPLICABLE, []` (intake row trusted) or INCOMPLETE (anything else).

## Not settled by the rules
- 93003 and 93007 sit closest to the line: each contains an imperative removal of one data item, a marketing membership or an old phone number. The expected NA follows AG:296's list of request types. No DEV row tests it. If the hidden key treated either as a partial deletion, the row would not be NA, and the rules give no shape for a partial deletion, so it is flagged.
