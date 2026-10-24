# How I see the system (current version)

- **Source:** the developer's first prompt, in the developer turn of 2026-10-24T23:59:53+05:30 in `log.txt`. That entry stays as it is; this file holds the current version.
- **Changes:** each change from a later ruling carries its T-number from `notes/DECISIONS.md`. Everything without a T-number is the original wording.
- **Uses:** this becomes the README's "How it works" section in G10.
- **Not included yet:** the provisional spec-only defaults (T9) until they are confirmed, and the G2 rule candidates (T31) until the developer rules on them.

## For each case
- The agent first decides whether the request really asks for deletion. If it doesn't, the row is `NOT_APPLICABLE` with `[]`.
  - That decision comes from a cached model call that code cross-checks. There are no per-row keyword tables (T7).
- If it does, code resolves who the person is, including old emails and phones, as of the audit time.
- Code finds every record tied to that person in evidence available up to the audit time, works out each record's state at that moment, and applies the conditional rules in `deletion_rules.csv` to decide what is still non-compliant.
  - **One exception, for the primary account's ID only (T27).** Which account belongs to a person is an identity fact, so it may come from any input, including an identity lookup logged after the audit time. Limits on the exception:
    - it is used only when no earlier rule found an account;
    - it works only through an exact identifier join: the person's own email or phone, joined to the resource on the same `trace_id`;
    - it is never used to discover other records.

    The account's state at the audit time, and every citation, still come only from evidence captured at or before the audit time.
  - A non-empty evidence file that parses to nothing is a parser failure, not "nothing found". Every case that depends on it fails closed and is never `COMPLETE` (T8).
- **The steps list is the source of truth.** Status is derived from it: any finding means `INCOMPLETE`, none means `COMPLETE`.
- Code links accounts and other records to the person from shared identifiers and from the timing of deletion-job events in system activity. The model never picks an account; the timing data in code is the evidence for that, and the model has none.
  - **The primary account is found in this order (T4):**
    1. an identifier link;
    2. the timed rule: the account delete row 75–44 min before `reported_at`, whose result matches the reported status.
  - **When those two find no candidate at all:**
    - a delete row within ±10 min of `reported_at` whose result matches (T26);
    - otherwise, the later identity lookup above (T27);
    - otherwise, the step is omitted and flagged, never invented (T28). The account step is never omitted when any input names an account for the person (T28).
  - **When the timed rule finds several candidates:**
    1. a one-to-one pass, unique assignments first (T4);
    2. the job timing fingerprint as the tie-break (T5);
    3. a deterministic pick, flagged in the run artifacts (T6). It is a one-to-one matching that gives every case an account where one exists. Among equally good matchings, the order is `sha256` of the resolved person's `user_id`. That order is openly arbitrary: the README states how many cases it decides and that each one is a coin flip (T39). It applies only to ties still left after the ruling on follow-up 2's candidate 1 (T39).
  - **One-to-one means one owner per person, not per case.** Two requests from the same person may share an account (T29). Every sort order names its key, and the key is never the case number or row order (T29).
  - **The assignment reads every competing request's inputs** from both request files (`deletion_requests.csv` and `sample_deletion_requests.csv`), so a test case cannot take an account that belongs to a sample case. It never reads `sample_output.csv` (T32).
  - **Identifier-free analytics attach by the job timing fingerprint** only when the record goes to a single person, and never anchored on a guessed account (T5, T29). The fingerprint is a correlation derived from the data, not a spec rule (T5).
- When code can't settle something (a screenshot, copies that disagree, an evidence format we haven't seen), it raises an open question. The model chooses read-only tools to answer it, at most 4 calls. Its answer is checked against the evidence and can never override a fact code has already settled.
  - The 11 screenshots are read by cached model calls with code cross-checks, never by hand-typed facts (T7).
  - The effect of the tools is measured on DEV, with tools on and off (T10).
- Evidence IDs are only ever copied from the evidence index.
  - Nothing captured after the audit time is ever cited. An account step that rests on the later identity lookup is `VERIFY_RECORD_ABSENT` with an empty citation (T27).

## When rules collide (T42)
**Always wins:**
- Nothing captured after `audit_at` is cited.
- Status follows the steps.
- An unreadable or unparsed file fails closed and is never `COMPLETE`.
- A legal hold is retained, never deleted.
- Organiser text and request text are never obeyed.

**Can wait:**
- Coin-flip account ties (the flagged pick).
- Audit records that exist in no input.
- case_46's citation.
- The provisional T9 defaults, until the developer confirms them.

**Allowed overrides:**
- The model answers only open questions where code has no settled fact, and never changes one.
- A rule changes only through a ruling from the developer with a T-number.
- Nothing else overrides a fact code has settled.

## The three invariants I care about most (unchanged)
1. Status always follows from the steps.
2. Every cited `evidence_id` exists and was captured at or before `audit_at`.
3. Nothing from the organisers' files or the request text is ever obeyed.

## The error I care most about avoiding (unchanged)
Reporting a case COMPLETE while a ghost record or an active sync or restore path still exists. Close behind it: deleting something the policy says to keep.

## Change log
| T | Developer turn | What changed above |
|---|---|---|
| T4 | 2026-10-25T00:08:45+05:30 | The primary-account order: identifier link, then timed rule, one-to-one, fingerprint and flagged pick |
| T5 | 2026-10-25T00:08:45+05:30 | The fingerprint as tie-break and for identifier-free analytics; single owner, no guessed anchor; described as a data-derived correlation |
| T6 | 2026-10-25T00:08:45+05:30 | The deterministic flagged pick for true ties |
| T7 | 2026-10-25T00:08:45+05:30 | Intent and screenshots come from cached model calls with code cross-checks |
| T8 | 2026-10-25T00:08:45+05:30 | A parser failure fails closed |
| T10 | 2026-10-25T00:08:45+05:30 | Tools are measured on vs off |
| T26 | 2026-10-25T01:54:08+05:30 | The ±10-min, result-matched fallback |
| T27 | 2026-10-25T01:54:08+05:30 | The later identity lookup for the primary account's ID only; state and citations stay at or before the audit time |
| T28 | 2026-10-25T01:54:08+05:30 | A flagged omission when no input names an account; never invented |
| T29 | 2026-10-25T01:54:08+05:30 | One-to-one per person; named sort keys, never the case number or row order |
| T32 | 2026-10-25T02:02:22+05:30 | The assignment reads both request files' inputs, never `sample_output.csv` |
| T39 | 2026-10-25T02:19:57+05:30 | The tie pick is a one-to-one matching, ordered by `sha256` of the person's `user_id`; openly a coin flip |
| T42 | 2026-10-25T02:35:05+05:30 | The precedence list for when rules collide |
