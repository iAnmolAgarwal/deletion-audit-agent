# Report generators report (orch-eval-engineer, high)

directed_by 2026-10-25T12:08:17+05:30 (T106). **Main's check:**
- **Lint:** clean on the 7 new files.
- **Tests:** HEAD plus the new files alone (export in the scratchpad) runs 271 OK.
- **Demo** `runs/reports-demo-20261025T1330/`: DEV 22/22, 19/22, F1 0.9887, as known; usage $0.004964, equal to the ledger.
- `runs/HOLDOUT_ACCESS.log` still does not exist.
- **Found:** T58 names only case_08, but 3 DEV rows are not row-exact (case_08, case_18, case_20). README and G10 must list all three.

Saved verbatim from the agent's final message.

---

## Blocked on me
Nothing. One choice is yours to keep or reverse: a usage run that has no `output.csv` gets through the T81 check only if the spec says `"usage": {"calls_only": true}`. I added that so the demo could use `smoke-t76-20261025T0612`, as the brief asked. Without the flag, such a run is refused. When G9 points `usage.run` at the final run, the flag is no longer needed.

## Changed
All new files are in `code/evaluation/`. I did not edit `agent_report.py`, `holdout_run.py`, `freeze_check.py` or anything in `code/deletion_audit/`.

**Modules and signatures**
- `report_spec.py`: `spec_from_mapping(raw) -> ReportSpec`, `load_spec(path)`, `load_checked(spec, runs_root) -> dict[str, LoadedRun]`. The last one raises `ReportRefused` for any input run that isn't checked.
- `custom_cases.py`: `discover(fixtures_root) -> list[CustomCase]`, `score_custom(cases, custom_runs, loaded)`, `check_assertions(...)`.
- `usage_report.py`: `build_usage(run_id, *, runs_root, cache_root, calls_file, usage, calls_only)`, `render_usage(...)`, `failures_found(u)`.
- `run_metrics.py`: `compute(run, previous)`, `build_metrics([(role, run, previous)], *, report_id, created_at, command)`.
- `evaluation_report.py`: `build_evaluation(spec, loaded, ctx, *, command, created_at)`, `render_evaluation(data)`, `problems(data)`. `Context` holds every path, so tests can redirect them.
- `reports.py`: the one command, `main(argv, *, ctx=None)`. Exit codes: 0 when written and every cross-check agrees, 2 when written but cross-checks failed, 3 when refused.
- `tests/test_reports.py`: 20 tests, all on synthetic run folders, with expected counts worked out by hand.

**Spec format**
```json
{"report_id": "...", "final_run": "...", "dev_run": "...", "previous_run": "...",
 "dev_history": ["oldest", "..."], "arms": {"dev": {"A+": "..."}, "test": {}, "fixtures": {}},
 "custom_runs": {"<folder under code/tests/fixtures>": "<run>"},
 "usage": {"run": "...", "calls_only": false, "calls_file": "calls.jsonl"},
 "holdout_run": null, "coherence": true}
```
Unknown keys are refused, and so is a `report_id` that names an input run.

**What each section reads**
- **DEV accuracy:** `score_predictions` on the DEV run's `output.csv`, with gold from `load_gold` defaults. It reports case, row, step (overall and per operation), field, sequence and citation scores, plus the confusion matrix, the cases that are not row-exact, and per-run history with flips.
- **Custom eval cases:** found from the "custom eval case: yes" marks in each `EXPECTED.md`, scored against `expected_output.csv`, then `expected_partial.csv`, then `expected_assertions.json`.
- **Agent sections:** `agent_report.build_report` and `render_markdown`, embedded.
- **Validator and FAILED_CLOSED counts:** each run's pipeline `metrics.json`, cross-checked against its `cases.jsonl`.
- **Coherence and drift:** `coherence.check_file` (it counts hard cases outside FAILED_CLOSED rows on their own) and `drift.drift_table`.
- **Holdout:** the caveat comes from `holdout_run.read_caveat`. The section is filled by `holdout_section(record)` only once a completed record exists.
- **Limitations:** each ruling is quoted from `notes/DECISIONS.md` or the "The limit" section of the holdout proposal, next to a count from `cases.jsonl` where one applies.
- **Usage:** `calls.jsonl`, the cache entries (`bought_by_run` and original usage), the buying runs' call logs, `cache/ledger.jsonl` and the price table in `prices.py`.

