# G7 wiring report (orch-builder-core, high)

directed_by 2026-10-25T11:28:05+05:30 (T99), with the T100/T101 additions in its brief. **Main's check:**
- **Scope:** policy, discovery, validate, inputs and evidence untouched; `model/` holds only the GM error-text fix (68+/11-).
- **Tests:** `code/tests` 489 OK; `code/evaluation/tests` 277 OK.
- **Lint:** the 4 ruff findings are pre-existing (`inputs/__init__.py` ×3, `code/main.py` D100); mypy is clean across 222 files.
- **Gate runs:** `g7wire-dev22-20261025T1233` gives `641dbc8d…` and `g7wire-test-20261025T1233` gives `cf2a90b0…`, with paid_model_calls 0.
- `runs/HOLDOUT_ACCESS.log` still does not exist.
- **Committed before its review (T105),** together with G7a's agent package and the GM error-text fix.

Saved verbatim from the agent's final message.

---

I wired G7a's agent package into the G5 pipeline and added the paid entry points. The regression gate holds: with an empty reply cache the run made 0 sends, and both outputs are byte-identical to G5's. I made no paid call, did not read `.env`, opened no gold file and never opened `dataset/sample_output.csv`.

## Blocked on me
1. **G7b's adapter cannot read real vision artifacts yet.** I tested it on real-shaped readings built with the fake transport:
   - **Failed image:** its readings are null, which the adapter reports as an error. That is the right outcome.
   - **Unusable label** (like `CS-…` or `ORD-…`, which the real screenshots show): `system_id` is null, and the adapter refuses it.
   - **Disagreeing readings:** the disagreement paths (`records[x].sync_enabled`) are not ID-shaped, and the adapter only compares the readings' top-level keys.
   
   Fixing this needs a change to the vision part of `agent_report.py`, which was outside my scope (label comparison only). Until then the freeze check will report adapter errors on the real vision run.
2. **A screenshot can be read without showing a record we were waiting on.** Once the vision step reads a PNG successfully, a record known only from a catalog row that the image does not show gets no state and no step. That follows the brief and the existing no-step rule for a record with no observation. The regression gate stops any such row (I added this check), but the engine itself does not fail it closed. Do you want the engine to fail it closed too?
3. **A failed loop call keeps the committed intent (G7a design).** If a later turn fails after turn 1 committed NOT_DELETION, the case still becomes NOT_APPLICABLE. The gate allows that only when both replicates and the intake cross-check agree. Worth putting on the G7 verifier's list.

