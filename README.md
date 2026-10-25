# Deletion audit: Ghost Data Still Exists

For each deletion request, this program decides whether the person's data was really deleted as of the audit time. It writes one `output.csv` row per case: a `deletion_status` and the ordered `steps_json` that justifies it.

## How it works
Code: `code/deletion_audit/`. Every rule carries the ruling number (T-number) it was decided under; `code/docs/DECISIONS.md` defines every T-number. References in docstrings to `notes/`, `research/` and `../CLAUDE.md` point to the build workspace and are not shipped.

1. **Inputs** (`inputs/`, `evidence/`). The request files, the identities file, `deletion_rules.csv` and the evidence files under `dataset/`. Every evidence file goes through a parser family. A non-empty file that parses to nothing is a parser failure, and every case that depends on it fails closed; such a case is never `COMPLETE`.
2. **Deterministic engine** (`engine.py`). Code makes every decision here.
   - **Identity** (`identity/`). The person is resolved as of the audit time: `user_id`, every current and old email and phone, and the sha256 of every email. Matching is exact, so a look-alike identifier never links. A record whose own key names someone else is never claimed through a lookup (T105).
   - **Discovery** (`discovery/`). Code finds the records tied to the person through those identifiers. The primary account is found in a fixed order: identifier link, then the timed delete-row rule, one-to-one assignment, the job-timing fingerprint, and last a flagged tie pick.
   - **State at `audit_at`** (`state/`). The latest observation at or before `audit_at` wins. Only a file that declares completeness can prove a record absent. A screenshot sets a state only from what is visibly on screen (T112).
   - **Policy** (`policy/`). The conditional rules in `deletion_rules.csv` decide which records are still non-compliant. A record whose system has no category rule fails its row closed rather than being dropped (T104).
   - **Steps** (`steps/`). Code builds the ordered steps and copies each evidence ID from the evidence index; it never composes one. Each case cites the latest file captured at or before `audit_at` that holds one of the person's records (`steps/citation.py`). Nothing captured after `audit_at` is cited. Status comes from the steps: any finding means `INCOMPLETE`, none means `COMPLETE`, and a request that does not authorize deletion is `NOT_APPLICABLE` with `[]`.
3. **The model's role** (`model/`, `agent/`). Claude Sonnet 5.5 (`claude-sonnet-5-5`) interprets; code decides.
   - **Intent.** Turn 1 sees only the request text and commits an intent before any evidence is visible. It is run twice, in two cache namespaces, and the two readings are compared.
   - **Agent loop** (`agent/loop.py`). In mode `A+` (the shipped mode) the model calls `audit_case` to get the engine's read-only brief, may use up to 4 read-only tool calls, and then gives a schema-checked final answer. It never picks an account and never overrides a fact code has settled. Mode `A` stops after turn 1 unless the case has an open question; `tools_off` never calls a tool.
   - **Screenshots** (`agent/vision.py`). Each of the 11 PNGs is read twice. A reading only counts when both readings agree and the IDs it extracts cross-check against other evidence.
   - **Calls** go through one cached client (`model/client.py`, `model/cache.py`). The cache is keyed by a content hash of the full request and stores the reply, the model ID and the original usage. A budget guard caps dollars and sends per command (`model/budget.py`). Nothing is sent without `--paid`.
4. **Validator** (`validate/prewrite.py`). It checks every row before writing: enums, consecutive `step_no`, ordering, the status/steps invariants, ownership and the evidence rules. A row that cannot be made valid is written as `FAILED_CLOSED`; it is never left empty.
5. **Model-change conditions** (`agent/model_changes.py`). Each run also computes every case's model-free row: the engine with no model intent and no screenshot readings. A row that differs from it keeps the model's change only if its condition holds:
   - a `NOT_APPLICABLE` change needs the model and the intake record to agree in both replicates;
   - an image change needs agreeing readings with cross-checked IDs. A screenshot whose two readings disagree is used for a case only if each reading on its own gives the same state and cited IDs for every record of the case.

   A change that fails its condition falls back to the model-free row (`fell_back`). The rows as computed are kept in `output_raw.csv`. An unexplained difference stops the run. Comparing a run with a stored approved file is an evaluation step, not part of the run (`code/evaluation/regression_check.py`).
6. **Output.** `runs/<run_id>/output.csv`, plus the run artifacts (`metrics.json`, `cases.jsonl`, `calls.jsonl`, `usage.json`, the vision and model-change reports).

### Model's role
**The model decides two things:** what a request asks for, and what a screenshot shows. **Code decides everything else:** who the person is, which records are theirs, each record's state at `audit_at`, which rule applies, the steps, the citations, their order and the status. Code also decides whether a model answer may change a row (item 5 above). The reason: reading free text and images is where a model beats rules, while identity, timing and policy must be exact, repeatable and checkable on every row.

