# F01: non-deletion requests with negation and keyword traps

**Tests:** a request that names deletion words inside a negation, or asks for access or correction, gets `NOT_APPLICABLE` with `[]`, whatever the evidence shows. Every person here has live, identifier-linked records, so a misread produces a destructive plan for an account the person wants kept: the most harmful single error in `research/16` §1.1.

**Provisional:** yes. **SPEC-ONLY:** DEV has 0 NA rows (`notes/CONTRACT_DRAFT.md` F04b, F16, F28; `notes/gold_forensics.md` Q6 note A9).
**G8 custom eval case:** yes.
**Parse:** `evidence_9101` OK (`flat_record_list`, 11 observations).

Rule keys: `R15-Rn` = `research/15` rule n, re-run 22/22 in `notes/gold_forensics.md` (rules table, "report 15 R1–R17"); `CD-…` = `notes/CONTRACT_DRAFT.md` claim or §3 invariant; `PS:n` = `problem_statement.md` line n (organiser text, secondary).

## Inputs (all fictional)
Common times: `requested_at` 2026-06-08T08:00:00Z, `reported_at` 2026-06-09T02:00:00Z, `audit_at` 2026-06-10T12:00:00Z. All three rows are `reported_status=NOT_STARTED`.

| case | email | text (summary) | trap |
|---|---|---|---|
| case_90101 | `ROWAN.PELLAM@example.com` (uppercase) | "take me off your promotional mailing list **only**. Do **not** close or **delete** my account" | marketing opt-out; "close" and "delete" inside a negation |
| case_90102 | `marisol.quenby@example.org` | "I am **not** asking for **deletion**. Please send me a copy of the personal information you hold" | access request; "deletion" inside a negation |
| case_90103 | `teodor.halvik@example.net` | "correct it on my profile **without removing or erasing** any of my records" | correction request; "removing", "erasing" inside a keep phrase |

- `evidence_9101` (flat records JSON, captured 11:40, at or before audit). For each person:
  - Rowan: `account_900110` FOUND, `search_900111` FOUND, `data_flow_900112` ACTIVE, `audit_record_900113`;
  - Marisol: `account_900120` FOUND, `support_900121` IDENTIFIABLE, `audit_record_900122`;
  - Teodor: `account_900130` FOUND, `analytics_900131` IDENTIFIABLE, `backup_900132` ACTIVE, `audit_record_900133`.
- `system_activity.csv`: one `CLASSIFY_REQUEST … as non-deletion` row, for `account_900110` (case_90101) only. case_90102 and case_90103 have none, so the answer cannot rest on that row.

## Expected rows
```
case_90101,NOT_APPLICABLE,[]
case_90102,NOT_APPLICABLE,[]
case_90103,NOT_APPLICABLE,[]
```

## Derivation
1. **Intent.** None of the three asks for deletion or for verification of a deletion. Marketing opt-out, access and correction are the non-deletion types named in the spec. Basis: PS:19 ("`NOT_APPLICABLE` because the person did not request deletion"), PS:91; R15-P1 (provisional, spec only). SPEC-ONLY.
   - Not caught by A12/S10: DEV's "verify / check / audit my deletion" texts (case_21, 26, 27) are deletion requests. None of these three asks about a deletion at all.
2. **Steps.** NA ⇒ `[]` (PS:91 "no deletion or deletion verification is authorized", PS:96 row form; CD-F16, CD invariant 3). The FOUND and ACTIVE records produce **no** step: steps are emitted only on the deletion path (`../CLAUDE.md` §3).
3. **The CLASSIFY_REQUEST row is not the basis.** Per T71 Q10 it is a cross-check input only; the model's intent decides (T63). The two rows without it must give the same answer.

## What a failure looks like
- A keyword classifier fires on "delete", "deletion", "removing" → status INCOMPLETE with `REPORT_REMAINING_RECORD account_…` → `DELETE_RECORD`: unsafe.
- "Evidence shows data, so INCOMPLETE": any non-empty steps list.
- Uppercase email not resolved (case_90101): the row must still be NA; it must not become an identity failure row, since the email resolves case-insensitively (R15-R1).

## Not settled by the rules
- None for the expected row. Whether the run log should record the CLASSIFY_REQUEST agreement for case_90101 and the absence of one for the other two is an engine artifact, not part of the row.
