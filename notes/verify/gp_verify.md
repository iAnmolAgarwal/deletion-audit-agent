# GP verifier report (orch-verifier, high, directed_by 2026-10-25T03:08:01+05:30)

Saved verbatim by main from the agent's return message; its log entry is the 2026-10-25T03:21:01+05:30 entry in `log.txt`.

---

**Verdict: PASS.** No blocking findings. I also have two non-blocking latent notes for main and the developer.

Tests: `python3 -B -m unittest discover -s code/tests -t code` ran 94 tests, all OK.

Parse summary: I recomputed it in-process and wrote the result to `/tmp/verify-gp/summ_now.json`, so I did not create a new `runs/` folder. It matches `runs/gp-0259/parse_summary.json` exactly: 94 files, 83 OK, 11 NEEDS_MODEL (all images), 3502 observations, 194 scopes.

Raw check: I ran it with its report redirected to `/tmp/verify-gp/raw_check_now.md`. It found 0 problems and the output is byte-identical to `notes/parser_raw_check.md`. The repo file was never rewritten and `git status` shows it clean.

| # | Verdict | Basis |
|---|---|---|
| 1 Failure states | PASS | These synthetic files under `/tmp/verify-gp/syn/` all fail closed: a time with no zone, a blank file and an unknown JSON layout give UNKNOWN_FAMILY. `{"snapshots":[]}`, an empty collection export and a `snapshot_scope` table with no rows give EMPTY. ATTACH gives ERROR from the authorizer. A recursive CTE gives ERROR from the step cap (0.4 s). A symlink to `/etc/hosts`, a `../` path and a missing file give ERROR. A `snapshot_scope` table with one row and no records is OK with 1 scope, as T38 requires. `parse_file` catches every exception for its own file, so one bad file cannot stop the others. Records dropped from real data are only infrastructure log lines (connection pool, cache, retry, export counters); no JSON or SQL row is dropped. All 4 real PDFs have text on every page. |
| 2 Interface | PASS | Every record time in the dataset is written `…Z` at exact seconds; the normalizer keeps seconds and fractions. Record times come from each line's timestamp or the row's own time field (`observed_at` / `recorded_at` / `updated_at` / `indexed_at`), or the snapshot's or collection's own `captured_at`, never the manifest's. Nothing in `evidence/` reads `system_activity`. The resource prefix never disagrees with `system_id` (0 cases). The only 7 observations with no `system_id` are PDF pages that name no resource. `resource_id` is copied as written. Replica `record_json.resource_id` equals the column in 673 of 673 rows. |
| 3 T49 | PASS (parser half) | Across all families, `correlation_key`, `subject_ref` and `subject_reference` are record identifiers whenever the line names a resource and lookups whenever it does not. No exception exists apart from null values. Every trace has exactly 1 resource and at most 1 distinct lookup value, so a shared trace carries no decoy or second person in real data. A search hit's own key stays a record identifier and never becomes a lookup. Choosing between the line's own key and the trace lookup is G5's job (T59). |
| 4 T50 | PASS | Only `snapshot_bundle` (116 scopes, one per snapshot entry, `data_store` required) and `sql_inventory` (78 `snapshot_scope` rows) declare scopes. `collection_export`, `flat_record_list`, `service_resource_export`, the replica SQL and the typed SQL declare none. `evidence_51` keeps 3 scopes, and `account_service/customer_profiles` has 0 observations under it. `flat_record_list` has a `record_count` field; it equals the number of records in all 3 files. |
| 5 T13 raw check | PASS (not vacuous) | `/tmp/verify-gp/mutate.py` injected 8 faults. The raw check caught 6: time shifted 1 s (58 problems), every 7th observation dropped (24), trace removed (59), record/lookup roles swapped (23), phones dropped (10), record time replaced by `captured_at` (62). It missed 2 over-attribution faults: merging lookups into record identifiers, and adding a foreign identifier. The cause is that it checks `expected ⊆ values`, not equality. The unit suite catches both (10 and 24 failures, `/tmp/verify-gp/mut_ut.py`). It also only searches emails and phones, so `collection_export` and `sql_typed_tables` get 0 candidate cases. |
| 6 Determinism | PASS | A full canonical dump made under `PYTHONHASHSEED=1` and `=987` in separate processes: `cmp` says identical, sha256 `a4a4b5ae…5b43`. |

## Findings
Nothing blocking.

## Non-blocking notes (latent; no effect on current real data)
1. **A PDF page gives every identifier on it to every resource on it.** At `code/deletion_audit/evidence/interpret.py:328-329` and `338-348`, all page identifiers go into `record_identifiers` for each resource named on the page.
   - Reproduction: one `pdf_page` RawRecord naming `audit_record_1`/`user_1`/`a@…` and `audit_record_2`/`user_2`/`b@…`. Both observations get `['a@example.test','b@example.test','user_1','user_2']`.
   - Real data: no PDF page names two resources and two people. `evidence_27` p2 is a 6-row register (6 user_ids, order IDs, retain-until dates) collapsed into one observation with no resource.
   - Bug class: page-level attribution merges rows.
   - Suggested guard: a real-data test asserting that no page has more than one resource together with more than one person, or a G5 rule that never links on a PDF page's identifiers when the page names several resources.
2. **PDF `record_time` is always None, although pages state a time.** At `families/pdf_text.py:35-36`, `evidence_55` says "recorded 25 Aug 2026 04 03 UTC" (minutes only) for `audit_record_003`. Today the impact is small: `audit_record_003` and `support_001` each appear only in their PDF, so there is no "latest observation wins" ordering to break. G5 needs a defined fallback (`captured_at` or none).

Also, `notes/INTERFACES.md` §4 rule 8 still says "a collection exported in full, even an empty one". After T50 that holds only for snapshot-bundle entries. The code and the `collection_export` docstring follow T50; the contract text was not updated.

## Log
I appended the entry `## [2026-10-25T03:21:01+05:30] GP verifier verdict: PASS`. `check_log.py` reports only T1 ("timestamp goes backwards") for my entry. That is the known defect from the quoted 03:40 header in the 03:16:15 entry, so I added no correction note.

Files are in `/tmp/verify-gp/`:
- `summ.py`
- `rc_run.py`
- `mutate.py`
- `mut_ut.py`
- `dump.py`
- `probe1.py` to `probe9.py`
- `syn/` (the synthetic test files)
