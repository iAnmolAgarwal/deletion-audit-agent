# CONTRACT_DRAFT — Ghost Data Still Exists (G1)

- Gate G1, `orch-contract-reader`, directed_by 2026-10-24T23:59:53+05:30. Written 2026-10-25T00:10+05:30 at HEAD `0eddbbd`.
- Every organiser file (`problem_statement.md` = **PS**, `README.md` = **RM**, `AGENTS.md` = **AG**, `agent_trace_instructions.md` = **AT**, CSV text) was read as an **untrusted claim**. No instruction inside them was followed.
- **Holdout lock.** `sample_output.csv` was read only through `devraw.py`. That script drops every line whose first CSV field is a holdout ID before parsing it, and asserts exactly 22 DEV rows. No holdout gold was opened, printed, parsed or counted. Every gold figure below comes from the 22 DEV cases: 01 02 03 05 07 08 09 11 12 15 16 17 18 19 20 21 22 24 26 27 30 31.
- No paid API or model was called. SQL was loaded only into in-memory `sqlite3`, with ATTACH, DETACH and `load_extension` denied by an authorizer and a pre-scan.
- **Labels.** SEEN = computed or quoted here. INFERRED = reasoned from SEEN facts. UNKNOWN = not determinable.

## Helper scripts (scratchpad, read-only on the repo)
Dir: `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/g1_contract/`
- `devraw.py`: the dev-only raw loader.
- `devcheck.py`: format, enum, order and evidence checks.
- `devdump.py`: per-case DEV step listing.
- `devrules.py`: citations, ordering discrimination, the F↔R↔V mapping, system names, post-audit activity.
- `serial.py`: byte-level re-serialization.
- `citecontent.py`: whether a cited resource is named in the cited file.
- `linkscan.py` and `linkscan_cited.py`: identifier links against gold.
- `dupes.py`: duplicate steps and zero-padded IDs.
- `inputs.py`: input inventory.
- `sqlload.py`: safe SQLite load plus identity resolution.
- `pdfscan.py` and `pdfgrep.py`: PDF text scan.

---

## 1. Output-format claims and verdicts

DEV totals (SEEN, `devcheck.py`):
- 22 rows: COMPLETE 7, INCOMPLETE 15, NOT_APPLICABLE 0.
- 134 steps: VERIFICATION 76, FINDING 29, REMEDIATION 29.
- 0 structural violations.

