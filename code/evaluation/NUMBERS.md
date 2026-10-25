# NUMBERS

Every number here carries its run ID, the command that produced it and what it measures
(the kit rules, `../../../CLAUDE.md` section 4, outside this repo). The block between the markers is regenerated from
`runs/<run_id>/score.json` by `python3 -B code/evaluation/evaluate.py numbers`; nothing inside
it is typed by hand. The prose outside the block gives context only and quotes no figures.

## Scope and lock
- All scores are on the 22 DEV cases. Gold loads only through `code/evaluation/gold.py`, which
  drops holdout rows on their first CSV field before `steps_json` is parsed. The holdout has
  not been scored. It will be scored once, after freeze, on the developer's "HOLDOUT EVALUATION RUN".
- The split was made after the prep forensics agent had read all 32 answers, and its
  stratification used gold status, step count and operations (`code/evaluation/split.py`). DEV
  numbers are in-sample: every prototype rule was designed while looking at DEV.
- The lock covers gold only (T47). `outputs.read_output` refuses the gold file by identity (same
  file, or same bytes), whatever the path spelling. Request inputs are not locked; a DEV run
  selects its cases explicitly.

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
- Evidence guard (T47, `code/evaluation/evidence_guard.py`). The producer writes no output when:
  - a skip reason is outside the allow-list (`png-model-needed` only);
  - a parsed file yields zero units and declares no empty scope;
  - a log line's JSON fails to parse.

  One exception is listed instead of refused (T51): "text present, no resource ID". It covers a
  PDF (recognised by content) whose text layer is non-empty and whose raw text holds no token
  shaped like a resource ID. If such a token is present while the parser yields nothing, the run
  refuses. An empty text layer also refuses.
  `evaluate.py score` checks the producer record next to the prediction file and refuses on any
  failure. Only runs whose producer check passed feed this file (T51). A run with no record, or with
  a record from before the guard, is listed by ID with the reason, under "Excluded runs", and nothing else.
  The producer record carries the evidence skip count, which must be 0 at freeze (G9).
- T72 tightenings:
  - A `png-model-needed` skip is allowed only when the file's bytes start with the PNG signature.
  - The producer record carries `output_sha256`; a record whose hash differs from the scored file is
    `output-mismatch`, and one without a hash is `unverified`.
  - The check is re-run with the current rules when this file is rendered, so a run that passed
    an older, weaker check is excluded and listed with the reason.

## Reconciliation with report 15 and G2 (by definition, not by tuning)
- The `prep` block re-implements `research/prototype/score.py`. Each listed baseline run compares
  it, count by count, with G2's re-measure `runs/g2-0137/q2.json` (`g2-q2_reconcile-0137`) and states
  whether every count is equal; the reference values themselves live in that run's `score.json`.
  G2 found that re-measure equal to report 15 section 1.
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
## Scored runs (DEV, 22 cases; holdout never loaded; producer check passed)

