# G5 fix-round verifier report (orch-verifier, high)

directed_by 2026-10-25T11:28:05+05:30 (T90, T99 A). Brief: scratchpad `g5fix1_verifier_brief.md`; the diff: scratchpad `g5fix1.diff`. Saved verbatim by main from the agent's final message.

---

**Verdict: PASS.** 2 findings: 0 BLOCKER, 0 MAJOR, 2 MINOR. Nothing blocking. Under T93, main can commit G5, and the two MINORs go on the G9 list.

All five first-round findings are fixed. DEV and test outputs are byte-identical to G5 and to the pre-fix code. The holdout guard holds, and T69 is kept. I edited no repo file, made no model calls, and never opened `.env` or `dataset/sample_output.csv`.

## Findings

**1. MINOR: the new rule fails a row closed on evidence captured after `audit_at`.**
- **Where:** `code/deletion_audit/engine.py:518-520`. It counts an observation as "seen" by its line time only, never by the file's `captured_at`.
- **Reproduce:** `cd /tmp/g5v2/post/code && <repo>/.venv/bin/python -B -I /tmp/g5v2/scripts/edge_probe.py /tmp/g5v2/post/code`. The setup is a record known only by a catalog row, plus a stateless DEBUG line timed before `audit_at` in a file captured after it.
  - Pre-fix code: `COMPLETE fc=None`.
  - Fixed code: `INCOMPLETE fc=UNINTERPRETED_RECORD`.
- **Expected vs actual:** expected the R8 no-step outcome, COMPLETE, because evidence captured after `audit_at` doesn't count (`../CLAUDE.md` §3). Actual: FAILED_CLOSED.
- **Bug class:** an "at or before `audit_at`" check made by line time without capture time.
- **Why MINOR:** it errs toward failing closed, never toward a wrong COMPLETE, and it hits 0 real rows on DEV or test.

**2. MINOR: `notes/INTERFACES.md` §7.1 is out of date.**
- **Where:** `notes/INTERFACES.md:602-643`.
- **Reproduce:** `grep -n "HoldoutRefused\|refuse_holdout\|UNINTERPRETED_RECORD\|_dev_ids" notes/INTERFACES.md` returns nothing.
- **Expected vs actual:** §7.1 should list the four interface changes; it lists none of them. The fix report handed this to main.
- **Bug class:** docs not matching code.

## Items 1–8

| # | Verdict | Basis |
|---|---|---|
| 1 Five fixes | Pass | Pre-fix snapshot (`/tmp/g5v2/pre`) with the new tests laid over it: `test_request_rows` fails 5/5, `test_uninterpreted` 2 (both fail-closed tests), `test_prewrite` 2 (both `COMPLETE_VERIFICATION_ONLY` tests), `test_holdout_guard` fails to import. All pass on the fixed code. The fix-1 tests pass on pre-fix code, as expected, because they exist to kill mutations. The hand-written order matches the contract's F10–F12 and the production table. The first verifier's repros now give: p1 a MALFORMED_REQUEST row for case_91201 and no row for `zzz` or `Robert.Tables`; p2 `UNINTERPRETED_RECORD`; valprobe a `COMPLETE_VERIFICATION_ONLY` hard failure. |
| 2 T69 kept | Pass | `/tmp/g5v2/scripts/t69_probe.py`, 8 variants. A hold naming no resource (by user_id, by email, or with `record_id`/`hold_id` fields) gives COMPLETE, no step, no flag. A hold that does carry a resource ID gives `VERIFY_RECORD_PRESENT`, not FAILED_CLOSED. On DEV the output is byte-identical and the rule fires 0 times. |
| 3 Holdout guard | Pass | `/tmp/g5v2/scripts/guard_probe.py`, synthetic data only. A list, tuple, duplicate list or iterator naming a holdout ID is refused with 0 `build_context` calls and 0 files opened. A `"test"` run is refused when the test file names a holdout ID, whether its row is valid or malformed, and writes nothing. A holdout request in the sample file only still runs, and no holdout ID appears in the output. The CLI exits 2, writes nothing and names no ID. `run()` takes no unlock argument. The `__main__` docstring matches the code. |
| 4 Mutations | Pass | First verifier's set: 35/35 killed, including the 4 earlier survivors. My own: 13/13 killed (`/tmp/g5v2/scripts/muts.json`), covering the new rule switched off or demoted, its time window, the validator check, the old case-ID regex and trimming, three clash-handling variants, and both guard calls plus the CLI exit code. |
| 5 No regression | Pass | DEV `641dbc8d…` and test `cf2a90b0…` under `/tmp/g5v2/runs`, equal across PYTHONHASHSEED 1 and 98765, and equal to the pre-fix code's output. FAILED_CLOSED is 18 (NOTHING_FOUND 9, UNPARSED_DEPENDENCY 9). Coherence finds 58 hard lines, all H03, in exactly those 18 rows. Suites: 413 OK and 252 OK. Ruff and mypy are clean. |
| 6 Interfaces | Pass | An AST diff of the two trees shows only the four listed changes. Beyond them, only the private `_load_file` return type and one new `VALIDATOR_PARTS` entry changed. |
| 7 Fail-closed paths | Pass | No step can be lost: `failed_closed=True` only blanks verification citations. A malformed or clashing row never takes the sample file's answer (mutations N7 and N8 are killed). No DEV row changes, and the rule fires 0 times on DEV and test. The one hypothetical false fail-closed is finding 1. |
| 8 Agent patch | Pass | The repo's `code/tests/agent` equals the prefix plus the patch. After mapping the IDs back, what's left is blank lines and one docstring my normalizer rewrote. Assert counts are 328 before and 328 after. |

## Notes (outside the diff)
- **Pre-existing:** state reconstruction also uses lines from files captured after `audit_at`. The third case of the edge probe gives a FINDING. The validator catches it as VALIDATOR_REFUSED, so the row still fails closed.
- **Pre-existing, G7a:** `code/tests/agent/test_properties.py:108` still checks step order with the production `step_sort_key`. That is the same self-confirming pattern T63 pin 5 forbids.
- **T99 E (later ruling):** an out-of-enum `reported_status` is still treated as a malformed row (`requests.py:76`). T99 E says to flag it and audit it as normal.
- **By the ruling:** a case ID padded with spaces is now unreadable and gets no row. All 550 real request rows have the exact shape.

`python3 -I scripts/check_log.py` reports PASS. It warns that my entry's summary is about 8 sentences against the 2–5 format. Main's commit `0e061ac`, made while I worked, is the only change to git status.

Scratch work is in `/tmp/g5v2/`: `scripts/` holds the harnesses and probes, `runs/` the runs, and `pre/`, `post/` and `mut/` the trees.