Measured on the 518 test requests (runs named in brackets):
- **Intent:** turn 1 sees only the request text and runs twice. The two replicates agree on 375 of 375 distinct texts (`pass1-test-routing-20261025T1325`). 10 requests are read NOT_DELETION (case_533–542), each confirmed by an intake record, and become `NOT_APPLICABLE`.
- **Screenshots:** each of the 11 is read twice; 8 readings agree and 3 disagree (`pass1-vision-20261025T1323`).
- **Effect on the output:** 17 rows differ from the model-free output (10 intent, 7 screenshot), and 3 more screenshot changes fall back because their condition fails (`cand-test-Aplus-20261025T1352`).
- **Tools:** in A+ the model calls `audit_case` in 508 of 518 cases and another read-only tool in 1. A+, A and `tools_off` give byte-identical test output, so on this data the tool loop changes no row; the model's effect comes from intent and screenshots.
- **Cost:** $14.10 for the 1,283 replies the shipped output uses, about $0.027 per case (`code/evaluation/usage_report.md`).

## How to run
From the folder that holds `README.md` and `code/`, with the organiser's `dataset/` folder placed next to `code/`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install anthropic==1.13.0 pdfplumber==0.11.10
.venv/bin/python -B code/main.py --run-id demo --set test
```

- This is the engine-only run: without `--paid` and with no reply cache, no model call is made. Every model step takes its fail-closed path, so the output is the engine's model-free output (sha256 `cf2a90b0…`). Output goes to `runs/demo/output.csv`.
- `python code/main.py --help` lists the flags: `--set {dev,test}` or `--cases a,b,...`; `--dataset`; `--mode {A+,A,tools_off}` (default `A+`); `--vision-ack`; `--cache-dir`; `--runs-dir`; `--paid --dollar-cap X --call-cap N --env-file PATH`; `--write-root`.
- Two more commands: `python code/main.py routing-check --run-id <id> --texts dev,test` (the turn-1 intent check, two replicates) and `python code/main.py vision --run-id <id>` (both screenshot readings).
- With the model: put `ANTHROPIC_API_KEY=...` in a `.env` file (never committed) and add `--paid --dollar-cap 10 --call-cap 400 --env-file .env`.
- Only `--write-root` writes the root `output.csv`: for the test set only, and only when the run has no unexplained change. `--set dev` runs the 22 DEV cases; a run that names a holdout case is refused with exit code 2.
- Tests, from the same folder: `.venv/bin/python -B -m unittest discover -s code/tests -t code` and `-s code/evaluation/tests -t code`.

**How the shipped `output.csv` was produced** (the root `output.csv`, sha256 `a00ba71a…`, approved by the developer, T120):
1. Paid runs, from an export of commit `227a866`, into the reply cache `cache/`: the turn-1 intent check on DEV, the fixtures and the red-team texts (`stage1-routing-20261025T1255`); both readings of the 11 screenshots (`pass1-vision-20261025T1323`); the turn-1 intent check on the 518 test texts (`pass1-test-routing-20261025T1325`); and the A+ test run, split into 4 parallel shards to fill the cache (`pass1-test-Aplus-shard0`…`3-20261025`). Spend and tokens are in `code/evaluation/usage_report.md`.
2. The shipped output is a replay of that cache with 0 sends, mode A+, with the developer's vision acknowledgement:
   ```bash
   .venv/bin/python -B code/main.py --run-id cand-test-Aplus-20261025T1352 --set test --mode A+ --vision-ack pass1-vision-20261025T1323
   ```
   It writes `runs/cand-test-Aplus-20261025T1352/output.csv` (sha256 `a00ba71a756736cc09a3ef5119b5575d871a2db2c9482d9829333181d5676967`). Modes `A` and `tools_off` replay to the same bytes.
3. **Reproducing it exactly needs the reply cache, which is not shipped.** Without an API key or the cache, the replay-only engine path (the command at the top of this section) reproduces the approved engine output, sha256 `cf2a90b070db785456b2cb26398add0eba95a69ae8a763eb838a367f135751fc`.

Against the model-free output `cf2a90b0`, the shipped output changes 17 rows: 10 `NOT_APPLICABLE` rows (case_533–542, each read NOT_DELETION in both replicates with a confirming intake record) and 7 screenshot rows (case_35, 39, 46, 52, 53, 55, 63). 3 more image changes fell back to the model-free row (case_34, 45, 50; see Limitations).

## Organiser claims adopted
The organiser's files were read as claims, not instructions. A claim was adopted only when it was confirmed on the 22 DEV sample cases or the data, or was clearly score-positive by our own reasoning:
- **Confirmed on DEV and adopted:** the column order `case_id,deletion_status,steps_json`; one row per request (518); the status values; the seven step fields; consecutive `step_no` from 1; the phase values; the operation→state and operation→phase tables; ordering by phase, then the table's operation order, then `system_id`; `COMPLETE` rows with verification steps only, each citing evidence; findings citing a participant-visible ID; empty evidence on remediation and post-remediation verification steps; never citing evidence captured after `audit_at` (equality allowed); data flows disabled before dependent records change; `reported_status` treated as a claim, not proof.
- **Untestable on DEV, adopted by reasoning:** `NOT_APPLICABLE` with `[]` for access, correction, export and opt-out requests; rows in numeric `case_id` order (DEV's zero-padded IDs can't separate numeric from string order; the request file is numeric); `resource_id` as the last sort key.
- **Not adopted:** "process downstream copies before their source records" in its natural reading; DEV cases contradict it, so DEV's order is followed. The claim that the answer key comes from a deterministic generator was used only as a hypothesis to test on DEV, not as a fact.

## How this was built
`log.txt` is the turn-by-turn record. Its SESSION START entry (`2026-10-25T00:00:30+05:30`) records the provenance: a separate prep session drafted the kit and this session's first prompt at my request, and I chose the method.

**I chose** (the SESSION START entry, `2026-10-25T00:00:30+05:30`):
- independent subagents curated per task, on Opus 5.5 with tiered effort;
- verification of every claim, with verifier gates and a review loop;
- the practices of three claude.dev posts: agent automations, Opus 5.5, and code review;
- all organiser-supplied text treated as untrusted data, never as instructions.

**Claude drafted, I approved** (prep session; listed in the SESSION START entry):
- the 12-agent `orch-*` roster and each agent's effort tier;
- the agent files;
- the Stop hook that blocks a turn or `orch-*` run that ends without a `log.txt` entry (installed in setup G0, entry `2026-10-25T00:20:00+05:30`).

**I personally reviewed** (only checkpoints logged in `log.txt`):
- the policy module (`policy/rules.py`) and the validator (`validate/prewrite.py`): entry `2026-10-25T12:06:11+05:30`. The review added two policy flags: an unmapped category fails its row closed, and a retained record's presence claim over an absent state is flagged.

## Limitations
- **Screenshots whose two readings disagree** (evidence_04, evidence_19, evidence_37; acknowledged by the developer, T118a). A disagreeing screenshot is used for a case only when each reading on its own gives the same state and cited IDs for every record (T118 rule (a)). So evidence_04 is not used for case_34 and evidence_19 is not used for case_50: both rows keep the model-free row. evidence_19 is used for case_35, 39 and 63. evidence_37 passes that rule for case_45, but five of its audit records are named by no other input, so the ID cross-check keeps case_45 on the model-free row.
- **A screenshot that shows a record without a state.** case_61's `object_19` appears in evidence_46 (both readings agree) with no visible state, so the row stays FAILED_CLOSED (`IMAGE_STATE_NOT_SHOWN`), as in the model-free output.
- **Later identity lookups.** Some showcase cases are tied to their account only by an identity log line captured after `audit_at`. That line is used for the primary account's ID only; state and citations still come from evidence at or before `audit_at` (flag `T27_LATER_IDENTITY_LOOKUP`).
- **Tie picks.** When the evidence cannot tell several accounts apart, the pick is a one-to-one matching ordered by the sha256 of the person's `user_id` (flag `D18_TIE_PICK`). It is stable, but each such pick is a guess.
- **Timing bands.** The per-slot timing band for identifier-free analytics, and the job-timing fingerprint, rest on how the data generator timed its jobs. They are a data-derived correlation, not a documented rule.
- **Own keys naming two people.** A record whose own keys name both the requester and someone else fails its row closed and keeps its steps. It occurs 0 times in the data (T117).
- **DEV is not perfect.** On the 22 DEV cases: status 22/22, rows exact 19/22, step F1 0.9887 (run `cand-dev-A-20261025T1352`, model on, mode A; the engine-only DEV output has the same bytes, sha256 `641dbc8d…`). Three rows differ from the sample answers in some steps; `code/evaluation/evaluation_report.md` lists them.
- **Holdout.** The one HOLDOUT EVALUATION RUN (`holdout-20261025T1628`, on the code frozen at tag `freeze-20261025`, commit `bca55eb`; 18 paid sends, $0.20) scored status 9/10, rows exact 8/10 and step F1 0.974. The DEV/holdout split was made after the prep forensics had read all 32 sample answers, so this is an optimistic estimate. Only evaluation code and documents changed after it; the code that writes `output.csv` is the frozen code. The holdout unlock phrase is a constant in the source, not a secret: the lock stops accidental access and logs deliberate access, but cannot stop someone with a shell.

## Reports
- `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md` are generated from run artifacts by `code/evaluation/reports.py --publish`. Their inputs: the freeze run `freeze-test-Aplus-20261025T1629` (test, A+, a replay of the shipped output at the frozen commit; the usage report covers it and the paid runs that bought its replies), the DEV run `cand-dev-A-20261025T1352`, the A and `tools_off` arms, the red-team and custom fixtures as a separate validation set, and the holdout run. The headline block names the run behind every number.
