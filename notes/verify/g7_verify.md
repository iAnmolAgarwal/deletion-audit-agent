# G7 verifier report (orch-verifier, high)

directed_by 2026-10-25T06:15:34+05:30 (T92). It reviewed an export of 4dcd719; brief: scratchpad `g7verifier_brief.md`. Saved verbatim from the agent's final message.

**Main's spot-check:** `probes/p4_vision_real.py agree`, run on the export, reproduces finding 1 (`case_53 COMPLETE ... support_1034 REDACTED COMPLIANT image_extraction`). `probes/p5_writeroot.py` (which patches REPO_ROOT to a temp folder) reproduces finding 5 (`gate passed False | root output.csv written: True`). The repo has no root `output.csv`.

---

**Verdict: FIX.** There are 0 BLOCKER, 6 MAJOR and 2 MINOR findings. None of them touches the paid stage-1 entry points, and the developer has ruled that 14c alone does not block stage 1.

I reviewed an export of `4dcd719` at `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g7v`. Both suites pass there: `code/tests` 489 OK and `code/evaluation/tests` 277 OK. I made no model call, did not read `.env`, did not open `sample_output.csv` and edited no repo file. The probe scripts are in `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/probes/` and use FakeTransport on the real dataset. Run each with `.venv/bin/python -I -B <probe> <export>/code …`.

**Stage 1 (stated precisely).**
- **No send without `--paid`.** A replay setup gets `NoSendTransport`, and caps or `--env-file` without `--paid` are refused (exit 2). One `BudgetGuard` covers each command.
- **Caps.** The code does not enforce the totals; you pass them on the CLI. The documented commands give $3.50 + $1.50 = $5.00 and 146 + 24 = 170 sends. Retries count against those send caps.
- **Key.** `--env-file` loads only `ANTHROPIC_API_KEY` into the process. A made-up key appears in no output, artifact, cache file or request body (`test_cli_paid.py:133`, FakeTransport only).
- **Replay-only gate.** It reproduced on fresh run IDs with empty caches: DEV `641dbc8d…` twice and test `cf2a90b0…` three times, all byte-identical. Every run made 0 sends, and the cache stayed empty (0 files). The gate passes against the approved baseline, and a missing baseline refuses with exit 5.

## Findings

