# G7b agent report and freeze check report (orch-eval-engineer, high)

directed_by 2026-10-25T05:49:46+05:30 (T88). Main's check (06:09): evaluation 187 OK, lint clean, gold only through load_gold. Committed in 73c2309 with the holdout build; still gets the G7 verifier's review. Saved verbatim by main from the agent's final message.

---

I built both deliverables. The freeze check refuses the G5 test run, as the brief expected, and no G5 run has the agent fields or `vision.json` yet. `.venv/bin/python -B -m unittest discover -s code/evaluation/tests -t code` gives `Ran 187 tests ... OK` (150 before). `bash scripts/lint.sh code/evaluation` reports ruff and mypy clean. No model calls were made, `.env` was not read, and no holdout gold or `sample_output.csv` was touched. My log entry is appended and `check_log.py` passes.

## Blocked on me
Nothing. Four things for you or G7a to settle when G7a is wired in:
1. **Vision file name.** I assumed `vision.json`, a JSON list of image entries. If G7a uses another name, change `VISION_ARTIFACT` in `agent_report.py`.
2. **What `committed_key` / `final_key` hold.** I report whether the two values are equal, plus the `INTENT_DRIFT` count. If they turn out to be reply cache keys rather than labels, that equality says nothing about intent. In that case G7a should add `committed_label` / `final_label` to the `agent` block.
3. **Resolving a vision disagreement.** The vision schema has no resolution field, so the freeze check treats every image whose two readings disagree as unresolved. If disagreements can be resolved after the developer reviews them, G7a needs to add a field for it.
4. **Vision consistency check.** The adapter recomputes the per-field disagreements from the two readings and treats it as an error if `agree` or `disagreements` doesn't match. If G7a deliberately ignores some reading fields, the two will clash at wiring time.

## Changed
Files are all new; nothing outside the brief's scope was edited:
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/agent_report.py`
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/freeze_check.py`
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/tests/run_dirs.py` (synthetic run directories, written with the standard library only)
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/tests/test_agent_report.py` (23 tests)
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/tests/test_freeze_check.py` (13 tests)

**Public signatures:**
- `read_run_artifacts(run_dir: Path) -> RunView` is the single adapter. Every field name is in one constants block at the top of `agent_report.py`.
- `build_report(spec: Spec, *, report_id, runs_root=RUNS, gold_path=SAMPLE_OUTPUT, test_ids=None, fixtures_root=FIXTURES_ROOT, command="") -> dict`. It raises `ReportRefused` when an input run is unchecked.
- `render_markdown(report) -> str`
- `load_run(runs_root, run_id) -> LoadedRun`
- The counting functions: `count_tools`, `count_answers`, `intent_table`, `vision_summary`, `rows_differ`, `fixture_result`, `dev_score`.
- `agent_report.main(argv)` exits 0 when clean, 2 with adapter errors (the report is still written) and 3 when refused (only `refused.json` is written). Usage: `--run-id <report> --dev ARM=RUN --test ARM=RUN --fixture ARM:FIXTURE=RUN [--spec file.json]`.
- `freeze_check(run_id, *, runs_root=RUNS) -> dict` and `freeze_check.main(argv)`, which exits 0 on pass and 1 on refusal. `--record-run-id` writes `freeze_check.json` under a separate run ID.

**Fields the adapter reads:**
- Record level: `case_id`, `row_state`, `failed_closed`, `flags[].code`, `intent_source`.
- Under `agent`: `mode`, `intent.{label, source, committed_key, final_key, agrees, crosscheck.{intake_non_deletion, activity_ids}}`, `turn1_replicates`, `tool_calls[].{name, args_hash, is_error, evidence_ids}`, `audit_case_calls`, `answers_applied`, `answers_rejected[].{oq_id, reason}`, `steps_differ_when_applied`, `status`, `flags`.
- Vision items: `file_id`, `readings` (exactly 2), `agree`, `disagreements`, `flags`, `resource_ids[].{system_id, resource_id, well_formed, named_elsewhere}`.
- `usage.json`: `model_calls`, `input_tokens`, `output_tokens`, `cost_usd`, `model_ids`.

**What each count reads:**
- **N:** `agent.tool_calls` and `agent.audit_case_calls`.
- **M:** `agent.steps_differ_when_applied` and the rejection reasons.
- **Arm deltas:** `output.csv` scored by `score_predictions` against `gold.load_gold(gold_path)` with its defaults (DEV only).
- **Fixtures:** row exact against `code/tests/fixtures/<name>/expected_output.csv`.
- **Test rows that differ:** status plus parsed steps, compared per case ID.
- **Intent:** `label` (null counts as FAILED) against `intake_non_deletion`.
- **Vision:** the two readings compared field by field.
- **Cost:** `usage.json`.
- **Freeze, FAILED_CLOSED rows:** `row_state` or `failed_closed`, cross-checked against `metrics.json`.
- **Freeze, intent:** the `INTENT_FAILED_CLOSED` flag, or an intent source of `FAILED_CLOSED`/`FAILED_BUDGET`, in the record or in `agent`.
- **Freeze, skips:** the producer's `evidence_skipped`, which must agree with `evidence_skip_count`.
- **Freeze, vision:** images whose readings disagree.

**Deviations from G3 §9 and the brief:**
- **No subcommand.** `main.py` is an empty placeholder and the package's CLI is `evaluate.py`, which is outside my scope. Each module runs as its own script instead. Wiring them into `evaluate.py` is a small follow-up.
- **"3 read by hand" is not automated.** The report lists every differing test row by case ID, for you to read.
- **The intent freeze count is stricter than T87's wording.** It also counts `FAILED_BUDGET`, which is the same Q2 path.
- **Vision against text evidence for the same resource** (G3 item 5) is reported only through the recorded `named_elsewhere` flag.
- **F11a and F11b have no `expected_output.csv`,** so they cannot be named as fixtures.

## Found
- **Agent report, run `g7b-agent-report-g5-20261025T0609`, exit 2:**
  - DEV A+ arm on `g5-dev22-20261025T0530`: status 22/22, row exact 19/22, step P/R/F1 1.0000/0.9776/0.9887. This matches the existing `g5-dev22-20261025T0530-score`.
  - All 8 agent and vision sections are errors: `agent: missing` in 22 DEV and 518 test cases, and `vision.json` missing in both runs.
  - Cost is 0 calls and $0.00 in both runs.
- **Freeze check:**
  - `g5-test-20261025T0530` refused (exit 1): `failed_closed_rows = 18`, `evidence_skips = 11`. The intent and vision counts could not be computed. At record level the intent count is at least 518.
  - `g5-dev22-20261025T0530` refused (exit 1): `evidence_skips = 11`, with the same two counts not computed.
  - Records are in `runs/g7b-freeze-g5-dev22-20261025T0530/` and `runs/g7b-freeze-g5-test-20261025T0530/`.
- **Unchecked-run refusal on real data:** `g7b-agent-report-refusal-probe` refused `g4-baseline-20261025T0228` with exit 3, reason "producer check refused: evidence_skipped is NoneType, not a list".
- **The tests catch real faults.** I ran 7 deliberate code faults against a scratch copy, including uncounted tool calls, a missing agent block passing, unchecked runs accepted, skips zeroed, `FAILED_BUDGET` ignored, the vision consistency check dropped, and holdout gold loaded. Each one made new tests fail. The holdout probe only read a synthetic gold file, and its scratch access-log lines were deleted.
- **Side effect:** `runs.code_hash()` hashes every `.py` file in `code/evaluation/`, so the two new modules change the scorer code hash recorded by future score runs.