| run | status | status (c) | row exact | steps exact | step P / R / F1 | state | evidence | step_no | seq exact | pairwise order | citation set | prep tuple | prep fields | prep resources | coherence hard / soft |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `g4fix2-baseline-20261025T0428` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix2-baseline-final-20261025T0429` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix2-baseline-forceintent-20261025T0429` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix2-baseline-nosig-20261025T0429` | 22/22 | 22/22 | 16/22 | 16/22 | 1.0000 / 0.9552 / 0.9771 | 128/128 | 128/128 | 120/128 | 16/22 | 459/459 | 22/22 | 128/134 | 864/938 | 70/76 | 0 / 0 |
| `g4fix2-baseline-vision-20261025T0429` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix3-baseline-20261025T0453` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix3-baseline-nosig-20261025T0453` | 22/22 | 22/22 | 16/22 | 16/22 | 1.0000 / 0.9552 / 0.9771 | 128/128 | 128/128 | 120/128 | 16/22 | 459/459 | 22/22 | 128/134 | 864/938 | 70/76 | 0 / 0 |
| `g4fix3-baseline-forceintent-20261025T0453` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4fix3-baseline-vision-20261025T0453` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4g9-baseline-20261025T0506` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4g9-baseline-nosig-20261025T0506` | 22/22 | 22/22 | 16/22 | 16/22 | 1.0000 / 0.9552 / 0.9771 | 128/128 | 128/128 | 120/128 | 16/22 | 459/459 | 22/22 | 128/134 | 864/938 | 70/76 | 0 / 0 |
| `g4g9-baseline-vision-20261025T0506` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4g9-baseline-forceintent-20261025T0506` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g5-dev-iter1-score` | 21/22 | 21/22 | 18/22 | 18/22 | 0.9922 / 0.9552 / 0.9734 | 128/128 | 127/128 | 122/128 | 18/22 | 464/464 | 22/22 | 127/134 | 876/938 | 73/76 | 0 / 1 |
| `g5-dev-iter2-score` | 22/22 | 22/22 | 19/22 | 19/22 | 1.0000 / 0.9776 / 0.9887 | 131/131 | 131/131 | 126/131 | 19/22 | 470/470 | 22/22 | 131/134 | 899/938 | 73/76 | 0 / 1 |
| `g5-dev-iter3-score` | 22/22 | 22/22 | 19/22 | 19/22 | 1.0000 / 0.9776 / 0.9887 | 131/131 | 131/131 | 126/131 | 19/22 | 470/470 | 22/22 | 131/134 | 899/938 | 73/76 | 0 / 1 |
| `g4lint-baseline-20261025T0529` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4lint-baseline-nosig-20261025T0529` | 22/22 | 22/22 | 16/22 | 16/22 | 1.0000 / 0.9552 / 0.9771 | 128/128 | 128/128 | 120/128 | 16/22 | 459/459 | 22/22 | 128/134 | 864/938 | 70/76 | 0 / 0 |
| `g4lint-baseline-vision-20261025T0529` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |
| `g4lint-baseline-forceintent-20261025T0529` | 22/22 | 22/22 | 20/22 | 20/22 | 1.0000 / 0.9851 / 0.9925 | 132/132 | 132/132 | 128/132 | 20/22 | 473/473 | 22/22 | 132/134 | 908/938 | 74/76 | 0 / 0 |

Metric definitions (code: `code/evaluation/scorer.py`):

- **status**: cases whose deletion_status equals gold; reading (a): an unparseable steps_json row's status is still credited
- **status (c)**: reading (c): as status, but a row whose steps_json is not a JSON list counts as status-wrong
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

### `g4fix2-baseline-20261025T0428`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T04:28:54+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix2-baseline-20261025T0428/output.csv --run-id g4fix2-baseline-20261025T0428 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix-baseline-20261025T0314`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix2-baseline-20261025T0428`
- Config hash `89ea06d931587989`; scorer code `91c12d0fecf70fc5`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix2-baseline-20261025T0428/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix-baseline-20261025T0314`: not shown here (that run is excluded below); they are in this run's `flips.json`