## Changed
**Signatures** (files are under the repo's `code/` folder):
- `pipeline.run(...)` keeps every existing parameter, and `holdout_unlock` with its guard is unchanged. It adds `model: ModelSetup | None = None`, `vision_ack: str | None = None`, `regression_gate: bool = False`, `approved_record: Path | None = None` and `caps: LoopCaps | None = None`. `RunSummary` gains `gate` and `passed`.
- `ModelSetup(transport, budget, roots, paid, policy, extra_log)`, with `.replay(cache_dir)`, `.paid_run(transport, *, dollar_cap, call_cap, cache_dir)`, `.from_client(client)` and `.client(namespace, *, paid, log, run_id)`. Also `namespace_roots`, `check_vision_ack`, `VisionReviewRequired`, `text_cases`, `run_routing_check(*, run_id, sources, model, runs_dir, command, repo_root)` and `run_vision(dataset_dir, *, run_id, model, runs_dir, command)`.
- **What a full run may buy:** only the case conversation. The turn-1 replicate and both vision readings are always replayed from the cache.
- New `agent/regression.py`: `load_baseline`, `classify`, `verdict`, `run_gate` and `write_gate`. It reads the baseline path and sha256 from `notes/approved_output.json` and writes `regression_vs_engine.json` and `.md`.
- `audit_with_agent(..., world_for_answers=None)` builds the patched world for `IMAGE_FIELD_UNREADABLE` answers.
- **Per-case report:** adds `intent.committed_label` and `intent.final_label` (T92). `turn1_replicates` is now `[the case's own turn 1, each replicate's]`.
- `engine.py`:
  - `AuditContext.vision_read`: a PNG the vision step read is no longer pending or skipped.
  - R06 rule: a FINDING whose record only post-audit files hold fails the row closed as `POST_AUDIT_ONLY_FINDING`, with a flag naming the resource, decided before the validator.
- `artifacts.py`: `calls.jsonl` is written through GM's `JsonlCallLog` and never truncated. `usage.json` is derived from the calls, including each reply's reply-cache namespace. `cases.jsonl` carries `agent`, `instruction_like_text`, `intent_label`, `open_questions`, `answers` and `rejected`.
- `freeze_check(run_id, *, runs_root, approved_record=None)` prints both sha256 values and refuses on a mismatch.
- The adapter compares intent labels; the keys stay as provenance.
- `holdout_run.pipeline_runner` passes `model=pipeline.ModelSetup.from_client(client)`, which keeps the one $1/60 budget. Vision replays from the cache. `anthropic_client` uses `namespace_roots`.
- `test_properties.py` now checks step order with the hand-written `hand_key` (T63 pin 5).

**Paid commands for stage 1 and vision.** Two commands, one `BudgetGuard` each, with caps that sum to $5.00 and 170 sends. They cannot share one guard: each is its own process, and only one paid run may hold the ledger lock at a time. Run from `.../hackerrank-orchestrate-october26/code`:
```
../.venv/bin/python -B -m deletion_audit routing-check --run-id stage1-routing-<TS> --texts dev,fixtures,redteam --paid --dollar-cap 3.50 --call-cap 146 --env-file ../.env
../.venv/bin/python -B -m deletion_audit vision --run-id vision-<TS> --paid --dollar-cap 1.50 --call-cap 24 --env-file ../.env
```

| Command | Measured on a replay-only dry run | Expected sends | Worst-case reservation per call |
|---|---|---|---|
| Routing check | 66 cases, 61 distinct texts | 122 (not 126) | $0.065 |
| Vision | 11 images | 22 | $0.100 |

The stage-2 dry run found 375 distinct texts, so 750 sends under T97's $20 and 820 caps.

**`--env-file`:** it reads only the `ANTHROPIC_API_KEY` line (an `export` prefix and quotes are allowed) into this process's environment. It is refused without `--paid`, and no message ever quotes the file. A test with a made-up key value checked stdout, stderr, every run artifact, the cache files and the request bodies, and the value appears in none of them.

**Vision-review acknowledgement:** `--vision-ack <vision run id>`. A paid full run is refused (exit 4, `refused.json`, no send) while any image needs review, unless that run's review list and image reports are identical to this run's. The acknowledgement is recorded in `producer.vision.review`.

**Deviations from G3 §5 and §9:**
- `run` takes a `ModelSetup`, not a client.
- `turn1_replicates` now includes the case's own turn 1.
- The regression gate is opt-in (`--regression-gate`, exit 5 on a stop), so a clone without `runs/` can still run.
- `usage.json`'s `cost_usd` is the logged send cost. The guard's settled spend, which counts outcome-unknown failures at their worst case, is in `producer.budget`.
- The adapter's `vision.json` is written next to G7a's `vision_readings.json` and `.md`.

**Not done:** `notes/INTERFACES.md` is not updated (outside my paths). The engine module docstring still says G7 is "not built yet".

## Found
- **Tests:** `code/tests` went from 421 to 489, all OK. `code/evaluation/tests` went from 251 to 277, all OK; 20 of those came from main's T106 report-generator commit during my run. The starting counts were 421 and 251, not the brief's 413 and 252. Lint is clean on every path I touched.
- **Planted faults:** 17 of 17 were caught by a test. Two tests only caught theirs after I tightened them. The script is `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g7wire/mutate.py`.
- **Regression gate (empty cache, replay-only):**

| Set | Run | sha256 | Sends | Replay misses |
|---|---|---|---|---|
| DEV | `g7wire-dev22-20261025T1233` | `641dbc8d921186efbf92514b2c71fe25a3b133d412515dd952da19f8ac85b15c` | 0 | 66 |
| test | `g7wire-test-20261025T1233` | `cf2a90b070db785456b2cb26398add0eba95a69ae8a763eb838a367f135751fc` | 0 | 1058 |

  - The test run's model-on gate found 0 changed rows and passed.
  - The freeze check prints the output and approved sha256 as a match. It still refuses the run, as expected: 18 failed-closed rows, 518 fail-closed intents and 11 skips.
  - Nothing was written to the empty cache.
- **Vision skip fix:** it changes nothing until real readings exist. With no cached readings, `evidence_skip_count` is still 11, `evidence_read_by_vision` is empty, and `UNPARSED_DEPENDENCY` is still 9.
- **R06 rule on real data:** 0 such findings on DEV or test.
- **DEV flips:** none, since the DEV output is byte-identical.
- **UNEXPLAINED steps:** none.