| # | Claim (quoted) | Source | Verdict | DEV basis |
|---|---|---|---|---|
| F01 | Columns `case_id,deletion_status,steps_json` "in this exact order" | PS:64, RM:67-71, AG:228-232 | **CONFIRMED ON DEV** | The header line is exactly `case_id,deletion_status,steps_json`. All 22 DEV rows parse to 3 fields. The `dataset/output.csv` template has the same header and 0 rows. SEEN |
| F02 | "exactly one row in `output.csv` for every case"; "exactly 518 data rows" | PS:61, PS:73, RM:75, AG:236 | **CONFIRMED (data)** | `deletion_requests.csv` has 518 rows and 518 distinct `case_id`s, `case_33`…`case_550` and contiguous. Our output's count is our job. SEEN |
| F03 | "sorted by `case_id`" | PS:73, RM:75, AG:237 | **UNTESTABLE ON DEV** | DEV IDs are zero-padded (`case_01`…`case_31`), so string and numeric order coincide. DEV rows are in sorted order. Test IDs are **not** padded: `deletion_requests.csv` is in **numeric** order, not string order (`inputs.py`: string-sorted False, numeric-sorted True). See A1. SEEN |
| F04a | `deletion_status` ∈ {`COMPLETE`,`INCOMPLETE`,…} | PS:19, PS:70, AG:238 | **CONFIRMED ON DEV** | COMPLETE: 01 02 03 21 26 27 31. INCOMPLETE: the other 15. SEEN |
| F04b | `NOT_APPLICABLE` is a value | PS:19, PS:70 | **UNTESTABLE ON DEV** | 0 DEV NA rows. SEEN |
| F05 | Each step contains "exactly these fields": `step_no`,`phase`,`system_id`,`resource_id`,`operation`,`state`,`evidence_id` | PS:75-87, AG:244-256 | **CONFIRMED ON DEV** | 134 of 134 steps have exactly these 7 keys. `step_no` is a JSON int; the other six are strings. SEEN |
| F06 | "Step numbers start at `1` and increase consecutively" | PS:89, AG:241 | **CONFIRMED ON DEV** | 22 of 22 cases. SEEN |
| F07 | `phase` ∈ `FINDING`,`REMEDIATION`,`VERIFICATION` | PS:89 | **CONFIRMED ON DEV** | All three are used; nothing else appears. SEEN |
| F08 | Operation→state table (15 rows) | PS:103-119, AG:262-290 | **CONFIRMED ON DEV** | All 15 operations occur, and each carries its table state in 134 of 134 steps. Counts: VERIFY_RECORD_ABSENT 33, VERIFY_RECORD_PRESENT 17, REPORT_REMAINING_RECORD 14, DELETE_RECORD 14, VERIFY_RECORD_ANONYMIZED 8, REPORT_EXPOSED_PII 8, VERIFY_RECORD_REDACTED 7, VERIFY_DATA_FLOW_DISABLED 7, REPORT_ACTIVE_DATA_FLOW 5, DISABLE_DATA_FLOW 5, VERIFY_RESTORE_BLOCKED 4, REDACT_RECORD 4, ANONYMIZE_RECORD 4, REPORT_RESTORE_RISK 2, BLOCK_RESTORE 2. SEEN |
| F09 | Operation→phase as tabled | PS:103-119 | **CONFIRMED ON DEV** | 134 of 134. SEEN |
| F10 | "Order steps by phase: findings, remediation, then verification" | PS:126, RM:75, AG:242 | **CONFIRMED ON DEV** | 22 of 22. SEEN |
| F11 | "Within each phase, follow the operation order in the table above" | PS:126, RM:75 | **CONFIRMED ON DEV** | 22 of 22. In 22 phase-blocks a (system, op) sort would give a different order; operation-first is what DEV shows. Examples: case_11, 18 and 30 in all three phases; 03, 09, 15, 17, 20, 21, 22, 26, 27 and 31 in verification. In case_26 and 27, `VERIFY_RECORD_REDACTED support_platform` precedes `VERIFY_RECORD_ANONYMIZED analytics_platform`, against alphabetical system order. SEEN |
| F12 | "…followed by `system_id` … ascending" | PS:126 | **CONFIRMED ON DEV** | Same-operation ties are broken by system. Examples: case_11, 18 and 30 have `REPORT_EXPOSED_PII analytics_platform` before `support_platform`; 8 INCOMPLETE cases (11, 16, 18, 19, 20, 22, 24, 30) have `VERIFY_RECORD_ABSENT account_service` before `search_service`. SEEN |
| F13 | "…and `resource_id` in ascending order" | PS:126 | **UNTESTABLE ON DEV** | No DEV case has two resources with the same (phase, operation, system_id). SEEN (`devrules.py`) |
| F14 | COMPLETE: "include only verification steps proving the current state" | PS:91, AG:258 | **CONFIRMED ON DEV** | 7 of 7 have only VERIFICATION steps, with step counts 1, 1, 3, 3, 6, 6, 3. SEEN |
| F15 | INCOMPLETE: "findings, the complete remediation plan, and the checks that must pass afterward" | PS:91, AG:258 | **CONFIRMED ON DEV** | 15 of 15 have all three phases. Verification also lists items that were **not** remediated; see A2/I-2. SEEN |
| F16 | NA: "use an empty JSON array (`[]`)"; row form `case_000,NOT_APPLICABLE,[]` | PS:91-97, RM:73, AG:239 | **UNTESTABLE ON DEV** | No DEV NA row. `csv.writer` emits `[]` unquoted, which matches PS:96. SEEN |
| F17 | COMPLETE verification steps "must cite" evidence | PS:127, AG:314, RM:153 | **CONFIRMED ON DEV** | 23 of 23 COMPLETE steps cite. In 3 of them the cited file does not literally name the resource: case_01 `account_001` and case_02 `account_002` (evidence_54), and case_31 `account_4857` (evidence_51). "Proving" is therefore looser than literal naming. SEEN (`citecontent.py`) |
| F18 | "A finding must use the participant-visible `file_id`, `activity_id`, or `audit_id` that proves it" | AG:313, RM:153 | **CONFIRMED ON DEV** | 29 of 29 findings cite. 28 name the resource in the file's text; the 29th, case_07 `support_001`, is named in the text layer of evidence_58 (a PDF). SEEN |
| F19 | "Proposed remediation and future verification steps for `INCOMPLETE` cases use an empty `evidence_id`" | PS:127, AG:315, RM:154 | **CONFIRMED ON DEV** | 29 of 29 remediation steps and 53 of 53 INCOMPLETE verification steps carry `""`. SEEN |
| F20a | Evidence may be a `file_id` | PS:127, RM:73 | **CONFIRMED ON DEV** | 52 of 52 citations are `evidence_NN`, all present in the manifest. Each case cites exactly one file (22 of 22). SEEN |
| F20b | …or an `activity_id` / `audit_id` | PS:127, RM:73, AG:313 | **UNTESTABLE ON DEV** | DEV cites an activity_id 0 times and an audit_id 0 times. See A10. SEEN |
| F21 | "Never cite … an evidence item captured after the case's `audit_at`" | AG:316, AG:224 | **CONFIRMED ON DEV** | 52 of 52 cited files have `captured_at ≤ audit_at`. **Equality is allowed**: case_11, 16, 22 and 31 cite files captured exactly at `audit_at`. SEEN |
| F22 | "JSON object-key order and whitespace are ignored" | PS:99, RM:75, AG:240 | **UNTESTABLE ON DEV** (grader claim) | The gold uses two key orders: 17 cases in `step_no,phase,system_id,resource_id,operation,state,evidence_id` order, and 5 hand-built cases (01, 02, 05, 07, 08) with sorted keys. All 22 are compact (`,` and `:` with no spaces), so the gold's own format is consistent with the claim. SEEN (`serial.py`) |
| F23 | "array order is not [ignored]" | PS:99, RM:75 | **UNTESTABLE ON DEV** (grader claim) | — |
| F24 | "disable data flows and block unsafe restores before changing dependent records" | AG:303 | **CONFIRMED ON DEV** | DISABLE_DATA_FLOW precedes DELETE, REDACT and ANONYMIZE in case_11, 18, 20 and 30. BLOCK_RESTORE never co-occurs with another remediation (case_09 and 17 have one remediation each). It is also implied by the table order. SEEN |
| F25 | "Process downstream copies before their source records when the dependency requires it" | AG:303 | **CONTRADICTED ON DEV** (under the natural reading) | case_16 (`account_994`, then `search_1007`) and case_24 (`account_5334`, then `search_5577`): the account (the source) is remediated and verified **before** its search copy, in plain system order. That search is downstream of the account is INFERRED from 400 `INDEX_RECORD account_service→search_service` rows. The "when required" escape clause is never exercised. See A5. |
| F26 | "Verification must cover the required final state for each remediated record or process" | AG:304 | **CONFIRMED ON DEV** | In 15 of 15 INCOMPLETE cases, findings and remediations correspond 1:1 on (system, resource). Every remediation has its matching verification: DELETE→ABSENT, REDACT→REDACTED, ANONYMIZE→ANONYMIZED, DISABLE→DISABLED, BLOCK→BLOCKED. SEEN |
| F27 | Tombstone: "stable user reference may remain … direct identifiers … removed"; rule_15 `REDACT` | PS:13, AG:300 | **CONFIRMED ON DEV** | case_31 has `VERIFY_RECORD_REDACTED identity_service tombstone_440` (REDACTED, not PRESENT). SEEN |
| F28 | "access, correction, export, marketing opt-out … is `NOT_APPLICABLE`" | AG:296, PS:19 | **UNTESTABLE ON DEV** | 0 DEV NA. In the test inputs, case_533–542 are 10 such texts, all with `reported_status=NOT_STARTED` (quoted in §6 A9). SEEN |
| F29 | `reported_status` "is a claim … not proof" | PS:57, AG:298 | **CONFIRMED ON DEV** | Reported COMPLETE but gold INCOMPLETE: case_05, 07, 11, 12, 15, 18, 22, 24, 30. Reported NOT_STARTED but gold COMPLETE: case_26. SEEN |
| F30 | `steps_json` is a valid JSON array | RM:152, AG:240 | **CONFIRMED ON DEV** | 22 of 22 parse to lists. SEEN |
| F31 | The answer key is generated deterministically from private truth (AG:380, AG:383, AG:385) | AG:378-394 | **UNTESTABLE ON DEV** | The DEV skeleton is perfectly regular (0 violations in 134 steps), which is consistent with a generator. "Deterministic" itself cannot be observed. INFERRED |

