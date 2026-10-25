# Resume point (updated 2026-10-25 ~13:15 IST)

Durable state: `TASKS.md` (the T114 plan at the top of the agent queue), `notes/DECISIONS.md` (T1–T115), `notes/INTERFACES.md` (§7.1, §7.1.1, §8), `notes/approved_output.json` (the approved output), `notes/verify/*.md`, `notes/agent_reports/*.md`, `notes/g7_verifier_items.md`, `notes/HOLDOUT_RUN_PROPOSAL.md` (ruled by T96).
Scratchpad = `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## Goal (T114): only the best output.csv and the best code.zip
**Order** (T114/T115, agreed by the developer):
1. **Fix round 2 and the vision adapter finish.**
   - Done = both suites pass, and DEV `641dbc8d…` and test `cf2a90b0…` are unchanged.
   - No verifier.
   - Then main commits them together: the adapter depends on fix round 2's schema fields.
2. **One paid pass,** from an export of the committed code (git archive HEAD into the scratchpad), with the repo cache (`--cache-dir <repo>/cache`), writing to `--runs-dir <repo>/runs`, with `--env-file <repo>/.env`.
   - The gate is on. **Total caps $40 and 1,200 sends.**
   - No intermediate stops; stop only if a cap is hit, a case fails twice, or the gate stops.
   - Steps, in order:
     1. the routing check on DEV (cached by stage 1, $0);
     2. vision, 11 images × 2;
     3. stage 2, the test texts (`routing-check --texts test`; ~736 sends);
     4. the mode-A test run;
     5. the A+ test run.
   - Backup rule F applies (fix round 2 item 13).
3. **One message to the developer:**
   - every row changed against cf2a90b0, with its class (intent or image);
   - the readings for the 7 showcase cases (34, 35, 39, 50, 52, 53, 55) and for 46, 61, 63;
   - case_55's row;
   - the spend;
   - every test text read NOT_DELETION in both replicates, with its intake row, or, without one, its assigned account and request text (the developer rules per row; T101's condition stays until then);
   - whether A+ equals mode A, and if not, each differing row with its class and tool calls.

   The developer approves a file. cf2a90b0 stays approved until then.
4. **Reports** from those runs (`code/evaluation/reports.py --spec … --publish`), including T111/T113: the improvements ledger `notes/improvements.json`, the headline block, the usage fields from ORGANISER_README:97.
5. **Cold `orch-judge`** (xhigh), directed_by 2026-10-25T13:00:29+05:30, over the upload set (code, README, both reports, output.csv). Then one fix round, for high-value findings only, checked by tests and unchanged hashes. No re-judge.
6. **Freeze:**
   1. the `freeze-<YYYYMMDD>` tag;
   2. the freeze check (output = the approved file; any FAILED_CLOSED rows are brought to the developer);
   3. the HOLDOUT EVALUATION RUN ($1 cap; **ask the developer for the phrase**; main runs `code/evaluation/holdout_run.py` in that turn);
   4. the reports regenerated (holdout section).
7. **G10:**
   1. the README: T111's items, plus the command and mode that produced the shipped output.csv;
   2. `code.zip` by `orch-packager` (low, directed_by 2026-10-25T13:00:29+05:30): secret scan, the command tested from a fresh export;
   3. check_log PASS;
   4. the developer submits.

## Running now (the cap is 3; never two of one type)
- **G5 fix round 2** (`orch-builder-core`, directed_by 2026-10-25T12:07:17+05:30, brief `g5fix2_brief.md`). Items:
  1. R04, the per-record own-key rule, plus a hard validator check;
  2. R06 blanking and a single count;
  3. R11 reasons;
  4. a committed R01–R12 test;
  5. T104 (a);
  6. T104 (b);
  7. a record waiting on an image that no reading mentions fails closed (widened by T112);
  8. a FAILED loop is never NOT_APPLICABLE (AGENT_CALL_FAILED) and the gate checks the loop status (T109);
  9. image states only from visible cues, with `visible_markers` and `status_label` in the schema (T112);
  10. the root output.csv is written only after the gate passes;
  11. the gate is mandatory with the model on;
  12. an end-to-end test of R03's evidence flag;
  13. backup rule F;
  - and 4(b): the review list covers every image that changes a row, and the acknowledgement records `{file_id, reply_keys, reading_sha256}`.
- **Reports part 2** (`orch-eval-engineer`, directed_by 2026-10-25T12:52:06+05:30, brief `reports2_brief.md`).
- **Done, but uncommitted:** the vision adapter (`agent_report.py`, `freeze_check.py` and its tests; report in `notes/agent_reports/vision_adapter.md`), to be committed together with fix round 2.

## Paid so far
| Run | Sends | Cost |
|---|---|---|
| `smoke-t76-20261025T0612` | 2 | $0.004964 |
| `stage1-routing-20261025T1255` (DEV, fixtures, red team) | 122 | $1.308508 |

- **Ledger:** $1.313472.
- **Stage 1:** replicates agree 61/61; the 11 NOT_DELETION are exactly the expected NA fixtures; only case_90101 has a confirming intake row.
- **Measured turn 1:** about 4,547 input and 163 output tokens. The engine brief is about 233 tokens.
- **Paid commands** (the wiring): `routing-check --run-id <id> --texts <sources> --paid --dollar-cap X --call-cap N --env-file ../.env`; `vision --run-id <id> --paid …`; a full run is `--set test --mode A|A+ --vision-ack <vision run id> --regression-gate --paid …`. Run from the export's `code/`.

## Rules easy to forget
- **Every turn:** a log.txt entry by Bash heredoc only, with a summary of **2–5 sentences**, and check_log after it.
- **Briefs:** no line starting with "## ["; a `directed_by` line.
- **Commits:** stage only the paths at hand; run the secret scan; push to `github`.
- **Output lock (T101):** a change to the test output needs the developer's approval before freeze.
- **Holdout gold stays locked.**
- Never read `.env` into the shell.