### `g4fix2-baseline-final-20261025T0429`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T04:29:53+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix2-baseline-final-20261025T0429/output.csv --run-id g4fix2-baseline-final-20261025T0429 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix-baseline-20261025T0314`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix2-baseline-final-20261025T0429`
- Config hash `ef5876722b2cd3c5`; scorer code `de6ac88cf636cbb8`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix2-baseline-final-20261025T0429/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix-baseline-20261025T0314`: not shown here (that run is excluded below); they are in this run's `flips.json`

### `g4fix2-baseline-forceintent-20261025T0429`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: force-intent; vision table off; job-timing signature on; intent tables bypassed (all deletion-authorized)
- Scored at 2026-10-25T04:29:54+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix2-baseline-forceintent-20261025T0429/output.csv --run-id g4fix2-baseline-forceintent-20261025T0429 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix2-baseline-forceintent-20261025T0429 --force-intent`
- Config hash `bc4e42be5af97976`; scorer code `de6ac88cf636cbb8`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix2-baseline-forceintent-20261025T0429/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-final-20261025T0429`: none

### `g4fix2-baseline-nosig-20261025T0429`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: no-signature; vision table off; job-timing signature off; intent tables as in intent.py
- Scored at 2026-10-25T04:29:54+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix2-baseline-nosig-20261025T0429/output.csv --run-id g4fix2-baseline-nosig-20261025T0429 --reconcile runs/g2-0137/q2.json:dev_nosig --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix2-baseline-nosig-20261025T0429 --no-signature`
- Config hash `2f40f7a09be284b8`; scorer code `de6ac88cf636cbb8`; output sha256 `2950ef2780c75a28`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix2-baseline-nosig-20261025T0429/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_03, case_18, case_20, case_21, case_26, case_27
- Reconciliation with `runs/g2-0137/q2.json:dev_nosig` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-final-20261025T0429`: case_03 row_exact True->False, case_03 order_exact True->False, case_21 row_exact True->False, case_21 order_exact True->False, case_26 row_exact True->False, case_26 order_exact True->False, case_27 row_exact True->False, case_27 order_exact True->False

### `g4fix2-baseline-vision-20261025T0429`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: vision; vision table ON (hand-typed, T7: not shippable); job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T04:29:54+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix2-baseline-vision-20261025T0429/output.csv --run-id g4fix2-baseline-vision-20261025T0429 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix2-baseline-vision-20261025T0429 --vision`
- Config hash `adb519014d113e9e`; scorer code `de6ac88cf636cbb8`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix2-baseline-vision-20261025T0429/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-final-20261025T0429`: none

### `g4fix3-baseline-20261025T0453`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T04:53:16+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix3-baseline-20261025T0453/output.csv --run-id g4fix3-baseline-20261025T0453 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix3-baseline-20261025T0453`
- Config hash `38a838ad884c9737`; scorer code `025bae7413827288`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix3-baseline-20261025T0453/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-final-20261025T0429`: none

### `g4fix3-baseline-nosig-20261025T0453`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: no-signature; vision table off; job-timing signature off; intent tables as in intent.py
- Scored at 2026-10-25T04:53:16+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix3-baseline-nosig-20261025T0453/output.csv --run-id g4fix3-baseline-nosig-20261025T0453 --reconcile runs/g2-0137/q2.json:dev_nosig --prev g4fix2-baseline-nosig-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix3-baseline-nosig-20261025T0453 --no-signature`
- Config hash `f2b9cd75dfacc75a`; scorer code `025bae7413827288`; output sha256 `2950ef2780c75a28`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix3-baseline-nosig-20261025T0453/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_03, case_18, case_20, case_21, case_26, case_27
- Reconciliation with `runs/g2-0137/q2.json:dev_nosig` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-nosig-20261025T0429`: none

### `g4fix3-baseline-forceintent-20261025T0453`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: force-intent; vision table off; job-timing signature on; intent tables bypassed (all deletion-authorized)
- Scored at 2026-10-25T04:53:17+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix3-baseline-forceintent-20261025T0453/output.csv --run-id g4fix3-baseline-forceintent-20261025T0453 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix2-baseline-forceintent-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix3-baseline-forceintent-20261025T0453 --force-intent`
- Config hash `3da8216ca111ce6d`; scorer code `025bae7413827288`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix3-baseline-forceintent-20261025T0453/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-forceintent-20261025T0429`: none

### `g4fix3-baseline-vision-20261025T0453`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: vision; vision table ON (hand-typed, T7: not shippable); job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T04:53:17+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4fix3-baseline-vision-20261025T0453/output.csv --run-id g4fix3-baseline-vision-20261025T0453 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix2-baseline-vision-20261025T0429`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4fix3-baseline-vision-20261025T0453 --vision`
- Config hash `0974d771959072ee`; scorer code `025bae7413827288`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4fix3-baseline-vision-20261025T0453/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix2-baseline-vision-20261025T0429`: none

### `g4g9-baseline-20261025T0506`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T05:06:47+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4g9-baseline-20261025T0506/output.csv --run-id g4g9-baseline-20261025T0506 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix3-baseline-20261025T0453`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4g9-baseline-20261025T0506`
- Config hash `852ce97295d0dbdb`; scorer code `5b928a4c3405196d`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4g9-baseline-20261025T0506/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix3-baseline-20261025T0453`: none

### `g4g9-baseline-nosig-20261025T0506`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: no-signature; vision table off; job-timing signature off; intent tables as in intent.py
- Scored at 2026-10-25T05:06:48+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4g9-baseline-nosig-20261025T0506/output.csv --run-id g4g9-baseline-nosig-20261025T0506 --reconcile runs/g2-0137/q2.json:dev_nosig --prev g4fix3-baseline-nosig-20261025T0453`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4g9-baseline-nosig-20261025T0506 --no-signature`
- Config hash `bc88ac722614c59f`; scorer code `5b928a4c3405196d`; output sha256 `2950ef2780c75a28`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4g9-baseline-nosig-20261025T0506/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_03, case_18, case_20, case_21, case_26, case_27
- Reconciliation with `runs/g2-0137/q2.json:dev_nosig` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix3-baseline-nosig-20261025T0453`: none