### Serialization facts (SEEN, `serial.py`)
- File: UTF-8, no BOM, **LF** line endings, trailing newline, header row first.
- Each DEV line is reproduced byte-for-byte by `csv.writer(lineterminator="\n")` (QUOTE_MINIMAL; `steps_json` is double-quoted with inner `"` doubled) applied to `json.dumps(steps, separators=(",",":"))`:
  - for 17 cases, with insertion order `step_no,phase,system_id,resource_id,operation,state,evidence_id`;
  - for 5 cases (01, 02, 05, 07, 08), with `sort_keys=True`.
- No DEV value is non-ASCII.
- **Caution (INFERRED):** Python's default `csv.writer` line terminator is `\r\n`. Set `lineterminator="\n"` to match the sample file.

## 2. Input facts (computed; `inputs.py`, `sqlload.py`)

| File | Columns | Data rows | Notes (SEEN) |
|---|---|---|---|
| `deletion_requests.csv` | `case_id,email,requested_at,reported_status,reported_at,audit_at,request_text` | 518 | IDs `case_33`…`case_550`, in numeric order. `reported_status`: COMPLETE 254, PARTIALLY_COMPLETE 152, NOT_STARTED 112. 517 distinct lower-cased emails (`ingrid.dahl@outlook.com` appears twice: case_33 and case_52). 20 emails carry uppercase. Emails resolve 418 current, 100 historical, 0 unresolved. `audit_at` runs 2026-01-29T12:00Z → 2026-10-01T12:00Z. `requested_at` and `reported_at` are ≤ `audit_at` in 518 of 518. |
| `sample_deletion_requests.csv` | same 7 | 32 | `case_01`…`case_32`. COMPLETE 17, NOT_STARTED 10, PARTIALLY_COMPLETE 5. 32 distinct emails, 3 of them historical (DEV: only case_30). `audit_at` 2026-09-03 → 10-01. |
| `sample_output.csv` | `case_id,deletion_status,steps_json` | — | Only the 22 DEV rows were read; the holdout rows were not counted. |
| `output.csv` | `case_id,deletion_status,steps_json` | 0 | Header only. |
| `user_identities.csv` | `user_id,name,email,phone,email_hash,updated_at` | 850 | 850 distinct emails. `email_hash = sha256(lower(email))` for 850 of 850. |
| `user_audit_log.csv` | `audit_id,user_id,event_time,field_name,old_value,new_value` | 306 | `audit_01`…`audit_306`. `field_name`: email 107, email_hash 107, phone 92. |
| `system_activity.csv` | `activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details` | 4011 | `activity_01`…`activity_4011`. `reported_result`: SUCCESS 2914, FAILED 721, PARTIAL 376. 17 event types: DELETE_RECORD 890, UPDATE_RECORD 672, SYNC_RECORD 447, INDEX_RECORD 400, SEND_EMAIL 368, REFRESH_CACHE 284, RETAIN_RECORD 206, ANONYMIZE_RECORD 204, REDACT_RECORD 173, CREATE_EXPORT 155, CHECK_DATA_FLOW 89, DISABLE_DATA_FLOW 36, BLOCK_RESTORE 36, CHECK_RESTORE_ACCESS 28, LINK_RESOURCE_IDENTITY 12, CLASSIFY_REQUEST 10, RESTORE_BACKUP 1. |
| `deletion_rules.csv` | `rule_id,data_category,condition,required_action` | 15 | DELETE 7 (USER_PROFILE, SECONDARY_IDENTIFIER, SEARCH_INDEX_ENTRY, CACHE_ENTRY, SUPPORT_ATTACHMENT, USER_EXPORT, MARKETING_PROFILE). REDACT 3 (SUPPORT_MESSAGE, EMAIL_DELIVERY_LOG, ACCOUNT_TOMBSTONE). RETAIN 3 (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD, BACKUP_ARCHIVE). ANONYMIZE 2 (ANALYTICS_PROFILE, PRODUCT_TELEMETRY). |
| `evidence_files.csv` | `file_id,file_path,origin,captured_at` | 94 | `evidence_01`…`evidence_94`, 30 origins, `captured_at` 2026-01-29T11:44:59Z → 2026-10-01T12:00:00Z. Manifest and disk agree exactly (94 = 94; nothing missing either way). |

