# G2 gold forensics: how DEV gold follows from the inputs

- Gate G2, `orch-gold-forensics` (xhigh). `directed_by` 2026-10-25T01:29:52+05:30. Written 25 Oct, about 01:45–02:05 IST. It is a report only; the developer makes the decisions.
- **Holdout lock.** Gold is read only through `../research/prototype/devgold.py`, which drops holdout rows before `steps_json` is parsed. `notes/forensics/common.py:load_cases` also drops the holdout request rows and asserts there are 22 DEV and 518 test rows. Every count below covers DEV (22) plus test (518) and **no holdout row, inputs included**. One raw `grep` in §1 printed `sample_output.csv` lines; they were DEV rows 01, 02, 07 and 08 only. After that, the raw-byte search (`q5_q6.py`) skips `sample_output.csv`.
- **Labels.** SEEN = computed here, with the run named. INFERRED = reasoned from SEEN facts. UNKNOWN = the data cannot settle it.
- **Runs.** Scripts are in `notes/forensics/`. Every one runs with `python3 -I notes/forensics/<script>.py` from the repo root and writes to `runs/g2-0137/`. Run ID = `g2-<script>-0137`. The prototype is imported read-only; its `out/` folder and its `__pycache__` were not touched (their mtimes are still 24 Oct 23:50).
- No model calls, no network, no git writes. SQL goes only through the prototype's in-memory `sqlite3` loader (authorizer denies ATTACH and `load_extension`).

## Summary (10 lines)
1. **Report 15 and verify 14_15 reproduce exactly** (SEEN, `g2-q2_reconcile-0137`): DEV 22/22 status, 20/22 exact, 132/134 steps, 908/938 fields, 74/76 resources. All 11 verify figures I re-measured match, including 43, 20/43, 28/57, 23, 70, ±1 s→33 and 234/236.
2. **T4 as written finds no account in 4 DEV cases** (01, 02, 07, 08) and 10 deletion-authorized test cases (the showcase series). The DEV four are all one pattern: the delete row sits 0–5 min from `reported_at`, not 44–75 min before it.
3. **The "hand-built" label holds on input features alone:** non-round timestamps, plus a delete row within ±10 min whose wording is not "submitted primary profile". Exactly 5 DEV cases (01, 02, 05, 07, 08) and **0 of 518 test cases** have it.
4. **T4 order on DEV:** identifier link 11/11 correct, timed rule 7/7, then nothing left for stages 3–5. Those stages are exercised only by ablations: D17 4/4 correct, the D18 pick 1/2.
5. **T4 order on test (508 deletion-authorized):** S1 236, S2 157, S3 2, S4 D17 64 (+12 by a second one-to-one pass), S5 flagged **27**, none 10. Verify's "about 43" was the prototype's order.
6. **New defect class:** the S5 pick as specified (closest to −60 min, chosen per case) gives **the same account to both cases of every tie**: 27 cases share 13 accounts. S5 has to be one-to-one aware.
7. **D17 limits cost 0 DEV analytics** (4/4 kept, 0 false positives). Exclusivity cuts test claims 137→85, and the guessed-anchor ban 137→125. ±1 s matters: widening adds the DEV false positive in case_19; narrowing loses 4/4.
8. **UNEXPLAINED:** 2 DEV steps (`audit_record_6645`, `audit_record_5569`), in no input; 3 hypotheses tested. Under T4 as written, the 4 hand-built accounts are also unexplained; a ±10-min rule explains them (case_08 only if the result-mismatch fallback is allowed).
9. **T9 on DEV:** "compliant records in INCOMPLETE get verification" is supported only for account and audit (12+12 steps). Rule_05's condition is not observable in 3 of 4 REDACT cases. Tombstone-PII and legal-hold have no DEV evidence either way.
10. **No input signal I tested separates the 27 true ties.** Checked: request digits, candidate evidence, region overlap, second offsets, and mod-60 phase (which is not stable on identifier-linked jobs).

---

## Q1. Cases where the timed account rule finds no candidate