### `g4g9-baseline-vision-20261025T0506`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: vision; vision table ON (hand-typed, T7: not shippable); job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T05:06:48+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4g9-baseline-vision-20261025T0506/output.csv --run-id g4g9-baseline-vision-20261025T0506 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix3-baseline-vision-20261025T0453`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4g9-baseline-vision-20261025T0506 --vision`
- Config hash `63d79af53834d974`; scorer code `5b928a4c3405196d`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4g9-baseline-vision-20261025T0506/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix3-baseline-vision-20261025T0453`: none

### `g4g9-baseline-forceintent-20261025T0506`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: force-intent; vision table off; job-timing signature on; intent tables bypassed (all deletion-authorized)
- Scored at 2026-10-25T05:06:49+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4g9-baseline-forceintent-20261025T0506/output.csv --run-id g4g9-baseline-forceintent-20261025T0506 --reconcile runs/g2-0137/q2.json:dev_all --prev g4fix3-baseline-forceintent-20261025T0453`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4g9-baseline-forceintent-20261025T0506 --force-intent`
- Config hash `7b64757f0ec2b21e`; scorer code `5b928a4c3405196d`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4g9-baseline-forceintent-20261025T0506/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4fix3-baseline-forceintent-20261025T0453`: none

### `g5-dev-iter1-score`

- What: G5 deterministic engine on 22 case(s); mode A+ recorded, engine path only; intent fail-closed (T71 Q2); no model calls
- Scored at 2026-10-25T05:12:02+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g5-dev-iter1/output.csv --run-id g5-dev-iter1-score --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python -m deletion_audit --run-id g5-dev-iter1 --set dev`
- Config hash `a12adba587efc0c3`; scorer code `5b928a4c3405196d`; output sha256 `ab02ffa871c7fef9`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g5-dev-iter1/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (0): none
- Cases not row-exact: case_07, case_08, case_18, case_20
- Flips against `g4fix2-baseline-final-20261025T0429`: case_07 status_ok True->False, case_07 row_exact True->False, case_07 order_exact True->False, case_08 row_exact True->False, case_08 order_exact True->False

### `g5-dev-iter2-score`

- What: G5 deterministic engine on 22 case(s); mode A+ recorded, engine path only; intent fail-closed (T71 Q2); no model calls
- Scored at 2026-10-25T05:12:29+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g5-dev-iter2/output.csv --run-id g5-dev-iter2-score --prev g4fix2-baseline-final-20261025T0429`
- Produced by: `python -m deletion_audit --run-id g5-dev-iter2 --set dev`
- Config hash `d235f72aee9e9197`; scorer code `5b928a4c3405196d`; output sha256 `641dbc8d921186ef`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g5-dev-iter2/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (0): none
- Cases not row-exact: case_08, case_18, case_20
- Flips against `g4fix2-baseline-final-20261025T0429`: case_08 row_exact True->False, case_08 order_exact True->False

### `g5-dev-iter3-score`

- What: G5 deterministic engine on 22 case(s); mode A+ recorded, engine path only; intent fail-closed (T71 Q2); no model calls
- Scored at 2026-10-25T05:28:39+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g5-dev-iter3/output.csv --run-id g5-dev-iter3-score --prev g5-dev-iter2-score`
- Produced by: `python -m deletion_audit --run-id g5-dev-iter3 --set dev`
- Config hash `b7b50d18d276dc0d`; scorer code `525d2d76ef5ee651`; output sha256 `641dbc8d921186ef`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g5-dev-iter3/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (0): none
- Cases not row-exact: case_08, case_18, case_20
- Flips against `g5-dev-iter2-score`: none

### `g4lint-baseline-20261025T0529`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: default; vision table off; job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T05:29:09+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4lint-baseline-20261025T0529/output.csv --run-id g4lint-baseline-20261025T0529 --reconcile runs/g2-0137/q2.json:dev_all --prev g4g9-baseline-20261025T0506`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4lint-baseline-20261025T0529`
- Config hash `b03c4f87a7400032`; scorer code `525d2d76ef5ee651`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4lint-baseline-20261025T0529/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4g9-baseline-20261025T0506`: none

