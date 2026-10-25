# G5 fix round 2 (orch-builder-core, directed_by 2026-10-25T12:07:17+05:30)

## Main's check (2026-10-25 ~13:16 IST), on an export of the staged index (`git checkout-index`)
- `code/tests`: `Ran 542 tests … OK`. `code/evaluation/tests`: `Ran 308 tests … OK`.
- Replay-only, empty reply cache, fresh run IDs `mainchk-fr2-dev` / `mainchk-fr2-test`:
  - DEV `641dbc8d921186efbf92514b2c71fe25a3b133d412515dd952da19f8ac85b15c` (equal);
  - test `cf2a90b070db785456b2cb26398add0eba95a69ae8a763eb838a367f135751fc` (equals `notes/approved_output.json`).
- Lint on every staged path: mypy clean on 182 files. Ruff gives 3 findings, all in the untouched `inputs/__init__.py` (UP035, B905, UP047), which were there before (G9 list).
- R04's exact row and the p4 "agree" property are pinned by committed tests (`tests/pipeline/test_redteam_fixtures.py`, `tests/pipeline/test_real_data_vision.py`), and both pass in the suite above.
- The open decisions below go to the developer in the paid pass's one message. None blocks the paid pass: real-data counts for items 1 and 3 are 0, and the DEV paid step is the routing check, not a gated full run.

## The agent's report (verbatim)

### Blocked on me
1. **Item 12 can't be done in my scope.** No agent tool returns evidence text. I called `inspect_evidence` on all of R03's files and it returns only IDs, states and times. So the evidence-side code flag can never fire in the wired pipeline. Making it fire needs a change in `agent/tools.py` or `agent/loop.py`, for example scanning the cited records' text in `_record`. I removed the test I had drafted rather than ship one that only shows the gap. How do you want it fixed?
2. **The gate is now mandatory, so model-on DEV and fixture runs exit 5.** Their case set isn't the approved file's 518 test cases, and the gate refuses them. That fails closed, but it means DEV scoring runs with model replies will end "not passing". Should DEV get its own baseline, or do you accept this?
3. **Two decisions for you on item 1.**
   - When a record's own keys name the requester and someone else (`OWN_KEY_CONFLICT`), the row fails closed but keeps the steps on that record. The new validator check then refuses it (gate never drops a step). Dropping those steps is the other option.
   - I went beyond the literal T105 wording. The own key decides whose record it is, so a lookup link is blocked even when the own key resolves to no one (the `.jr` look-alikes). The literal wording ("resolves to a person other than the requester") leaves R04 at 14 steps.
4. **Paths I wrote outside the listed scope.**
   - `agent/schemas.py` and `agent/prompts/vision.md`: item 9 says it changes the vision schema and prompt.
   - Test helpers in `tests/agent` (the reading builders) and `tests/pipeline/_wiring.py`.
5. **The gate still waves through an image-caused citation change.** Under probe p4 "agree", case_45 stays COMPLETE but now cites the screenshot `evidence_37` instead of `evidence_55`. The gate allows it because its image check counts any image observation as an image state. I didn't change the gate's image condition.

