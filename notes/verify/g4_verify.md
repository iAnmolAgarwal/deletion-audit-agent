# G4 verifier report (orch-verifier, high, directed_by 2026-10-25T02:35:05+05:30)

Saved verbatim by main from the agent's return message; its log entry is the 2026-10-25T02:41:57+05:30 entry in `log.txt`.

---

**Verdict: FIX.** 4 findings: 2 BLOCKER, 2 MAJOR.

The scorer's arithmetic is right; I worked one case by hand and got the same numbers. The two blockers are in the holdout lock and in the producer's evidence-failure guard, not in the metric code. The 80 tests pass (`python3 -B -m unittest discover -s code/evaluation/tests -t code`). Replaying the baseline twice gives byte-identical output, sha256 `60234e8f…`, the same as the stored `output.csv`. Re-scoring that output reproduces the stored `score.json` aggregate exactly, and regenerating `NUMBERS.md` into a temp copy leaves its generated block unchanged.

## Verdict per question
| Q | Verdict | Basis |
|---|---|---|
| 1. Metrics vs published wording | PARTIAL | My hand-worked case matched on all 12 checks (below). Every metric the text names has at least one reading computed. Several reasonable readings are not computed (table). |
| 2. Holdout lock | FAIL | `gold.py` itself is sound, and so are `load_requests`, the tests and the prototype import. `outputs.read_output` is a bypass (B1). |
| 3. Skipped or failed file → COMPLETE | FAIL | Only raised exceptions are refused. An empty parse, a non-`FAILED` skip label or a swallowed exception still writes the wrong case_07 COMPLETE row, with 0 coherence violations (B2). |
| 4. Other | PASS, with 2 MAJOR | Counts in `NUMBERS.md` match the artifacts and every number carries a run ID. Two MAJOR issues below. |

The hand-worked case (`/tmp/verify-g4/hand.py`): gold is the 4-step `incomplete_example`. In the prediction, steps 1 and 2 are swapped and renumbered, step 3 cites `evidence_02`, and step 4 is replaced by a step on `search_1`. The scorer and my hand count agree on every value:
- step tp/pred/gold = 3/4/4, F1 0.75;
- fields on matched steps: state 3/3, evidence 2/3, step_no 1/3, all three together 0/3;
- pairwise order 2/3;
- citation on cited steps 1/1; citation set exact 0; citation IDs 1/2/1;
- prep tuple 2; prep positional 15/28; resources 1/2/2.

