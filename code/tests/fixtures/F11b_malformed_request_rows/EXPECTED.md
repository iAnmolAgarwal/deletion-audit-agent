# F11b (robustness): malformed rows in `deletion_requests.csv` between valid ones

**Tests:** the request loader isolates rows (T86 (1)):
- a bad row whose `case_id` is readable becomes a **FAILED_CLOSED** row for that case;
- a bad row whose `case_id` is not readable is **reported in the run artifacts** and gets no output row;
- valid rows next to a bad one load and are answered normally.

**Provisional:** n/a (robustness). The two valid rows' answers are settled by DEV-confirmed rules.
**G8 custom eval case:** no.
**Files:**
- `expected_partial.csv` holds the two valid rows;
- `expected_assertions.json` holds the assertions for every row;
- there is deliberately no `expected_output.csv`.

**Parse:** `evidence_11201` OK (`kv_log`, 8 observations).

## Inputs (all fictional), in file order
| file line | case_id | defect | other fields |
|---|---|---|---|
| 2 | case_91201 | none (valid) | `fenwick.brindle@example.net`, `COMPLETE`, times as in F01 |
| 3 | case_91202 | `audit_at = 2026-13-40T99:00:00Z` (month 13, day 40, hour 99) | `kestrel.imrie@example.net` (`user_901202`) |
| 4 | *(empty)* | **unreadable case_id**; every other field is valid | `bram.tillet@example.net` (`user_901203`) |
| 5 | case_91203 | empty `email` field | — |
| 6 | case_91204 | **5 fields instead of 7** (`audit_at` and `request_text` missing) | `sable.quint@example.org` (`user_901204`) |
| 7 | case_91205 | none (valid) | `orla.fenmore@example.org`, `COMPLETE`, times as in F01 |

`evidence_11201` (kv log, captured 11:40) holds:
- for Fenwick: `account_901210` (404 by his email) and `audit_record_901211` (`user_901201`);
- for Orla: `account_901250` (404 by her email) and `audit_record_901251` (`user_901205`).

Nothing exists for the other people.

## Expected for the valid rows (settled; `expected_partial.csv`)
Both are `COMPLETE` with 2 steps, citing `evidence_11201`:

| case | # | phase | operation | system_id | resource_id | state | basis |
|---|---|---|---|---|---|---|---|
| case_91201 | 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_901210 | ABSENT | S1; R15-R7, R15-R10 |
| case_91201 | 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_901211 | PRESENT | rule_12; R15-R10 |
| case_91205 | 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_901250 | ABSENT | same |
| case_91205 | 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_901251 | PRESENT | same |

Citations follow R15-R14 and R15-R15. The two people share one file, but each row cites only its own records. Rule keys as in F02.

## Assertions (`expected_assertions.json`)
| # | Assertion | Basis |
|---|---|---|
| 1 | The output has exactly 5 rows: case_91201, 91202, 91203, 91204, 91205. There is none for the empty-case_id row | T86 (1); CD invariant 16 |
| 2 | case_91201 and case_91205 equal their rows in `expected_partial.csv`, unaffected by the bad rows between them | T86 (1) "valid rows next to it load normally" |
| 3 | case_91202, case_91203 and case_91204 are each `FAILED_CLOSED`: INCOMPLETE, never COMPLETE or NOT_APPLICABLE, steps possibly `[]`, H03 reported as hard | T86 (1), Q5. For case_91203 also T63 (unresolved identity is never NA) |
| 4 | Each FAILED_CLOSED reason in the run artifacts names its case and the column: `audit_at` for case_91202, `email` for case_91203, the field count for case_91204. It never repeats the cell value | T86 (1); T51 (2) states the no-cell-value rule for coherence messages |
| 5 | The empty-case_id row (file line 4) is reported in the run artifacts, without its cell values, and produces no output row | T86 (1) |

## Readings I chose (flagged)
- **"case_id readable"** means the first field is non-empty and has the `case_<digits>` shape. case_91204 has a readable case_id even though its row is short, so it is a FAILED_CLOSED row, not an unreadable one.
- **The empty-email row:** an empty email could be classed either as a malformed row or as an unresolved identity (`FAILED_CLOSED(IDENTITY_UNRESOLVED)`, G3 §6). Both are FAILED_CLOSED; the assertion only requires the reason to name the `email` column.
