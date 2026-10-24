# G4 fix round-3 verifier report (orch-verifier, high, directed_by 2026-10-25T04:50:18+05:30)

Saved verbatim by main from the agent's return message; its log entry is the 2026-10-25T04:58:10+05:30 entry in `log.txt`. This was the last review round (`../CLAUDE.md` §6). Under T80, its non-BLOCKER findings go on the G9 list in `TASKS.md`.

---

**Verdict: PASS.** Nothing blocking. I found 1 MAJOR and 3 MINOR problems; all four go on the G9 list.

All 144 tests pass. I never opened `sample_output.csv`, made no paid calls, and wrote to the repo only my log entry (stamped 2026-10-25T04:58:10+05:30; `check_log.py` reports 0 blocking).

| Q | Verdict | Basis |
|---|---|---|
| 1a. M1 closed | YES | The repro now gives `rows ['case_01'] ['record 3: invalid UTF-8 bytes; record skipped']`. `score` and `coherence` exit 2 with `[HARD H16]`, and `drift` exits 0 without crashing. I also tried a bad byte inside a multi-line cell, a bad byte before an unterminated quote, CESU surrogates, a NUL byte and a UTF-16 file. Each one gives a hard issue and none crashes. |
| 1b. Misalignment | NO | A decode skip drops only its own record, because escaped bytes are never CSV delimiters. Every skip counts as a hard H16, and the CSV-error path keeps its "may be misaligned" hard issue from round 2. |
| 1c. M2 closed | PARTIAL | `--prev` refuses `../outside/x`, `a b`, `.x`, `x/../y` and `x%2f` with a ValueError. `load_score` and `run_dir` both check the ID. But `numbers_md` reads files using a run ID taken from inside `score.json`, with no check (m1). |
| 2. Hash and parse | MOSTLY | `cfg.pred_sha256` is `out.sha256`, the hash of the bytes that were parsed. The second gold check refuses a copy of the synthetic gold, and it does not refuse a non-gold file of the same size. But it fails open if the file disappears between the read and the check (M1). |
| 3. Regression | PASS | `g4fix3-baseline-20261025T0453` and the reference `g4fix2-baseline-final-20261025T0429` both have output sha256 `60234e8f…`, and `cmp` finds the files identical. Aggregates and cases are equal, flips are `[]` and coherence is 0/0. The run's scorer code hash `025bae74…` matches the current code, and the rendered numbers block matches `NUMBERS.md`. Two replays into `/tmp` gave identical bytes. In mutation tests, 6 of 8 reverted fixes make the tests fail; 2 still pass (m2). |

## Findings

**M1 MAJOR: the second gold check fails open when the path vanishes** (`code/evaluation/outputs.py:115-122`, reached from `:152`)
- **Cause:** when `data` is passed, `os.path.samefile(path, gold)` still runs first. If the path has been removed or renamed, it raises OSError, and `except OSError: return False` returns before the held bytes are ever compared.
- **Repro:** `.venv/bin/python -B /tmp/verify-g4fix3/gold2.py` (synthetic gold only). In this test the file holds gold bytes when it is read and is removed right after.
  ```
  held gold bytes, path gone: False
  RACE: read gold rows: ['case_99']
  ```
- **Expected vs actual:** expected `HoldoutLockedError`, because the bytes held are gold. Actually, the gold rows are parsed.
- **Why not a BLOCKER:** it takes a deliberate concurrent rename or unlink, and nothing in the pipeline does that.
- **Bug class:** a guard that fails open on an error from a check it doesn't need. With `data` in hand, compare the size and hash of `data` first, and catch OSError only around the gold-side `stat`.

**m1 MINOR (pre-existing): `numbers_md` reads by a run ID taken from file content** (`code/evaluation/numbers_md.py:124`, `:162`)
- **Repro:** `.venv/bin/python -B /tmp/verify-g4fix3/nm.py`. It plants a `score.json` whose `run_id` is `"../outside"`, then reads `['/tmp/verify-g4fix3/nm/runs/../outside/config.json']`.
- **Expected vs actual:** expected `check_run_id` to refuse the ID, or the code to use the directory name. Actually, it reads a file outside `runs/`. Only a hand-made `score.json` can trigger this.
- **Bug class:** the same as M2 from round 2.

**m2 MINOR: two round-3 claims have no test that pins them** (`code/evaluation/tests/test_round3.py:105`, `:120-124`)
- **Repro:** `bash /tmp/verify-g4fix3/mutate.sh`
  ```
  no-early-prev: round3=[OK] all=[OK]
  rehash-hashlib: round3=[OK] all=[OK]
  ```
- **Early `--prev` check:** removing it at `evaluate.py:105-106` still passes, because `load_score` raises at `:160` before anything is written. The test checks that no files exist, not that the directory doesn't.
- **One read:** re-hashing with `hashlib` from a second read still passes, because the test only patches `runs.sha256_file`.
- **Bug class:** a test that only confirms what the code already did.

**m3 MINOR: `drift` ignores read issues** (`code/evaluation/evaluate.py:243-251`)
- **Repro:** `score_tmp.py drift --pred runs/v3-utf8/output.csv --run-id v3-utf8`, run from `/tmp/verify-g4fix3`, exits 0.
- **Actual:** it prints nothing about the skipped record, so the drift table silently covers fewer rows.
- **Bug class:** an error that is recorded but never shown.

Scratch files are in `/tmp/verify-g4fix3/`:
- `gold2.py`
- `nm.py`
- `mis.py`
- `mutate.sh`
- `utf8.py`
- `score_tmp.py`
- `proto_tmp.py`
- `runs/`