### Definitions (applied to every row; no case ID, file or row position is a signal)
- **Account delete row:** a `system_activity` row with `event_type=DELETE_RECORD` and `target_system=account_service` (539 rows).
- **Offset:** `event_time − reported_at`, in minutes.
- **S1 identifier link:** an `account_service` or `profile_service` unit linked to the request's user, through a current or historical identifier, with line time in [`requested_at`, `audit_at`].
- **Timed rule (T4 step 2):** offset in [−75, −44], inclusive, and `reported_result` = map(`reported_status`) (COMPLETE→SUCCESS, PARTIALLY_COMPLETE→PARTIAL, NOT_STARTED→FAILED). Accounts identifier-linked to a *different* user are excluded (owner filter; the variant without it is in Q3).
- **No candidate:** no S1 account, and the timed set is empty before one-to-one. The one-to-one pass never emptied a non-empty set in any variant (SEEN, `g2-acct_stages-0137`, base and all 10 variants).
- **Reasons**, checked in this order:
  - **(d)** no row in the window, but an account delete row within ±10 min of `reported_at`;
  - **(b)** the user's own account (identifier-linked at any time) has delete rows, all after `audit_at`;
  - **(f)** the user's own account delete row lies before `requested_at` (a separate earlier request);
  - **(a)** no account delete row linked to the user, and none in the window;
  - **(c)** rows in the window, but none matches the result;
  - **(e)** result-matched rows exist, but all belong to another user.

### Counts (SEEN, `g2-acct_stages-0137` base + `g2-q1_q3_handbuilt-0137`)
| Group | DEV | Test, deletion-authorized | Test, NA (output `[]` anyway) | Cases |
|---|---:|---:|---:|---|
| (d) delete row within ±10 min only | **4** | 0 | 0 | DEV 01 (−0.28 min, SUCCESS), 02 (+5.05, PARTIAL), 07 (−1.35, SUCCESS), 08 (+4.97, **SUCCESS vs PARTIALLY_COMPLETE**) |
| (b) own account's delete rows only after `audit_at` | 0 | **5** | 0 | 33, 39, 50, 52, 55 |
| (f) own account's delete row before `requested_at` | 0 | **1** | 0 | 35 (`account_8491` deleted 08-25; this request is 08-30) |
| (a) no account delete row anywhere for the user, none in the window | 0 | **4** | 4 | 45, 53, 61, 63; NA 534, 537, 540, 542 |
| (c) result mismatch | 0 | 0 | 1 | NA 538 |
| (e) all result-matched rows owned by another user | 0 | 0 | 2 | NA 535, 541 |
| **Total** | **4** | **10** | 7 | |

My first-pass labels in the JSON put case_35 under "a0" and the (a) cases under "a0_no_row_within_3h". The table above reclassifies case_35 as (f), from the row dates listed in the detail below (SEEN). The 3 remaining NA cases (533, 536, 539) do get a candidate, which is irrelevant because NA outputs `[]`.

**Split by "an identifier link already resolves it"** (SEEN, `id_linked_accounts(form=...)`):
| Group | Resolved by a link with no time filter | Resolved by a link ≤ `audit_at` | Left with no account in any text input |
|---|---:|---:|---:|
| DEV (d), 4 cases | 0 | 0 | 4: only the activity row names the account |
| Test (b)+(f), 6 cases | **6**. The only link is a **post-audit** line in `evidence_01` (`profile_lookup_completed`, 2026-09-15). | 0 | 0 |
| Test (a), 4 cases | 0 | 0 | **4**. 45, 53, 61 and 63 have no `account_*` resource linked to the user anywhere. The prototype's hand table of the 11 PNGs (`vision_facts.py`) lists only one account (`account_5762`, case_34). |

### DEV case_08: every place `account_008` appears (SEEN, raw `grep -w` over `dataset/`)
| File | Row | Timestamp | Content |
|---|---|---|---|
| `system_activity.csv` | line 3555, `activity_3554` | 2026-08-31T13:48:58Z, +4.97 min from `reported_at` 13:44:00 | `DELETE_RECORD deletion_worker→account_service account_008 SUCCESS` "Deletion worker reported the requested operation as completed. Target resource: account_008." |
| Any evidence file (text, SQL, JSON, log, PDF, PNG) | — | — | **not present** |
| `user_identities.csv`, `user_audit_log.csv` | — | — | not present |

