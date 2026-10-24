# NUMBERS

Every number here carries its run ID, the command that produced it and what it measures
(`../../CLAUDE.md` section 4). The block between the markers is regenerated from
`runs/<run_id>/score.json` by `python3 -B code/evaluation/evaluate.py numbers`; nothing inside
it is typed by hand. The prose outside the block gives context only and quotes no figures.

## Scope and lock
- All scores are on the 22 DEV cases. Gold loads only through `code/evaluation/gold.py`, which
  drops holdout rows on their first CSV field before `steps_json` is parsed. The holdout has
  not been scored. It will be scored once, after freeze, on the developer's "HOLDOUT EVALUATION RUN".
- The split was made after the prep forensics agent had read all 32 answers, and its
  stratification used gold status, step count and operations (`code/evaluation/split.py`). DEV
  numbers are in-sample: every prototype rule was designed while looking at DEV.

## How the baseline was produced (G4)
- `code/evaluation/prototype_baseline.py` imports the prep prototype (`../research/prototype/solver.py`)
  read-only and writes the 22 DEV rows to `runs/<run_id>/output.csv`. No model calls; nothing is written under `../research/`.
- Variants, each with its own run ID: default (as report 15 ran DEV: no vision table, signature on);
  `--vision` (the hand-typed `vision_facts.py` table, which T7 says does not ship); `--no-signature`;
  `--force-intent` (bypasses `intent.py`'s per-row keyword tables, which T7 also excludes).
- The vision and force-intent outputs are byte-identical to the default output (`cmp`), and the
  flips against the default are empty. So on DEV neither hand-typed input changes any number.
  Their effect is on test cases only: the screenshots, and the 10 non-deletion texts. DEV has no
  NOT_APPLICABLE case, so it cannot measure that effect.

## Reconciliation with report 15 and G2 (by definition, not by tuning)
- The `prep` block re-implements `research/prototype/score.py`. Each valid baseline run's
  reconciliation table below compares it, count by count, with G2's re-measure
  `runs/g2-0137/q2.json` (`g2-q2_reconcile-0137`). G2 found that re-measure equal to report 15 section 1.
- The published block differs from the prep block by definition only:
  - **row exact** is prep `case_exact`, and **steps exact** is prep `steps_exact`.
  - **step**: the published metric matches on the 4-field key (phase, operation, system, resource).
    Prep matches the 6-field tuple, which also includes state and evidence. They agree when no matched
    step has a wrong state or evidence. The discrimination run shows them diverging under `wrong_evidence`.
  - **field**: the published metric compares fields on key-matched steps. Prep compares position by
    position over max(len) slots, so one missing step shifts every later slot. That is why prep
    fields fall below the matched-field rates on the two cases that miss an audit record.
  - **citation set** is report 15's "citation file equal to gold's", generalised to sets.
    The two coincide when each case cites one file, as in every DEV case.
  - **prep resources** is report 15's "(case, resource) pairs found".
- One reconciliation failure happened and was fixed; see "Invalidated runs" at the end of the generated block.

<!-- BEGIN GENERATED: evaluate.py numbers (do not edit by hand) -->
## Scored runs (DEV, 22 cases; holdout never loaded)

| run | status | row exact | steps exact | step P / R / F1 | state | evidence | step_no | seq exact | pairwise order | citation set | prep tuple | prep fields | prep resources | coherence hard / soft |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `g4-baseline-20261025T0229` | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4-baseline-forceintent-20261025T0229` | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4-baseline-nosig-20261025T0229` | 22/22 | 16/22 | 16/22 | 1.0000 / 0.9552 / 0.9771 | 128/128 | 128/128 | 120/128 | 16/22 | 459/459 | 22/22 | 128/134 | 864/938 | 70/76 | 0 / 0 |
| `g4-baseline-vision-20261025T0229` | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |

Metric definitions (code: `code/evaluation/scorer.py`):

- **status**: cases whose deletion_status equals gold
- **row exact**: status equal AND parsed steps_json equal (key order ignored, list order kept)
- **steps exact**: parsed steps_json equal, status ignored (alternative reading of 'row')
- **step P/R/F1**: multiset match on (phase, operation, system_id, resource_id), micro
- **state / evidence / step_no**: field equality on key-matched steps
- **seq exact**: ordered list of step keys equals gold's
- **pairwise order**: concordant pairs / all pairs of matched steps (order only)
- **citation set**: cases whose set of non-empty evidence_ids equals gold's
- **prep tuple**: prep replay: multiset of 6-field tuples (step_no excluded), tp/gold
- **prep fields**: prep replay: position-aligned 7-field hits / (max(len) x 7) slots
- **prep resources**: prep replay: (system_id, resource_id) set, tp/gold

### `g4-baseline-20261025T0229`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T02:29:43+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4-baseline-20261025T0229/output.csv --run-id g4-baseline-20261025T0229 --reconcile runs/g2-0137/q2.json:dev_all --prev g4-baseline-20261025T0228`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4-baseline-20261025T0229`
- Config hash `e40b2d6707f9a08b`; scorer code `25fb6007374a62da`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Cases not row-exact: case_18, case_20

Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions):

