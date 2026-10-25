# How the HOLDOUT EVALUATION RUN gets past the holdout guards: a proposal (for the developer's ruling)

Main drafted this at 2026-10-25 ~06:27 IST at the developer's request. It is a proposal only; nothing here is built.

## What exists today (main checked)
- **Gold side:** `evaluation/gold.py`. `load_gold(holdout=True, unlock_phrase=...)` opens holdout gold only when the phrase equals `UNLOCK_PHRASE = "HOLDOUT EVALUATION RUN"`. Otherwise it raises `HoldoutLockedError` before any I/O. A granted unlock prints a stderr banner and appends one JSON line to `runs/HOLDOUT_ACCESS.log`.
- **The log has never been written:** the file does not exist. No non-test code passes `holdout=True` or the phrase; only `gold.py` defines and checks it.
- **Engine side:** the CLI refuses holdout IDs (`__main__.py:49`). The G5 fix round adds the same refusal to `pipeline.run`, with no unlock path (T90).
- **Two weak points:**
  1. The refusal message (`gold.py:61`) prints the phrase it wants.
  2. `runs/` is gitignored, so the access log is never committed and could vanish without trace.

## Proposal
1. **The phrase:** keep "HOLDOUT EVALUATION RUN", which `../CLAUDE.md` §4 and `gold.py` already use. It is compared exactly: case, spaces and punctuation, with no normalising.

2. **Who triggers it:** only the developer, in their own turn, after the freeze checks pass. Two ways; main recommends (b).
   - **(a)** The developer's message contains the exact phrase, and main runs the command in that turn. log.txt quotes the message verbatim.
   - **(b)** The developer runs the command themselves, with `! <command>` in the prompt. The transcript then shows the developer's own command as the trigger. Main gives the exact command line beforehand, with its cost.

3. **One command, the only caller:** a new `code/evaluation/holdout_run.py`, built and verified before the G9 freeze run, so the final verifier and judge review it.
   ```
   python -m evaluation.holdout_run --unlock "HOLDOUT EVALUATION RUN" --freeze-run <final run id> \
       --freeze-commit <sha> --run-id holdout-<YYYYMMDDTHHMM>
   ```
   Before it reads any holdout input or gold, it refuses unless all of these hold:
   1. **the phrase,** taken from argv only (never from an environment variable, a file or a default);
   2. **the code is the frozen code:** the git tree is clean (untracked files only under `runs/` and `cache/`), HEAD equals `--freeze-commit`, and the freeze run's producer record names that commit;
   3. **the freeze check passes on `--freeze-run`,** run again at that moment (G7b's `freeze_check`): 0 FAILED_CLOSED, 0 `INTENT_FAILED_CLOSED`, 0 skips, 0 unresolved vision disagreements, producer check OK;
   4. **once only:** no completed holdout record exists. A crashed attempt, with no score written, may resume under the same `--run-id` only, and is logged as a retry. A second complete run needs a new developer ruling.
   5. **budget:** the 10 holdout request texts have never been sent to the model, so their calls are bought here. That is about 20–40 calls, roughly $0.20 expected (G3's A+ cost of about $0.02 per case). Main proposes caps of $1 and 60 sends, stated before the run.

   Then it runs `pipeline.run(cases=HOLDOUT_IDS, mode="A+", holdout_unlock=<phrase>, ...)` and scores with `load_gold(holdout=True, unlock_phrase=<phrase>, run_id=...)`. It writes `runs/<id>/output.csv`, `score.json` and `holdout_record.json`. Both guards call the same `check_unlock`, so there is one phrase and one log.

4. **What it logs:**
   - **`runs/HOLDOUT_ACCESS.log`,** one JSON line per granted unlock: `at`, `what` (engine run or gold), `run_id`, `git_head`, `freeze_run`, `freeze_commit` and `argv`. A final `complete` line carries the output and score sha256.
   - **The stderr banner,** as today.
   - **The holdout run's `producer.json`:** `holdout: true`, the freeze commit and run, and the unlock times.
   - **log.txt:** the developer's turn, verbatim. Main's entry copies the access-log lines, since `runs/` is not committed.
   - **`evaluation_report.md`:** a holdout section labelled with the run ID, commit and time. Any later change marks it "pre-change" (`../CLAUDE.md` §6).

5. **Small code changes alongside:**
   - `pipeline.run` gains `holdout_unlock: str | None = None`. With holdout IDs it calls `check_unlock(..., what="engine run")`. The import is lazy, so the normal path stays as it is.
   - The refusal message stops printing the phrase.

## Tests that prove nothing else can unlock it
1. **Static (AST over `code/`, tests excluded):** only these may reference `UNLOCK_PHRASE` or the literal phrase, or pass `holdout=True` to `load_gold`, `holdout_unlock=` to `pipeline.run` or `holdout=True` to `check_unlock`:
   - `gold.py`, which defines the phrase;
   - `pipeline.py`, which checks it;
   - `holdout_run.py`, the one caller.

   In `holdout_run.py` the phrase must come from argv: no `os.environ`, and no file read, feeds it. Adding a second caller fails this test.
2. **Engine guard, behavioural** (synthetic dataset and a patched synthetic split, under T48):
   - Refused: no phrase, a wrong phrase, lower case, a trailing space, the phrase in an environment variable, the CLI with a holdout ID.
   - Each refusal happens before any input file is opened, checked with a spy on file opening, and the access log is untouched.
   - Deleting the guard makes this test fail.
3. **The command, behavioural** (a temporary git repo, synthetic runs and gold, a temporary access-log path):
   - Refused: a dirty tree, HEAD different from `--freeze-commit`, a failed freeze check, a completed earlier record.
   - The good path writes exactly the expected access lines.
4. **The existing gold tests** (`test_gold.py`, `test_gold_identity_guard.py`) stay as they are.

## The limit, stated plainly
The phrase is a constant in the source, not a secret. The lock stops accidental and incidental access by code paths and makes deliberate access visible and logged. It cannot stop someone with a shell who calls the function on purpose. The real control is procedural: the developer's own turn is the trigger, and the access log, log.txt and the once-only check make any other unlock show. The README's limitations section should say so.

## For the developer to rule
1. The phrase as is.
2. Trigger (a) or (b).
3. The paid-call caps for the 10 holdout texts.
4. The build: `orch-eval-engineer` (high) builds `holdout_run.py`, the static and behavioural tests and the message fix. The `holdout_unlock` parameter goes into `pipeline.py` after G5 commits. Both land before the G9 clean-cache run, so the final verifier and judge review them.