### `g4lint-baseline-nosig-20261025T0529`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: no-signature; vision table off; job-timing signature off; intent tables as in intent.py
- Scored at 2026-10-25T05:29:10+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4lint-baseline-nosig-20261025T0529/output.csv --run-id g4lint-baseline-nosig-20261025T0529 --reconcile runs/g2-0137/q2.json:dev_nosig --prev g4g9-baseline-nosig-20261025T0506`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4lint-baseline-nosig-20261025T0529 --no-signature`
- Config hash `13083b167feb021d`; scorer code `525d2d76ef5ee651`; output sha256 `2950ef2780c75a28`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4lint-baseline-nosig-20261025T0529/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_03, case_18, case_20, case_21, case_26, case_27
- Reconciliation with `runs/g2-0137/q2.json:dev_nosig` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4g9-baseline-nosig-20261025T0506`: none

### `g4lint-baseline-vision-20261025T0529`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: vision; vision table ON (hand-typed, T7: not shippable); job-timing signature on; intent tables as in intent.py
- Scored at 2026-10-25T05:29:10+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4lint-baseline-vision-20261025T0529/output.csv --run-id g4lint-baseline-vision-20261025T0529 --reconcile runs/g2-0137/q2.json:dev_all --prev g4g9-baseline-vision-20261025T0506`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4lint-baseline-vision-20261025T0529 --vision`
- Config hash `1d2ed74939a643e8`; scorer code `525d2d76ef5ee651`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4lint-baseline-vision-20261025T0529/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4g9-baseline-vision-20261025T0506`: none

### `g4lint-baseline-forceintent-20261025T0529`

- What: prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; variant: force-intent; vision table off; job-timing signature on; intent tables bypassed (all deletion-authorized)
- Scored at 2026-10-25T05:29:11+05:30 by: `python3 -B code/evaluation/evaluate.py score --pred runs/g4lint-baseline-forceintent-20261025T0529/output.csv --run-id g4lint-baseline-forceintent-20261025T0529 --reconcile runs/g2-0137/q2.json:dev_all --prev g4g9-baseline-forceintent-20261025T0506`
- Produced by: `python3 -B code/evaluation/prototype_baseline.py --run-id g4lint-baseline-forceintent-20261025T0529 --force-intent`
- Config hash `b1d78ea6cc5cbed8`; scorer code `525d2d76ef5ee651`; output sha256 `60234e8f847c1526`; model IDs: none; paid calls: 0
- Producer check: **ok** (record: `runs/g4lint-baseline-forceintent-20261025T0529/producer.json`); evidence skip count 11 (must be 0 at freeze, G9)
- Allowed evidence skips (11, allow-list `png-model-needed` only): `evidence_04:png-model-needed`, `evidence_09:png-model-needed`, `evidence_14:png-model-needed`, `evidence_19:png-model-needed`, `evidence_23:png-model-needed`, `evidence_28:png-model-needed`, `evidence_32:png-model-needed`, `evidence_37:png-model-needed`, `evidence_42:png-model-needed`, `evidence_46:png-model-needed`, `evidence_60:png-model-needed`
- Text present, no resource ID (T51; listed, not refused) (2): `evidence_18`, `evidence_27`
- Cases not row-exact: case_18, case_20
- Reconciliation with `runs/g2-0137/q2.json:dev_all` (prototype `score.py` definitions; the reference values are not reproduced here): all counts equal
- Flips against `g4g9-baseline-forceintent-20261025T0506`: none

