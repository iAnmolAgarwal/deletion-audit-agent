G7 verifier brief: the items, collected as they were ruled. The full brief is written when the G7 wiring finishes.
Approved: T92 (`orch-verifier`, high, directed_by 2026-10-25T06:15:34+05:30). It launches when the wiring is done.

## Scope
- **G7a, the agent package:** `code/deletion_audit/agent/**` and `code/tests/agent/**`, including main's test-only case-ID patch (T99 A).
- **G7b:** `code/evaluation/agent_report.py` and `freeze_check.py` (committed in 73c2309, not yet reviewed).
- **The GM error-text change:** `model/{transport, policy, calllog, client}.py`, `tests/model/test_api_error_text.py`, and the §8 line.
- **The G7 wiring diff:** what the wiring agent changed in `pipeline.py`, `artifacts.py`, `engine.py`, `record.py`, `config.py`, `__main__.py`, `agent/` and `evaluation/{agent_report,holdout_run,freeze_check}.py`.

## Items
1. **G7b's four open details:**
   - the vision file name;
   - `committed_key`/`final_key`: **they must compare intent labels, not reply keys (T92)**;
   - no resolution field for a vision disagreement;
   - the adapter recomputing `agree`/`disagreements`.
2. **T95 C1:** each prompt has a role, constraints, the refusal path (UNCERTAIN with a reason), fenced untrusted text and made-up IDs only. Each tool says when to use it, when not to, what it returns, and that it is read-only.
3. **T95 C4:** the code-side instruction-like-text flag only flags, never decides, and is merged with the model's flag in the per-case record. A G8 injection fixture (R03) exercises both.
4. **The replay-only regression gate:** DEV `641dbc8d…` and test `cf2a90b0…` stay byte-identical with an empty reply cache, and 0 sends are made.
5. **The model-on regression gate (T100, narrowed by T101):**
   - The baseline is read from `notes/approved_output.json`, with its hash checked.
   - Only the two allowed changes pass: (a) NOT_APPLICABLE `[]` with both replicates and the cross-check agreeing; (b) an image change with both readings agreeing and the IDs cross-checking.
   - Every other change stops the run, including `intent+image`, `unexplained` and a failed condition.
6. **The R06 rule (T101):** a FINDING whose record only post-audit files hold fails its row closed, with its own reason and a fixture test on `redteam/R06` (case_93051, against `expected_assertions.json`).
7. **The freeze check (T101):** it compares the run's `output_sha256` with `notes/approved_output.json` and prints both.
8. **T63 pin 5:** `code/tests/agent/test_properties.py:108` no longer uses the production `step_sort_key`.
9. **The dependency gap (developer, 2026-10-25T11:59:56+05:30; main's finding at the T102 pre-check).** An unread screenshot newer than a record's text evidence is not counted as a dependency of that record, so its row can be COMPLETE while the screenshot is unread.
   - The case: `case_34` is COMPLETE in the approved output. It verifies `account_5762` absent, citing `evidence_01` (captured 2026-09-15T11:59:39Z). Its screenshot `evidence_04` (`account_admin_console_20260926.png`, captured 2026-09-26T11:00:00Z, before audit_at 2026-09-27T13:00:00Z, 7 minutes before LINK row `activity_4000`) is not in that record's `depends_on`.
   - Today's rule makes an unread PNG a dependency only for records known solely by a catalog row.
   - Check that, after the wiring, a screenshot that cannot be read (a failed reading, or two readings that disagree) is a dependency of every record it could be a newer observation for. A COMPLETE row must never stand on an unread screenshot captured after its latest text evidence and at or before `audit_at`.
   - Check that, with readings applied, the latest observation wins (T54).
10. **Vision:**
    - The two cache namespaces: reading 2 is a fresh send.
    - The `merge_readings` rule never hides a record.
    - Malformed IDs are flagged, not used.
    - IDs named by no other input are flagged and kept (T88).
    - The vision-review acknowledgement before a paid full run.
11. **The paid entry points** (routing check and vision): nothing is sent without `--paid`, the caps hold ($5 and 170 sends for stage 1 plus vision; T99 B), and `--env-file` loads only the key into the process and never logs it.
12. **`holdout_run.pipeline_runner`** matches `pipeline.run`'s client parameters, and the holdout lock tests still pass (static and behavioural).
13. **G7a's risks:** a support image with no IDs read as REDACTED (check it against the rules); `backup_9291` flagged and kept.