- Request: `reported_status=PARTIALLY_COMPLETE` (wants PARTIAL), `audit_at` 2026-09-14T16:10Z.
- Gold account step (DEV): step 3 is `VERIFICATION account_service account_008 VERIFY_RECORD_ABSENT ABSENT ""`. The case is INCOMPLETE, so verification carries `""`; the finding `export_001` cites `evidence_59`.
- The account step therefore rests only on the activity row. Its result (SUCCESS) **does not** match the reported status. It is the only account delete row within ±200 min of `reported_at` (SEEN, `explore1`, scratch).

### Options (DEV counts from `g2-q1_q3_handbuilt-0137` and `g2-q1_effects-0137`)
Baseline, T4 as written: DEV 01/02/07/08 get no account. Case_01 and case_02 then have **0 steps**, which is a validator failure ("deletion case with no steps") and fails closed. Case_07 and case_08 lose 1 of 4 steps each (fields 19/28 each); status is unchanged in all four. T6 ("never omit the account step") cannot be met for these cases.

| Option | Rule | DEV account right / wrong / none | DEV effect vs T4 baseline | Test cases touched | Reopens T4 "not shipped"? |
|---|---|---|---|---|---|
| **A** | If S1 and S2 are empty: an unowned account delete row within ±10 min of `reported_at` **with** result match | 3 / 0 / 1 (case_08 none) | +3 steps (01, 02, 07 exact again). Status unchanged. case_08 stays at 3/4 steps, 19/28 fields. | **0** (no test case has a ±10-min row and an empty S2) | No |
| **B** | A, then, inside the ±10-min window only, any result if none matches | 4 / 0 / 0 | +4 steps; all 4 cases exact | **0** | **Yes**: "the fallback to a delete row whose result doesn't match". Its only basis is case_08. |
| **C** | For the post-audit showcase pattern: take the user's own account from any identifier link, *including lines after `audit_at`*, used for **identity only** (state still from pre-audit evidence, so default ABSENT under R8) | 0 / 0 / 0 (no DEV case has the pattern) | none | **6** (33, 35, 39, 50, 52, 55); 4 remain with no account | Not on the T4 list, but it uses post-audit lines, which R5/A6 exclude for state. **No DEV support at all.** case_33 and case_52 are both user_18 and would both get `account_2373`; one-to-one would have to allow the same account for the same user. |

- The 4 test cases with no account ID anywhere (45, 53, 61, 63) cannot satisfy T6 without composing an ID, which `../CLAUDE.md` §3 forbids. Under any option they need an explicit flagged state (INFERRED).
- A and B together touch **0** test rows (SEEN). Their value is DEV fidelity. They would also matter for any hand-built holdout case, which I did not and may not measure.

---

## Q2. Reconciling report 15 with `verify/14_15` (DEV re-measured, test inputs only)
Run `g2-q2_reconcile-0137` (`runs/g2-0137/q2.json`) and `g2-q2_extra-0137`. Test figures use the prototype with its hand vision table, as report 15 §6 did.

