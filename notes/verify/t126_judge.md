<!-- T126 cold orch-judge (xhigh), directed_by 2026-10-25T16:42:15+05:30; report saved verbatim by main at 17:05 IST. -->

# Cold judge: the upload set (code.zip, output.csv, log.txt)

**Overall: code about 23/30, transcript about 8.5/10, output.csv about 21–24/30 (format fully valid).** The biggest problem: the shipped code turns 10 of 16 "don't delete" fixture requests into deletion plans, while the evaluation report says they pass.

**Path note.** File:line paths below are relative to the repo root, `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26`. The zip's `README.md` and `code/` match HEAD byte for byte, so they open the same files as the unzipped tree at `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/judge2/upload`. The only extras in the repo are a ruff cache and one empty fixture folder.

**What I checked (no model calls, no gold, no `.env`).**
- I built a scratch test bed: the upload plus `dataset/` with `sample_output.csv` left out.
- The README's engine-only command gives sha `cf2a90b0…`. Replaying from a scratch copy of `cache/` gives test `a00ba71a…` and DEV `641dbc8d…`.
- The engine suite passes (564 tests). The evaluation suite has 7 errors, all from the gold file I left out.
- ruff and mypy are clean with the repo's configs. A holdout case is refused with exit 2.
- The engine has not changed since the freeze: `git diff bca55eb HEAD -- code/deletion_audit` is empty.

## 1. Scores

**Code zip: about 23/30**

| Part | Score | Reason |
|---|---|---|
| Architecture | 5.5/9 | The tool loop is real and bounded: commit before evidence, a 4-call cap, a hard request bound, a forced final turn (`agent/loop.py:259-279`, `:351-382`). But A+, A and `tools_off` give byte-identical test output, and answers changed 0 of 518 rows (`code/evaluation/evaluation_report.md:14-16`). A NOT_DELETION reading changes a row only when an intake row agrees (`agent/model_changes.py:253`). `code/docs/DECISIONS.md:18` says the agent exists because "the code score still needs a visible agent". |
| Prompt and tool craft | 7.5/9 | The prompts have a role, constraints, an untrusted-data section, an explicit `UNCERTAIN` path and examples (`agent/prompts/system.md`, `vision.md`). Each tool says when to use it and when not (`tools.md`). Schemas are strict with `additionalProperties: false`; the quote is checked against the text; untrusted text is fenced. The weaknesses: the open-question machinery almost never fires, and prompt caching is off on about 4.8k input tokens per call. |
| Robustness | 6.5/7.5 | Retries, budget and caching are strong. There is one place that gives up (`model/policy.py:120-174`) and SDK retries are off. Every send reserves its worst case under a run lock. Cache writes are fsync'd and hard-linked into place. Every row passes the validator gate. Deductions: two fail-toward-deletion paths (findings 1 and 11), two shipped INCOMPLETE rows with no FINDING, and a crash below Python 3.13. |
| Rigor | 3.5/4.5 | All 933 functions have return types; type checks and lint are clean; the key comes from the environment. But the lint configs aren't shipped, 21 functions run over 60 lines (`engine.py:543` is 128), and about 70 docstrings point to files the zip doesn't ship. |

**Output: format passes in full; my read is about 21–24/30.**
- The header is exact and there are 518 rows, in numeric `case_id` order, the same order as the request file. Every `steps_json` parses.
- `step_no` is consecutive, phase, operation and state agree, and the phase → operation → system → resource order has no breaks.
- All 1,241 cited IDs exist and none was captured after `audit_at` (384 sit exactly at it). NOT_APPLICABLE rows are `[]`.
- Two rows break the status contract: `case_50` is INCOMPLETE with only two uncited VERIFICATION steps, and `case_61` is INCOMPLETE with `[]`.
- Accuracy from the run artifacts:
  - DEV: status 22/22, rows exact 19/22, step F1 0.9887 (`cand-dev-A-20261025T1352`).
  - Holdout: 9/10, 8/10, F1 0.974, precision 1.0, recall 0.949 (`holdout-20261025T1628`).
  - Both are optimistic, because the split was made after the forensics pass read all 32 answers.
