# F06: account deleted from the primary but still in one regional replica, plus an active sync connector

**Tests:**
- in the regional-replicas SQL layout (no DEV primary; 30 test primaries), the account row is **missing from `customer_data_primary`** and from the `ap_south` replica, but **still present in `customer_data_replica_eu_west`**;
- an enabled `continuous_sync` connector keyed by the person's email;
- three activity claims the evidence contradicts: the account delete `SUCCESS`, a replication `SYNC_RECORD` checkpoint, and `DISABLE_DATA_FLOW SUCCESS`.

**Provisional:** no. DEV confirms the replica-only account (case_05 failover, case_16 read replica), the connector (5/5) and the ignored SUCCESS claims. Only the two-replica layout is new.
**G8 custom eval case:** yes. It is a non-provisional case with every finding type except restore risk, in a layout DEV never uses as a primary.
**Parse:** `evidence_9601` OK (`sql_replica_topology`, 10 observations: three rows in each of the three tables, plus the eu_west account).

Rule keys as in F02.

## Inputs (all fictional)
- `case_90601`, `odile.brand@example.com`, `COMPLETE`; times as in F01.
- `evidence_9601` (regional replicas SQL, captured 11:40; every row's `updated_at` is the capture time, as in the dataset). All three tables (`customer_data_primary`, `customer_data_replica_ap_south`, `customer_data_replica_eu_west`) hold:
  - `search_900602` (customer_search_documents; the person's email and `user_900601`);
  - `data_flow_900603` (connector_configurations; `subject_selector` = the email; `enabled: true`; `mode: continuous_sync`);
  - `audit_record_900604` (security_audit_events; `user_900601`).

  `customer_data_replica_eu_west` also holds `account_900605` (customer_profiles, ACTIVE, with name, email and phone).
- Activity, all before audit:
  - `activity_90601`, 01:00: `DELETE_RECORD account_900605 SUCCESS`, 60 min before `reported_at`;
  - `activity_90602`, 01:20: `SYNC_RECORD account_service → account_replication_cluster account_900605 SUCCESS` ("final checkpoint");
  - `activity_90603`, 01:30: `DISABLE_DATA_FLOW data_flow_900603 SUCCESS`.

## Expected row: `INCOMPLETE`, 10 steps
| # | phase | operation | system_id | resource_id | state | evidence | basis |
|---|---|---|---|---|---|---|---|
| 1 | FINDING | REPORT_REMAINING_RECORD | account_service | account_900605 | PRESENT | evidence_9601 | rule_01; R15-R17: a replica-only profile is `account_service` with its own `resource_id` (DEV case_05, 16) |
| 2 | FINDING | REPORT_REMAINING_RECORD | search_service | search_900602 | PRESENT | evidence_9601 | rule_03; R15-R9 |
| 3 | FINDING | REPORT_ACTIVE_DATA_FLOW | integration_service | data_flow_900603 | ACTIVE | evidence_9601 | R15-R9 enabled connector (DEV 5/5); PS:27 |
| 4 | REMEDIATION | DISABLE_DATA_FLOW | integration_service | data_flow_900603 | DISABLED | "" | DISABLE first (CD-F24; table order) |
| 5 | REMEDIATION | DELETE_RECORD | account_service | account_900605 | ABSENT | "" | R15-R9 |
| 6 | REMEDIATION | DELETE_RECORD | search_service | search_900602 | ABSENT | "" | R15-R9 |
| 7 | VERIFICATION | VERIFY_RECORD_ABSENT | account_service | account_900605 | ABSENT | "" | CD-F26 |
| 8 | VERIFICATION | VERIFY_RECORD_ABSENT | search_service | search_900602 | ABSENT | "" | CD-F26 |
| 9 | VERIFICATION | VERIFY_RECORD_PRESENT | security_service | audit_record_900604 | PRESENT | "" | rule_12; R15-R10 |
| 10 | VERIFICATION | VERIFY_DATA_FLOW_DISABLED | integration_service | data_flow_900603 | DISABLED | "" | CD-F26 |

- **Claims ignored:**
  - the SUCCESS delete and the DISABLE claim are contradicted by evidence captured after them (11:40). Activity results are claims, and the latest observation wins (CD-F29; verify-12 R14: DEV case_16 and 24 have SUCCESS deletes still remaining; R15-R6);
  - the replication `SYNC_RECORD` is not a data flow (R15-R17: "replication SYNC rows never become ACTIVE_DATA_FLOW").
- **Order:** CD-F11/F12. The account and search deletes come in plain system order, not "downstream first" (A5 settled (a), DEV case_16 and 24).
- **One finding per resource,** even though each record appears in two or three tables (CD invariant 7).

## What a failure looks like
- Reading only `customer_data_primary`, or treating the primary's missing row as proof of absence, misses the account. A replica topology declares no `snapshot_scope`, and T54 says a SQL inventory does not rule out replica copies.
- Trusting `activity_90601` SUCCESS → account verified ABSENT, a false negative on a live profile.
- Trusting `activity_90603` → no ACTIVE_DATA_FLOW, and the connector can repopulate the data.
- The replica copy reported under `account_replication_cluster`, or as a data flow.

## Not settled by the rules
- None.