**Evidence by extension (SEEN):**
- `.json` 28, `.log` 26, `.sql` 24, `.png` 11, `.pdf` 4, `.txt` 1.
- By folder: records 29, logs 26, databases 24, images 11, documents 4.
- All 24 `.sql` files execute in in-memory SQLite.
- Table families:
  - `customer_data_primary` + `snapshot_scope` + 8 typed tables (11 inventory files);
  - `customer_data_read_replica` (5), `customer_data_reporting_replica` (2), `customer_data_replica_ap_south`/`_eu_west` (3), `customer_data_failover_replica` (1);
  - one hand-built file each with `customer_profiles_primary`/`_failover_replica` and `search_documents_primary`.
- The 4 PDFs have text layers (615–1001 chars).

**System names (SEEN, `devrules.py`):**

| Resource prefix | Gold `system_id` (DEV, 134 steps) | `target_system` in activity rows |
|---|---|---|
| `account` | `account_service` | `account_service`, `account_replication_cluster`, `account_failover_replica`, `privacy_case_management` |
| `audit_record` | `security_service` | `archive_service` 196, `security_service` 1 |
| `export` | `export_service` | `object_store` 155, `export_service` 34 |
| `support` | `support_platform` | `search_service` 232, `support_platform` 193 |
| `data_flow` | `integration_service` | `integration_service` 126, `search_service` 31 |
| `search`, `analytics`, `backup`, `tombstone` | `search_service`, `analytics_platform`, `backup_service`, `identity_service` | the same systems (plus one `backup` row aimed at `search_service`) |