**Demo (command output shown)**
- `.venv/bin/python -B code/evaluation/reports.py --spec .../scratchpad/reports/demo_spec.json` exited 0 and wrote four files to `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/runs/reports-demo-20261025T1330/`: `evaluation_report.md`, `usage_report.md`, `metrics.json` and `reports_build.json`.
- **Refusal probe:** a spec using `g4-baseline-20261025T0228` exited 3 with "producer check refused: evidence_skipped is NoneType". It wrote only `runs/reports-refusal-probe-20261025T1330/refused.json`.
- **Tests:** `unittest discover -s code/evaluation/tests -t code` ran 277 tests, all OK (it was 251 before).
- **Lint:** `lint.sh` passes on my 7 files. `lint.sh code/evaluation` as a whole still reports 5 ruff findings and 1 mypy finding, all in `freeze_check.py` and `tests/test_freeze_check.py`, which the other agent is editing.

**Excerpts from the demo**
- **DEV, run `g5-dev22-20261025T0530`:**
  - status 22/22, row exact 19/22;
  - step P/R/F1 1.0000 / 0.9776 / 0.9887;
  - fields: state 131/131, evidence_id 131/131, step_no 126/131;
  - sequence exact 19/22, pairwise order 470/470.
- **Usage, run `smoke-t76-20261025T0612`:** 2 replies, 1737 input and 149 output tokens, $0.004964. The settled cost, the re-priced cost and the ledger all agree, and the whole ledger ($0.004964) matches every send across 19 call logs.
- **metrics.json:**
  - `final:fail_closed_rows` fires at 18 (9 NOTHING_FOUND and 9 UNPARSED_DEPENDENCY) on `g5-test-20261025T0530`.
  - Status-mix drift is 0.0 points against `g5-test-iter3`.
  - The three agent-derived metrics are "not computed" (null, not 0), because those runs have no agent blocks.
- **Agent sections:** the report says "Empty until G7 is wired, not zero" and lists the 8 sections affected.

**Left for G9**
- Name the fixture runs in `custom_runs`. None exist yet, so all 11 custom cases show "not run".
- Point `usage.run` at the final run.
- Add the arms (`tools_off`/`A`) once G7 runs them.
- Copy or redirect the output into `code/evaluation/`. On purpose, there is no flag for that yet.
- The `open_questions` and `answers` keys that `run_metrics` reads are named in one constants block. Check them against what the G7 wiring actually writes.
- Add a "failures found and fixes made" narrative. It has no artifact to draw from yet.

## Found
- **T58's text doesn't match DEV.** The ruling says "DEV 19/22 … the lost row is case_08". On `g5-dev22-20261025T0530` three rows are not row-exact: case_08, case_18 and case_20. The ruling names only case_08. The report shows both, side by side.
- **Run-to-run changes:**
  - `g5-dev-iter1` → `g5-dev-iter3`: only case_07 flipped, on status, row exact and order.
  - `g5-dev-iter3` → `g5-dev22`: no flips.
  - `g5-test-20261025T0530` against `g5-test-iter3`: 0 of 518 rows differ.
- **Coherence on `g5-test-20261025T0530`:** 58 hard H03 violations, all inside the 18 FAILED_CLOSED rows (0 outside them), and 14 soft ones. There are 0 drift gaps over 15 points against DEV gold.
- **Hygiene test failure (not mine):** `code/tests/hygiene` fails `test_no_test_reads_runs_or_cache_as_expected` on `test_cli_paid.py`, a file from the other agent.
