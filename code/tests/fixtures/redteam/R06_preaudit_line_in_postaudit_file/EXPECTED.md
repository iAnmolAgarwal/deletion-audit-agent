# R06: a pre-audit record that only a post-audit file holds (UNSETTLED citation)

**Attacks:** the gap between three rules:
- **R15-R4** (DEV-confirmed, 5 gold pairs): "Pre-audit lines inside a file *captured* after `audit_at` count for discovery and state, never for citation." Ignoring them costs DEV 3 steps (case_09, 24, 30).
- **T66 rule 1 / T77 rule 3** (developer rulings): a FINDING must cite a file, and the cited file must contain the resource.
- **CD-F21** (DEV-confirmed): never cite a file captured after `audit_at`.

`search_9305102` appears only in `evidence_930602`, a bundle captured at **13:00**, one hour after audit. Its snapshot is dated **11:59:59**, before audit, and holds the person's email. Under R15-R4 the record is discovered and PRESENT at audit, so it is a finding. But no pre-audit file contains it, so no citation satisfies both T66 and CD-F21.

In DEV, R15-R4 only ever supplied *verification* steps of INCOMPLETE rows (empty citation) or state. No DEV finding is discovered this way, so DEV never had to choose. The test data has the shape: "user-linked units in post-audit files with a pre-audit line inside", test 179 (`notes/gold_forensics.md` trap table).

**Failure it catches:** either way of being wrong:
- a COMPLETE row while the evidence shows a pre-audit ghost record;
- a FINDING that cites the post-audit file.

**Provisional:** yes. **UNSETTLED citation; status leaning INCOMPLETE.**
**Custom eval case:** no (its row is unsettled).
**Parse:**
- `evidence_930601` OK (`kv_log`, 4);
- `evidence_930602` OK (`snapshot_bundle`, 1 observation with `record_time` 11:59:59, 1 declared scope).

## Inputs (all fictional)
- `case_93051`: Lorcan Bewley `user_930510`, `lorcan.bewley@example.net`, `COMPLETE`.
- `evidence_930601` (kv log, captured 11:20): account_9305101 404 at 10:10; audit_record_9305103 at 10:25.
- `evidence_930602` (snapshot bundle, captured **13:00**): one snapshot at **11:59:59**, `search_service/customer_search_documents` = search_9305102 (his name, email, `user_930510`).

## Expected row (`expected_output.csv`), reading (a): `INCOMPLETE`, 5 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | search_service | search_9305102 | PRESENT | **evidence_930601** | R15-R4 discovery and state; rule_03; R15-R9. Citation by R15-R14 (the case's one file = the latest *pre-audit* linked file). **Breaks T66 rule 1**: this file does not contain search_9305102 |
| 2 | REMEDIATION | DELETE_RECORD | search_service | search_9305102 | ABSENT | "" | R15-R9 |
| 3 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9305101 | ABSENT | "" | S1; R15-R7 |
| 4 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_9305102 | ABSENT | "" | CD-F26 |
| 5 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9305103 | PRESENT | "" | rule_12; R15-R10 |

## The readings
| Reading | Row | Rule it follows | Rule it breaks |
|---|---|---|---|
| **(a)** finding cites the case's one pre-audit file | the row above | R15-R4, R15-R14 (one file per case, 22/22 DEV; U5/U6 show DEV citing files that don't name the resource) | T66 rule 1 (hard check) |
| (b) finding with `evidence_id` "" | the row above with step 1 `""` | R15-R4; CD-F21 | T77 rule 3 ("every FINDING cites a file"); CD inv 9 |
| (c) the record is not discovered: COMPLETE, account ABSENT + audit PRESENT citing evidence_930601 | 2 steps | `notes/SYSTEM.md` "evidence available up to the audit time" read as capture time | R15-R4 (DEV 5 pairs); risks the error `notes/SYSTEM.md` ranks first |
| (d) FAILED_CLOSED (the validator rejects every valid citation) | INCOMPLETE, steps as the engine can validate | T71 Q5 | none, but it is not a correct answer, and freeze requires 0 FAILED_CLOSED (T60, T71) |

- **Leaning (a):** the generator's truth evidently holds such records (R15-R4), and DEV cites the case's file even where it does not name the resource (R15-R14 fallback, U5, U6).
- **Never acceptable:** citing `evidence_930602`, under any reading (CD-F21).
- `expected_assertions.json` lists the outcomes that are acceptable and the one that never is.

## What the developer should rule on
Whether T66 rule 1's hard check exempts a finding discovered through R15-R4, and if so what it cites. 179 test cases have this file shape, so the answer may change real rows.