- In DEV gold each resource prefix maps to exactly one system_id.
- **The activity `target_system` is not the gold `system_id`** for audit records, exports and support.
- The evidence files spell `security_service` and `export_service`; `archive_service` appears in no evidence file.

## 3. Hard invariants (testable statements; each holds on 22 of 22 DEV unless marked)
1. The header equals `case_id,deletion_status,steps_json`; every row has 3 fields.
2. `deletion_status` ∈ {`COMPLETE`,`INCOMPLETE`,`NOT_APPLICABLE`}.
3. `steps_json` parses as a JSON list.
   - NA ⇔ `[]` (spec only; 0 DEV examples).
   - COMPLETE ⇒ non-empty and all steps VERIFICATION.
   - INCOMPLETE ⇒ at least one each of FINDING, REMEDIATION and VERIFICATION.
4. Every step has exactly the 7 keys; `step_no` is an int equal to its 1-based index; the other six are strings.
5. `operation` is one of the 15, and `phase` and `state` equal that operation's table values.
6. The steps are sorted by (phase rank F<R<V, operation-table index, `system_id`, `resource_id`).
7. No duplicate (phase, operation, system_id, resource_id). No resource gets more than one operation within a phase.
8. INCOMPLETE: FINDING and REMEDIATION correspond 1:1 on (system_id, resource_id), using:
   - REMAINING→DELETE;
   - EXPOSED_PII→REDACT or ANONYMIZE;
   - ACTIVE_DATA_FLOW→DISABLE;
   - RESTORE_RISK→BLOCK.
   Each remediation has a verification with DELETE→ABSENT, REDACT→REDACTED, ANONYMIZE→ANONYMIZED, DISABLE→DISABLED, BLOCK→BLOCKED.
9. Evidence:
   - FINDING has non-empty `evidence_id`;
   - REMEDIATION has `""`;
   - INCOMPLETE VERIFICATION has `""`;
   - COMPLETE VERIFICATION has non-empty `evidence_id`.
10. Every non-empty `evidence_id` is a manifest `file_id` with `captured_at ≤ audit_at` (inclusive).
11. *(Empirical, soft)* All non-empty `evidence_id`s within a case are the same single file.
12. *(Empirical, soft)* `system_id` is fixed by resource prefix, using the table in §2.
13. *(Empirical, soft)* Every non-NA DEV case verifies the account ABSENT in `account_service`: 22 of 22, either untouched or after DELETE.
14. *(Empirical, soft)* Generated cases (the 17 with insertion-order keys) carry exactly one `VERIFY_RECORD_PRESENT security_service audit_record_*`. The 5 hand-built cases carry none.
15. *(Empirical, soft)* `BACKUP_ARCHIVE` (rule_14 "RETAIN") never yields `VERIFY_RECORD_PRESENT`. Backups appear only as RESTORE_RISK → BLOCK_RESTORE → VERIFY_RESTORE_BLOCKED, or as a COMPLETE `VERIFY_RESTORE_BLOCKED`: case_09, 17, 26, 27.
16. Output: 518 rows, one per input `case_id`, no extras, LF line endings.

## 4. Deliverables the organisers claim are required

