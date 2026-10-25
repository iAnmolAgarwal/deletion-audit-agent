# R11 (robustness): unreadable evidence beside a readable file that alone would give COMPLETE

**Attacks:** the fail-closed rule when a failed file is *not* the case's only file. F11a's only file was missing, so "no evidence at all" caught it. Here every person has a readable kv log (`evidence_931101`) that on its own gives a clean COMPLETE row: account 404 and audit PRESENT. Three more files fail in three different ways:

| file | captured | failure | GP parse status | ties to |
|---|---|---|---|---|
| `evidence_931102` | 11:40 | listed in the manifest, **missing on disk** | ERROR "file not found" | unknown, since the content can't be read |
| `evidence_931103` | 11:40 | read-replica SQL **cut off mid-INSERT** (no COMMIT). Its first INSERT is complete and holds Bettany's email in a support record | ERROR "SQL could not be executed (OperationalError)" | Bettany (93102), by raw text |
| `evidence_931104` | 11:40 | snapshot-bundle JSON **truncated** mid-object. It holds Cyprian's email in a search document | UNKNOWN_FAMILY "no family sniffer matched the content" | Cyprian (93103), by raw text |

All three are captured after the readable file (11:30) and before `audit_at`. Each would therefore be the case's latest file, and the most current view of the state.

**Failure it catches:**
- "the readable files say COMPLETE, so COMPLETE";
- partial loading of a truncated SQL file (the first INSERT executing) and treating it as OK;
- a truncated JSON file silently dropped as "not evidence" because no family matched.

**Ruling:** T8, T42 ("an unreadable or unparsed file fails closed and is never COMPLETE"), T60, T86 (1) and T71 Q5 (FAILED_CLOSED). INTERFACES §4 rule 2 makes UNKNOWN_FAMILY a failure.
**Provisional:** n/a (robustness). There is deliberately no `expected_output.csv`; see `expected_assertions.json`.
**Custom eval case:** no.

## Inputs (all fictional)
- `case_93101`: Aurelio Penhallow `user_931010`; account_9310101 404 and audit_record_9310102 in `evidence_931101`.
- `case_93102`: Bettany Crewe `user_931020`; account_9310201 404 and audit_record_9310202 in `evidence_931101`. support_9310203 appears only in the cut-off SQL file.
- `case_93103`: Cyprian Lusk `user_931030`; account_9310301 404 and audit_record_9310302 in `evidence_931101`. search_9310303 appears only in the truncated JSON.
- All three are `COMPLETE` with plain deletion text.

## Assertions (`expected_assertions.json`)
| # | Assertion | Basis |
|---|---|---|
| 1 | Exactly 3 output rows: case_93101, 93102, 93103 | CD inv 16 |
| 2 | case_93102 and case_93103 are FAILED_CLOSED (INCOMPLETE), never COMPLETE or NOT_APPLICABLE. The reason names the failed file (`evidence_931103` and `evidence_931104` respectively) and its parse status | T8, T42, T86 (1) |
| 3 | No step cites `evidence_931102`, `evidence_931103` or `evidence_931104` | T8; an unread file proves nothing |
| 4 | No step names `support_9310203` or `search_9310303` as **verified** (absent, redacted, present). Their state is unknown, so they are never checked off | T8 |
| 5 | case_93101 is never COMPLETE (see "Not settled") | T42 precedence |
| 6 | Coherence reports H03 as hard for every FAILED_CLOSED row | T86 (1) |

## Not settled by the rules
- **Which cases "depend on" a missing file (case_93101).** T8 says "any case that depends on it fails closed", but a missing file's content is unknown, so dependency can't be shown from it.
  - Reading (i): every case whose `audit_at` is at or after the file's `captured_at` cannot be COMPLETE. That makes all three cases here FAILED_CLOSED.
  - Reading (ii): only cases whose person can be tied to the file fail closed. That ties no one to `evidence_931102`, so case_93101 would be COMPLETE on the readable file alone.
  - I assert (i). T42's "never COMPLETE" is the precedence rule, and (ii) can report COMPLETE while the unread file holds a live record. On real data T60 requires 0 such files at freeze, so the question matters only for robustness.
- **Whether a FAILED_CLOSED row may carry the readable file's two verification steps.** T86 (1) says "whatever steps the remaining inputs still give". In an INCOMPLETE row those verifications carry `""` (T77 rule 1). The assertions allow either `[]` or those two steps with empty citations.

## Ruling (T99 E, 2026-10-25)
The developer adopted reading (i) for a missing file: every case whose `audit_at` is after that file's capture time is never COMPLETE. `expected_assertions.json` holds it.