## Metric-reading table
| Metric | Published wording | Readings | Computed? |
|---|---|---|---|
| Case status | PS:135 "case-level status accuracy"; RM:83 "deletion assessment accuracy" | (a) exact status match over cases, a missing row counts as wrong | yes, `status_accuracy` |
| | | (b) per-class or balanced accuracy | no; can be derived from `status_confusion` |
| | | (c) an unparseable `steps_json` row counts as status-wrong | **no**: the status is credited (M2) |
| Row | RM:96 "row accuracy" | (a) status and parsed steps equal | yes, `row_exact` |
| | | (b) parsed steps only | yes, `steps_exact` |
| | | (c) byte-exact CSV row | no (`serialize_steps` matches only 17/22 gold rows byte for byte) |
| | | (d) "row" means each step element | see Step (c) and (d) |
| Step | PS:136 "step-level accuracy" | (a) multiset P/R/F1 on (phase, operation, system, resource) | yes |
| | | (b) multiset on the 6-field tuple, step_no excluded | yes, `prep.step_tuple` |
| | | (c) full 7-field equality, step_no included | no |
| | | (d) positional: step i equals gold step i | no |
| | | (e) Jaccard tp/(pred+gold−tp) as "accuracy" | no; can be derived from counts |
| | | (f) per-case macro average of any of these | no; micro only |
| | | (g) per operation | yes, `step_per_operation` |
| Field | PS:136, RM:96 "field-level accuracy" | (a) state / evidence / step_no on key-matched steps | yes |
| | | (b) positional, 7 fields over max(len) slots | yes, `prep.field_positional` |
| | | (c) positional over min(len) | no |
| | | (d) per CSV column (`case_id`, `deletion_status`, `steps_json`) | effectively yes (status, `steps_exact`) |
| | | (e) best-alignment matching that gives partial credit when system/resource is wrong | no (key matching gives 0 field credit) |
| | | (f) per-case macro | no |
| Sequence | PS:137 "sequence accuracy"; PS:131 "completeness and order of `steps_json`" | (a) exact ordered list of step keys | yes |
| | | (b) Kendall pairwise on matched steps | yes |
| | | (c) positional key match rate | no |
| | | (d) LCS / edit-distance ratio | no |
| | | (e) ordered operation list only | no |
| | | (f) the prediction is in spec order (gold-free) | coherence H06 only, not a metric |
| | | (g) step_no correct | yes, field step_no |
| Cited evidence | PS:131 "cited evidence"; RM:86 "evidence references" | (a) equality on matched steps with non-empty gold evidence | yes |
| | | (b) evidence_id equality on all matched steps | yes |
| | | (c) per-case citation set equal | yes |
| | | (d) P/R over (case, id) pairs | yes |
| | | (e) cited ID exists and was captured ≤ `audit_at` | coherence H10 only |
| Identity resolution | PS:131, RM:84 | (a) (system, resource) set P/R | yes, `prep.resources` |
| | | (b) correct system_id per resource | no |
| Discovered records and risks | PS:131, RM:85 | (a) recall per REPORT_* operation | yes, per op |
| | | (b) FINDING-phase P/R as an aggregate | no; can be derived |
| Policy decisions | PS:131, RM:86 | (a) remediation-op P/R per op | yes |
| | | (b) confusion of the chosen remediation per resource (DELETE / REDACT / ANONYMIZE) | no (a wrong op scores as one miss plus one extra) |

Equality is Python `==` after `json.loads`, so `true` and `1.0` both equal `1` (`scorer.py:154`). A Python grader would very likely do the same, so I list this as a reading, not a defect. Coherence H04 flags such rows anyway.

## Findings

**B1 BLOCKER: the holdout lock is bypassed through `read_output`** (`code/evaluation/outputs.py:55`)
- **Cause:** the guard is `path.resolve() == SAMPLE_OUTPUT.resolve()`. APFS is case-insensitive and `resolve()` does not normalise case, so any case variant gets past it. Copies and hard links also get past it, and the guard does not cover the sample requests file at all.
- **Reachable from:** `evaluate.py score`, `coherence` and `drift --pred …` (`evaluate.py:98,198,206`). These run coherence over every row, print it, and compute drift distributions on it.
- **Repro 1** (`python3 -I -B /tmp/verify-g4/probe_lock.py`, counts only):
  ```
  dataset/Sample_Output.csv exists: True resolve==gold: False samefile: True
    read_output ACCEPTED: holdout rows loaded = 10 ; holdout steps_json json-decoded = 10
  ```
  `dataset/SAMPLE_OUTPUT.csv` and `Dataset/sample_output.CSV` give the same result.
- **Repro 2** (`python3 -B /tmp/verify-g4/probe_req.py`):
  ```
  accepted; holdout request rows loaded: 10 ; H02 violations on holdout rows (each detail embeds column 2 verbatim): 10
  ```
  Column 2 is `email`. So `evaluate.py coherence --pred dataset/sample_deletion_requests.csv` would print the holdout requesters' emails.
- **Expected vs actual:** expected a refusal; actual, all 10 holdout rows are parsed and processed.
- **Bug class:** a guard on path identity instead of on content. Fix: `read_output` drops or refuses holdout case IDs unless unlocked, and the identity check uses `os.path.samefile`.

