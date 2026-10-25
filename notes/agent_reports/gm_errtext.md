# GM error-text fix report (orch-builder, medium)

directed_by 2026-10-25T06:08:27+05:30 (T90). Main's check (06:13): model 81 and code/tests 273 OK at that time; lint clean; the new tests fail on committed GM. Uncommitted until the G7 verifier. Saved verbatim by main from the agent's final message.

---

**Blocked on me:**
- Nothing is blocked. One point to note: §8 of `notes/INTERFACES.md` had no separate list of call-log fields. So I extended the one line that names call-log content ("each failed call's error class and status go to the run artifacts"). If you want a proper field table there, that would be a separate edit.

**Changed:**
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/model/transport.py`
  - New `API_TEXT_LIMIT = 500`.
  - New `cap_api_text(value, limit)`: it cuts long text to exactly 500 characters, ending in `...[cut, N chars]`. A value that is not a string becomes None.
  - New `api_error_fields(body) -> (type, message)`: it reads `{"error": {"type", "message"}}`. Any other shape, or a missing body, gives `(None, None)`.
  - New `_status_failure(exc)`, which the `APIStatusError` branch now uses. The request ID comes from `exc.request_id`, or else the `request-id` header.
  - The module and `send` docstrings are updated.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/model/policy.py`: `Failure` gained `api_error_type`, `api_error_message` and `request_id`, all defaulting to None and added at the end. `detail` means the same as before.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/model/calllog.py`: `CallLogEntry` gained `api_error_type` and `api_error_message` (default None, added at the end). The existing `request_id` field is now also filled for failed HTTP sends.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/model/client.py`: `_log` copies the two `api_error_*` fields. It uses `request_id or failure.request_id`.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/tests/model/test_api_error_text.py` (new): five tests.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/INTERFACES.md`: one line in §8.
- `log.txt`: one entry added; `check_log.py` passes.

Every existing public name and signature still works; all the new fields have defaults.

**Found:**
- **Tests before the change:** I stashed only the four model source files and ran the new tests: `Ran 5 tests ... FAILED (errors=9)`. Every test failed, including all five subtests of the odd-body test.
- **Tests after the change:**
  - `.venv/bin/python -B -m unittest discover -s code/tests/model -t code` gives `Ran 81 tests ... OK` (76 before, plus 5 new).
  - `-s code/tests -t code` gives `Ran 273 tests ... OK`.
- **Lint:** `bash scripts/lint.sh code/deletion_audit/model code/tests/model` reports ruff `All checks passed!` and mypy `Success: no issues found in 27 source files`. The first lint run flagged import sorting in the new test, which `ruff --fix` fixed.
- **What the tests cover:**
  - A 400 shows the API's type, message and request ID in `calls.jsonl`, with `detail` still `NON_RETRYABLE` and one send.
  - Two 429s are retried, and each attempt carries its own text, then the reply succeeds.
  - Five odd bodies give None fields without crashing: non-JSON, no `error` key, `error` not an object, fields that are not strings, and no body at all.
  - A 1200-character message is cut to 500 with the marker.
  - A connection error is retried as before and its fields are null.
  - No test makes a network call or reads `.env`.
- **Example `calls.jsonl` line** (fake values, from the 400 test setup):
  ```
  {"api_error_message":"fake: field x is not allowed","api_error_type":"invalid_request_error","attempt":1,"cost_usd":0.0,"detail":"NON_RETRYABLE","error_class":"BadRequestError","event":"send","from_cache":false,"key":"5d735d23...","outcome":"give_up","request_id":"req_fake_400","run_id":"run-fake","status":400,"stop_reason":null,"usage":{}}
  ```
- **Two choices worth checking:**
  - The marker counts toward the 500 characters, so a stored message is never longer than 500.
  - The error `type` and the request ID are capped the same way as the message, because they are also untrusted API text.
- **Untouched file:** `notes/DECISIONS.md` shows as modified in git status. I did not edit it; it was most likely changed by main.