1. **MAJOR: an image reading that shows nothing becomes a compliance claim.** Code: `vision.py:188-207` (empty subject lists add no attributes) feeding `state/observe.py:150` (support defaults to REDACTED) and `:133` (analytics defaults to ANONYMIZED).
   - **Repro:** `p4_vision_real.py <export>/code agree <work>`, with both readings agreeing: ID shown, no subjects, every state `not_shown`.
   - **Result:** case_53 `support_1034` becomes REDACTED and the row COMPLETE (`VERIFY_RECORD_REDACTED`, evidence_28). case_50 `analytics_7438` becomes ANONYMIZED and case_46 `tombstone_17` REDACTED, both rows COMPLETE.
   - **The gate rules all three "image, allowed".** The vision review list holds only failed or disagreeing images, so nobody reviews them.
   - **Expected:** an untranscribed subject is not evidence of redaction.
   - **Class:** "nothing found" read as compliant (G7a's risk, now real). The schema cannot say "shown redacted".

2. **MAJOR: 14c, judged against T109. All three parts fail at 4dcd719.**
   - **(a) The engine:** `answers.py:129-134` keeps the committed label with source `MODEL` when the outcome is FAILED (`loop.py:356-358`). `p1_failed_loop_na.py` returns NOT_APPLICABLE `[]` in both A+ and A, with an unanswered INTENT_CROSSCHECK and a disagreeing cross-check. In `p3_t108.py` the pipeline writes `case_9002,NOT_APPLICABLE,[]` where the approved row is INCOMPLETE. The row's own flags are empty: AGENT_CALL_FAILED is only in the agent block.
   - **(b) The gate:** `regression.py:199-207` checks only the turn-1 labels and intake, and `CaseEvidence` has no loop-status field. A FAILED case with labels [ND, ND] and intake true is classed "intent, allowed". Today the cross-check alone stops it, because a NOT_DELETION commit only loops when the cross-check disagrees.
   - **(c) The freeze check:** `freeze_check.py:89-93` never lists case_9002; it is absent from the whole freeze record.
   - **T108's parts:** there is no re-send, and the approved row is not kept; the gate stops the run instead. T109 superseded T108 on the re-send.
   - **Class:** a failed call becomes NOT_APPLICABLE, against T71 Q2. Fixes are already assigned.

3. **MAJOR: item 9's dependency gap is not fixed.**
   - **Code:** `engine.py:502` (`if not usable and basis == "link_row" and pending_png`).
   - **Repro:** `p4 … fail04`, where reading 2 of evidence_04 fails with a 400.
   - **Result:** case_34 stays COMPLETE (`account_5762` ABSENT, `depends_on` empty), and the gate passes because the row equals the approved one.
   - **The only backstop:** freeze refuses on `evidence_skips=1`.
   - **With the readings applied** ("agree"), the latest observation wins: case_34 becomes INCOMPLETE with a FINDING, as T54 requires.
   - **Class:** a COMPLETE row resting on an unread, newer screenshot.

4. **MAJOR: 14a is confirmed. The freeze check can never pass on a real vision run.**
   - **Code:** `agent_report.py:426-446`.
   - **Repro:** in `p4 agree`, `CS-3245` gives `resource_ids[*].system_id: expected string, got null`, so `vision_unresolved_disagreements` is "not computed".
   - In `dis04`, the error is `disagreements: expected ID-shaped strings`. In `fail04` it is `agree … null` and `expected 2 reading objects`.
   - There is also no resolution field, so a disagreement the developer has acknowledged blocks freeze permanently.
   - The check fails closed, but freeze and the agent report are blocked until this is fixed.

5. **MAJOR: `--write-root` writes the root file before the gate runs.**
   - **Code:** `pipeline.py:491-494` comes before the gate at `:497`.
   - **Repro:** `p5_writeroot.py` (planted baseline) prints `gate passed False | root output.csv written: True`.
   - **Expected:** a stopped run leaves the root `output.csv` untouched.
   - **Class:** a write before its gate.

6. **MAJOR: 14b is confirmed. The engine gives COMPLETE and only the gate stops it.**
   - **Code:** `engine.py:502`. The dependency disappears once the PNG counts as read, whether or not the image shows the record.
   - **Repro:** `p4 … empty32` (evidence_32 read OK with no records).
   - **Result:** case_55 is COMPLETE, and `backup_9287` comes out ABSENT by omission with `VERIFY_RESTORE_BLOCKED`.
   - The gate stops it ("records waiting on an image got an image state: False"), but only when `--regression-gate` is on.

7. **MINOR: the regression gate is opt-in.** In `__main__.py` the flag is `--regression-gate` (store_true), and `pipeline.py:428` defaults it to False. A paid mode-A run without it has no T101 stop, which matters given findings 2, 5 and 6. Make it mandatory for paid full runs.

8. **MINOR: R03's evidence-side code flag is not exercised end to end.** `test_redteam_wired.py:44-53` asserts only the `request` source. The evidence path is covered only in unit tests (`test_injection.py`).

## Items

| # | Verdict | Basis |
|---|---|---|
| 1 | Partly | The file is `vision.json` (OK). Labels are compared, with the keys kept as provenance (OK). There is no resolution field, and the adapter's recompute clashes with the real artifacts (finding 4). |
| 2 | PASS | All three prompts have Role, Constraints, Untrusted data, an UNCERTAIN path with a reason, and made-up IDs. Each `tools.md` section has when to use, when not, what it returns and that it is read-only. |
| 3 | PASS (MINOR 8) | The code flag only flags (`loop.py:195-199`). `{code, model, merged}` is in the record, and the R03 test passes. |
| 4 | PASS | Hashes reproduced with 0 sends. |
| 5 | PASS | Baseline sha256 checked. Only the two allowed classes pass; intent+image and unexplained stop. The gap is (b) of finding 2. |
| 6 | PASS | `POST_AUDIT_ONLY_FINDING` holds on R06 case_93051 against `expected_assertions.json`. |
| 7 | PASS | Both sha256 values are printed, and a mismatch or unreadable record refuses. |
| 8 | PASS | `test_properties.py:109` uses `hand_key`. |
| 9 | FAIL (finding 3) | Readings applied: the latest observation wins (OK). Unread image: no dependency is added. |
| 10 | PASS (finding 1) | 22 sends for 11 images; the merge keeps every record. `CS-3245`/`ORD-…` are unrecognized and not used, `account_57620000000` is malformed. `backup_9291` is flagged and kept. The ack must match exactly. |
| 11 | PASS | See Stage 1. |
| 12 | PASS | `from_client` keeps the client's transport, guard, policy and log. The lock tests pass (inside the 277). No `HOLDOUT_ACCESS.log`. |
| 13 | FAIL (finding 1) / PASS | REDACTED from no IDs is confirmed and spreads to analytics and identity. `backup_9291` is flagged and kept. |
| 14 | a: confirmed (finding 4); b: confirmed (finding 6); c: fails T109 (finding 2) | |
| 15 | PASS | The FakeTransport test covers stdout, stderr, artifacts, cache and bodies. The real `AnthropicTransport` is not exercised. |
| 16 | PASS | Fresh run IDs `v-dev-1/2` and `v-test-1/2/3` under `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g7vwork/runs`. |

## Notes (outside the diff)
- `observe.py:133/150` are G5 defaults written for text records; finding 1 comes from feeding image observations into them.
- In `p4 agree`, `backup_9287` comes out ABSENT, which then compiles to `VERIFY_RESTORE_BLOCKED`. That sits with the T97(3) backup ruling.
- Holdout replicates always replay-miss, because the routing check has no holdout source. That is harmless with no gate, but holdout NOT_APPLICABLE rows rest on one reading.

The log entry is appended, and `python3 -I scripts/check_log.py` passes.