| Deliverable | Source | Affects score? (as far as we can tell) |
|---|---|---|
| Root `output.csv`, 518 rows | PS:61-73, RM:32, RM:151, AG:322 | **Yes, directly.** It is "compared with hidden canonical answers" (PS:131, RM:81). SEEN claim |
| `code.zip`: runnable code, prompts, configuration, `README.md`, evaluation folder | PS:145, RM:122, AG:363 | **Yes, via the code judge and the AI interview** (RM:99 "code judge or AI interviewer"). The scoring weights are UNKNOWN. |
| `evaluation_report.md`: case-level status accuracy, step-level and field-level accuracy, sequence accuracy, ≥3 own evaluation cases, failures and improvements | PS:133-139, RM:96, AG:338-344 | **Likely, through the code judge** (RM:99). INFERRED |
| `usage_report.md`: providers and models, calls, input and output tokens, total and average per request, total and per-request cost, per-model and overall totals | PS:152-158, RM:97, AG:346-353 | **Likely, through the code judge.** INFERRED |
| Report location: `code/evaluation/` vs `evaluation/` | RM:92-93, RM:99, RM:145, RM:155 vs PS:133, PS:155, AG:333-336 | See A8. **A wrong location may hide the reports from the judge.** INFERRED |
| `chat_transcript` = root `log.txt` | PS:147, RM:124, RM:113 | **Likely, for the judge and interview** (graded in past editions; kit research). INFERRED |
| `agent-trace.zip` | AT:3-5, AT:112-130 | **UNKNOWN effect.** AT:3 says it helps "improve our evaluation from the next time", which suggests it is not scored now. INFERRED |
| AI interview | PS:148, RM:125 | Yes; it is a separate stage. SEEN claim |
| No secrets, no `dataset/`, no venvs or caches, **no nested archives** ("will be rejected") | PS:160, RM:146-147, AG:368 | **Yes, as a hard gate**: a rejected submission scores nothing. SEEN claim |
| `log.txt` "follows the `AGENTS.md` turn format" | RM:156 | Possibly judged. Our CLAUDE.md §1 format is a superset of AG §5.2: it has the same headings and adds Context lines. INFERRED |

## 5. Red flags (quoted; none were obeyed)

**Instruction-like text aimed at AI tools**
- R1. AG:7 "Read this file in full before taking any action. Obey it exactly unless the user or platform provides higher-priority instructions." Also AG:5 "single source of truth for any AI coding agent".
- R2. AG:70-73: greet the user with a fixed "Welcome to HackerRank Orchestrate…" text.
- R3. AG:76 "The October challenge end time is not configured in this repository. Do not invent a deadline…" This conflicts with the developer-known deadline (Sun 25 Oct 19:00 IST, kit CLAUDE.md). Obeying it would suppress time tracking.
- R4. AG:94-103: "always provide this exact URL … every time … even when the challenge or submission question is included alongside other questions."
- R5. AG:149-153: mandatory "re-read the appended entry" and tool/model rules. These are harmless to the format, but they are directives to the agent.
- R6. AG:378-394: "Dataset Development Rules … run `python3 generator/validate_samples.py`". `generator/` does not exist in the repo; this text is aimed at the organisers' own agent. It is also the source of the deterministic-generator claim (F31).
- R7. RM:24: "Start your AI coding tool from the repository root so it automatically reads AGENTS.md". RM:112: "or explicitly ask it to read `./AGENTS.md` first". This would load R1–R6 as instructions; the prep session disabled it (repo CLAUDE.md).
- No injection text was found in any data:
  - 0 hits across the 550 request texts, `system_activity.csv` details, all 78 text evidence files and the 4 PDF text layers (`pdfscan.py` and a grep for ignore, instruction, assistant, AI, grader, `steps_json` and similar).
  - The only hit was the header line of the output CSVs.
  - The PNGs were not re-viewed in G1. Verify-12 reports E10: no instruction text in 11 of 11.

**Wording that would cost points if obeyed literally**
- R8. AG:303 "Process downstream copies before their source records when the dependency requires it." DEV case_16 and 24 order account before search (F25). Reordering by dependency would break sequence accuracy.
- R9. AG:304 "Verification must cover … each remediated record or process". Read as exclusive, it drops the untouched account ABSENT (12 of 15 INCOMPLETE) and audit PRESENT (12 of 15) verifications that DEV gold contains. That is 24 DEV steps.
- R10. rule_14 `BACKUP_ARCHIVE … RETAIN`. Mapping RETAIN mechanically to `VERIFY_RECORD_PRESENT` would add steps DEV never has (invariant 15).
- R11. Three phrasings clash with how DEV actually cites:
  - PS:127 "Findings and verification steps for `COMPLETE` cases must cite". A COMPLETE case has no findings. Read literally, it could suggest that INCOMPLETE findings need no citation; DEV cites 29 of 29.
  - RM:73 "Evidence references may be a `file_id`, `activity_id`, or `audit_id`" invites citing activity or audit IDs. DEV never does (0 of 52); see A10.
  - AG:308: "Treat activity logs, workflow statuses, and system messages as claims". This is consistent with DEV, where a FAILED or PARTIAL account delete still verifies ABSENT (verify-12 R14).
