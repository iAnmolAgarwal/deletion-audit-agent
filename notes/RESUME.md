# Resume point (updated 2026-10-25 ~05:47 IST, before a compaction)

The durable state is in these files. Read them first after a compaction:
- `TASKS.md`: gate status, the agent queue, the G9 list and the freeze checks.
- `notes/DECISIONS.md`: T1–T87, every developer ruling.
- `notes/INTERFACES.md`:
  - §7 is G5's engine, amended by T68–T77; §7.1 holds its **as-built signatures**, accepted under T87.
  - §8 is GM's model client.
- `notes/SYSTEM.md`: how the system works.
- `notes/ARCHITECTURE_OPTIONS.md`: G3. A+ in text-first routing form was decided (T70).
- Verifier reports in `notes/verify/`:

  | Report | Gate | Verdict |
  |---|---|---|
  | `g4_verify.md`, `g4fix_verify.md`, `g4fix2_verify.md`, `g4fix3_verify.md` | G4 | FIX, FIX, FIX, then PASS |
  | `gp_verify.md` | GP | PASS |
  | `gm_verify.md`, `gm2_verify.md` | GM | FIX, then PASS |
  | `g5_verify.md` | G5 | pending |

Scratchpad below means `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## State (05:47)
**Committed and pushed to `github`** (all of these, in order):
- `dad20d0`, `92fabd2`: G4 fixes;
- `b9bd05a`: lint cleanup, plus the two GP annotation fixes;
- `cb6113f`, `ee6aa8c`: the G5b fixtures, committed before any engine run on them;
- `3f89310`: GM;
- `61b315f`: the G5 as-built interface, T87.

**Uncommitted:**
- G5's engine and tests: `code/deletion_audit/{inputs/requests.py, identity, discovery, state, policy, steps, validate, engine.py, record.py, artifacts.py, pipeline.py, config.py, timeutil.py, __main__.py}` and `code/tests/{identity, discovery, state, policy, steps, validate, pipeline, hygiene}`, `code/tests/engine_fixtures.py`. These commit after the G5 verifier's verdict and the developer's reply (T87).
- `log.txt`, from this turn on.

**Running:** the **G5 verifier** (`orch-verifier`, high, directed_by 2026-10-25T05:38:42+05:30, brief at scratchpad `g5_verifier_brief.md`). It reports to `notes/verify/g5_verify.md` and includes a fixture run. On completion:
- save its report verbatim;
- spot-check its repros;
- stop for the developer's reply (the verdict rule);
- if the verdict is PASS and the developer agrees, commit G5.

If it was cut, relaunch it with the same brief and log an `[auto]` entry.

**Waiting on the developer:** approval of the **G7 proposal** (main's 05:44 message; summary in the 05:43 log entry):
- **G7a:** `orch-builder-core`, high, building `code/deletion_audit/agent/**` and `code/tests/agent/**`. That covers turn-1 text-only intent with UNCERTAIN, the CLASSIFY_REQUEST cross-check (flags only), the 11-image vision step (PNG signature, IMAGE_SUBJECT_CONFLICT), the loop (≤4 tool calls, then `tool_choice` none; modes A+/A/tools_off), the read-only tools and answer validation. Fake transport only. No edits to G5's files until G5 commits; the pipeline wiring comes after.
- **G7b:** `orch-eval-engineer`, high, building `code/evaluation/agent_report.py` (N/M, tools on vs off, the agreement table) and a freeze-check command.
- **The T76 smoke call** (main runs it): 2 paid calls plus a cache replay, on `claude-sonnet-5-5` with anthropic 1.13.0. It tests a tool together with the JSON-schema format, effort, a tool_result follow-up giving a schema-valid answer, and a cache replay with 0 sends. Expected about $0.014; worst-case reservation $0.075; caps $0.10 and 4 sends. The key is loaded from `.env` inside the process, never printed. Project spend so far: $0.
- **Next paid step**, proposed later with its cost: the turn-1 routing check, about 820 calls, about $4.5 expected.

**Key numbers:**
- **Baseline:** `g4lint-baseline-20261025T0529` (prototype), sha256 `60234e8f…`.
- **G5 DEV** (`g5-dev22-20261025T0530`): 22/22 status, 19/22 exact; the case_08 flip is accepted under T58.
- **G5 test replay** (`g5-test-20261025T0530`):
  - 518 rows, 0 crashes;
  - 18 FAILED_CLOSED rows: 9 non-deletion texts waiting on G7's intent, 9 waiting on G7's images;
  - 58 hard H03 violations, all on those 18 rows, which T87 allows until G7.
- **Freeze checks (T60/T71/T87):** 0 FAILED_CLOSED, 0 `INTENT_FAILED_CLOSED`, 0 skips.

**Environment:**
- `.venv/` (anthropic 1.13.0, pdfplumber 0.11.10, ruff 0.17.0, mypy 2.4.0), with `requirements*.txt` and `requirements.lock`.
- Lint: `bash scripts/lint.sh <paths>`.
- Upstream cron `a94d194d`, every 2 h at :07, baseline unchanged.

## Rules in force that are easy to forget
- **Before any spawn or message to an agent,** check the brief has no line starting with `## [`. Example headers go in backticks (T64).
- **Every subagent brief carries:**
  - a `directed_by: <ts>` line, taken from the `.claude/.log_guard_turn` mtime;
  - the header shape in backticks;
  - a summary of 2–5 sentences;
  - one heredoc for the append;
  - a `check_log` run afterwards.
- **Verifier briefs** prove lock bypasses with synthetic files only (T48).
- **Main's log entries:** the header from `TZ=Asia/Kolkata date -Iseconds`, a title ≤ 80 characters, **a summary of 2–5 sentences** (main went over on 05:16 and 05:34), detail in Actions. Record the pushed commit hash.
- **Commits** stage only the gate's own paths plus `log.txt` and `TASKS.md`. Push to `github`, never to `origin`.
- **Scripted edits:** chain each step with `&&`; take slice positions after every replacement, never before.
- **At any failure (T43):** give the hypothesis and the expected signal, then wait for the developer's confirm.
- **After any verifier, judge or code-review verdict:** stop for the developer's reply. Review rounds are capped at 3; after that, non-BLOCKER findings go to the G9 list.
- **Paid calls:** only with the developer's approval and a stated cost. Never print `.env`.
- **Holdout gold stays locked.** Never decode it.
- **Agent cap:** 3 at once (T79), never two of the same type.
