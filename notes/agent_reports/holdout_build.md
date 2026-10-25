# Holdout run build report (orch-eval-engineer, high)

directed_by 2026-10-25T06:32:14+05:30 (T96). Brief: scratchpad `holdout_run_brief.md`. Saved verbatim by main from the agent's final message.

**Main's check (T98):**
- `gold.py`: the refusal message only (2+/2-).
- Evaluation tests: 252 OK in the working tree. Lint is clean (ruff and mypy, 41 files).
- `runs/HOLDOUT_ACCESS.log` does not exist before or after.
- The real script with no `--unlock` prints `HOLDOUT RUN REFUSED` and exits 3.
- **Committed with G7b's `agent_report.py` and `freeze_check.py` and their tests,** because `holdout_run.py` imports `freeze_check`, which imports `agent_report`. They still get the G7 verifier's review.
- **The committed snapshot alone** (exported with `git checkout-index`) runs 252 tests with 2 failing: `test_pipeline_runner_passes_the_intended_keywords` (it imports `deletion_audit.pipeline`) and `test_the_scan_covers_the_tree` (it expects `deletion_audit/pipeline.py` and `__main__.py`). Both files are G5's and stay uncommitted until G5's verifier (T98), and both tests pass once G5 commits.

---

## Blocked on me
Nothing is blocking this build. Three things must happen before the command can work for real:
1. **`pipeline.run` keywords.** `pipeline_runner` calls `pipeline.run(dataset_dir, run_id=, cases=, mode="A+", replay_only=False, holdout_unlock=phrase, client=client, runs_dir=, command=)`. Today that call fails with a TypeError before the engine starts, so the run exits 1 before any gold is unlocked. `client=` is my assumption. If G7a wires clients another way (vision needs two cache roots), only that one function needs changing. The client must keep using the `BudgetGuard` that `holdout_run` passes in; the code checks this and fails if it doesn't.
2. **The freeze run's `producer.json` must contain `"git_head": <40-hex HEAD>`.** `pipeline.py` doesn't write this field today, so every real attempt will be refused until main adds it.
3. **A decision for the developer.** `outputs.read_output` calls `check_unlock(True, unlock_phrase, …)`, which makes it a 4th file that passes the unlock along. I can't edit `outputs.py`, so the static rule allows it narrowly: only that exact call, with its own `unlock_phrase` parameter. No other file can pass `unlock_phrase=`, and a test shows that this forwarder with any other value is caught. The alternative is to remove the unlock route from `read_output`.

## Changed
**Files**
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/holdout_run.py` (new)
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/gold.py`: message only. It now reads "holdout {what} is locked: it opens only with the developer's own unlock phrase, given in the single post-freeze run…". `paths.py` is unchanged.
- New tests in `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/evaluation/tests/`: `holdout_fixtures.py`, `test_holdout_run.py`, `test_holdout_static.py`, `test_gold_refusal_message.py`. `test_gold.py` and `test_gold_identity_guard.py` are unchanged and pass.

**Public signatures** (`holdout_run.py`)
- Constants: `HOLDOUT_DOLLAR_CAP = 1.00`, `HOLDOUT_CALL_CAP = 60`, `HOLDOUT_MODE = "A+"`, `EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 3`
- `main(argv=None, *, settings=None, runner=None, client_factory=None, freeze_checker=None) -> int`
- `run_checks(inv, *, phrase, settings, freeze_checker) -> Context`, which runs `check_phrase`, `check_ids`, `check_frozen_code`, `check_freeze_run`, `read_caveat` and `check_once`
- `execute(ctx, *, phrase, settings, runner, client_factory, freeze_checker, command) -> dict`
- `make_budget(settings) -> BudgetGuard`, `anthropic_client(run_id, budget, settings) -> ModelClient`, `pipeline_runner(*, dataset_dir, run_id, cases, phrase, client, runs_dir, command)`
- `holdout_section(record, *, current_head=None) -> str`: raises if the record is not complete or has no caveat, and marks the section "Pre-change" when HEAD ≠ the frozen commit
- `dirty_paths(porcelain_z) -> list[str]`, plus `Settings`, `Invocation` and `HoldoutRefused`