- Risk on the test set (`cand-test-Aplus-20261025T1352/metrics.json`): 27 tie picks, 64 timing-fingerprint matches, 13 cases with no account found, 6 linked by a later lookup.

**Transcript: about 8.5/10.**
- log.txt has 188+ entries, 139 from main. Every Context block says `tool=Claude Code` and `model=claude-opus-5-5`.
- All six stages are visible:
  - plan: G1–G3, 00:20–03:42;
  - implement: G4, G5, G7;
  - run: the paid passes, 13:25–13:52;
  - debug: G7 verifier FIX with 6 MAJOR, 12:50:17;
  - correct: fix round 2 (T112), and T123's revert;
  - review: T104 at 12:06:11, T120 at 14:29:28, the judges.
- The developer sets gates and caps (T97 at 06:37:14), asks for hypotheses with counts, and ran the holdout once (16:33:50).
- Deductions:
  - Many developer turns are 1–3k-character structured rulings that read as written with the advisor session. This is disclosed (D15), but a judge may still discount ownership.
  - There are four late entries (16:37:20 twice, 16:56:10 twice).
  - Some timestamps are out of order or in other formats (line 110; `Z` at line 3753; `+0530` at lines 293 and 3774).
  - My own entry passed `check_log.py` with a warning that its summary runs about 6 sentences.

## 2. Remaining findings, highest cost first

1. **A non-deletion request with no intake row gets a deletion plan, and the report says it doesn't** (`agent/model_changes.py:241-253`). Not QUICK.
   - Replaying the frozen code (0 sends) gives F01 1/3, R01 2/7 and R02 3/6, in both `tools_off` and A+. The model reads NOT_DELETION, then the row falls back to INCOMPLETE with DELETE steps.
   - The report's 11/11 and 46/46 (`evaluation_report.md:122`, `:126-128`, `:138`, `:177`) come from runs at `git_head 0795147`, which predates WP1.
   - It is a safety and credibility hit. The 518 test rows are unaffected: the routing table has 0 NOT_DELETION readings without an intake row.
   - The code fix takes 45–60 minutes plus a verifier, and makes the holdout figure "pre-change". Re-running the fixtures and regenerating report §5/§5b is about 20 minutes.
