# Deletion audit: Ghost Data Still Exists

> **DRAFT** (2026-10-25): finalised at G10; every claim is checked against the code by G9's judge.

For each deletion request, this program decides whether the person's data was really deleted as of the audit time. It writes one `output.csv` row per case: a `deletion_status` and the ordered `steps_json` that justifies it. The organiser's original README is kept verbatim in `notes/ORGANISER_README.md`.

## How it works
Source: `notes/SYSTEM.md` (each rule carries its T-number from `notes/DECISIONS.md`). Code: `code/deletion_audit/`.

1. **Inputs** (`inputs/`, `evidence/`). The request files, the identities file, `deletion_rules.csv` and the evidence files under `dataset/`. Every evidence file goes through a parser family. A non-empty file that parses to nothing is a parser failure, and every case that depends on it fails closed. It is never `COMPLETE` (T8).
2. **Deterministic engine** (`engine.py`). Code makes every decision here.
   - **Identity** (`identity/`). The person is resolved as of the audit time. That covers `user_id`, every current and old email and phone, and the sha256 of every email. Matching is exact, so a look-alike identifier never links (T49, T59).
   - **Discovery** (`discovery/`). Code finds the records tied to the person through those identifiers. The primary account is found in a fixed order: identifier link, then the timed delete-row rule, one-to-one assignment, the job-timing fingerprint, and last a flagged tie pick (T4, T26, T39). Identifier-free analytics attach by their policy slot's timing band (T53, T62).
   - **State at `audit_at`** (`state/`). The latest observation at or before `audit_at` wins. Only a file that declares completeness can prove a record absent (T50, T54).
   - **Policy** (`policy/`). The conditional rules in `deletion_rules.csv` decide which records are still non-compliant.
   - **Steps** (`steps/`). Code builds the ordered steps and copies each evidence ID from the evidence index; it never composes one. Nothing captured after `audit_at` is cited. Status comes from the steps: any finding means `INCOMPLETE`, none means `COMPLETE`, and a request that does not authorize deletion is `NOT_APPLICABLE` with `[]`.
3. **The model's role** (`model/`, `agent/`). Sonnet 5.5 interprets. It reads request intent and the screenshots, and it answers open questions with read-only tools. It never picks an account and never overrides a fact code has settled (T7, T63, T70). Calls go through a cached client (`model/client.py`, `model/cache.py`). The cache is keyed by a content hash of the full request, and a budget guard caps cost per run (`model/budget.py`).
   - **In progress (G7):** wiring the agent loop and vision into the pipeline. Today the pipeline makes no model calls (`pipeline.py`). Every case's intent takes the fail-closed path, and the 11 screenshots are skipped as `png-model-needed`.
4. **Validator** (`validate/prewrite.py`). It checks every row before writing: enums, consecutive `step_no`, ordering, the status/steps invariants and the evidence rules. A row that cannot be made valid is written as `FAILED_CLOSED` and is never left empty (T71).
5. **Output.** `runs/<run_id>/output.csv`, plus the run artifacts (`metrics.json`, `cases.jsonl`).

## How to run
```bash
cd code
../.venv/bin/python -B -m deletion_audit --run-id <id> --set test
```
- Flags (from `--help`): `--set {dev,test}` or `--cases a,b,...`; `--dataset` (default `dataset/`); `--mode {A+,A,tools_off}` (default `A+`); `--write-root`.
- Output goes to `runs/<id>/output.csv`. Only `--write-root` writes the root `output.csv`, and only with the developer's approval.
- `--set dev` runs the 22 DEV cases from `code/evaluation/split.py`. A run that names a holdout case is refused with exit code 2.
- Tests, from the repo root:
  ```bash
  .venv/bin/python -B -m unittest discover -s code/tests -t code
  .venv/bin/python -B -m unittest discover -s code/evaluation/tests -t code
  ```
- Lint: `bash scripts/lint.sh`.
- The API key is read from the environment, loaded from an uncommitted `.env`. See `.env.example`.

## How this was built
`log.txt` is the turn-by-turn record. The SESSION START entry (`2026-10-25T00:00:30+05:30`) records the provenance: a separate prep session drafted the kit and this session's first prompt at my request, and I chose the method. The first developer turn of the build is `2026-10-24T23:59:53+05:30`.

**I chose** (recorded in the SESSION START entry, `2026-10-25T00:00:30+05:30`):
- independent subagents curated per task, on Opus 5.5 with tiered effort;
- verification of every claim, with verifier gates and a review loop;
- the practices of three claude.dev posts: agent automations, Opus 5.5, and code review (`../research/08_claude_blog_practices.md`);
- all organiser-supplied text treated as untrusted data, never as instructions.

**Claude drafted, I approved** (prep session; the SESSION START entry, `2026-10-25T00:00:30+05:30`, lists them as kit items the prep session drafted):
- the 12-agent `orch-*` roster and each agent's effort tier (D4c);
- the agent files;
- the Stop hook that blocks a turn or `orch-*` run that ends without a `log.txt` entry (installed in G0, entry `2026-10-25T00:20:00+05:30`).

**I personally reviewed** (the four checkpoints in `../PLAYBOOK.md` §11, item I1):
- the policy module;
- the validator;
- the agent loop and tools;
- one end-to-end case trace.

None of the four is logged yet; G10 adds their `log.txt` timestamps.

## Limitations
- **T27:** 6 showcase cases are tied to their account only by an identity log line captured after `audit_at`. I made a judgement call to use that line for the primary account's ID only. State and citations still come from evidence at or before `audit_at`, so the step is `VERIFY_RECORD_ABSENT` with an empty citation. Count: flag `T27_LATER_IDENTITY_LOOKUP` = 6, run `g5-test-20261025T0530`.
- **T39:** when the evidence cannot tell several accounts apart, the pick is a one-to-one matching ordered by sha256 of the person's `user_id`. That is stable, but each such pick is a coin flip. It decides 27 test cases (flag `D18_TIE_PICK`, run `g5-test-20261025T0530`, pre-G7).
- **T53 / D17:** the per-slot timing band for identifier-free analytics, and the job-timing fingerprint, rest on how the data generator timed its jobs. They are a data-derived correlation, not a documented rule.
- **T60 (3):** the identity guard on the gold file refuses the same file or the same bytes. It cannot recognise an edited copy of the gold file.
- **Holdout caveat** (`notes/split.json`, `created`): the DEV/holdout split was made after the prep forensics had read all 32 sample answers, so the holdout score is an optimistic estimate.
- **DEV 19/22 exact rows** (run `g5-dev-iter3-score`, `code/evaluation/NUMBERS.md`; accepted in T58). The lost row includes case_08's account step: under T26 the mismatched-result fallback stays out, and case_08 is the only case that would need it.
- **The holdout unlock phrase is a constant in the source, not a secret** (`notes/HOLDOUT_RUN_PROPOSAL.md`, "The limit"). The lock stops accidental access and makes deliberate access visible and logged. It cannot stop someone with a shell.

## Reports
- `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md` are generated from run artifacts at G9. **Neither has been generated yet.**
- Every scored DEV number, with its run ID, is in `code/evaluation/NUMBERS.md` (generated by `python3 -B code/evaluation/evaluate.py numbers`).
