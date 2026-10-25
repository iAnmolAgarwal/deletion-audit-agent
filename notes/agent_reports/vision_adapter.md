# Vision-adapter fix report (orch-eval-engineer, high)

directed_by 2026-10-25T12:41:01+05:30 (T108), with T109 (c) and T110 added. **Main's check:** `code/evaluation/tests` 308 OK; lint clean (50 files); no access log. The changes depend on fix round 2's uncommitted schema fields (`visible_markers`, `status_label`), so they are committed together with fix round 2. The acknowledgement shape `{file_id, reply_keys, reading_sha256}` was sent to fix round 2.

Saved verbatim from the agent's final message.

---

The agent report and the freeze check now read the real vision artifacts, and every image is reported. No model calls; I did not read `.env`, open gold or `dataset/sample_output.csv`, or write anything under `code/deletion_audit/`.

## Blocked on me
1. **The acknowledgement record's shape is my guess.** Fix round 2 hasn't written it yet. I read `producer.json` → `vision.review.acknowledged` as a list of `{"file_id", "reply_keys": [reading 1 key, reading 2 key]}`. If that list is missing, nothing counts as acknowledged, so disagreements stay blocking. If fix round 2 picks other names, they only change in `REVIEW_KEYS` in `agent_report.py`. Can main pass this shape to fix round 2, or tell me theirs?
2. **A key match can't tell a re-read from the original.** The writer gives both readings the same request key (same request, different cache roots). So "both keys match" only proves the same request was sent. A re-read of the same PNG after a cache flush would still match. Should the acknowledgement also carry a hash of the two readings' contents? That would be a change on the writer's side.
3. **My work depends on fix round 2's uncommitted writer change.** `deletion_audit/agent/vision.py` and `schemas.py` gained `visible_markers` and `status_label` while I was working; my fixture test caught it. The adapter and fixture follow the current working tree, so these files should be committed together with fix round 2's changes.

## Changed
- **`code/evaluation/agent_report.py`, how vision artifacts are read:**
  - **Failed image:** counted as failed, never as agreeing or as zero. The report gives its failure code (`VISION_READ_FAILED` or `VISION_NOT_PNG`) and which readings came back null.
  - **Label with no resource ID** (no system, e.g. `CS-4821`): listed and counted as unmapped.
  - **Nested disagreement:** I re-check each one from the two readings using the writer's own comparison rule, and name it by path, e.g. `records[acct_1003].sync_enabled`. The phone-number "+" case can go either way, so the check accepts either answer there.
  - **Review file:** `vision_readings.json` must hold the same images and review list as `vision.json`.
  - **T112 4(a):** acknowledged and unresolved disagreements are listed separately.
  - **T112 4(b):** images that changed a row are listed from `regression_vs_engine.json`. A run without that file says "not recorded", not zero.
  - Text the model read off a screenshot (shown IDs, markers, labels) is never printed unless it is ID-shaped.
- **`code/evaluation/freeze_check.py`, six blocking counts:**
  - **`agent_failed_cases`** (T109 (c), T110 (1)): blocks. Each case is listed with its error class, taken from the record flag's detail, else from the failed call in `calls.jsonl`, else "not recorded". The refusal says to re-run the same command.
  - **`vision_failed_readings`:** blocks, because an unread screenshot is an unread dependency and freeze needs 0 skips (T60).
  - **`vision_unresolved_disagreements`:** blocks (T88/T101) unless an acknowledgement names that file and both reading keys.
  - **`vision_unmapped_labels`:** listed only, not blocking, because a label is not a resource ID.
- **T110 (2) repeat-failure stop:** `--prior-run-id` (repeatable, oldest first). If a case fails with the same error class in this run and the two runs just before it, the check returns `STOP-FOR-DEVELOPER` (exit 4) with the case, the error class and the request size. Nothing clears it. The request size is the largest `input_tokens` logged for the case's requests; the failed request itself logs none. An unrecorded error class counts as the same class every time, so missing data can't avoid the stop.
- **Tests:** a new fixture, `code/evaluation/tests/vision_fixtures.py`, is written by the real writer (`assess_image`, `vision_run_report`, `write_vision_artifacts`) with fake readers. It holds a clean image, a failed one, one with an unmapped label and one with a nested disagreement. New tests are in `code/evaluation/tests/test_vision_artifacts.py`. I updated `run_dirs.py`, `holdout_fixtures.py`, `test_agent_report.py` and `test_freeze_check.py`.
- **Log:** entry appended, and `python3 -I scripts/check_log.py` passes.

## Found
- **Fixture through both tools:** the report shows `Images 4: read 3, failed 1 … disagree 1`, with `evidence_09 | VISION_READ_FAILED | 2`, `evidence_19 | records[acct_1003].sync_enabled` and `evidence_14 | CS-4821 | unrecognized | none`. The freeze check exits 1 with `vision_failed_readings = 1 (e.g. evidence_09 [VISION_READ_FAILED])` and `vision_unresolved_disagreements = 1 (e.g. evidence_19 [records[acct_1003].sync_enabled])`. It lists `evidence_14:CS-4821` as not blocking.
- **Real run `g7wire-dev22-20261025T1233`** (read-only): no adapter errors now. It refuses on real counts: `intent_failed_closed` 22, `agent_failed_cases` 22 (all `CacheMiss`), `evidence_skips` 11, `vision_failed_readings` 11, and its output sha256 does not match the approved file.
- **Re-running doesn't fix a `CacheMiss`:** on a replay-only run, re-running the same command can't help, because the missing reply has to be bought in a paid run first. The refusal text doesn't say this yet.
- **Tests:**

  | Check | Result |
  |---|---|
  | `code/evaluation/tests` | 308 OK |
  | `code/tests` | 541 OK, twice in a row |
  | `bash scripts/lint.sh code/evaluation` | ruff and mypy clean |
  | Planted faults | 13 of 13 caught |

  One earlier `code/tests` run showed 542 tests and 1 failure while fix round 2 was editing its tests. It did not repeat.
- **Limit:** `vision.json` stores only failure codes. Details such as `max_tokens` stay in the writer's flag text, so the report can't show them.