| Claim | Source | Re-measured | Reproduced |
|---|---|---|---|
| DEV status 22/22, exact 20/22, steps 132/134 (132 predicted), fields 908/938, resources 74/76, misses case_18 and 20 | R15 §1, V A1 | 22, 20, 132/132/134, 908/938, 74/74/76, inexact [18, 20] | **yes** |
| Without the signature: 16/22, 128/134, 864/938, 70/76 | R15 §1 | 16; 128; 864; 70. Inexact: 03, 18, 20, 21, 26, 27. | **yes** |
| `audit_record_6645` and `5569` in no input | V A4 | No byte match in any file, decompressed PDF stream or PDF text layer; `sample_output.csv` skipped (`g2-q5_q6-0137`) | **yes** |
| ±1 s band: one DEV case lost, 33 test cases changed | V #6 | Widened: DEV 19/22 (case_19 lost), **33** test cases changed. Narrowed: DEV 16/22, 122 changed. | **yes** |
| 43 guess cases | R15 §6.3, V A6 | 43 | **yes** |
| 20 accounts given to 43 test cases | V #1 | 20 / 43 | **yes** |
| 28 analytics with 57 claims; 136 cases / 111 resources; 23 anchored on a guess | V #2, B4 | 28 / 57; 136 / 111; 23 | **yes** |
| `--no-signature` still breaks account ties with the signature | V #3 | 70 test cases still use `+signature` with `use_signature=False` | **yes** |
| 10 test cases without an account step; case_34 cites two files | V #7 | 10 (33, 35, 39, 45, 50, 52, 53, 55, 61, 63); `[case_34]` | **yes** |
| B1: 234/236 identifier-linked offsets in −74.9…−44.0 min; outliers 34, 46 | V B1 | 234/236, range −74.90…−44.02; outliers case_34 (−41232 min), case_46 (+272937 min) | **yes** |
| B2: 262/496 generated without an identifier-linked account | V B2 | 262/496 ("generated" = authorized minus the 12 showcase cases) | **yes** |
| B3: 81 generated cases without an audit record (+2 showcase = 83) | V B3 | 81 under each of 3 definitions (window, ≤ audit, any); showcase 2 with "any" | **yes** |
| B5: 103 ties after window, result and one-to-one; about 43 truly unresolved | V B5 | **103** reproduced (S4 64 + S4b 12 + S5 27, `g2-acct_stages-0137`). Under T4's order only **27** remain; 43 is the prototype's order. | 103 yes; 43 **order-dependent** |
| Account methods on test: identifier 236, window+result 143, +signature 68, +in-evidence 8, guesses 43 | R15 §6.3 | 143 / 68+2 / 8+3 / guess 38+3+2 | **yes** |
| B4: 121 unlinked analytics records over 240 cases | V B4 | not re-measured | NOT DONE |

Verify findings #4 (tie policy discards signal), #5 (analytics reachability) and #8 (hand tables) are judgments, not counts. The Q3 and Q4 numbers below bear on #4 and #5.

---

## Q3. T4 account order on DEV, stage by stage
Run `g2-acct_stages-0137` (variants via flags) and summary `g2-q3_summary-0137`. DEV, resolved/correct:

