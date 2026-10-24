# F02: Korean full-deletion request, syslog evidence, remaining export and search entry

**Tests:**
- a deletion request in a language DEV lacks (Korean; test has 12 ko, 14 pt, 12 ja: `research/16` §1.2) is deletion-authorized and processed like any other;
- evidence in the RFC5424 syslog dialect (no DEV primary; 10 test primaries, `research/16` §3.2): identifiers sit on `*_started` lines and reach the resource only through the shared trace;
- a remaining user export (rule_09; 31 test cases, DEV 1 hand-built);
- a `cache_lookup result="miss"` line that is noise, not absence.

**Provisional:** partly. The Korean intent reading is SPEC-ONLY (no DEV text in ko). Every step's shape is DEV-confirmed.
**G8 custom eval case:** no.
**Parse:** `evidence_9201` OK (`syslog_log`, 8 observations).

Rule keys: `R15-Rn` = `research/15` rule n, re-run 22/22 in `notes/gold_forensics.md`; `S1` = gold_forensics identifier-link rule (11/11); `CD-…` = `notes/CONTRACT_DRAFT.md`; `PS:n` = `problem_statement.md` (secondary).

## Inputs (all fictional)
- `case_90201`, `hana.oduya@example.com`, `PARTIALLY_COMPLETE`; times as in F01. Text (written for this fixture): "제 계정과 개인정보를 모두 삭제해 주세요. 예전 이메일 주소로 남아 있는 기록이 있는지도 함께 확인해 주세요. 처리가 끝나면 알려 주세요." ("Please delete my account and all personal data. Please also check whether records remain under an earlier email address. Tell me when it is done.")
- `user_900201`, Hana Oduya.
- `evidence_9201` (syslog, captured 11:40). Traces:
  - `tr-9002011`: `profile_lookup_started lookup_key=hana.oduya@example.com`, `connection_acquired`, `cache_lookup result="miss"`, then `profile_lookup_completed resource_id=account_900210 rows=0 http_status=404`;
  - `tr-9002012`: `index_query_started match_key=<email>`, then `index_query_completed resource_id=search_900211 result="hit" correlation_key=<email>`;
  - `tr-9002013`: `export_download_check_started owner_key=<email>`, then `export_download_check_completed resource_id=export_900212 available="true"`;
  - `tr-9002014`: `audit_record_query_started subject_ref=user_900201`, then `audit_record_read_completed resource_id=audit_record_900213 rows=1 correlation_key=user_900201`;
  - one `timer_tick` noise line.
- No activity rows.

## Expected row: `INCOMPLETE`, 8 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | export_service | export_900212 | PRESENT | evidence_9201 | rule_09 Always DELETE; R15-R9 (DEV export 1/1, case_08); `available="true"` at 10:31 is the latest state at or before audit (R15-R6) |
| 2 | FINDING | REPORT_REMAINING_RECORD | search_service | search_900211 | PRESENT | evidence_9201 | rule_03; R15-R9 (DEV search 8/8) |
| 3 | REMEDIATION | DELETE_RECORD | export_service | export_900212 | ABSENT | "" | R15-R9 mapping; CD-F26 |
| 4 | REMEDIATION | DELETE_RECORD | search_service | search_900211 | ABSENT | "" | same |
| 5 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900210 | ABSENT | "" | 404 at 10:02 linked by the trace's lookup key (S1); R15-R7, R15-R10; CD invariant 13 |
| 6 | VERIFICATION | VERIFY_RECORD_ABSENT | export_service | export_900212 | ABSENT | "" | CD-F26 |
| 7 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_900211 | ABSENT | "" | CD-F26 |
| 8 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900213 | PRESENT | "" | rule_12 RETAIN; R15-R10 (DEV 17/17 generated cases) |

- **Status:** at least one finding ⇒ INCOMPLETE (R15-R13).
- **Order:** CD-F10/F11/F12. Within REMAINING, `export_service` < `search_service`. Within VERIFY_RECORD_ABSENT, `account_service` < `export_service` < `search_service`.
- **Evidence:** findings cite the single primary file, the latest linked file at or before audit (R15-R14); remediation and INCOMPLETE verification are `""` (R15-R15; CD-F19; T77 rule 1).
- **Identity linking:** the trace lookup keys (`lookup_key`, `match_key`, `owner_key`, `subject_ref`) are the person's own email and `user_id`, joined to each resource on the same `trace_id` (T49, T59).
- **The `cache_lookup result="miss"` line** names no resource and is not an absence observation (`research/16` §3.2).

## What a failure looks like
- Korean text read as unknown → NA → `[]`: two remaining records go unreported.
- A syslog parser that only reads `*_completed` lines finds no identifiers, so it misses the export and search entry and the case becomes COMPLETE.
- The export verified ABSENT without a finding, or mapped to `object_store` (the activity `target_system`; CD-R12) instead of `export_service`.

## Not settled by the rules
- The audit line states no `retention_until`, so rule_12's condition ("within the supplied retention period") is not observable here. DEV treats this the same way: case_31's bundle audit events also carry no retention date, and the 17 generated DEV rows all verify their audit record PRESENT. Not flagged as provisional for that reason.
