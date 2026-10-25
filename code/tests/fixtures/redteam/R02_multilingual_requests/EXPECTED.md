# R02: requests in six languages that DEV lacks, with in-language negations

**Attacks:** intent in Spanish, Portuguese, Japanese, German, French and Hindi; DEV has English only. There are three in-language negations (pt, de, hi) and one French negation that *reinforces* deletion ("N'en gardez aucune copie": keep no copy). The Spanish request is also sent from the person's **old** email.

**Failure it catches:**
- "non-English means unknown, so NA" (93011, 93013, 93015 lose real findings or checks);
- "negation word present means NA" (93015 becomes NA);
- a translation that drops the negation (93012, 93014, 93016 become destructive plans);
- request-email resolution through the current email only (93011).

**Provisional:** yes for intent. Every intent reading is **SPEC-ONLY**: DEV has no text in these languages (`research/16` §1.2) and no NA row. Every step's shape is DEV-confirmed.
**Custom eval case:** no.
**Parse:**
- `evidence_930201` OK (`kv_log`, 20 observations);
- `evidence_930202` OK (`service_resource_export`, 2 observations).

## Inputs (all fictional)
| case | person (user) | request email | text (translation) | records |
|---|---|---|---|---|
| 93011 | Inés Valcárcel `user_930110` | `ines.v@example.net`, her **old** email (`audit_930201`/`930202`, 2026-03-01) | es: "Please delete my account and all my personal data. I used to use another email address; delete what you hold under it too." | account_9301101 200 (current email); audit_record_9301102 |
| 93012 | Joaquim Lontra | current | pt: "I **don't** want you to erase my account or my data. I only ask that you stop sending me promotional emails." | account_9301201 200; search_9301202 hit |
| 93013 | Sayo Kurobane | current | ja: "Please check whether my account and personal data have been completely deleted. Could you tell me the result?" | account_9301301 404; audit_record_9301302 |
| 93014 | Wendelin Abernoth | current | de: "Please do **not** delete my account. I only want a copy of my stored data." | account_9301401 200; support_9301402 |
| 93015 | Maëlys Tournemire | current | fr: "Delete my account and all my personal data, please. Keep **no** copy, not even in backups." | account_9301501 404 (kv log); backup_9301502 `restore_allowed: true` at 11:20 and audit_record_9301503 (export JSON) |
| 93016 | Anvika Tellore | current | hi: "Please do **not** delete my account. I only want my postal address corrected." | account_9301601 200 |

- `evidence_930201`: kv log, captured 11:30.
- `evidence_930202`: service_resource_export JSON, captured 11:40.

## Expected rows
### case_93011: INCOMPLETE, 4 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | account_service | account_9301101 | PRESENT | evidence_930201 | rule_01; R15-R9 (DEV account 3/3); 200 with rows=1, linked by the current email (S1) |
| 2 | REMEDIATION | DELETE_RECORD | account_service | account_9301101 | ABSENT | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9301101 | ABSENT | "" | CD-F26 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9301102 | PRESENT | "" | rule_12; R15-R10 |

- **Identity:** the request email is in `user_audit_log` only. It resolves to `user_930110` (R15-R1; DEV case_30), and the evidence is keyed by her current email and `user_id` (T59).

### case_93013: COMPLETE, 2 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9301301 | ABSENT | evidence_930201 | S1; R15-R7 |
| 2 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9301302 | PRESENT | evidence_930201 | rule_12; R15-R10 |

- **Intent:** a request to check a deletion is a deletion request (CD-A12, settled on DEV for English; T63). The Japanese reading is SPEC-ONLY.

### case_93015: INCOMPLETE, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_RESTORE_RISK | backup_service | backup_9301502 | ACTIVE | evidence_930202 | rule_14; R15-R9 "restorable backup → BLOCK" (DEV 2/2); PS:27 |
| 2 | REMEDIATION | BLOCK_RESTORE | backup_service | backup_9301502 | BLOCKED | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9301501 | ABSENT | "" | S1; R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9301503 | PRESENT | "" | rule_12; R15-R10 |
| 5 | VERIFICATION | VERIFY_RESTORE_BLOCKED | backup_service | backup_9301502 | BLOCKED | "" | CD-F26; CD inv 15 (no VERIFY_RECORD_PRESENT for a backup) |

- **Citation:** the latest linked file at or before audit is `evidence_930202` (11:40), and it holds the backup (R15-R14; T66 rule 1).

### case_93012, case_93014, case_93016: `NOT_APPLICABLE`, `[]`
- Each request explicitly refuses deletion and asks for something else: a marketing opt-out (pt), access (de) or a correction (hi). Basis: AG:296, PS:19, PS:91, R15-P1. SPEC-ONLY.

## What a failure looks like
- 93011 sent to an unresolved-identity row because only current emails are searched, or read as NA.
- 93015 read as NA because it contains a negation.
- 93012, 93014 or 93016 read as deletion: their live accounts get `REPORT_REMAINING_RECORD` → `DELETE_RECORD`.

## Not settled by the rules
- None for the rows above, apart from the general SPEC-ONLY status of NA (no DEV example).