| Stage | Base (T4) | No owner filter | No result match (stress test) | Window −74..−45 | Window −76..+9 (prototype) |
|---|---|---|---|---|---|
| S1 identifier link | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 |
| S2 timed, unique | 7/7 | 5/5 | 1/1 | 6/6 | 10/10 |
| S3 one-to-one | 0 | 1/1 | 0 | 0 | 0 |
| S4 D17 (+ S4b one-to-one again) | 0 | 1/1 | 3/3 + 1/1 | 0 | 0 |
| S5 flagged pick | 0 | 0 | **2/1** | 0 | 0 |
| No candidate | 4 | 4 | 4 | 5 (case_31's account at −74.03 is outside) | 1 (case_08) |

- **Edges (SEEN):** −76..−44 and −75..−43 give the same DEV and test results as −75..−44. Tightening one minute at each end (−74..−45) loses DEV case_31 (−74.03 min) and adds 9 test no-candidate cases. The earliest DEV gold offset is −74.03 (case_31) and the latest is −45.08 (case_20).
- **Scope:** one-to-one over DEV+test, or within each set, gives identical results (variant `split`).
- **On DEV the base T4 order uses only S1 and S2.** Stages 3–5 are untested by gold except under ablation. There D17 is 4/4 and the flagged pick 1/2 (INFERRED: a coin flip, as expected).

Test, 508 deletion-authorized cases (SEEN):
| Variant | S1 | S2 | S3 | S4 | S4b | S5 flagged | None |
|---|---:|---:|---:|---:|---:|---:|---:|
| Base T4 | 236 | 157 | 2 | 64 | 12 | **27** (tie sizes 2:25, 3:2) | 10 |
| D17 band +1 s | 236 | 157 | 2 | 47 | 8 | 48 | 10 |
| D17 band −1 s | 236 | 157 | 2 | 15 | 8 | 80 | 10 |
| No owner filter | 236 | 132 | 22 | 67 | 13 | 28 | 10 |

**Defect (SEEN):** all 27 S5 cases pick an account that another S5 case also picks (13 accounts). The closest-to-−60 order is case-independent, so both members of a tie get the same account. A one-to-one-aware S5 would give distinct picks with the same expected hits and no duplicated resource (INFERRED).

**The "hand-built" label (report 14 §C6: DEV 01, 02, 05, 07, 08).** Report 14 states no basis. The basis I find is in the inputs (SEEN, `g2-q1_q3_handbuilt-0137`, cross-tab over authorized cases):
| Feature combination: (round timestamps, delete row within ±10 min, that row's wording, 3-digit zero-padded account ID) | DEV | Test |
|---|---:|---:|
| (not round, yes, "reported the requested operation…", yes) | **5** (01, 02, 05, 07, 08) | **0** |
| (round, no, —, no) | 15 | 368 |
| (round, yes, "submitted primary profile", no or yes) | 2 (18, 20, a neighbouring batch) | 139 |
| (not round, no, —, no) | 0 | 1 (case_63, 22:20) |

- The label **holds**: the four features coincide on exactly these 5 DEV cases and on no test case.
- Hand-built cases measured separately: S1 1/1 (case_05); no candidate 4/4 (01, 02, 07, 08). Generated cases: S1 10/10, S2 7/7.
- **The hand-built pattern does not occur in the 518 test inputs.** Any rule written for it changes DEV only.

---

## Q4. D17 limits (T5), measured on the T4 picks
Run `g2-q4_d17-0137`, with `--band-pad=±1`. It is the prototype's attachment rule, re-anchored on each case's T4 account. DEV gold has 9 analytics pairs: 5 identifier-linked and 4 identifier-free.

| Form | DEV true / false positive (of 4 identifier-free) | Test pairs / cases / records |
|---|---|---|
| All claims | 4 / 0 | 137 / 133 / 111 |
| L1 single-case exclusivity (drop records claimed by more than one case) | 4 / 0 | **85** / 85 / 85 |
| L2 never anchored on a guessed account (drop claims anchored on an S5 pick) | 4 / 0 | 125 / 121 / 105 |
| L1 + L2 | 4 / 0 | 85 (every guess-anchored claim is also multi-claimed) |
| Band +1 s, all claims | 4 / **1** (case_19 `analytics_3264`) | 163 / 158 / 113; 51 records multi-claimed |
| Band +1 s with L1 | 3 / 0 | 62 |
| Band −1 s | **0** / 0 | 46 |

- **Multi-claimed records:** 26 records carry 52 claims, and no DEV case is involved. 12 test cases anchor on an S5 pick.
- **Both limits cost 0 on DEV.** Precision is a knife edge in both directions. The precision fixture should pin bands 9–11 / 20–22 on second-truncated offsets (SEEN).
- **The fingerprint is stable only mod 30 s, not mod 60 s.** On identifier-linked jobs, policy rows fall at 9–11 *and* 39–41, after-rows at 20–22 *and* 50–52 (`g2-q7_mod60-0137`). A mod-60 refinement has no input basis.

---

## Q5. UNEXPLAINED list (every DEV gold value no candidate rule derives from inputs)
| # | DEV value | Status | Hypotheses tested (≥2 forms each) | Closest hypothesis |
|---|---|---|---|---|
| U1 | case_18, `VERIFICATION security_service audit_record_6645 VERIFY_RECORD_PRESENT PRESENT ""` | **UNEXPLAINED** (SEEN) | (H1) under another identifier of user_50: no security unit for any identifier. (H2) number taken from a resource of this case or of a co-batched case (same `reported_at`): no match, while `account_6645` belongs to user_467 (Feb). (H3) an unlinked or renamed audit record in the batch file `evidence_94`: its 3 audit records belong to user_42, 43 and 49. (H4) in a post-audit file: no bytes anywhere. | The generator's truth lists an audit record its renderer never wrote (INFERRED). |
| U2 | case_20, `… audit_record_5569 …` | **UNEXPLAINED** (SEEN) | H1 and H3 as above. **H2 fits:** `support_5569` is case_18's support ticket in the same batch. But the base rate is 0/15 among DEV audit records that are in the inputs, and nothing says which peer resource to borrow (`g2-q5_suffix-0137`). H4: no. | Same as U1. The suffix coincidence is 1 hit in 17 and is not a rule. |
| U3 | Hand-built accounts 001, 002, 007 (VERIFY_RECORD_ABSENT) | Unexplained **under T4 as written**; explained by the ±10-min rule (Option A, 3/3) | Window −75..−44 (no); −76..+9 (yes); ±10 (yes); identifier link (no: the account is in no evidence file) | Option A |
| U4 | Hand-built `account_008` | Unexplained under T4 **and** Option A; explained only with the result-mismatch fallback (Option B) | Result-matched ±10 (no row); any result ±10 (yes, the only row) | Option B; it rests on 1 case |
| U5 | Citation `evidence_54` for case_01 and 02 (`account_001`/`002`, which the file does not name) | **WEAK**: explained by R14's fallback "latest pre-audit account_service file"; three alternative forms give the same file on DEV | — | R14 fallback (form undetermined) |
| U6 | Citation `evidence_51` for case_31 `account_4857` (the file does not name it) | Explained by R14's "one file per case" (F holds the user's other units) | — | R14 |
| U7 | 4 identifier-free analytics (03, 21, 26, 27) | Explained by D17 only, **no domain basis** (flagged) | Signature on/off; bands ±1 s | Generator artifact (verify A5) |

No other DEV value differs from a rule-derived value: the prototype has 0 extra steps and 82/82 empty evidence fields, and the remaining 132 steps match (Q2).

### Rules table (data first; spec secondary)
| Rule | Basis | DEV explained | DEV contradicted |
|---|---|---|---|
| S1 identifier link (current + historical, window [`requested_at`, `audit_at`]) | Data: 11/11 accounts. No lower bound gives 19/22 (case_17 gains `account_6523`), `g2-q5_q6-0137` | 11 accounts | 0 |
| S2 timed rule −75..−44 + result match + owner filter | Data: 234/236 test identifier-linked offsets; DEV 7/7 | 7 | 0 (4 hand-built not reached) |
| ±10-min hand-built account rule (Option A/B) | Data: 4/4 DEV hand-built, 0 test. **DOMAIN LOGIC ONLY**: "the worker's row for this report". | 3 (A) / 4 (B) | 0 |
| D17 account tie-break | Data: 4/4 DEV under ablation; no domain basis | 0 in base order | 0 |
| D17 analytics attach (with L1 + L2) | Data: 4/4 DEV, 0 FP; **no domain basis** | 4 | 0 |
| Policy mapping, state, citation, order (report 15 R1–R17) | Re-run: 22/22 status, 132/134 steps | 22 cases | 0 |

**Rules with neither a data nor a domain basis:** none shipped. D17 has a data basis but no domain basis (flagged, as T5 records).

---

## Q6. T9 provisional defaults vs DEV (`g2-q5_q6-0137`)
| T9 default | Fixture (`../research/16`) | DEV for | DEV against | Verdict |
|---|---|---|---|---|
| Follow `deletion_rules.csv` literally | all | 29/29 findings and 47 compliant verifications match rule actions (Q2 re-run, 0 extra steps) | **rule_14** says RETAIN, but gold does BLOCK_RESTORE → VERIFY_RESTORE_BLOCKED (2 DEV backups). **rule_05**'s condition ("shared … context that must be retained") is visible in only 1 of 4 REDACT cases (case_30). For 11, 18 and 19 the observation has no message text (handover TXT, PII-scan log, ticket-read log), yet gold still REDACTs. | **Partly against**: actions are mapped, conditions are not gated. Keep "support message → REDACT" (4/4); don't gate on the rule_05 condition. |
| Tombstone with PII → finding (REDACT) | F8 | none (the only DEV tombstone is clean: case_31 `tombstone_440` → VERIFY_RECORD_REDACTED) | none. `tombstone_17` (case_17) is linked only before `requested_at` via `activity_4011` and is absent from gold, which is consistent with the window rule; it is not about PII. | **No DEV evidence**; stays PROVISIONAL |
| User's email or phone in support free text → redact | F9 | case_30 `support_6477`: own identifier in the text → REPORT_EXPOSED_PII/REDACT | none | **Weak for (1 case, confounded):** that record also has `requester_email`. PROVISIONAL. |
| Legal hold never deleted (RETAIN → VERIFY_RECORD_PRESENT) | F10 | none: no legal_hold resource is linked to any DEV user (10 legal rows; owners are test users or nobody) | none | **No DEV evidence**; PROVISIONAL |
| Compliant records in INCOMPLETE get verification steps | — | account VERIFY_RECORD_ABSENT 12 and audit VERIFY_RECORD_PRESENT 12 in INCOMPLETE gold | none. No DEV INCOMPLETE case has a compliant flow, backup, analytics or support record in its window. | **Supported for account and audit only**; other types PROVISIONAL |

**G1 ambiguities DEV can settle:**
| # | DEV settles? | How |
|---|---|---|
| A2 | Partly | Account and audit settled (12+12). Other types are not present in DEV. |
| A5 | Yes, (a) for account/search | case_16, case_24 order |
| A6 | Yes, (a) at evidence level | case_27 post-audit recreation ignored |
| A7 | Yes, leaning (a) | Lower bound `requested_at` gives 20/22; no lower bound gives 19/22 (case_17 gains `account_6523`) |
| A10 | Yes for DEV | 52/52 citations are file IDs |
| A12 | Yes, (a) | case_21, 26, 27 "verify/check/audit" texts are deletion cases |
| A14 | Yes for DEV | One file per case 22/22; 3 cited files don't name the resource (U5, U6) |
| A1, A3, A4, A8, A9, A11, A13 | No | Padded IDs; no same-key ties; no `object_*`, NA or legal-hold gold; A8/A11 are packaging |

---

## Q7. Signals for the true ties (S5, 27 test cases under T4; `g2-q7_ties-0137`)
| Signal | Count of the 27 |
|---|---:|
| D17 had no own rows to test | 15 |
| D17 fit every candidate (candidates 30 s apart: the mod-30 phase cannot split them) | 12 |
| Request text carries 3+ digits (a phone fragment) | 0 |
| No candidate has any evidence observation | 23 (18 two-way, 5 three-way) |
| Candidates have evidence, with a unique region overlap with the user's own units | 0 |
| Candidates share a second offset | 0 |
| mod-60 phase (Q4): not stable on identifier-linked jobs | no basis |

No tested signal separates them, and DEV has 0 such ties, so nothing here has DEV support. NOT TESTED: system name and phone-region prefix against candidate rows. Candidates have no identifier-bearing evidence in 23/27, so those signals would mostly be empty too (INFERRED).

---

## Trap table (counts re-measured here unless marked)
| Trap | Count | Source |
|---|---:|---|
| Post-audit-only account link (showcase) | test 6 | Q1 |
| Account named only in an activity row (no evidence) | DEV 4 hand-built + 9 default-ABSENT accounts (report 15 R8) | Q1 / R15, not re-measured |
| Truth-only resources | DEV 2 steps; test 81 generated + 2 showcase cases with no audit record anywhere | Q2 B3 |
| Result-mismatch account (reported status ≠ row result) | DEV 1 (case_08); test 0 among no-candidate cases | Q1 |
| Same account claimed by more than one case (S5 independent pick) | test 13 accounts / 27 cases | Q3 |
| D17 multi-claimed analytics | test 26 records / 52 claims | Q4 |
| Historical email, decoys, replica drift, tombstones, negation traps | see report 15 §6.4 | **not re-measured** |

---

## NOT DONE / open
- B4 (121 unlinked analytics records over 240 cases) not re-measured.
- Q7: system and phone-region signals not tested.
- Report 15 §6.4 trap counts (historical email 100, decoys 22, replica 13, tombstones 11, negation 10) not re-measured.
- A one-to-one-aware S5 is not implemented or measured (proposed only).
- Option C's state rule (ABSENT vs a finding for an account deleted after `audit_at`) is UNKNOWN: there is no DEV analogue.
- `notes/forensics/__pycache__/` was written by the first run, before `dont_write_bytecode` was set. It is gitignored and was left in place.