**The exact command line main will run**
```
.venv/bin/python -B code/evaluation/holdout_run.py --unlock "HOLDOUT EVALUATION RUN" --freeze-tag freeze-<YYYYMMDD> --freeze-run <final run id> --run-id holdout-<YYYYMMDDTHHMM>
```

**Access-log line format.** Each line is one JSON object, appended to `gold.HOLDOUT_ACCESS_LOG`:
- `holdout_run`'s own line, written just before each unlock: `{"at","what","run_id","git_head","freeze_tag","freeze_run","argv","attempt","by":"holdout_run"}`, with `what` set to `"engine run"`, then `"gold"`.
- `check_unlock`'s own line follows each grant: `{"at","what","run_id"}`.
- The last line is `what:"complete"`, which adds `output_sha256` and `score_sha256`.
- So a good run writes 5 lines. A run that was retried after a crash adds the crashed attempt's engine lines in front, numbered by `attempt`.

**Engine-guard test spec for main** (goes with the `pipeline.py` change; synthetic dataset, patched split, temporary access log, a file-open spy):
- `test_engine_refuses_holdout_without_phrase`: `run(cases=<holdout>)` with no `holdout_unlock` raises `HoldoutLockedError`; no file is opened and no log line is written.
- `test_engine_refuses_wrong_lowercase_trailing_space`: the same for each wrong form.
- `test_engine_ignores_phrase_in_environment`: with the phrase only in `os.environ`, it is still refused.
- `test_engine_refusal_before_any_open`: the spy records no dataset path.
- `test_engine_unlock_logs_one_line`: with the right phrase, exactly one `{"what":"engine run","run_id":…}` line is written.
- `test_dev_cases_need_no_phrase`: a DEV-only run is unchanged and writes no log line.
- `test_cli_still_refuses_holdout_ids`: `__main__` exits 2.
- `test_guard_removed_fails`: with the guard monkeypatched out, the refusal test fails.

**Deviations from the proposal**
- `--freeze-commit` became `--freeze-tag`, per T96.
- `--run-id` must start with `holdout-`.
- The access lines carry `git_head` (which equals the frozen commit) plus `attempt` and `by`. `check_unlock` writes its own line too, so there are 2 lines per unlock. I was only allowed to change `gold.py`'s message, not what it logs.
- The unlock times and the freeze commit go in `holdout_record.json`, not in `producer.json` (that file belongs to the pipeline).
- A retry builds a new $1/60 guard for each attempt. Each attempt's sends and spend are recorded and summed in the record, and a retry replays cached replies (the test shows 0 sends on attempt 2).
- The record also includes the holdout run's own freeze-check counts, for information only. Coherence is not run on the holdout output.

## Found
- **No run ID:** nothing was run or scored, no model was called, and `.env` and `dataset/sample_output.csv` were never opened.
- **Tests:** `.venv/bin/python -B -m unittest discover -s code/evaluation/tests -t code` gives `Ran 252 tests … OK` (187 before).
- **Lint:** `bash scripts/lint.sh code/evaluation` gives ruff "All checks passed!" and mypy "Success: no issues found in 41 source files".
- **Access log:** `ls runs/HOLDOUT_ACCESS.log` gives "No such file or directory". Running the real script with no phrase printed `HOLDOUT RUN REFUSED: the developer's unlock phrase is missing or not exact` and exited 3.
- **Static scan:** it is clean on the real tree, and 13 planted violations are caught (a second `load_gold` caller, a constant import, `vars(gold)['UNLOCK_PHRASE']`, a lower-case or f-string literal, `holdout_unlock=` and `unlock_phrase=` elsewhere, `check_unlock(True…)`, `**` splat, aliased import). 8 planted ways of getting the phrase other than from argv are caught: environment, file read, reassignment, the constant, `default=`, `fromfile_prefix_chars`, `args` built another way, and a positional `phrase`.
- **Behavioural tests:** every refusal exits 3, leaves no access log, opens no gold and no dataset file, runs no engine, builds no client and never shows the phrase. The spy is shown to see the gold being opened on the good path. Each `split.py` docstring mentions the phrase; the scan skips docstrings on purpose.
- **Not done:** no `evaluation_report.md` generator exists yet; it should call `holdout_section`. The README limitations line about the phrase being a constant is not written.
- **Log:** my entry is `2026-10-25T06:48:11+05:30`, and `python3 -I scripts/check_log.py` gives PASS.