## Scorer discrimination `g4-discrim-20261025T0229`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4-discrim-20261025T0229` at 2026-10-25T02:29:49+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Scorer discrimination `g4fix-discrim-20261025T0318`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4fix-discrim-20261025T0318` at 2026-10-25T03:16:08+05:30
- Note: the time suffix `T0318` in this run ID was chosen before the run and does not match its created_at; the created_at shown is the run's real time.
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Scorer discrimination `g4fix2-discrim-20261025T0429`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4fix2-discrim-20261025T0429` at 2026-10-25T04:29:55+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Scorer discrimination `g4fix3-discrim-20261025T0453`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4fix3-discrim-20261025T0453` at 2026-10-25T04:53:17+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Scorer discrimination `g4g9-discrim-20261025T0506`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4g9-discrim-20261025T0506` at 2026-10-25T05:06:49+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Scorer discrimination `g4lint-discrim-20261025T0529`

- Command: `python3 -B code/evaluation/evaluate.py discriminate --run-id g4lint-discrim-20261025T0529` at 2026-10-25T05:29:11+05:30
- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: not applicable (no evidence file is parsed).

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

## Excluded runs (producer check not passed; T51: listed by ID and reason only)

- `g4-baseline-20261025T0229`: scored before the producer check existed (T47): its evidence skips and failures were never checked
- `g4-baseline-forceintent-20261025T0229`: scored before the producer check existed (T47): its evidence skips and failures were never checked
- `g4-baseline-nosig-20261025T0229`: scored before the producer check existed (T47): its evidence skips and failures were never checked
- `g4-baseline-vision-20261025T0229`: scored before the producer check existed (T47): its evidence skips and failures were never checked
- `g4fix-rescore-20261025T0302`: producer check unverified: producer record predates the evidence guard (no evidence_failures field): zero-unit files and swallowed log-line errors were not checked
- `g4fix-baseline-20261025T0314`: passed the producer check at scoring time, but the current check says unverified: producer record carries no output_sha256: it cannot be tied to the file being scored
- `g4fix-baseline-nosig-20261025T0316`: passed the producer check at scoring time, but the current check says unverified: producer record carries no output_sha256: it cannot be tied to the file being scored
- `g4fix-baseline-forceintent-20261025T0316`: passed the producer check at scoring time, but the current check says unverified: producer record carries no output_sha256: it cannot be tied to the file being scored
- `g4fix-baseline-vision-20261025T0316`: passed the producer check at scoring time, but the current check says unverified: producer record carries no output_sha256: it cannot be tied to the file being scored

## Invalidated runs (kept as evidence; their numbers are not results)

- `g4-baseline-20261025T0228`: INVALID: produced while code/evaluation/numbers.py shadowed the stdlib `numbers` module (the script's folder was sys.path[0]), so pdfplumber failed to import, the prototype skipped evidence_58 (the one DEV PDF) and case_07 came out COMPLETE with 1 step. Fixed by renaming the module to numbers_md.py, dropping the script folder from sys.path, and refusing to write output on any evidence parse failure. Superseded by the g4-baseline*-20261025T0229 runs.
  - **Correction:** the guard that note describes refused output only on `:FAILED:` or `-failed` skip labels, that is, on raised exceptions. An empty parse, other skip labels (`unknown-json`, `unknown`) and a log line whose JSON failed to parse still passed (verifier finding B2, `notes/verify/g4_verify.md`). Replaced under T47 by `code/evaluation/evidence_guard.py`: a skip allow-list holding only `png-model-needed`, a zero-unit check with the T38 declared-scope exception, and a log-line JSON check; `evaluate.py score` checks the producer record.
- `g4fix-baseline-nosig --no-signature-20261025T0314`: INVALID: mislabelled. A shell quoting error (zsh does not word-split) put the variant flag into the run ID instead of passing it, so this is the DEFAULT variant (producer.json variant: ['default']), not the variant its name says. Superseded by the correctly named g4fix-baseline-*-20261025T0316 runs.
- `g4fix-baseline-forceintent --force-intent-20261025T0314`: INVALID: mislabelled. A shell quoting error (zsh does not word-split) put the variant flag into the run ID instead of passing it, so this is the DEFAULT variant (producer.json variant: ['default']), not the variant its name says. Superseded by the correctly named g4fix-baseline-*-20261025T0316 runs.
- `g4fix-baseline-vision --vision-20261025T0314`: INVALID: mislabelled. A shell quoting error (zsh does not word-split) put the variant flag into the run ID instead of passing it, so this is the DEFAULT variant (producer.json variant: ['default']), not the variant its name says. Superseded by the correctly named g4fix-baseline-*-20261025T0316 runs.
<!-- END GENERATED -->