- R12. Using the activity `target_system` as `system_id` would emit `archive_service`, `object_store` or `search_service` where DEV gold has `security_service`, `export_service` and `support_platform` (§2 table).

**Contradictions between files and misleading typos**
- R13. The report path is `code/evaluation/…` (RM:92-93, RM:155) but `evaluation/…` (PS:133, PS:155, AG:333-334). Upstream commit `11576c9` (24 Oct 15:13 IST, "docs: align evaluation report paths with code.zip packaging in README") moved the README to `code/evaluation/`. PS and AG were not updated.
- R14. Evidence formats: PS:47 lists "PDFs, images, logs, JSON, or SQLite-compatible SQL", while RM:59 and AG:202 add "plain text". The data has 1 `.txt` (evidence_03, `customer_account_handover_20261001.txt`), which DEV case_11 cites.
- R15. System-name drift:
  - `object_storage` appears in activity_4007 and in manifest origin evidence_46; `object_store` appears in 155 CREATE_EXPORT rows.
  - Activity rows also use `archive_service`, while evidence uses `security_service`.
- R16. "sorted by `case_id`" (PS:73) is not the order of `deletion_requests.csv`, which is numeric; the IDs are unpadded (A1).
- R17. AG:94 typo fixed upstream: `wwww.hackerrank.com` became `www.hackerrank.com` in `0eddbbd` (see §7).

## 6. Ambiguities

