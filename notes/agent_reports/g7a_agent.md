# G7a agent package report (orch-builder-core, high)

directed_by 2026-10-25T05:49:46+05:30 (T88), with the T95 additions sent at 06:24. Main's check (06:50): agent 108, code/tests 381 and evaluation 187 OK; lint clean; no G5 or model/ file touched. Uncommitted until the G7 verifier. Saved verbatim by main from the agent's final message.

---

# G7a agent package: built and tested, waiting on pipeline wiring

The agent package is built under `code/deletion_audit/agent/` with 108 tests, all on GM's fake transport. I made no paid call, did not read `.env` and opened no gold file. Lint is clean, and all three suites pass:

| Suite | Result |
|---|---|
| `code/tests/agent` | 108 OK |
| `code/tests` | 381 OK |
| `code/evaluation/tests` | 187 OK |

`check_log.py` passes. The three hygiene failures another agent saw at about 06:22 were from work in progress and are fixed.

**DEV cases:** nothing is wired into the pipeline yet, so the agent produces no DEV output on its own. No DEV case flipped either way, and no step is left unexplained.

## Blocked on me
Nothing is blocked. These changes fall outside my paths; they are proposals for after G5 commits:
1. **`pipeline.py`:**
   - **Vision step:** two `ModelClient`s that share one `BudgetGuard` but have separate cache roots, then `learn_shapes` and `read_images`, then `write_vision_artifacts(run_dir, run)`.
   - **Refusal:** refuse a paid full run while `run.needs_review()` is non-empty and the developer hasn't acknowledged it.
   - **Engine:** run it on `replace(ctx, image_observations=run.observations)`.
   - **Per case:** `audit_with_agent(...)`; write `result.applied` as the row and `result.report` under the `"agent"` key.
2. **`engine._failures` and `pipeline.evidence_record`:** stop treating PNGs that the vision step read successfully (`run.read_ok()`) as pending or skipped. Without this, the T60 zero-skips freeze check can never pass.
3. **`CaseRecord.open_questions`, `answers` and `rejected`:** fill them from the result.
4. **Artifacts:** write `calls.jsonl` with GM's `JsonlCallLog`; derive `usage.json` and `producer.model_ids` from the calls.
5. **Image answers:** for an `IMAGE_FIELD_UNREADABLE` answer, build `world_applied` from `patch_image_observations(...)` and pass it to `compile_twice`.
6. **Freeze check:** besides 0 `INTENT_FAILED_CLOSED`, also require 0 `INTENT_FAILED_BUDGET`. Both flags come from G5's engine and are countable.

## Changed
**Public signatures:**
- `audit_with_agent(case_id, world, client, *, mode, caps=None, vision=None, replicate_clients=(), world_applied=None, clock) -> AgentCaseResult`
- `run_case(case_id, world, client, *, mode, caps, vision, replicate_clients, clock) -> AgentOutcome`
- `read_images(ctx, clients, shapes) -> VisionRun`
- `learn_shapes(observations, activity) -> IdShapes`
- `check_id(shown_id, shapes) -> IdCheck`
- `write_vision_artifacts(run_dir, run) -> (json_path, md_path)`
- `validate_answers(outcome, ctx, audit_at) -> AnswerCheck`
- `resolve_intent(outcome, check) -> (applied, withheld)`
- `compile_twice(case_id, world, applied, withheld, world_applied=None) -> Compiled`
- `agent_case_report(outcome, check, intent, steps_differ) -> dict`
- `vision_run_report(run)`
- `routing_table(texts, clients)`
- `LoopCaps(4, 6, 180.0, True)`

**Deviations from G3 §5 and the brief:**
- **No pydantic:** the answer types are dataclasses checked with GM's `schema_check`. `FinalAnswer.intent` holds the intent fields instead of inheriting them.
- **One shared turn 1:** A and tools_off reuse the A+ turn-1 request, following G3 §3 item 3, rather than §1.1's separate no-tools intent call. In tools_off no tool ever runs.
- **Added parameter:** `validate_answers` takes `audit_at`.
- **Cross-check source:** the cross-check wraps G5's `engine.crosscheck`.
- **INSTRUCTION_LIKE_TEXT is never posed as a question;** it is only a flag. **UNKNOWN_FORMAT** is posed, but its answers never add observations: not built, 0 such files today.
- **Fields added, none renamed:**
  - per-case report: `answers_noted`, `instruction_like_text`, `replies`;
  - vision items: `status`, `reply_keys`, plus `shown_id`, `basis` and `named_by` on each ID.
- **Null values:** `turn1_replicates` may hold null for a failed reading. For an unusable vision ID, `resource_id` holds the text as shown, with `well_formed: false`.
- **Flag names:** the model's flag is `INSTRUCTION_LIKE_TEXT_MODEL` and the code check's is `INSTRUCTION_LIKE_TEXT_CODE`.

**How the two vision readings work (T88 item 1):**
- The two readings are the same request through two `ModelClient`s with different `ReplyCache` roots. Reading 2 is a cache miss in its own root, so it is a fresh send. GM needed no change.
- `check_namespaces` refuses one shared root. A test shows the transport is called twice with no cache hit.
- **Shared guard:** both clients must share one `BudgetGuard`. A second guard on the same ledger is refused by GM's paid-run lock.
- **When the readings disagree, the engine uses `merge_readings`:**
  - every record either reading shows is kept, and identifier lists are united;
  - a state field takes the value that keeps a finding (sync enabled, restore allowed, not deleted, download available);
  - otherwise the field becomes `unreadable`, which raises `IMAGE_FIELD_UNREADABLE` for the cases it touches.