| metric | this run | reference | equal |
|---|---:|---:|---|
| status_exact | 22 | 22 | yes |
| case_exact | 20 | 20 | yes |
| steps_exact | 20 | 20 | yes |
| sequence_exact | 20 | 20 | yes |
| step_tp | 132 | 132 | yes |
| step_pred | 132 | 132 | yes |
| step_gold | 134 | 134 | yes |
| field_hits | 908 | 908 | yes |
| field_slots | 938 | 938 | yes |
| res_tp | 74 | 74 | yes |
| res_pred | 74 | 74 | yes |
| res_gold | 76 | 76 | yes |

Flips against `g4-baseline-20261025T0228`: case_07 status_ok False->True, case_07 row_exact False->True, case_07 order_exact False->True, case_07 citation_set_exact False->True

### `g4-baseline-forceintent-20261025T0229`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: force-intent; vision table off; job-timing signature on; intent tables bypassed (all deletion-authorized)
- Scored at 2026-10-25T02:29:43+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4-baseline-forceintent-20261025T0229/output.csv --run-id g4-baseline-forceintent-20261025T0229 --reconcile runs/g2-0137/q2.json:dev_all --prev g4-baseline-20261025T0229`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4-baseline-forceintent-20261025T0229 --force-intent`
- Config hash `4b3101541dd4c446`; scorer code `25fb6007374a62da`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Cases not row-exact: case_18, case_20

Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions):

| metric | this run | reference | equal |
|---|---:|---:|---|
| status_exact | 22 | 22 | yes |
| case_exact | 20 | 20 | yes |
| steps_exact | 20 | 20 | yes |
| sequence_exact | 20 | 20 | yes |
| step_tp | 132 | 132 | yes |
| step_pred | 132 | 132 | yes |
| step_gold | 134 | 134 | yes |
| field_hits | 908 | 908 | yes |
| field_slots | 938 | 938 | yes |
| res_tp | 74 | 74 | yes |
| res_pred | 74 | 74 | yes |
| res_gold | 76 | 76 | yes |

Flips against `g4-baseline-20261025T0229`: none

### `g4-baseline-nosig-20261025T0229`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: no-signature; vision table off; job-timing signature off; intent tables as in intent.py
- Scored at 2026-10-25T02:29:43+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4-baseline-nosig-20261025T0229/output.csv --run-id g4-baseline-nosig-20261025T0229 --reconcile runs/g2-0137/q2.json:dev_nosig --prev g4-baseline-20261025T0229`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4-baseline-nosig-20261025T0229 --no-signature`
- Config hash `0636e701a28a26c1`; scorer code `25fb6007374a62da`; output sha256 `2950ef2780c75a28`; model IDs: none; paid calls: 0
- Cases not row-exact: case_03, case_18, case_20, case_21, case_26, case_27