| # | Question | Candidate readings | DEV evidence | Status |
|---|---|---|---|---|
| **A1** | Output row order for unpadded IDs | (a) string sort (`case_100` < `case_33`), the literal PS:73; (b) numeric order, as in `deletion_requests.csv` | DEV IDs are padded, so (a) = (b) | **UNSETTLED.** It matters only if the grader compares by position; PS:131 "compared with" does not say. INFERRED: the input order (numeric) is what a generator would also write for gold. |
| A2 | Already-compliant records (redacted support, anonymized analytics, disabled flow, blocked backup) in **INCOMPLETE** verification | (a) included, cited `""`; (b) omitted | INCOMPLETE verification does include untouched compliant **account ABSENT** (12 of 15: 07, 08, 09, 11, 12, 15, 17, 18, 19, 20, 22, 30) and **audit PRESENT** (12 of 15). No INCOMPLETE DEV case has a compliant support/analytics/flow/backup record identifier-linked in its cited file (`linkscan_cited.py`: 0 extras in 22 of 22). | **UNSETTLED** for non-account, non-audit types; account and audit are settled as (a). |
| A3 | `resource_id` order | (a) plain string; (b) numeric suffix | No same (phase, op, system) pair in DEV. DEV IDs include zero-padded ones (`analytics_037`, `search_052`, `support_001`, `export_001`), which makes a numeric reading ill-defined. | **UNSETTLED.** INFERRED leaning: (a). |
| A4 | `object_storage` vs `object_store` | (a) `object_storage` (LINK row and manifest origin for object_19); (b) `object_store` (CREATE_EXPORT target) | No `object_*` resource in DEV. Exports use `export_service`, not `object_store` (case_08). | **UNSETTLED.** Only object_19 (test case_61) is affected. |
| A5 | "Downstream before source" vs plain order | (a) plain op/system/resource order; (b) dependency reorder | case_16 and 24 give (a) | **Settled (a)** for account/search. Other pairs are UNSETTLED but unexercised. |
| A6 | Post-audit restore, sync or recreation | (a) ignored for state at `audit_at`; (b) creates a finding | Evidence level: case_27 `account_3866` is 404 in evidence_92 (09-15) and live with PII in evidence_02 (09-17, after the 09-15 audit); gold verifies ABSENT citing evidence_92 → (a). Activity level: no DEV gold resource has any activity row after its case's `audit_at`. The only RESTORE_BACKUP (activity_3387, 08-22, backup_9287→search_4882) belongs to test case_55 (audit 04-30). | **(a) settled at evidence level (case_27).** Activity-row level UNSETTLED. |
| A7 | Email shared by two cases | (a) each case uses only its own window and evidence; (b) the union of the user's resources | DEV case_07 (priya, audit 09-12): object_19 is linked to user_07 before that audit (activity_4007 and evidence_46, both 02-13) yet is absent from gold. DEV case_17 (leonie, audit 09-15): tombstone_17 is linked to user_17 by activity_4011 and evidence_67 (03-10) yet is absent from gold. In both, the earlier resource belongs to a test case (case_61, case_46). | **Leaning (a) on case_07 and 17.** INFERRED: a different explanation, such as the resource being remediated by then, cannot be excluded. ingrid (test 33 and 52) has no DEV example. |
| A8 | Report path inside code.zip | (a) `code/evaluation/`; (b) top-level `evaluation/` | Not data. The latest upstream edit (`11576c9`) chose (a). RM:145 accepts (b) only if it is added to the zip command. | **UNSETTLED.** Lowest risk: generate in `code/evaluation/` and also place identical copies at top-level `evaluation/` inside the zip. That is a developer decision. |
| A9 | NA row format and triggers | `case_X,NOT_APPLICABLE,[]` | 0 DEV NA. The test inputs case_533–542 are non-deletion texts, all `reported_status=NOT_STARTED`. Several contain negated deletion words: case_534 "not asking for deletion", 536 "Do not close the account", 539 "not a request to erase it", 542 "please don't delete or change anything". Each has one `CLASSIFY_REQUEST` row ("classified … as non-deletion"). | **UNTESTABLE.** The format is spec-only. |
| A10 | Which IDs may appear in `evidence_id` | file, activity or audit IDs (RM:73) | DEV: file IDs 52 of 52; activity 0; audit 0. That includes case_30, whose request email is historical and is resolvable only via `user_audit_log` (`audit_280`, verify-12), yet it cites evidence_92. | **Settled for DEV: cite file IDs only.** Whether the hidden key ever uses activity or audit IDs is UNKNOWN. |
| A11 | Serialization and row count | (a) any key order and whitespace, per the grader claim | Gold: compact; two key orders (§1). Rows sorted; LF; 518 required. | Use compact JSON, the README key order and LF to match the 17 generated rows byte-for-byte. Settled as far as we can control it. |
| A12 | Is "verify my deletion" authorized? | (a) yes, deletion-authorized; (b) NA | case_21 ("Could you verify that the profile is gone…"), case_26 ("Please check the latest state and confirm…") and case_27 ("Please audit the deletion as it stood…") are all COMPLETE with steps. | **Settled (a)** on 21, 26 and 27. PS:91 "no deletion or deletion verification is authorized" applies only to genuine non-deletion requests. |
| A13 | Legal-hold step shape | (a) `VERIFY_RECORD_PRESENT legal_service legal_hold_N`, no finding; (b) no step; (c) a different system | 0 legal_hold resources in DEV gold. Activity: 10 `RETAIN_RECORD → legal_service legal_hold_*`. rule_13 RETAIN; by analogy, rule_12 RETAIN gives `VERIFY_RECORD_PRESENT` (17 DEV steps). | **UNSETTLED.** INFERRED leaning: (a). |
| A14 | Which file to cite | the latest pre-audit file linked to the user, or any proving file | One file per case in 22 of 22. In 3 COMPLETE steps the cited file does not name the resource (case_01, 02, 31). | Forensics scope (G2); recorded here only as a constraint. |

**Most dangerous** (highest expected point loss × uncertainty):
1. A2: compliant extras in INCOMPLETE verification, which affect many test cases' step counts.
2. A13: legal-hold steps; 8 test cases per research/16.
3. A1: row order, if the grader is positional; it affects every row.

A3 (string vs numeric) is next.

## Verdict tally
- Format claims F01–F31 (33 rows): CONFIRMED 23, CONTRADICTED 1 (F25), UNTESTABLE 9 (F03, F04b, F13, F16, F20b, F22, F23, F28, F31).
- Input claims checked in §2 (13: request and sample columns and counts, `reported_status` enum, current or historical email, manifest mapping, evidence formats, SQLite executability, replica types, unrelated activity rows, identity fields, blank template, rule actions, multilingual text): CONFIRMED 13. R14 notes the `.txt` omission in PS:47.
- Overall: **36 confirmed, 1 contradicted, 9 untestable.**

## 7. Diff
- No previous contract file exists (`notes/` held only `split.json`).
- Upstream delta `acb3dfc → 0eddbbd` (SEEN, `git diff`): one line in `AGENTS.md`, line 94: `https://wwww.hackerrank.com/...` became `https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists`. Nothing else changed: no data, PS or README edits. The only working-tree change is our own repo `CLAUDE.md` replacement.
