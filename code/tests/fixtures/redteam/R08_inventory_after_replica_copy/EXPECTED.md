# R08: a replica copy, then a *later* complete inventory that omits it (status settled by T54; citation UNSETTLED)

**Attacks:** R07 in reverse order.
- The read replica (`evidence_930801`, 11:10) holds `account_9307101` in `customer_data_read_replica` only.
- A complete inventory (`evidence_930802`, **11:45**, `snapshot_scope` includes `account_service`) omits it and holds `search_9307102`.

Under a naive "latest observation wins" (R15-R6), the account is ABSENT at 11:45. Under **T54** ("a SQL inventory doesn't rule out replica copies"), the inventory's omission says nothing about the replica copy, so the copy seen at 11:10 is still the latest observation *of that copy*.

**Failure it catches:**
- the declared-scope omission applied to replica copies, which gives ABSENT and loses a live profile;
- a citation rule that can't name two files in one case.

**Provisional:** yes, for the citation. The status and steps follow T54, a developer ruling adopted with DEV 0 changed (H3 `sql_strict`). The citation is **UNSETTLED** (below).
**Custom eval case:** no.
**Parse:**
- `evidence_930801` OK (`sql_replica_topology`, 3);
- `evidence_930802` OK (`sql_inventory`, 2 observations, 7 declared scopes).

## Inputs (all fictional)
- `case_93071`: Ottilie Grisewood `user_930710`, `ottilie.grisewood@example.com`, `COMPLETE`.
- `evidence_930801` (read replica, captured 11:10):
  - primary table: audit_record_9307103;
  - replica table: audit_record_9307103 and account_9307101 (ACTIVE, name, email, phone, `user_930710`).
- `evidence_930802` (inventory, captured 11:45):
  - scopes for seven systems, `account_service` included;
  - `customer_search_documents` search_9307102 (her email, 11:31);
  - `security_audit_records` audit_record_9307103;
  - no `customer_profiles` row.

## Expected row (`expected_output.csv`): `INCOMPLETE`, 7 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | account_service | account_9307101 | PRESENT | **evidence_930801** | rule_01; R15-R17; T54. Citation by T66 rule 1: the only file that contains it |
| 2 | FINDING | REPORT_REMAINING_RECORD | search_service | search_9307102 | PRESENT | **evidence_930802** | rule_03; R15-R9; R15-R14 latest linked file |
| 3 | REMEDIATION | DELETE_RECORD | account_service | account_9307101 | ABSENT | "" | R15-R9 |
| 4 | REMEDIATION | DELETE_RECORD | search_service | search_9307102 | ABSENT | "" | R15-R9 |
| 5 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_9307101 | ABSENT | "" | CD-F26 |
| 6 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_9307102 | ABSENT | "" | CD-F26 |
| 7 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_9307103 | PRESENT | "" | rule_12; R15-R10 |

- **Order:** CD-F11/F12. The two REMAINING findings sort by `system_id` (`account_service` < `search_service`), as do the two deletes and the two ABSENT checks.

## Not settled by the rules: the account finding's citation
| Reading | Account finding cites | Rule it follows | Rule it breaks |
|---|---|---|---|
| **(a), in `expected_output.csv`** | evidence_930801 | T66 rule 1 (hard): the cited file must contain the resource | CD inv 11 / R15-R14 "one file per case" (soft, empirical; 22/22 DEV) |
| (b) | evidence_930802 | R15-R14: the case's one file is the latest linked pre-audit file | T66 rule 1 (evidence_930802 does not contain account_9307101; it declares `account_service` complete *without* it, which is the opposite of containment) |

- T66 is a developer ruling, and CD inv 11 is marked soft, so (a) is the leaning.
- No DEV case has two findings whose only containing files differ. If the hidden key follows R15-R14 strictly, step 1's citation is wrong under (a), and the rest of the row is unchanged.

**Status is not in doubt under either reading:** INCOMPLETE, with the account and the search entry both remaining.

## What a failure looks like
- R15-R6 applied across the inventory omission → account ABSENT → 5 steps (search only). A live replica profile is unreported.
- account cited to `evidence_930802` together with the hard check → validator failure → FAILED_CLOSED. A row-level loss that comes from the citation rule, not the facts.
