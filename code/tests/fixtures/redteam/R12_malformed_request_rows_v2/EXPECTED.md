# R12 (robustness): an 8-field row, a duplicated case_id, a quoted multi-line row and an out-of-enum status

**Attacks:** the request loader's row isolation (T86 (1), T87 (5)), past F11b. F11b had a bad timestamp, an empty case_id, an empty email and a short row. R12 adds:

| file line(s) | case_id | defect | person |
|---|---|---|---|
| 2 | case_93111 | **8 fields**: an unquoted comma in `request_text` ("Please delete my account, and all of my personal data.") | Delphine Ashcombe `user_931110` |
| 3 | case_93112 | none on its own | Eamon Tregarth `user_931120` |
| 4 | case_93112 | **the same case_id again**, for a different person | Fenella Tregarth `user_931121` |
| 5–6 | case_93113 | none: a **valid** quoted `request_text` with an embedded newline, so the record spans two physical lines | Godric Hallam `user_931130` |
| 7 | case_93114 | `reported_status = DONE`, not one of COMPLETE, PARTIALLY_COMPLETE or NOT_STARTED (PS:57) | Hesper Vinnicombe `user_931140` |

Every person has account 404 and an audit record in `evidence_931201` (kv log, captured 11:40). So every case would be a clean 2-step COMPLETE if its row were read.

**Failure it catches:**
- a line-based reader that splits case_93113 into two broken rows;
- a reader that silently keeps the first 7 fields of case_93111, or joins the extra field back in;
- a duplicate case_id that produces two output rows, or silently drops one person's request;
- an enum violation that crashes the run.

**Provisional:** n/a (robustness). Only case_93113's row is settled; it is in `expected_partial.csv`. The rest are `expected_assertions.json`.
**Custom eval case:** no.
**Parse:** `evidence_931201` OK (`kv_log`, 20 observations). Python's `csv` module reads the requests file as 6 records, with field counts 7, 8, 7, 7, 7, 7.

## Settled: case_93113, COMPLETE, 2 steps (`expected_partial.csv`)
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9311301 | ABSENT | evidence_931201 | S1; R15-R7, R15-R10 |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9311302 | PRESENT | evidence_931201 | rule_12; R15-R10 |

- The multi-line text is a valid CSV field (RFC 4180 quoting). Its second line ("Also remove any copies kept in backups or search.") does not change the intent.

## Assertions (`expected_assertions.json`)
| # | Assertion | Basis |
|---|---|---|
| 1 | Exactly 4 output rows: case_93111, 93112, 93113, 93114. Exactly **one** row for case_93112 | CD inv 16 (one row per case) |
| 2 | case_93113 equals its `expected_partial.csv` row | T86 (1) "valid rows next to it load normally" |
| 3 | case_93111 is FAILED_CLOSED (INCOMPLETE), never COMPLETE or NA. The reason names the field count (8 where 7 are required) and never repeats a cell value | T86 (1); T87 (5) (a readable case_id is non-empty `case_<digits>`); T51 (2) |
| 4 | case_93112 is never COMPLETE and never NA (UNSETTLED; see below) | — |
| 5 | case_93114 is never NA and never INCOMPLETE with findings (UNSETTLED; see below) | — |
| 6 | No run crashes; each bad row is reported in the run artifacts without its cell values | T86 (1); T51 (2) |

## Not settled by the rules
- **Duplicate case_id (case_93112).** No ruling covers it. Two people's requests share one ID, and the output allows one row per ID.
  - My reading: one FAILED_CLOSED row, its reason naming the duplicate.
  - Choosing either person would audit one request and silently drop the other. A merged audit would mix two people's records under one row.
  - The real dataset has 518 distinct case_ids in 518 rows (CD-F02), so this is robustness only.
- **Out-of-enum `reported_status` (case_93114).** The field is "a claim … not proof" (PS:57; CD-F29), and here the account is found by an identifier link, so the value changes nothing in the audit. Two readings:
  - (i) it is a malformed row → FAILED_CLOSED (T86 (1));
  - (ii) the claim is ignored → COMPLETE with VERIFY_RECORD_ABSENT `account_9311401` and VERIFY_RECORD_PRESENT `audit_record_9311402`, both citing `evidence_931201`.

  Both are allowed by assertion 5. The developer should pick one. The timed account rule (T4 step 2) does read `reported_status`, so under (ii) a case with no identifier link would need a defined fallback.
