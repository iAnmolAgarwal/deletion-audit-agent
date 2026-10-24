# G4 fix round-2 verifier report (orch-verifier, high, directed_by 2026-10-25T04:24:24+05:30)

Saved verbatim by main from the agent's return message (HTML-escaped angle brackets restored); its log entry is the 2026-10-25T04:39:42+05:30 entry in `log.txt`.

---

**Verdict: FIX.** I found 2 MAJOR problems. Nothing is blocking.

All 135 tests pass. F1, F2 and F3 are closed on their original repros, and both notes hold. The two remaining problems are of the same kinds as F3 and T72, reached by inputs the round-2 changes didn't cover. I never opened `sample_output.csv` and made no paid calls. The only repo write is my log entry; `check_log.py` passes (0 blocking).

| Q | Verdict | Basis |
|---|---|---|
| 1. Findings closed | PARTIAL | **F1:** `fault.py fake_png_label` now exits 3 with `evidence_58:png-model-needed:not-a-png-by-content` and writes no output. The `unknown-json` and `png-model-needed-FAILED:x` labels also refuse. **F2:** a stale record next to a changed output gives `output-mismatch`, and so does a fallback `runs/<id>/producer.json`. Only identical bytes give `ok`. **F3:** a 200k cell now reads, and the field limit is restored to 131072 afterwards. **Other ways in:** a file that starts with the PNG signature passes by design (content signature only), and T60 empties the allow-list at freeze. A record whose hash matches but which comes from another variant can only describe identical bytes, so the numbers are the same. A file changed after scoring doesn't matter, because `NUMBERS.md` re-checks the hash stored in `config.json` for the bytes that were scored. A CSV error that misaligns later records does inject rows from inside a quoted cell, but it is flagged as hard H16 ("may be misaligned") and `score` exits 2. **Still open:** invalid UTF-8 crashes the read (M1 below). |
| 2. Notes | PASS | I fuzzed every message path with a marker string in every cell: case IDs with Arabic-Indic digits, a newline, an email, extra columns, duplicates, and status and step fields. The marker appeared 0 times in the issues, `format_report` or `summarize`. `drift` does print enum values, but that is its purpose (value distributions), not a coherence message. Across 16×17 skip/failure type combinations, only the true lists `[]` and `["e:png-model-needed"]` give `ok`. |
| 3. Run IDs | PARTIAL | `run_dir` rejects traversal, whitespace, separators, a leading dot or dash, and non-ASCII. The 3 old directories with spaces in their names still load and are excluded as INVALID. But `--prev` skips the check (M2 below). |
| 4. Reports | PASS | Rendering in memory gives exactly the block on disk. The only included runs are the five `g4fix2-*` runs. All four `g4fix-*` runs whose record has no `output_sha256` are excluded with "current check says unverified". |
| 5. Regression | PASS | `g4fix2-baseline-final-20261025T0429` and `g4fix-baseline-20261025T0314` both have output sha256 `60234e8f…`. All 183 aggregate leaves are equal, the cases are equal, flips are `[]`, and coherence is 0/0. My two separate replays gave the same bytes, and their producer records differ only in `command` and `created_at`. On the self-confirming question, I reverted each of the 11 fixes in a `/tmp` copy, and every revert makes `test_round2` fail. `test_cap_value` and `TestRunNotes` only assert constants, which is weak but harmless. |

## Findings

**M1 MAJOR: one non-UTF-8 byte in any cell crashes `read_output`, so `score` and `coherence` abort** (`code/evaluation/outputs.py:142`, which opens the file with `encoding="utf-8-sig"`; the decode error escapes the `except csv.Error` at line 151)
- **Repro:** `python3 -B /tmp/verify-g4fix2/f3/utf8.py` (one `\xe9` byte inside `steps_json`), then `score_tmp.py score --pred /tmp/verify-g4fix2/runs/v2-utf8/output.csv --run-id v2-utf8`.
  ```
  CRASH UnicodeDecodeError 'utf-8' codec can't decode byte 0xe9 in position 98
  ```
- **Expected vs actual:** expected an H16 issue for that record and the read to carry on, as the docstring promises ("never a crash"). Actual: a traceback, and the whole file is blocked.
- **Bug class:** F3 again. Untrusted input errors are handled for one error type only. Fix it in one place: decode `raw_bytes`, which the function already reads, and turn every decode or CSV failure into an issue.

**M2 MAJOR: `--prev` bypasses the T72 run-ID check** (`code/evaluation/runs.py:94–96` `load_score`; called at `code/evaluation/evaluate.py:158`)
- **Repro:** `score_tmp.py score --pred …/v2-clean/output.csv --run-id v2-clean --prev "../outside/x"`
  ```
  flips vs ../outside/x: [{'case_id': 'case_07', 'metric': 'status_ok', 'prev': False, 'now': True}, …]
  prev_run stored: '../outside/x'
  ```
- **Expected vs actual:** expected a `ValueError` for a bad run ID. Actual: it reads a `score.json` from outside `runs/` and writes the flips against it into `score.json` and `flips.json`. A slipped quote can also point it at one of the INVALID directories that have spaces in their names. `NUMBERS.md` then prints "excluded below" for a run that is never listed. Flips feed the keep-or-revert decisions (§4).
- **Bug class:** a rule applied at one entry point, not all of them. Put the `RUN_ID_RE` check in `load_score` (and in any other read by run ID).

## Not findings
- **Race in `cmd_score`:** the file is parsed (`read_output`), hashed at `evaluate.py:107` and hashed again at `:138` in separate reads, so a concurrent writer could split what is scored from what is hashed. Hashing and parsing one read of the bytes would close it.
- **Run ID taken from file content:** `numbers_md` finds `config.json` through the `run_id` inside `score.json`, not the directory name. For every existing run the two are equal.
- **Log entry deviation:** in its quote of this brief, I replaced the brief's eight-line Context code block with a one-line placeholder, so the quote is not verbatim at that point. I did it so that only one set of Context lines appears in the entry.

Files are in `/tmp/verify-g4fix2/`:
- `fault.py`
- `score_tmp.py`
- `note1.py`
- `note2.py`
- `f3/f3.py`
- `f3/utf8.py`
- `mutate.sh`
- `runs/`

Log entry: `log.txt`, stamped `2026-10-25T04:39:42+05:30`.
