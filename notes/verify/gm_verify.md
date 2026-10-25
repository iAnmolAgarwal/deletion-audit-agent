# GM verifier report (orch-verifier, high, directed_by 2026-10-25T05:03:50+05:30; questions 7–10 added by T83/T84)

Saved verbatim by main from the agent's return message.

---

**Verdict: FIX.** 5 findings, all MAJOR, no BLOCKER.

The code changed while I was reviewing it: `schema_check.py` was rewritten at 05:11:51 for T84. Every file in `model/` and `tests/model/` then kept the same hashes from 05:12 until I finished. Model tests: 58 OK. `scripts/lint.sh` reports ruff and mypy clean on `model/`. I made no network calls: the probes used the fake transport and a stub SDK client only.

| Q | Verdict | Basis |
|---|---|---|
| 1 Retry ladder | PASS | All the listed statuses and errors are retried by `policy.py:148-167`; anything else gives up as NON_RETRYABLE. `max_retries=0` is set at `transport.py:99` and checked at `:87`. Only the policy builds `GiveUp` and only `client._give_up` raises, and an AST test checks that. Caveat: `x-should-retry: true` makes even a 400 retryable. That matches the SDK, and a test covers it. |
| 2 Failed calls | PASS | `structure.py` fails any stop reason other than `end_turn` or an allowed `tool_use`. `max_tokens` fails even when its JSON is valid. Repairs stop at `max_repairs=2`; `model_context_window_exceeded` is never repaired. |
| 3 Budget | FIX (F3, F4) | The caps work, every send reserves first, and a second settle raises `ValueError`. |
| 4 Cache | PASS, with a note | Entries are written by `os.link`, so an existing one is never replaced. The key, `api_version` and request hash are checked on every read. A replay miss makes 0 sends. The key is the body plus the API version, nothing else. Note: an entry's `model` and `usage` fields are never checked against `raw`, so a hand-edited entry is served as is. |
| 5 Call log | FIX (F5) | Give-ups and budget refusals are logged; some other failures are not. |
| 6 Request rules | FIX (F1) | The rules run only when a `ModelRequest` is built. |
| 7 Run lock | PASS | `flock` blocks a second paid run, including from another process, and `_reserve` refuses to send without the lock. Edge case: the lock file is named from the ledger path, so two different paths to the same ledger (a symlink, say) would get two locks. |
| 8 Resume test | PASS | The test does prove it. It asserts 0 cache entries and 3 ledger lines for the refused call. On the re-run it asserts the `from_cache` flags, 2 sends, 2 reservations and the exact spend. A send or a reservation on a cache hit would fail it. Small gap: it doesn't check that the error is `RunDollarCap` rather than `ProjectLedgerCap`. |
| 9 `ModelReply.request` | FIX (F1) | The request is correct when the reply is returned, but a caller can change it afterwards. |
| 10 Exact enum/const | FIX (F2) | Top-level, `anyOf`, `items` and `additionalProperties` comparisons are exact, and a mismatch goes to repair. The `$ref` path skips the check. |

The repro scripts are `/tmp/verify-gm/probe.py` and `/tmp/verify-gm/probe2.py`. Run them with `.venv/bin/python -B -I`.

**F1 (MAJOR): the request is only frozen at the top level, so the rules can be bypassed after it is built.** `request.py:62` wraps only the top level in `MappingProxyType`; nested dicts and lists stay mutable. `client.py:125` sends `req.plain_body()` without checking it again.
- Repro: `req.body["tool_choice"]["type"]="any"; req.body["output_config"]["format"]["type"]="text"; client.call(req)`
- Output: `sent tool_choice {'type': 'any'}`, `sent format type text`. The reply was paid for, then `CacheCorruptError ... holds an invalid request` was raised, so it was lost.
- Q9 repro: `out.request.body["messages"].append(...)` gives `reply.key == reply.request.key()` → `False`. The `ModelReply.request` docstring invites exactly this, since it says a caller can extend the conversation from it.
- Expected: the request is rejected before any send, and a reply's key always matches its request.
- Class: rules checked at build time on a body that is only shallowly frozen. Fix by freezing deeply, or by rebuilding `ModelRequest(req.plain_body())` before each send and keying from that.

**F2 (MAJOR): keywords next to a `$ref` are skipped (Q10).** At `schema_check.py:87`, `validate()` returns the result for the resolved `$ref` target only, so sibling keywords such as `enum` are never checked. `check_schema_supported` doesn't flag that shape either.
- Repro: an `intent` property of `{"$ref":"#/$defs/S","enum":["DELETION_REQUEST"]}`, with the reply `"not_deletion"`.
- Output: `client accepted via $ref sibling ('end_turn', '{"intent": "not_deletion"}', 1)`.
- Expected: SchemaMismatch, then repair.
- Class: a constraint skipped silently, which the module docstring says never happens.
- Second instance of the same class: `_same` (`schema_check.py:144`) is exact only at the top level. Inside lists and objects, `[True]` matches `enum [[1]]` and `{"a":False}` matches `const {"a":0}`.

**F3 (MAJOR): non-finite numbers switch off the budget stop.** The checks are at `budget.py:178`, `:189` and `:191`. `json.loads` accepts `NaN`, and every comparison with NaN is False.
- Repro: a ledger line `{"cost_usd": NaN}` (or `"nan"`) with `project_cap=0.0001`.
- Output: `RESERVED (fail-open)`.
- The same happens with `dollar_cap=nan` or `project_cap=nan`. A negative `cost_usd` also lowers the total.
- Expected: `BUDGET`/`LedgerUnreadable`.
- Class: a cap comparison that fails open. Fix by requiring finite, non-negative values for the caps and for each ledger cost.

**F4 (MAJOR): sends whose outcome is unknown are settled at $0.** At `client.py:127`, every `TransportFailure` is settled with empty usage, so it costs nothing.
- Repro: 5 scripted `APITimeoutError` failures.
- Output: ledger costs `[0.0, 0.0, 0.0, 0.0, 0.0]`.
- The server may still have finished and billed a request whose client timed out, or whose connection dropped mid-reply. Neither research file says whether it does (UNKNOWN), so failing closed means charging the reservation.
- Expected: timeouts and connection errors are settled at the reserved worst case. Status errors (429, 529, 5xx) can stay at $0.
- Class: the budget undercounts when the outcome is uncertain.

**F5 (MAJOR): some failures leave no entry in the call log.**
- A non-`TransportFailure` exception from the transport (`client.py:134`) is charged at worst case and re-raised raw, with no log entry. Output: `exc type ValueError`, `log entries []`.
- A 200 reply whose body isn't JSON raises `JSONDecodeError` from `transport.py:108`, which isn't wrapped as a transport failure, so it takes the same unlogged path. Output: `AnthropicTransport non-JSON 200 raises JSONDecodeError`.
- `PaidRunLocked` from `client.py:108` logs nothing. Output: `PaidRunLocked log []`.
- `CacheCorruptError` from `client.py:94` logs nothing. Output: `CacheCorrupt log []`.
- Expected: one entry for each, with its error class and status (null where there is none).
- Class: exception paths that bypass the call log.

Not findings:
- The test rig (`_support.py`) makes its temp directories under the system temp folder and deletes them itself.
- Exact enum matching now sends a wrong-case reply to repair. Each repair is one more paid call per affected reply.

I appended my entry to `log.txt`, and `scripts/check_log.py` passes.
