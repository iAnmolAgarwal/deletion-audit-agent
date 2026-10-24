# G4-fix verifier report (orch-verifier, high, directed_by 2026-10-25T03:08:01+05:30)

Saved verbatim by main from the agent's return message; its log entry is the 2026-10-25T03:31:04+05:30 entry in `log.txt`.

---

**Verdict: FIX.** 3 findings, all MAJOR. Nothing blocking.

All 116 tests pass. Every lock probe used a synthetic gold file; I never opened the real `sample_output.csv`. I wrote nothing to the repo except the log entry, which `check_log.py` passes.

| Q | Verdict | Basis |
|---|---|---|
| 1. Holdout lock | PASS | On synthetic gold, the guard refuses the gold path itself, a copy and a stdin redirect. A pipe or `<(cat …)` gets past the check, but `read_output` reads the stream twice (`read_bytes`, then `open`), so it parses 0 rows. A copy with one byte changed still gets through: that is the accepted T47 residual, tracked under G10 for the README. Requests now load all 32 rows. The producer uses `cases=DEV_IDS`, and `score_predictions` scores only DEV gold keys (non-gold predictions are counted, not scored). This matches T47. |
| 2. Fail closed | PARTIAL | Every injected fault gave exit 3 and no output (below). The allow-listed skip is the gap (F1). The T51 state is decided by content (`%PDF-` magic plus the resource-ID token check). It is listed, never passed silently. |
| 3. Reports | PARTIAL | `numbers_md.render` includes only runs whose `producer_check` is `ok`. The pre-guard runs and the unverified `g4fix-rescore` run are listed under "Excluded" with a reason. `evidence_skip_count` (11) is in the producer record and in `score.json`. But the record is not tied to the output it scores (F2). |
| 4. M1 / M2 | PARTIAL | A fuzz of 74 inputs (list, dict, NaN or bool in each of the 7 fields, non-object steps, odd statuses, deep nesting) gave 0 crashes across the scorer, coherence and drift. Reading (c) is `status_ok and p.valid`, as the docstring says. One crash remains (F3). |
| 5. Coherence messages | PASS (by the ruling) | Status, step values and parse errors are no longer printed. Only the first-column value is printed, as the case name, unvalidated: a synthetic file with an email in column 1 printed it in 3 lines. T51 allows naming the case, and every dataset CSV has an ID in column 1, so this is not a finding. A `^case_\d+$` check would close it. |
| 6. Regression | PASS | Both outputs have sha256 `60234e8f…` and `cmp` finds them identical. All 180 aggregate leaves are equal; the only additions are the 3 new reading-(c) keys. The per-case diffs are only the new field, `flips.json` is `[]`, and coherence is 0/0 in both. Two fresh processes gave byte-identical output; their producer records differ only in `command` and `created_at`. The rendered `NUMBERS.md` block equals the file on disk. |

The fault-injection script is `python3 -B /tmp/verify-g4fix/fault.py <mode> vg4fix-<mode>`; its outputs go under `/tmp/verify-g4fix/runs`. Each mode refused with exit 3 and wrote no output:
- `empty_text`: 4 × `zero-units-empty-text`;
- `pdf_drop_units`: evidence_55 and evidence_58 refused with `resource-id-unparsed`, while evidence_18 and evidence_27 were listed under "text present, no resource ID";
- `skip_label` (`unknown-json`) and `png_prefix_label` (`png-model-needed-FAILED:x`) both refused;
- `log_trunc`: `evidence_06:log-json-failed`;
- `json_zero`: 4 × `zero-units`;
- `alias_fail`: 4 × `alias-scan-failed`.

## Findings

**F1 MAJOR: an allowed skip is trusted by its label, and the label comes from the file suffix** (`code/evaluation/evidence_guard.py:91`, `:217–222`; the label is set at `research/prototype/extract.py:363–364`)
- **Repro:** `python3 -B /tmp/verify-g4fix/fault.py fake_png_label vg4fix-fake_png_label`. This drops evidence_58's units (a PDF) and labels it `evidence_58:png-model-needed`.
  ```
  wrote 22 DEV rows ...; exit 0 | output written: True
  diff vs clean:  < case_07,INCOMPLETE   > case_07,COMPLETE
  producer evidence_failures: []
  ```
- **Expected vs actual:** expected a refusal, because the file is not an image. Actual: the producer check is `ok` and case_07 comes out with the wrong COMPLETE status. Any file whose name ends in `.png` reaches the allowed state by name alone. T51 required content-based checks for the new state, but the older allowed state was left on file names. In the dataset, all 11 `.png` files do start with the PNG magic bytes `89504e47…`.
- **Bug class:** a state decided by file name or label, not by content. **Fix:** allow a `png-model-needed` skip only when the file's bytes start with `\x89PNG\r\n\x1a\n`. Carry the same rule into G5. T60 empties the allow-list at freeze, which is why this is MAJOR and not BLOCKER.

**F2 MAJOR: `score` does not check that the producer record describes the file it scores** (`code/evaluation/evaluate.py:104–108`; `prototype_baseline.py:101–125` records no output hash)
- **Repro:** I copied a good `producer.json` into `/tmp/verify-g4fix/runs/vg4fix-stale/` beside a different `output.csv`, then ran `python3 -B /tmp/verify-g4fix/score_tmp.py score --pred /tmp/verify-g4fix/runs/vg4fix-stale/output.csv --run-id vg4fix-stale`. `score_tmp.py` patches `runs.RUNS` to point under /tmp.
  ```
  producer check: ok (.../vg4fix-stale/producer.json) ...
  status (a) 21/22 ...      score.json producer_check: ok
  ```
- **Expected vs actual:** expected the run to be "unchecked" or refused. Actual: it passes as `ok`, so under T60 it would feed `NUMBERS.md`. The same happens when `--pred` sits somewhere without a record and the fallback `runs/<run_id>/producer.json` belongs to another output, or when a later producer overwrites `output.csv` in a run directory that already has a record.
- **Bug class:** a provenance link made by location, not by content. **Fix:** the producer writes `output_sha256` into its record, and `check_producer` refuses (or marks the run unchecked) when that hash differs from `pred_sha256`.

**F3 MAJOR: an oversized `steps_json` cell crashes `read_output`** (`code/evaluation/outputs.py:111–112`)
- **Repro:** a synthetic row whose `steps_json` is `[{"x": "a"*200000}]`, read with `read_output`, gives `CRASH Error field larger than field limit (131072)`.
- **Expected vs actual:** expected the row to be recorded as an issue (H16, or H03 as unparseable) while scoring continues. Actual: `_csv.Error` aborts `score`, `coherence` and `drift`. This fails closed, but one red-team row blocks the whole file, which is the M1 class.
- **Bug class:** untrusted size or value limits not handled. **Fix:** raise `csv.field_size_limit`, or catch `csv.Error` per record and turn it into an issue.

Not findings:
- `check_producer` treats `evidence_failures: null` as an empty list (`evidence_guard.py:288`). Only a producer could write that, so I recorded it only as a note.
- A file whose units are only scope markers is not re-checked for rows. In the prototype, every row emits a unit, so the hole can't be reached today.

Files:
- `/tmp/verify-g4fix/mk_synth.py`
- `/tmp/verify-g4fix/probe_pipe.py`
- `/tmp/verify-g4fix/fuzz.py`
- `/tmp/verify-g4fix/fault.py`
- `/tmp/verify-g4fix/score_tmp.py`
- `/tmp/verify-g4fix/runs/`
- Log entry: `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/log.txt`, stamped `2026-10-25T03:31:04+05:30`.
