# F05: post-audit recreation, a post-audit line inside a pre-audit file, and an in-file FOUND→NOT_FOUND series (COMPLETE)

**Tests:** state is judged **at `audit_at`, per record time**. Four traps:
1. inside a file captured before audit, `account_900510` reads FOUND (09:30), then NOT_FOUND (11:00), then **FOUND again on 2026-06-12**, after both the file's capture and `audit_at` (test: case_135, case_383);
2. a snapshot bundle captured **after** audit shows the account recreated, ACTIVE with full PII, and a new search document (test: 11 post-audit recreations; DEV case_27);
3. that same post-audit bundle holds one snapshot dated **before** audit (11:55) in which the account collection is empty;
4. a post-audit `SYNC_RECORD` activity row claims a connector repopulated `search_900512`.

**Provisional:** partly. Trap 1 (a line dated after audit inside a pre-audit file) is **SPEC-ONLY**: 0 DEV examples. Traps 2–4 rest on DEV-confirmed rules.
**G8 custom eval case:** no.
**Parse:**
- `evidence_9501` OK (`flat_record_list`, 4 observations);
- `evidence_9502` OK (`snapshot_bundle`, 2 observations, 3 declared scopes, including the empty 11:55 `account_service` scope).

Rule keys as in F02.

## Inputs (all fictional)
- `case_90501`, `ivo.trembath@example.com`, `COMPLETE`; times as in F01 (`audit_at` 2026-06-10T12:00:00Z).
- `evidence_9501` (flat records JSON, captured 2026-06-10T11:40:00Z):
  - `account_900510` USER_PROFILE: FOUND at 09:30, NOT_FOUND at 11:00, FOUND at 2026-06-12T09:00 (subject: the person's email);
  - `audit_record_900511` SECURITY_AUDIT_LOG FOUND at 11:00 (`user_900501`).
- `evidence_9502` (snapshot bundle, captured **2026-06-12T12:00:00Z**, after audit):
  - snapshot at 2026-06-10T11:55: `account_service/customer_profiles` with `records: []`;
  - snapshot at 2026-06-12T12:00: `account_900510` ACTIVE (name, email, phone);
  - snapshot at 2026-06-12T12:00: `search_900512` (the person's email).
- `activity_90501` (2026-06-11T08:00, post-audit): `SYNC_RECORD … data_flow_900513 … repopulated downstream resource search_900512`.

## Expected row: `COMPLETE`, 2 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900510 | ABSENT | evidence_9501 | latest observation at or before audit: NOT_FOUND at 11:00, then the empty declared scope at 11:55 (R15-R6, R15-R4, T54). Later observations are ignored (R15-R5, DEV case_27) |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900511 | PRESENT | evidence_9501 | rule_12; R15-R10 |

- **Citation:** the case's one file is the latest linked file captured at or before audit: `evidence_9501` (R15-R14). `evidence_9502` is captured after audit and is never cited (CD-F21; AG:316 secondary). Its 11:55 snapshot may inform state but not citation (R15-R4: DEV 5 pairs).
- **No step for `search_900512`:** it exists only in a post-audit snapshot (R15-R5).
- **No step for `data_flow_900513`:** it appears only in a post-audit activity row. Activity rows are claims (CD-F29; verify-12 R14), and resources are discovered from evidence (`notes/SYSTEM.md`).
- **Status:** no finding ⇒ COMPLETE.

## SPEC-ONLY part
- Trap 1's correct reading (the 2026-06-12 FOUND line is not the state at audit, though the file was captured before audit) has no DEV example. Basis: PS:124 ("Determine the resource state at `audit_at`"), AG:224 and AG:298 (secondary), and `research/16` §3.3. Trusting file capture time alone would yield REPORT_REMAINING_RECORD → DELETE → INCOMPLETE.
- The in-file FOUND→NOT_FOUND series uses the same latest-wins rule as DEV case_26's cross-file series (R15-R6). The in-file form itself has no DEV example.

## What a failure looks like
- File-level time filtering (trusting every line in a pre-audit file) → account REMAINING.
- "Any FOUND observation means present" → account REMAINING.
- Citing `evidence_9502`, or adding `search_900512` from it.
