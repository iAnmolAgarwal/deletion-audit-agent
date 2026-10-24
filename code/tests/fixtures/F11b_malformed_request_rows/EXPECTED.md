# F11b (robustness): malformed rows in `deletion_requests.csv` next to a valid one

**Tests:** malformed request rows neither crash the run nor take the valid row down with them. Neither do they turn into a confident answer.

**Provisional:** n/a. **Partly DECISION NEEDED.** Only the valid row's answer is settled. `expected_partial.csv` holds that one row; there is deliberately **no `expected_output.csv`**.
**G8 custom eval case:** no.
**Parse:** `evidence_11201` OK (`kv_log`, 4 observations).

## Inputs (all fictional)
| case | defect | other fields |
|---|---|---|
| case_91201 | none (valid) | `fenwick.brindle@example.net`, `COMPLETE`, times as in F01 |
| case_91202 | `audit_at = 2026-13-40T99:00:00Z` (month 13, day 40, hour 99) | `kestrel.imrie@example.net` (a real fixture user, `user_901202`) |
| case_91203 | empty `email` field | — |

`evidence_11201` (kv log, captured 11:40) holds `account_901210` (404, looked up by Fenwick's email) and `audit_record_901211` (`user_901201`). Nothing exists for `user_901202`.

## Expected for the valid row (settled): `COMPLETE`, 2 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_901210 | ABSENT | evidence_11201 | S1; R15-R7, R15-R10 |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_901211 | PRESENT | evidence_11201 | rule_12; R15-R10 |

Rule keys as in F02.

## Invariants for the malformed rows
1. **Every input `case_id` gets an output row,** and the valid row's answer is unchanged by its neighbours (CD invariant 16: one row per input `case_id`).
2. **Neither malformed row is COMPLETE.**
   - case_91202: with no valid `audit_at`, no evidence can be checked against it, and every citation needs `captured_at ≤ audit_at` (CD invariant 10).
   - case_91203: no identity can be resolved.
3. **case_91203 is not NOT_APPLICABLE:** an unresolved identity is never NA (T63). G3 gives it `FAILED_CLOSED(IDENTITY_UNRESOLVED)` (`notes/ARCHITECTURE_OPTIONS.md` §6).
4. **Each defect is logged** with the case, the column and the reason, never the cell value (T51 item 2 states that rule for coherence messages).

## Why the malformed rows are not settled
- `notes/INTERFACES.md` §3 says the three CSV loaders for activity, identities and the audit log "raise `InputFormatError`… rows are never skipped silently". If the request loader does the same, a whole-file raise produces no output at all, which breaks invariant 1 for the valid row.
- Row-level containment is the alternative: the malformed row becomes `FAILED_CLOSED`. For case_91202 that row would hold INCOMPLETE with `[]` (no finding is possible), the same shape conflict as F11a. Which behaviour ships is a developer decision.