- **If either reading fails, the image fails** and stays an unparsed dependency of the cases that need it.
- **Review artifact:** `runs/<id>/vision_readings.json` and `vision_readings.md` show both readings and list what needs review. Identifiers are masked and hashed.

**Where the ID shapes come from (T88 item 2):** parsed evidence observations (system plus resource ID) and the LINK_RESOURCE_IDENTITY rows. Other activity rows are not used, because their `target_system` is noisy (for example, support IDs filed under search_service). Display names come from the parentheses in LINK rows.
- On the real data, all 11 screenshot IDs map to a resource: `user_17` → `tombstone_17`, `delivery_confirmation_19.pdf` → `object_19`, and `marketing_001` is well formed.
- Labels such as `CS-3245` and `ORD-…` are flagged and not used.
- `backup_9291` is kept but flagged, because no other input names it.

**T95 additions (developer turn 2026-10-25T06:24:17+05:30):**
- **Item 1, the code check:**
  - It is in `agent/injection.py`: `detect_instruction_like`, `detect_in_json` and `InstructionSignal`.
  - **Patterns:** `override_instructions`, `role_injection`, `address_the_model`, `dictate_outcome`, `skip_checks`, `authority_claim`, `prompt_reveal`. They are English only; other languages rely on the model's flag.
  - **What it scans:** the request text and every tool result the agent sees. The vision step also gets a code flag.
  - **Per-case record:** `instruction_like_text = {code, model, merged, code_patterns, code_sources}`.
  - **Real data:** it matches 0 of the 398 distinct dataset request texts and 0 of the 4,011 activity details. On the committed G5b fixture F09's planted injection text it matches 3 patterns.
  - **Tests:** `test_injection.py`, for example `test_request_check_flags_and_changes_nothing`, `test_model_flag_is_kept_beside_the_code_flag`, `test_evidence_text_the_agent_sees_is_checked` and `test_image_text_is_checked`.
- **Item 2, prompts as files:**
  - `prompts/system.md` and `prompts/vision.md` now have Role, Constraints, Untrusted data, When you cannot tell, and Examples (made-up) sections.
  - The final-answer schema gains `uncertain_reason`, and the screenshot is fenced between `<screenshot>` text blocks.
  - Each section of `prompts/tools.md` has "When to use / When not to use / Returns / Read-only" lines.
  - **Tests:** `test_prompt_parts.py`, for example `test_each_prompt_has_every_part`, `test_refusal_path_is_uncertain_with_a_reason`, `test_untrusted_text_is_fenced_in_the_prompt_and_in_the_request` and `test_every_tool_says_when_when_not_returns_read_only`.

## Found
**Tests:** G3 §7's names are used where they apply, for example `test_loop_cap_four_tool_calls_then_tool_choice_none`, `test_prompt_examples_use_made_up_ids`, `test_prompt_defines_verify_request_as_deletion`, `test_uncertain_routes_to_tool_or_failed_closed`, `test_intent_is_model_answer_crosscheck_flags_only`, `test_turn1_request_is_text_only` and `test_routing_consistency_drift_and_no_audit_call`. Also covered:
- **Seeded property tests** (Hypothesis is not installed), 60 seeds × all modes:
  - the loop bounds hold;
  - status is derived from the steps, and step order holds;
  - an undecided intent is never NOT_APPLICABLE;
  - the same script gives the same report.
- **Mutation check:** I removed one rule at a time (merge rule, namespace refusal, PNG check, quote check, tool cap, no-repeat rule, seen-evidence check, digit range, cross-check override, and the code-flag rules) and confirmed a test fails each time. All 10 rules plus the 3 code-flag mutations were caught.

**Cost estimates** (Sonnet 5.5 at $2/M input and $10/M output; prompt caching is off, `params.py`):

| Run | Calls | Input per call | Expected | High | Worst-case reservation |
|---|---|---|---|---|---|
| Turn-1 routing check | 808 = 404 distinct texts × 2 | about 2,900 tokens | about $8.3 (about $0.010 per call at 450 output tokens) | about $17 (1,500 output tokens) | about $51 |
| Vision | 22 = 11 images × 2 | about 3,700 tokens | about $0.49 (1,500 output tokens) | about $1.04 (4,000 output tokens) | about $2.20 |

The 404 distinct texts are 375 test, 22 DEV and 14 from the fixtures.

**Not done:**
- Pipeline wiring (proposals above).
- UNKNOWN_FORMAT answers that add observations.
- `query_snapshot` and the Batch client.
- A live check that cached thinking blocks are accepted when replayed on turn 2 (G3 lists this as UNKNOWN). The loop replays reply content unchanged.

**Risks for the developer, in the engine's reading of screenshots:**
- A support record whose image shows no identifiers is read as REDACTED.
- The backup screenshot shows no restore cue, so `backup_9287` will probably get no state (`NO_STATE`).

Files are in `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/deletion_audit/agent`:
- injection.py
- vision.py
- loop.py
- answers.py
- prompts/system.md
- prompts/vision.md
- prompts/tools.md

Tests are in `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/code/tests/agent`. The mutation script is `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g7a/mutate.py`.