2. **The decisions log states the agent exists for the score** (`code/docs/DECISIONS.md:18`, `:19`, `:253`). "The code score still needs a visible agent" answers the rubric's "is this an agent?" against you. QUICK (docs only): state the engineering reason next to the measured null result, or ship a glossary of T-numbers instead of the full log. log.txt keeps the original either way.
3. **The tool loop changes no row** (`evaluation_report.md:14-16`, §6.2 "M = 0 of 518"). The A+ follow-ups cost $5.66 (the four shard runs in `usage_report.md:50-53`). This is built into the design. Not QUICK; prepare the interview answer.
4. **case_34 shipped COMPLETE while one of the two readings of evidence_04 shows `account_5762` PRESENT** (`runs/cand-test-Aplus-20261025T1352/regression_vs_engine.md`). When a screenshot is disputed, the row falls back to the version that ignores the image, so you get a possible false COMPLETE. That is the exact failure the problem statement describes. Not QUICK (changes output).
5. **INCOMPLETE rows with no FINDING ship:** case_50 and case_61. The validator allows them (`validate/prewrite.py:118`, `:136`), and they contradict README lines 14 and 20. Fixing the rows is not QUICK; rewording the README is.
6. **The required Python version isn't stated, and the code crashes on Python 3.9** (`model/budget.py:31` uses `datetime.UTC`; `model/client.py:30` uses `TypeIs`, which needs 3.13). QUICK: one README line.
7. **The zip is missing `requirements.txt`, `.env.example`, `ruff.toml` and `mypy.ini`.** The clean lint result can't be reproduced from the zip. QUICK (packaging).
8. **The rule conditions in `deletion_rules.csv` are never evaluated** (`policy/rules.py:21-23`), but README line 13 says they decide. `retention_until` and `retained_until` are never read; on this data they are all 2031–2034, so nothing breaks. README fix is QUICK; the code fix is not.
9. **Account linking reproduces the data generator's timing** (`config.py:37-40`, `:66-90`). It uses 1–2 second bands, ±1 s changes 33 test cases, and tie picks use `sha256(user_id)`. This is brittle and will be asked about. Not QUICK.
10. **No test runs F01, R01 or R02 through `pipeline.run` with the model's intent.** The docstring at `tests/pipeline/test_fixtures.py:12-15` still says "until G7 is wired", and F01 never joined `EXACT`. That is how finding 1 slipped through. Not QUICK (the test would fail until the fix lands).
11. **A NOT_DELETION commit followed by a failed call writes a deletion plan** (T109(a); `agent/harness.py:3-7`). The archived A+ fixture runs show it on replay misses. FAILED_CLOSED with findings only, no remediation, would be safer. Not QUICK.
12. **README line 18 says a screenshot reading "only counts when both readings agree"**, but lines 23 and 89 describe evidence_19 being used despite a disagreement. QUICK.
13. **`code/evaluation/NUMBERS.md:11` still says the holdout "has not been scored".** QUICK.
14. **The usage report's counts don't line up.** Line 46 says "897 distinct replies" while lines 57–59 count 1,283 (request keys versus entries across the two cache namespaces). It also gives no tokens per deletion request (about 12,149, from 6,293,202 ÷ 518). QUICK (`usage_report.py` render).
15. **`evaluation_report.md:822` says "the code has changed since this run"** without adding that the engine diff is empty. That will alarm a reader for no reason. QUICK.
16. **About 70 docstring pointers to files the zip doesn't ship**, across 26 package files (`notes/`, `research/`, `../CLAUDE.md`, "G3 section"), plus 342 T-number references. Not QUICK (mechanical, about 30 minutes).
17. **The README's "I personally reviewed" list leaves out the T120 review** (14:29:28) of the candidate `output.csv` and `code.zip`. QUICK.
18. **`--regression-gate` is a dead flag** (`deletion_audit/__main__.py:195`). QUICK.

## 3. Over-engineering

**Yes, it reads as over-engineered for a 518-row batch job, mostly outside the engine.**
- Size: 90 package files (12.3k lines), 29 evaluation modules (8.6k lines, of which `agent_report.py` alone is 1,494), and 926 tests (17k lines).
- Process density: 126 rulings in DECISIONS.md, 342 T-number references, and a 977-line evaluation report with duplicated sections.

**The two changes that would help a reviewer most:**
- A one-screen "start here" map in the README: the 6 modules that matter, where the model is called, and where decisions are made. Label freeze check, holdout run, improvements, evidence guard and agent report as development tooling.
- One plain "Basis:" line per module instead of inline T-number and section pointers.

## 4. Claims the code or run artifacts contradict

- `code/evaluation/evaluation_report.md:122`, `:126-128`, `:138`, `:177` (fixtures 11/11, 46/46): the frozen code gives F01 1/3, R01 2/7, R02 3/6.
- README line 29, "the model decides … what a request asks for": a NOT_DELETION reading needs an intake row (`model_changes.py:253`). On test, the 10 NOT_APPLICABLE rows are exactly the 10 intake rows.
- README line 13, "the conditional rules … decide": `policy/rules.py:23` says the conditions "are not checked".
- README line 14 ("any finding means INCOMPLETE, none means COMPLETE") and line 20 ("never left empty"): contradicted by case_50 and case_61. `validate/prewrite.py:9` ("a deletion row is never empty") contradicts its own line 136.
- README line 18 ("only counts when both readings agree"): contradicted by README lines 23 and 89.
- `code/evaluation/NUMBERS.md:11` (holdout not scored) and `usage_report.md:46` versus `:57`.
- `model/budget.py:11-15` says two runs "can never overshoot the project cap together". The four paid shards ran in parallel from separate exports with separate ledgers (log entries at 13:38:18 and 14:01:27).