**B2 BLOCKER: the "refuse on any evidence parse failure" guard only catches exceptions** (`code/evaluation/prototype_baseline.py:67`)
- **Cause:** the guard looks only for `:FAILED:` or `-failed` in `world.skipped`. Three things get through:
  - the skip labels `:unknown-json`, `:unknown` and `:png-model-needed` (`extract.py:360-366`);
  - a parse that "succeeds" with no units;
  - a JSON error swallowed per log line (`logparse.py:38-41`).
- **Repro** (`python3 -B /tmp/verify-g4/fault.py <mode> verify-g4-0238-<mode>`, then `evaluate.py coherence --pred runs/verify-g4-0238-<mode>/output.csv --expect dev`):
  - mode `raise` (parse_pdf raises): `evidence parse failures, no output written`, exit 3. Correct.
  - mode `empty_text` (`pdf_text` returns ""): 22 rows written, skipped list `[]`. case_07 goes from INCOMPLETE to `COMPLETE` with 1 step; coherence reports 0 violations.
  - mode `skip_label` (evidence_58 units removed, `evidence_58:unknown-json` added): the same wrong case_07 COMPLETE, 0 violations.
  - swallowed log error: a truncated JSON log line comes back as `{'service': None, 'event': None, 'kv': {}}` with no skip entry.
- **Already present in the baseline:** the run skipped 11 PNGs and still wrote 7 COMPLETE rows. On DEV they do no harm (status 22/22), but nothing stops it on test.
- **Docs:** the INVALID note in `NUMBERS.md` claims "refusing to write output on any evidence parse failure", which overstates the guard.
- **Bug class:** "nothing found" treated as success. Fix: an allow-list of skip reasons, plus a check that each parsed file yields at least one unit, plus marking a case that depends on an unparsed file as failed, not COMPLETE. `evaluate.py score` should also refuse when `producer.json` lists failures or skips that are not allow-listed.

**M1 MAJOR: an unhashable value in a predicted step crashes both the scorer and coherence** (`scorer.py:65` via `contract.step_key`; `coherence.py:171`)
- **Repro:** `python3 -B /tmp/verify-g4/hand.py` prints `CRASH TypeError cannot use 'tuple' as a dict key (unhashable type: 'list')`. `python3 -B /tmp/verify-g4/coh_crash.py` prints `CRASH TypeError unhashable type: 'list'`.
- **Expected vs actual:** expected the row to score as wrong and get an H04 report; actual, the whole run aborts. It does fail closed, but one bad row blocks scoring of a red-team file.
- **Bug class:** untrusted JSON values used as dict, Counter or set members. The same pattern is in `_occurrence_keys`, `_prep_tuple`, `_resources` and the H07 Counters.

**M2 MAJOR: the docstring and the code disagree on unparseable rows** (`scorer.py:121`)
- The docstring says an unparseable prediction "scores as wrong everywhere". The code credits the status (`status_ok = p.status == gold.status`), and `tests/test_scorer.py:95` asserts that it does.
- **Repro:** `hand.py` prints `status_ok = True | pred_valid = False`.
- Pick one reading and record the other in `evaluation_report.md`.

Not blocking: `numbers_md.py` changed after the baseline was scored, so `code_hash()` is now `47195905…`, while `NUMBERS.md` shows `25fb6007…`. A re-score will record a different scorer hash with no change to any metric.

## Files
- Scratch scripts: `/tmp/verify-g4/probe_lock.py`, `/tmp/verify-g4/probe_req.py`, `/tmp/verify-g4/fault.py`, `/tmp/verify-g4/hand.py`, `/tmp/verify-g4/coh_crash.py`, `/tmp/verify-g4/sync.py`.
- Scratch runs, with no `score.json`, so they stay out of `NUMBERS.md`: `runs/verify-g4-0238-empty_text/`, `runs/verify-g4-0238-skip_label/`, `runs/verify-g4-0238-replay1/`, `runs/verify-g4-0238-replay2/`.
- The log entry is appended to `log.txt`. It went in as two back-to-back heredocs, not the single heredoc the brief asked for, because I needed the timestamp expanded in the header.