### Changed
All changes are in the working tree, uncommitted, on top of 4dcd719.
- **Item 1 (R04):** `discovery/links.py:148` adds `record_own_keys`. Within a record, a trace lookup links only a person the record's own keys name (`:138`). `LinkIndex` gains `own_keyed` and `own_persons`. `link_observation` gains a keyword `record_owners=`. `engine.py:619` / `:653` fail the row closed with `OWN_KEY_CONFLICT`. `validate/prewrite.py:161` adds the hard check `OWN_KEY_OTHER_PERSON`, counted under a new part, "ownership".
- **Item 2 (R06):** `prewrite.py:243` also blanks citations that fail `HARD_CONTAINS`. At `:251`, the check of the gated row adds only failures the first pass did not find.
- **Item 3 (R11):** `engine.py:712` adds `_failure_kind` with new reasons `EVIDENCE_PARSE_ERROR` and `UNKNOWN_EVIDENCE_FAMILY`. Each unread file also gets its own `FAILED_DEPENDENCY` flag.
- **Item 4:** `tests/pipeline/test_redteam_fixtures.py` names R01–R12 one by one and runs each replay-only on an empty cache. The rows expected to be NOT_APPLICABLE are checked on everything except intent, and marked to move to the exact list once model intent is in.
- **Item 5:** `NO_CATEGORY_RULE` at `engine.py:573`, covering the `decide()` line-187 path. T69 is pinned by tests.
- **Item 6:** `PRESENT_CLAIM_OVER_STATE` at `engine.py:614`.
- **Item 7, widened:** `IMAGE_OMITS_CATALOG_RECORD` when no reading mentions a record that waited on an image. Also `IMAGE_STATE_NOT_SHOWN` (`:593`) for a record a reading shows with no visible state. Without it, p4 "agree" still turned case_35, 39, 50, 52 and 53 COMPLETE through omission readings.
- **Item 8:** `pipeline.py:416` `_agent_failed_record`: a FAILED loop gives the engine-path row, flagged `AGENT_CALL_FAILED`. `regression.py:204`: `CaseEvidence.loop_status`. A FAILED or unknown loop status never allows an intent change.
- **Item 9:** the readings have new fields, `visible_markers` and `status_label`. `state/observe.py:221` `image_state` sets a state only from what is on screen.
- **Item 13:** backup rule F for images (`observe.py:247`). No visible cue gives RESTORABLE; a "blocked" or "denied" marker gives RESTORE_BLOCKED.
- **Item 10:** the root `output.csv` is written only when the gate passes (`pipeline.py:587`).
- **Item 11:** the gate is mandatory when the model is on or `--write-root` is given (`:573`).
- **Item 4(b):** `row_changing_images` (`pipeline.py:303`) puts every image whose reading changes a row on the review list. `producer.vision.review.acknowledged` lists `{file_id, reply_keys, reading_sha256}`. `image_report` now carries `reading_sha256`.
- **Interface changes against §7.1:** `link_observation(..., *, record_owners)`, plus `LinkIndex.own_keyed` and `own_persons`; `ValidationContext.resource_own_persons`, and `build_validation_context(..., *, own_persons)`; seven new `FailedClosedReason` values; `VisionRecord.visible_markers` and `status_label`, and `ReadAttempt.raw_sha256`; `check_vision_ack(..., needs_review)`, `write_vision_artifacts(..., needs_review)`, `review_list`, `row_changing_images`; `CaseEvidence.loop_status`, and `VALIDATOR_PARTS["OWN_KEY_OTHER_PERSON"]`.
- **Tests made self-contained:** `test_fixtures.py` and `test_real_data.py` now use their own empty reply cache. F01 had started failing because main's stage-1 replies landed in the repo's `cache/` at about 12:55.

### Found
- `code/tests`: 542 OK. `code/evaluation/tests`: OK. `scripts/lint.sh` is clean on every touched file; the only ruff findings left in the package are 3 that were already in `inputs/__init__.py`.
- On the base export, 88 tests fail or error: every new test for each fix, plus older tests whose reading builders now send the two new fields, which the base schema rejects. A few boundary tests (T69, R8, a text backup) pass both before and after, as intended.
- **Output lock** (replay-only, empty cache): `g5fix2-dev-final` `641dbc8d…` (equal); `g5fix2-test-final` `cf2a90b0…` (equals `notes/approved_output.json`).
- **Fixture changes against the base, all 24 folders:** only two changed. **R04** now equals `expected_output.csv`: 5 steps instead of 14 (wrong→right). **R06**: step 1's citation changes from `evidence_930601` to `""`; the row stays `POST_AUDIT_ONLY_FINDING`, and each failure is now counted once. R11's rows are unchanged; each case now names all three files with their own reasons.
- **New flags (artifacts only):** `PRESENT_CLAIM_OVER_STATE` DEV 9 (matches T104's 9), test 0; `AGENT_CALL_FAILED` DEV 22, test 518 (every replay miss); `FAILED_DEPENDENCY` DEV 0, test 46 (on the 9 rows that wait for images); `OWN_KEY_CONFLICT`, `NO_CATEGORY_RULE`, `IMAGE_OMITS_CATALOG_RECORD`, `IMAGE_STATE_NOT_SHOWN` 0 / 0. The ownership check passes 131 of 131 steps on DEV and 3238 of 3238 on test.
- **Probe p4 "agree"** (a copy with the two new fields): case_46, 50 and 53 are no longer COMPLETE; all three are `IMAGE_STATE_NOT_SHOWN`. case_55's backup becomes a RESTORABLE FINDING under rule F. The committed property test `test_real_data_vision.py` caught this gap before `IMAGE_STATE_NOT_SHOWN` was added.
- No UNEXPLAINED steps are open.
