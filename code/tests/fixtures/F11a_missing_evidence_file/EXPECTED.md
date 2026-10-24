# F11a (robustness): the case's only evidence file is listed in the manifest but missing on disk

**Tests:** a failed read is an explicit failure state, never "nothing found" (`../CLAUDE.md` §3; T8; T42 "an unreadable or unparsed file fails closed and is never COMPLETE").

**Provisional:** n/a. **No expected row: DECISION NEEDED.** The dataset has 0 such inputs (`research/16` §5), and no rule or DEV case defines the row. There is deliberately **no `expected_output.csv`** in this folder.
**G8 custom eval case:** no.
**Parse:** `evidence_11001` **ERROR**, "file not found" (GP `parse_all`). This is the intended input.

## Inputs (all fictional)
- `case_91101`, `imogen.calloway@example.org`, `COMPLETE`; times as in F01.
- `user_901101`, Imogen Calloway.
- `evidence_files.csv` lists `evidence_11001` (`evidence/logs/resource_lookup_trace_20260610_114000.log`, captured 11:40). The file does not exist.
- No activity rows, so no input names an account for this person.

## Invariants the engine's row must meet (each with its basis)
1. **A row is written** for `case_91101`. It is never skipped, and the output has one row per request (CD invariant 16).
2. **Not COMPLETE** (T8, T40, T42).
3. **Not NOT_APPLICABLE:** the request is a plain deletion request, so the intent does not change because a file is missing.
4. **Never cites `evidence_11001`:** an unread file cannot prove anything. The manifest ID exists, so a citation would pass a manifest-only check; that is why this invariant is listed.
5. **No invented account ID:** no input names one (T28: omitted and flagged, never invented).
6. **The failure is recorded** in the run artifacts with the file ID and the reason.

## Why the row is not settled
- G3's `FAILED_CLOSED` row class (`notes/ARCHITECTURE_OPTIONS.md` §6, accepted as T71 Q5) gives the status: INCOMPLETE, with "the validated subset" of steps and the reason logged. Here that subset is empty.
- INCOMPLETE with `[]` breaks the DEV-confirmed shape "INCOMPLETE ⇒ at least one FINDING, REMEDIATION and VERIFICATION" (CD invariant 3). A synthetic finding would break "findings cite evidence" (CD-F18).
- So the exact `steps_json` (`[]`, or something else) is a developer decision. T71 Q5 already requires 0 such rows at freeze, or the developer's acknowledgement.