Reconciliation with `runs/g2-0137/q2.json:dev_nosig` (prototype `score.py` definitions):

| metric | this run | reference | equal |
|---|---:|---:|---|
| status_exact | 22 | 22 | yes |
| case_exact | 16 | 16 | yes |
| steps_exact | 16 | 16 | yes |
| sequence_exact | 16 | 16 | yes |
| step_tp | 128 | 128 | yes |
| step_pred | 128 | 128 | yes |
| step_gold | 134 | 134 | yes |
| field_hits | 864 | 864 | yes |
| field_slots | 938 | 938 | yes |
| res_tp | 70 | 70 | yes |
| res_pred | 70 | 70 | yes |
| res_gold | 76 | 76 | yes |

Flips against `g4-baseline-20261025T0229`: case_03 row_exact True->False, case_03 order_exact True->False, case_21 row_exact True->False, case_21 order_exact True->False, case_26 row_exact True->False, case_26 order_exact True->False, case_27 row_exact True->False, case_27 order_exact True->False

### `g4-baseline-vision-20261025T0229`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: vision; vision table ON (hand-typed, T7: not shippable); job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T02:29:43+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4-baseline-vision-20261025T0229/output.csv --run-id g4-baseline-vision-20261025T0229 --reconcile runs/g2-0137/q2.json:dev_all --prev g4-baseline-20261025T0229`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4-baseline-vision-20261025T0229 --vision`
- Config hash `61d4fcda98ac2869`; scorer code `25fb6007374a62da`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Cases not row-exact: case_18, case_20

Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions):

| metric | this run | reference | equal |
|---|---:|---:|---|
| status_exact | 22 | 22 | yes |
| case_exact | 20 | 20 | yes |
| steps_exact | 20 | 20 | yes |
| sequence_exact | 20 | 20 | yes |
| step_tp | 132 | 132 | yes |
| step_pred | 132 | 132 | yes |
| step_gold | 134 | 134 | yes |
| field_hits | 908 | 908 | yes |
| field_slots | 938 | 938 | yes |
| res_tp | 74 | 74 | yes |
| res_pred | 74 | 74 | yes |
| res_gold | 76 | 76 | yes |

Flips against `g4-baseline-20261025T0229`: none

## Scorer discrimination `g4-discrim-20261025T0229`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4-discrim-20261025T0229` at 2026-10-25T02:29:49+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`).

| variant | status_accuracy.rate | row_exact.rate | step.f1 | field_on_matched.state.rate | field_on_matched.evidence_id.rate | field_on_matched.step_no.rate | sequence_exact.rate | sequence_pairwise_order.rate | citation_set_exact.rate | field_positional.rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gold | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| gold_reformatted | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| majority_empty | 0.6818 | 0.0000 | 0.0000 | n/a | n/a | n/a | 0.0000 | n/a | 0.0000 | 0.0000 |
| drop_last_step | 1.0000 | 0.0000 | 0.9106 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.9091 | 0.8358 |
| extra_step | 1.0000 | 0.0000 | 0.9241 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0.8590 |
| swap_first_two | 1.0000 | 0.0909 | 1.0000 | 1.0000 | 1.0000 | 0.7015 | 0.0909 | 0.9594 | 1.0000 | 0.8486 |
| wrong_state | 1.0000 | 0.0000 | 1.0000 | 0.8358 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9765 |
| wrong_evidence | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0.6119 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.9446 |
| step_no_shift | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 0.8571 |
| flip_status | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

## Invalidated runs (kept as evidence; their numbers are not results)

- `g4-baseline-20261025T0228`: INVALID: produced while code/evaluation/numbers.py shadowed the stdlib `numbers` module (the script's folder was sys.path[0]), so pdfplumber failed to import, the prototype skipped evidence_58 (the one DEV PDF) and case_07 came out COMPLETE with 1 step. Fixed by renaming the module to numbers_md.py, dropping the script folder from sys.path, and refusing to write output on any evidence parse failure. Superseded by the g4-baseline*-20261025T0229 runs.
<!-- END GENERATED -->
