# GM round-3 verifier report (orch-verifier, high, directed_by 2026-10-25T05:17:10+05:30)

Saved verbatim by main from the agent's return message. This was GM's third and last review round (`../CLAUDE.md` §6). Under T85, its non-BLOCKER findings go on the G9 list in `TASKS.md`.

---

**Verdict: PASS.** No blockers. I found 4 issues, all MINOR, which go on the G9 list. F1–F5 and both notes are fixed on their original reproductions, and I found no other way to reach the same bugs.

The 76 model tests pass, and ruff and mypy are clean. The source hashes stayed the same for the whole review. I used only the fake transport and a stand-in SDK client, made no network calls, and did not read `.env` or `sample_output.csv`. Scripts and their outputs are in `/tmp/verify-gm3/`: `probe3.py`, `probe4.py`, `mutate.py` and `hashes_start.txt`. The first verifier's `probe.py` crashes at its P7 step. That is a bug in the probe: the test directory was cleaned up before P7 ran. probe2 covers the same path, and it passes.

| Q | Verdict | Basis |
|---|---|---|
| 1. F1 | Fixed | Editing the output of `thaw()` or `plain_body()` doesn't change the request or the body sent: `tool_choice` still goes out as `auto`. I also swapped the stored body through `gc.get_referents`, both for a body that breaks no rule and for one with `temperature` added. Both were refused before any send, with 0 sends, 0 reservations and a `RequestRejected` log entry. A transport that edits the body it receives doesn't change the key or the cache entry. |
| 1. F2 | Fixed | A `$ref` with keywords beside it is flagged wherever it sits: in `$defs`, a `$defs` inside `$defs`, `anyOf`, `items`, `additionalProperties` or `allOf`. `validate()` refuses the shape as well. |
| 1. F3 | Fixed, with gaps | NaN, infinity, negative, string and bool values are refused for both caps and ledger costs, and a `1e999` cost is too. Very large ints get through (finding 1). |
| 1. F4 | Fixed | Two dropped connections followed by a success write ledger costs `[0.01303, 0.01303, 0.0]` and leave no reservation open. Each attempt is settled once. When settle itself raises, it was called once, with no second settle. Status ≥ 400 is settled at $0. |
| 1. F5 | Mostly fixed | The four named paths are now logged; a few are not (finding 2). |
| 1. Notes | Fixed | Editing an entry's `model` or `usage` makes it corrupt. A symlinked path to the ledger, or one with `sub/..` in it, gets the same lock. |
| 2. Round-1 guarantees | Not broken | The ladder 429 → 529 → timeout → success waits 1, 2 and 4 s; the costs are $0, $0, worst case, then actual. Only `_give_up` and the budget caps raise `ModelCallFailed` (grep and the AST test). Replay makes 0 sends. A repair re-checks the new request and its key matches its request. The lock and resume tests pass. |
| 3. New tests | 18 of 18 guard a fix | Each new test catches a reverted fix (round 1's reproductions show these failed before), but some code paths have no test (finding 4). |

**Findings**

**1. MINOR: `budget.py:239-246`. Settle trusts usage it can't price, and the budget undercounts.**
- `settle` removes the reservation before pricing it.
- A usage count of 10**400 makes the pricing raise `OverflowError`. The result is no ledger line, `run_spent_usd` still 0.0, nothing logged, and the reply not cached.
- A usage of `{"input_tokens":"1000","output_tokens":500.0}` is priced at **$0.0**: `flatten_usage` drops values that aren't ints.
- A ledger line `{"cost_usd": 10**400}` raises `OverflowError` raw instead of a `LedgerUnreadable` budget stop. Nothing is sent and nothing is logged.
- Repro: `.venv/bin/python -B -I /tmp/verify-gm3/probe3.py`, the lines starting `F3`.
- Expected: usage that is missing, not an int, or can't be priced is charged at the reservation's worst case; `OverflowError` is caught like `ValueError`.
- Class: the same as F3/F4, a budget that undercounts on bad input. None of these inputs can come from the real API.

**2. MINOR: `client.py:184-185` and `client.py:159`. Some failure paths still leave no call-log entry.**
- If `cache.put` raises after a paid send, the ledger shows $0.007 spent but the call log is empty (`[]`).
- If `settle` raises inside the transport-failure handler, nothing is logged.
- A cache entry whose `request.model` is a list raises `TypeError` instead of `CacheCorruptError`, and nothing is logged. The cause is the `PRICES` lookup at `request.py:98`, which fails on a value that can't be a dict key.
- Repro: `.venv/bin/python -B -I /tmp/verify-gm3/probe4.py`.
- Class: F5, exception paths that bypass the call log. All of these still stop the run, so none of them fails open.

**3. MINOR, pre-existing: `schema_check.py:81-94` and `:66-78`. Schema checker gaps.**
- A `$ref` that points at itself passes the checker, then `validate` hits `RecursionError`.
- A list-valued `items` passes the checker, then every reply fails (`schema node is not an object`), which uses up the repairs.
- A list-valued `properties` raises `AttributeError` instead of `RequestRejected`.
- Repro: the `F2` lines of `probe3.py`.
- Class: schema shapes the checker doesn't catch at build time. They all fail closed.

**4. MINOR: test gaps.** Five of my 22 mutants survive the full suite (`/tmp/verify-gm3/mutate.py`):
- `key()` computed from the live body instead of the text fixed at build. The code does refuse a body swapped after build (my gc probe), but no test covers a swapped body that breaks no rule.
- The `PaidRunLocked` log entry written when the client is built.
- The `RequestRejected` log entry from the pre-send re-check.
- The negative-usage clause and the finite-cost clause in `settle`. Each covers for the other, because the one test has a negative total; a usage of input −1 / output 1000 would pin the negative-usage clause.
- `parse_constant`, which the later finite check makes redundant.

None of the 18 tests only asserts what the old code already did.

I appended the log entry, and `scripts/check_log.py` reports PASS.
