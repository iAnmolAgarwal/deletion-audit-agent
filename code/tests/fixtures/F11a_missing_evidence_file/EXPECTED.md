# F11a (robustness): the case's only evidence file is listed in the manifest but missing on disk

**Tests:** a failed read is an explicit failure state, never "nothing found" (`../CLAUDE.md` §3; T8; T42 "an unreadable or unparsed file fails closed and is never COMPLETE").

**Ruling:** T86 (1), applying G3's Q5 (accepted in T71 Q5). The row is **FAILED_CLOSED**: INCOMPLETE with whatever steps the remaining inputs still give (possibly none), its reason recorded in the run artifacts, and coherence reporting H03 as hard. The fixture asserts the reason and that the row is never COMPLETE; it does **not** assert a "correct" row. Real data must have 0 such rows at freeze (T60).
**Provisional:** n/a (robustness).
**G8 custom eval case:** no.
**Files:**
- `expected_assertions.json` holds the machine-readable assertions;
- there is deliberately no `expected_output.csv`.

**Parse:** `evidence_11001` **ERROR**, "file not found" (GP `parse_all`). This is the intended input.

## Inputs (all fictional)
- `case_91101`, `imogen.calloway@example.org`, `COMPLETE`; times as in F01.
- `user_901101`, Imogen Calloway.
- `evidence_files.csv` lists `evidence_11001` (`evidence/logs/resource_lookup_trace_20260610_114000.log`, captured 11:40). The file does not exist.
- No activity rows, so no input names an account for this person.

## Assertions (`expected_assertions.json`), each with its basis
| # | Assertion | Basis |
|---|---|---|
| 1 | The output has exactly one row, for `case_91101`; it is never skipped | CD invariant 16 |
| 2 | Row state is `FAILED_CLOSED`, with `deletion_status` INCOMPLETE | T86 (1), Q5 |
| 3 | `deletion_status` is never COMPLETE or NOT_APPLICABLE (the request is a plain deletion request) | T8, T42, T63 |
| 4 | Steps: any list the remaining readable inputs still give, possibly `[]` | T86 (1) |
| 5 | No step cites `evidence_11001`: an unread file proves nothing. Its ID is in the manifest, so a manifest-only check would pass it | T8; CD invariant 10 |
| 6 | Every `resource_id` in a step occurs in a readable input: no invented account | T28; `../CLAUDE.md` §3 |
| 7 | The FAILED_CLOSED reason in the run artifacts names `evidence_11001` and states the file could not be read (parse status ERROR) | T86 (1) |
| 8 | Coherence reports H03 as hard for this row | T86 (1) |

By hand, the remaining inputs give no step (no other evidence, no activity row, no account ID anywhere), so assertion 4 should come out as `[]`. This note is not asserted, per T86.