**Claims I checked and found backed:** both engine-only hashes, the replay of `a00ba71a`, the holdout figures, $14.10 for 1,283 replies, `audit_case` in 508 of 518 cases, replicate agreement on 375 of 375 texts, and exit 2 on a holdout case.

## 5. Top 5 fixes by expected points

1. **Finding 1** (+1–3 across code and interview).
   - Re-run the fixture arms on the frozen code (replay, 0 sends), regenerate the report, and add a README limitation (about 20 min).
   - Then either let two agreeing NOT_DELETION readings stand without an intake row, or fail closed with no remediation steps (45–60 min plus a verifier). `output.csv` doesn't change.
2. **Reword `DECISIONS.md` T10, T11 and T95** (+0.5–1.5 architecture; 5 min).
3. **State Python 3.13+ in the README and ship the requirements, `.env.example` and lint configs** (+0.5–1; 10 min).
4. **Batch of claim fixes:** README lines 13/14/18/20/29, `NUMBERS.md:11`, the usage report counts and tokens per case, the line-822 clause, and the T120 review (+0.5–1; 20 min).
5. **Add F01, R01 and R02 to the pipeline fixture test**, paired with fix 1's code change (+0.5; 30 min).

None of these touches the prompts, schemas, tools or request builders.

## 6. Interview: the 8 hardest questions

A complete answer gives the direct answer, the implementation detail, the reasoning, evidence with a run ID, and the limitation.

1. **"A+ equals `tools_off` byte for byte; is this an agent?"** Cover what the model really decides (intent, screenshots), the commit-before-evidence loop and its caps, the 0/518 result (`freeze-test-Aplus-20261025T1629` vs `cand-test-toolsoff-20261025T1352`), and the next step: route tie picks and disputed screenshots to the loop as open questions.
2. **"'Send me my data, delete nothing', with no intake row: what do you output?"** The honest answer is a DELETE plan. Explain the intake rule, the fixture replays, and the fix.
3. **"Why is case_34 COMPLETE?"** Cover rule (a) and the fallback, the trade-off against inventing a finding from an unverified image, and that INCOMPLETE would be the safer fallback.
4. **"Isn't the timing fingerprint reverse-engineering the generator?"** Yes, and say so. Give its basis in the inputs, the ±1 s sensitivity (33 cases), the counts (64, 27, 13), the flags on every affected row, and that real job IDs would replace it in production.
5. **"Is your holdout really a holdout?"** Cover when the split was made, the lock (dev-filtered loader, unlock phrase in source, access log), the T48 incident, the single run (18 sends, $0.20), and why the number is optimistic.
6. **"A 529 three times, then `max_tokens`: what happens?"** Walk through the retry policy, backoff, worst-case settlement, the repair with a new key, the cache write, and the final row: `AGENT_CALL_FAILED`, never NOT_APPLICABLE.
7. **"Where are rule conditions like retention or an active hold evaluated?"** They aren't. Note that the evidence dates are 2031–2034, so it's harmless here, and name the next step.
8. **"What would you monitor in production?"** Fail-closed counts by reason, tie-pick and validator flag rates, replicate and vision disagreement rates (3 of 11 screenshots), cost per case ($0.027), the drift table, and a human review queue.

**What's novel:** recompiling with intent only, images only, and both, so that every changed row has a checkable cause.

Files are in `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/judge2`:
- `testbed/fxruns` (the fixture replays)
- `testbed/runs` (the DEV and test replays)

My check scripts are in `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/judgescripts`.