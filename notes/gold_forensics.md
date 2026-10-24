# G2 gold forensics: how DEV gold follows from the inputs

- Gate G2, `orch-gold-forensics` (xhigh), two runs. It is a report only; the developer makes the decisions.
  - **First run** (`directed_by` 2026-10-25T01:29:52+05:30): launched about 01:31 IST (main's log entry at 01:32:51). Its scripts were written 01:35:03–01:43:34 and this report at 01:46:09 (file times from `TZ=Asia/Kolkata date -r <file>`). Its log entry is stamped 01:47:03. The earlier line "written about 01:45–02:05" was wrong.
  - **Follow-up run** (`directed_by` 2026-10-25T01:35:50+05:30): started 01:49:47 IST (`TZ=Asia/Kolkata date -Iseconds`). Its scripts were written 01:57–02:10, and this update at 2026-10-25T02:14:01+05:30.
  - **Follow-up 2** (`directed_by` 2026-10-25T01:58:39+05:30, T31): started 02:18:02 IST. Six rule candidates from the developer's outside comparison, tested as hypotheses; nothing adopted. Scripts `notes/forensics/g2f2_*.py`; outputs `runs/g2f2-0242/` (run ID `g2f2-<script>-0242`; `runs/g2f2-0225/` holds superseded development runs of the same scripts). Section written at 2026-10-25T02:49:59+05:30. Adds the section "Follow-up 2: rule candidates" at the end and marks one correction: the first run's mod-60 claim (Summary 10, Q4, Q7) is contradicted for policy rows once the slot is known.
- **Holdout lock.** Gold is read only through `../research/prototype/devgold.py`, which drops holdout rows before `steps_json` is parsed. `notes/forensics/common.py:load_cases` also drops the holdout request rows and asserts there are 22 DEV and 518 test rows. Every count below covers DEV (22) plus test (518) and **no holdout row, inputs included**. One raw `grep` in §1 printed `sample_output.csv` lines; they were DEV rows 01, 02, 07 and 08 only. After that, the raw-byte search (`q5_q6.py`) skips `sample_output.csv`. The follow-up run used the same two loaders and also kept holdout request *inputs* out of every count, as its brief requires. T32 (developer turn 02:02:22) later allows holdout inputs as unknown competitors in the batch pass; this run did not use them.
- **Labels.** SEEN = computed here, with the run named. INFERRED = reasoned from SEEN facts. UNKNOWN = the data cannot settle it.
- **Runs.** Scripts are in `notes/forensics/`. Every one runs with `python3 -I notes/forensics/<script>.py` from the repo root and writes to `runs/g2-0137/`. Run ID = `g2-<script>-0137`. The prototype is imported read-only; its `out/` folder and its `__pycache__` were not touched (their mtimes are still 24 Oct 23:50).
- **Follow-up runs.** The scripts `f1_b4.py`, `f2_ties.py`, `f3_traps.py`, `f5_handbuilt_wording.py` and `s5_one_to_one.py` run with `python3 -I -B notes/forensics/<script>.py --run g2f-0152` and write to `runs/g2f-0152/`. Run ID = `g2f-<script>-0152`. They write no bytecode: `notes/forensics/__pycache__` still holds only the first run's 01:37 file.
- No model calls, no network, no git writes. SQL goes only through the prototype's in-memory `sqlite3` loader (authorizer denies ATTACH and `load_extension`).

## Follow-up run (`g2f-0152`): what changed
1. **B4 re-measured (Q2): reproduced.** There are 121 identifier-free analytics records over 240 generated test cases. 98 records are claimed by more than one case, and 22 cases own one outright. This holds under report 14's definition, verify's definition and 4 variants. New: on DEV, the same proxy flags 10 cases and is right in 4 of its 14 claims.
2. **Tie signals (Q7):** 14 more signal forms were tested on the 27 S5 cases. None separates a case on a validated basis. Its one hit (email digits, case_225) has 0/164 validity. **Correction:** the first run's region row read no region for any of the 27 cases, because `extract.py` drops the `region` field, so its 0 was vacuous. Re-measured with regions parsed from the log lines, it is still 0.
3. **Trap counts (trap table):** all five report 15 §6.4 figures reproduce under a stated definition. Two counts depend on the definition: replica-only records are 13 (table-based), 16 (adding replica-service log lines) or 307 (file-origin based), and tombstones are 10 in evidence vs 11 in any input.
4. **One-to-one-aware S5 (Q3):** implemented in `s5_one_to_one.py`, which first reproduces the first run's stages and picks on all 540 cases. The matching form gives 27 distinct picks, 0 duplicate accounts and 0 cases without a pick, under all 4 orders tested. Greedy assignment leaves case_410 without a pick under 2 of them. Reversing the order changes 27 of 27 picks (matching form). New full-mask test on the test inputs (identifier links hidden, linked account as the label): S2 116/116, D17 77/77, S4b 28/28, and S5 between 2/13 and 10/13 depending on the order.
5. **Corrections:** (a) Q3's hand-built wording: case_02's row reads "completed some internal work but could not confirm the final state". The counts are unchanged: DEV 5, test 0 of 518. (b) The header times, above.
6. **Not changed:** every other first-run figure. The developer's rulings made after the first run (T26–T33 in `notes/DECISIONS.md`) are not restated here; where one bears on a section, the section says so.

## Summary (10 lines)
1. **Report 15 and verify 14_15 reproduce exactly** (SEEN, `g2-q2_reconcile-0137`): DEV 22/22 status, 20/22 exact, 132/134 steps, 908/938 fields, 74/76 resources. All 11 verify figures I re-measured match, including 43, 20/43, 28/57, 23, 70, ±1 s→33 and 234/236. *Follow-up:* B4 (121 records over 240 cases) also matches (`g2f-f1_b4-0152`).
2. **T4 as written finds no account in 4 DEV cases** (01, 02, 07, 08) and 10 deletion-authorized test cases (the showcase series). The DEV four are all one pattern: the delete row sits 0–5 min from `reported_at`, not 44–75 min before it.
3. **The "hand-built" label holds on input features alone:** non-round timestamps, plus a delete row within ±10 min whose wording is not "submitted primary profile". Two other wordings occur: "reported the requested operation as completed" (4 cases) and "completed some internal work but could not confirm the final state" (case_02; corrected in the follow-up). Exactly 5 DEV cases (01, 02, 05, 07, 08) and **0 of 518 test cases** have it (re-checked, `g2f-f5_handbuilt_wording-0152`).
4. **T4 order on DEV:** identifier link 11/11 correct, timed rule 7/7, then nothing left for stages 3–5. Those stages are exercised only by ablations: D17 4/4 correct, the D18 pick 1/2. *Follow-up:* with identifier links hidden on the test inputs, S2 picks the linked account 116/116 and D17 77/77 (`g2f-s5_one_to_one-0152`).
5. **T4 order on test (508 deletion-authorized):** S1 236, S2 157, S3 2, S4 D17 64 (+12 by a second one-to-one pass), S5 flagged **27**, none 10. Verify's "about 43" was the prototype's order.
6. **New defect class:** the S5 pick as specified (closest to −60 min, chosen per case) gives **the same account to both cases of every tie**: 27 cases share 13 accounts. S5 has to be one-to-one aware. *Follow-up:* the matching form gives 27 distinct picks, no duplicate and no case left empty, under every order tested. The order decides which tie partner gets which account.
7. **D17 limits cost 0 DEV analytics** (4/4 kept, 0 false positives). Exclusivity cuts test claims 137→85, and the guessed-anchor ban 137→125. ±1 s matters: widening adds the DEV false positive in case_19; narrowing loses 4/4.
8. **UNEXPLAINED:** 2 DEV steps (`audit_record_6645`, `audit_record_5569`), in no input; 3 hypotheses tested. Under T4 as written, the 4 hand-built accounts are also unexplained; a ±10-min rule explains them (case_08 only if the result-mismatch fallback is allowed).
9. **T9 on DEV:** "compliant records in INCOMPLETE get verification" is supported only for account and audit (12+12 steps). Rule_05's condition is not observable in 3 of 4 REDACT cases. Tombstone-PII and legal-hold have no DEV evidence either way.
10. **No input signal I tested separates the 27 true ties.** First run: request digits, candidate evidence, region overlap, second offsets, and mod-60 phase (which is not stable on identifier-linked jobs). *[Follow-up 2 correction: for policy rows the mod-60 phase is stable once the slot is known (Q4 note). It still splits 0 of the 27 ties, because none of them has an own policy row (`g2f2-g2f2_h1x_slotgrid-0242`).]* Follow-up: system names, phone-region prefix, request order, request lag, job gaps, citation-file presence, observation time, ID suffixes and email digits (`g2f-f2_ties-0152`). DEV has no such tie, so no tie rule has DEV support.

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
| B4: 121 unlinked analytics records over 240 cases | V B4 | *Follow-up:* **121 records over 240 cases; 98 records claimed by more than one case; 22 cases own one outright** (`g2f-f1_b4-0152`). Definitions below the table. | **yes** |

**B4 definitions (follow-up, `g2f-f1_b4-0152`, test inputs only).** I read the two source definitions from the scripts that produced them (report 14 `a17_planproj.py`, verify `anal.py`), not from their outputs.
- *Scope:* the 496 generated test cases: the 508 deletion-authorized cases minus the 12 showcase cases (the input-derived set from `q2_extra.py`).
- *Unlinked:* no unit anywhere links the resource to any user.

| Form | Window (min from `reported_at`) | Rows | Records | Cases | Records claimed by >1 case | Cases owning one outright |
|---|---|---|---:|---:|---:|---:|
| Report 14 (`a17`) | −35…−25 | ANONYMIZE rows, SUCCESS only, no evidence filter | 121 | 240 | 98 | 22 |
| Verify (`anal.py`) | −35…−25 | deletion-worker ANONYMIZE rows, any result, resource has evidence | 121 | 240 | 98 | 22 |
| Verify, SUCCESS only; no evidence filter; open interval; all 508 authorized | −35…−25 | as stated | 121 | 240 | 98 | 22 |
| Policy-template window | −31…−2 | as verify | 122 | 243 | 99 | 22 |

- All 304 case-row matches in the verify form are "Policy action completed" rows, and all 121 records are ANONYMIZED in evidence.
- **Reach of the D17 offset rule over the 240 cases:** the prototype's own signature links reach 135 (verify's figure; 1 more prototype case lies outside the 240). Anchored on the T4 picks, D17 reaches 132 with all claims and 84 with L1 + L2.
- **DEV check of the proxy** (gold via `devgold.py`): it flags 10 DEV cases with 14 claims. 4 claims are gold analytics steps, and they are all 4 of DEV's identifier-free gold analytics (03, 21, 26, 27). The other 10 claims are not in gold. So 121/240 counts candidates, not owners: at most 121 of the 240 cases can own a record (INFERRED).

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

**Defect (SEEN):** all 27 S5 cases pick an account that another S5 case also picks (13 accounts). The closest-to-−60 order is case-independent, so both members of a tie get the same account. A one-to-one-aware S5 would give distinct picks with the same expected hits and no duplicated resource (INFERRED). The follow-up measures it below.

**One-to-one-aware S5 (follow-up, `g2f-s5_one_to_one-0152`).**
- *Implementation.* `s5_one_to_one.py` re-implements S1–S4b of `acct_stages.py`. Before measuring, it asserts that stage and pick equal the first run's saved output on all 540 cases for 4 variants (base, no-result, no-owner, split); 0 differ. S5 then runs in one of three modes:
  - *independent:* the first run's rule;
  - *greedy:* cases go in a stated order, and each takes the closest-to-−60 candidate that nobody has taken yet. A case with nothing left gets no pick and is flagged;
  - *matching:* within each group of S5 cases that share candidates, the assignment that gives the most cases a pick, then the smallest total distance from −60 min, then follows the stated order.
- *Orders tested* (none uses a case ID, file name or row position): `req_asc` (requested_at, then email); `req_desc` (its exact reverse); `email_sha` (sha256 of the lower-case email, a neutral content key); `fewest_first` (fewest candidates, then requested_at, then email). No order has an input basis: on identifier-linked pairs, request order predicts delete-row order 75 times and misses 78 (Q7).
- *NA requests.* In the first run NA cases go through every stage, and NA case_539 is itself an S5 case. Excluding NA cases changes no authorized pick under independent S5 (base and no-result), and no base count under any mode. Domain logic favours excluding them: each NA request has a CLASSIFY_REQUEST row naming the user's own account and authorizes no delete job (trap table). The tables below exclude NA cases unless stated.
- *Per person (T29).* The 27 S5 cases are 27 different people. The 3 people with two DEV/test requests (user_07: 07 and 61; user_17: 17 and 46; user_18: 33 and 52) never reach S5. On these inputs, per-case and per-person one-to-one give the same picks.

Test, base T4, 27 S5 cases (508 authorized):
| S5 mode | Order | Picks | Distinct accounts | Duplicate accounts, all stages (cases on them) | Cases left with no pick |
|---|---|---:|---:|---:|---:|
| independent (first run) | — | 27 | 13 | 13 (27) | 0 |
| greedy | req_asc | 26 | 26 | 0 | 1 (case_410) |
| greedy | req_desc | 27 | 27 | 0 | 0 |
| greedy | email_sha | 26 | 26 | 0 | 1 (case_410) |
| greedy | fewest_first | 27 | 27 | 0 | 0 |
| matching | each of the 4 | 27 | 27 | 0 | 0 |

- After one-to-one, the 27 cases form 12 pairs with 2 candidates each and 1 triple (410, 411, 412) with 3 candidates, where D17 already cut case_410 to 2. Greedy empties case_410 when the other two go first; matching never does.
- **Picks that change between orders** (matching, of 27): req_asc vs req_desc 27; req_asc vs email_sha 18; req_desc vs email_sha 10; email_sha vs fewest_first 19; req_asc vs fewest_first 2; req_desc vs fewest_first 26. Greedy vs matching in the same order: 0–2. Independent vs matching (req_asc): 14.
- Expected hits do not depend on the order (INFERRED). Partners in a pair share both candidates, so any one-to-one order gives the pair 2 or 0 right, where independent picks give exactly 1. What one-to-one buys is no duplicated account and no two answers that contradict each other.

DEV, the first run's S5 ablation (`--no-result`: S5 = case_21 and case_27, each in a group with test competitors, NA ones among them):
| S5 mode | Orders req_asc / req_desc / email_sha / fewest_first | NA included | NA excluded |
|---|---|---|---|
| independent | — | 1/2 | 1/2 |
| greedy | each order | 1/2, 2/2, 2/2, 1/2 | 2/2, 2/2, 2/2, 2/2 |
| matching | each order | 1/2, 1/2, 2/2, 1/2 | 2/2, 1/2, 2/2, 2/2 |

- On test under the same ablation there are 49 S5 cases. Independent picks give 24 distinct accounts (23 duplicated). Matching gives 49 distinct, 0 duplicated, 0 empty; greedy leaves 0–2 empty.
- Two DEV cases cannot rank the orders. They show only that the one-to-one modes are not worse than independent picks on DEV, which is expected and is not evidence.

**Full-mask pseudo-label test (follow-up; test inputs only, no gold).** I hide every identifier link to accounts (S1 off and the owner filter off), run S2–S5, and score each of the 236 identifier-linked test cases against its linked account:
| Variant | S2 | S3 | S4 D17 | S4b | S5: independent; then matching with req_asc / req_desc / email_sha / fewest_first (greedy gives the same) | No candidate |
|---|---|---|---|---|---|---|
| S1 off, owner filter on | 206/206 | 26/26 | 1/1 | — | 0/1 in every mode | 2 |
| S1 off, owner filter off (full mask) | 116/116 | — | **77/77** | **28/28** | 5/13, 2/13, 10/13, 8/13, 2/13 | 2 |
| Full mask, no result match | 29/29 | — | **129/129** | **38/38** | 18/38, 18/38, 19/38, 25/38, 18/38 | 2 |

- The 2 cases with no candidate are case_34 and case_46, the B1 outliers whose linked delete row lies outside −75…−44 min.
- **This supports S2–S4b on inputs, D17 included:** 105 of 105 and 167 of 167 tie-breaks pick the linked account. DEV under the full mask, scored the same way on its 11 identifier-linked cases, agrees: S2 6/6, D17 3/3, S5 0/1, no candidate 1 (case_05, whose row is at +8 min).
- **It supports no S5 order.** The S5 hit rate swings from 2/13 to 10/13 between mirror orders, and settles near half (18–19 of 38) in the larger sample. email_sha's 25/38 is one of 12 order × variant cells and has no mechanism behind it: a hash of the email cannot carry the generator's assignment. I read it as noise (INFERRED).
- *Caveat (INFERRED):* the labels are the identifier-linked accounts. That they are the true accounts agrees with DEV (S1 11/11), but is not proven for test.

**The "hand-built" label (report 14 §C6: DEV 01, 02, 05, 07, 08).** Report 14 states no basis. The basis I find is in the inputs (SEEN, `g2-q1_q3_handbuilt-0137`, cross-tab over authorized cases):
| Feature combination: (round timestamps, delete row within ±10 min, that row's wording, 3-digit zero-padded account ID) | DEV | Test |
|---|---:|---:|
| (not round, yes, "reported the requested operation as completed", yes) | **4** (01, 05, 07, 08) | **0** |
| (not round, yes, "completed some internal work but could not confirm the final state", yes) | **1** (02) | **0** |
| (round, no, —, no) | 15 | 368 |
| (round, yes, "submitted primary profile", no or yes) | 2 (18, 20, a neighbouring batch) | 139 |
| (not round, no, —, no) | 0 | 1 (case_63, 22:20) |

**Correction (follow-up, `g2f-f5_handbuilt_wording-0152`).** The first run's table gave all 5 DEV rows the wording "reported the requested operation…". Its script tested only "not 'submitted primary profile'", so the counts were right and the wording was not. The 5 rows (SEEN):

| Case | Row | Offset | Row result (request status) | Wording |
|---|---|---:|---|---|
| 01 | activity_3342, account_001 | −0.28 min | SUCCESS (COMPLETE) | "Deletion worker reported the requested operation as completed." |
| 02 | activity_3376, account_002 | +5.05 | PARTIAL (PARTIALLY_COMPLETE) | "Deletion worker completed some internal work but could not confirm the final state." |
| 05 | activity_3482, account_005 | +8.02 | SUCCESS (COMPLETE) | "…reported the requested operation as completed." |
| 07 | activity_3590, account_007 | −1.35 | SUCCESS (COMPLETE) | "…reported the requested operation as completed." |
| 08 | activity_3554, account_008 | +4.97 | SUCCESS (PARTIALLY_COMPLETE) | "…reported the requested operation as completed." |

- **Corrected feature:** a delete row within ±10 min whose wording is one of the two non-standard templates. In the whole file they occur on 7 of 539 account delete rows (6 + 1). 5 of those lie within ±10 min of a DEV case, and 2 within ±10 min of no DEV or test case. The wording follows the row's result: "completed" is SUCCESS in 6/6, "internal work" PARTIAL in 1/1.
- **The 0-of-518 re-check:** the corrected definition gives DEV 5 and test 0 of 518 (0 of 508 authorized). The single wording the table printed gives DEV 4 (case_02 drops out) and test 0. Dropping the timestamp condition changes neither count. The test count stays 0 for windows of ±5, ±10, ±15, ±30 and ±60 min (DEV 3 at ±5 min); it first becomes 2 (case_549, 550) at ±120 min.
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
- **CORRECTION (follow-up 2; both values kept).** First run (`g2-q7_mod60-0137`): policy residuals fall at 9–11 and 39–41 mod 60, "a mod-60 refinement has no input basis". Re-measured by policy slot (`g2f2-g2f2_h2_analytics-0242`): each minute slot before `reported_at` has its own 2-s band mod 60. On S1 jobs: slot −29 → 40–41 (4 rows), −22 → 10–11 (19), −15 → 39–40 (20), −8 → 9–10 (20), −3 → 39 (1). On S2 jobs, 29 more rows fall in the same bands. That is 93 of 93 rows in their slot's band, so a slot-conditioned mod-60 band **has** an input basis for policy rows. The unconditioned statement (both phases occur) still holds, and after rows still have no slot rule (Follow-up 2, H2).

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
| S2 timed rule −75..−44 + result match + owner filter | Data: 234/236 test identifier-linked offsets; DEV 7/7; *follow-up:* full-mask pseudo-labels 116/116 on test inputs | 7 | 0 (4 hand-built not reached) |
| ±10-min hand-built account rule (Option A/B) | Data: 4/4 DEV hand-built, 0 test. **DOMAIN LOGIC ONLY**: "the worker's row for this report". | 3 (A) / 4 (B) | 0 |
| D17 account tie-break | Data: 4/4 DEV under ablation; *follow-up:* full-mask pseudo-labels 77/77 + 28/28 (no result match: 129/129 + 38/38) on test inputs; no domain basis | 0 in base order | 0 |
| One-to-one-aware S5 (matching) | DOMAIN LOGIC ONLY: one account cannot be two people's. No order has data support (Q7). | 0 in base order (DEV has no S5 case); 1/2–2/2 under ablation, by order | 0 |
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
| Candidates have evidence, with a unique region overlap with the user's own units | 0 *(vacuous: the region sets were empty for 27/27 cases; re-measured below)* |
| Candidates share a second offset | 0 |
| mod-60 phase (Q4): not stable on identifier-linked jobs *[follow-up 2: stable per policy slot; still 0 of 27 split, since no tie case has an own policy row, `g2f2-g2f2_h1x_slotgrid-0242`]* | no basis |

No tested signal separates them, and DEV has 0 such ties, so nothing here has DEV support. The candidate counts in this table are before the one-to-one pass; after it the 27 cases form 12 pairs with 2 candidates and 1 triple with 3 (Q3).

### Follow-up: more signals (`g2f-f2_ties-0152`)
The tie cases and their remaining candidates come from the base T4 run (NA excluded), which is the same 27 cases as the first run. A signal *separates* a case when it keeps exactly one candidate. Validity is checked against identifier-linked (S1) or timed-unique (S2) accounts on the inputs, or against DEV gold.

| Signal (form) | Validity check | Tie cases separated (of 27) |
|---|---|---:|
| SYS-a: the candidates' delete rows name different source or target systems | none possible: every account delete row is deletion_worker → account_service | 0 |
| SYS-b: a candidate has any other activity row | none possible: each candidate has exactly one row, its delete row | 0 |
| SYS-c: a candidate's evidence system/collection matches the user's own units | — | 0 (4 cases have candidate evidence; both candidates sit in the same `profile_lookups` collection) |
| REG-a: the phone country code predicts the region of the user's own lines | log-line regions: purity 0.362 against 0.353 with phone codes permuted (share of permutations ≥ observed 0.26; 134 users, 373 lines). With replica-table tags: 0.266 against 0.271. **No association.** | basis absent |
| REG-b: a candidate has any region-bearing observation | — | 0 of 27 cases |
| REG-c: candidate region equals the user's own region or the phone code's majority region | — | 0 (own units carry a region in 7 cases, all replica-table tags, which every replicated record has in both replica tables) |
| FIFO: the earlier request gets the earlier delete row | identifier-linked pairs 75 concordant / 78 discordant; S1 + S2 pairs 151 / 127; DEV gold pairs 8 / 5 | basis absent |
| LAG: request lag (reported_at − requested_at) vs delete offset | Pearson −0.006 (245 S1 jobs) | basis absent |
| GAP: delete offset vs the same job's policy and after-row offsets | Pearson 0.008 (64 policy rows), −0.076 (293 after rows) | basis absent |
| FILE: the candidate is observed in the case's citation file F | cases resolved at S3/S4/S4b: the pick is in F 2/78, losing unowned candidates 4/97; in any evidence file 4/78 vs 4/97 | 0 (4 cases have candidates in F, both candidates each time) |
| OBST: inside F, the candidate's observation time is nearest to the user's own units | — | 0 |
| SUFX: the candidate's number equals another linked resource's number | S1 accounts 0/247 | 0 |
| EDIG: digits of the email's local part occur in the candidate's number | S2 accounts 0/164, DEV gold 0/22 | 1 (case_225: "66" in account_669); no basis |
| UIDO (diagnostic only, not admissible: ID order has no domain basis): user_id order predicts delete-row order | identifier-linked pairs 78 / 75 | — |

**Correction to the first run's region row.** The first run (`g2-q7_ties-0137`) took regions from unit attributes, but `extract.py` strips the `region` field from log lines, so every tie case had an empty region set and its 0 was vacuous. The follow-up re-parses the lines. `region=` appears on 1,511 lines in 12 of the 26 log files, with only 4 values (ap-south-1, eu-central-1, eu-west-1, us-east-2); no batch lookup trace carries one. The values do not follow the region in the file name (the af_south export carries us-east-2; SEEN, raw grep). Re-measured value: still 0.

**What DEV can and cannot support.**
- DEV has 0 S5 cases under T4. It has 2 under the no-result ablation (one tie group each), 1 under the full mask and 6 under the full mask without result match. No tie rule can rest on that.
- DEV tests a signal's validity only where DEV cases share a batch with known accounts: request order is 8 concordant / 5 discordant over 13 DEV pairs, which is noise.
- The full-mask test (Q3) supports S2–S4b and D17 on 236 test cases without gold. It supports no S5 order and no tie signal.

---

## Trap table (counts re-measured here unless marked)
| Trap | Count | Source |
|---|---:|---|
| Post-audit-only account link (showcase) | test 6 | Q1 |
| Account named only in an activity row (no evidence) | DEV 4 hand-built + 9 default-ABSENT accounts (report 15 R8) | Q1 / R15, not re-measured |
| Truth-only resources | DEV 2 steps; test 81 generated + 2 showcase cases with no audit record anywhere | Q2 B3 |
| Result-mismatch account (reported status ≠ row result) | DEV 1 (case_08); test 0 among no-candidate cases | Q1 |
| Same account claimed by more than one case (S5 independent pick) | test 13 accounts / 27 cases; 0 with a one-to-one-aware S5 (follow-up) | Q3 |
| D17 multi-claimed analytics | test 26 records / 52 claims | Q4 |
| Historical email, decoys, replica drift, tombstones, negation traps | re-measured below (follow-up) | `g2f-f3_traps-0152` |

**Report 15 §6.4 re-measured (follow-up, `g2f-f3_traps-0152`, inputs only).** File-level counts use no request row, so no holdout row enters them. They may include resources whose owner is a holdout user; that cannot be known without opening holdout rows, which I did not do. Case-scoped counts cover DEV (22) and test (518) only.

| Trap | Report 15 §6.4 | Form 1 | Other forms | Case-scoped (DEV / test) | Reproduced |
|---|---|---|---|---|---|
| Historical request email | DEV 1, test 100 | not the user's current email: DEV 1, test 100 | replaced at or before `requested_at`: 1 / 100; at or before `audit_at`: 1 / 100; only after `audit_at`: 0 / 0 | — | yes, every form |
| Upper-case request email | test 20 | contains an upper-case letter: DEV 0, test 20 | — | — | yes |
| Decoy emails in evidence | 22 (15 `.jr`) | raw text of every non-PNG file: 22 of 791 distinct emails match no user. 15 are `jr` look-alikes, 2 near misses (edit distance ≤ 2), 5 other; they sit in 18 files | extracted identifier fields: 22 of 793, same classes | a look-alike of the user's own email somewhere in evidence: DEV 0, test 14 (8 in a pre-audit file) | yes |
| Replica-only records | 13, all accounts | rows only in SQL tables named `*replica*`: **13, all accounts, all identifier-linked** (read replica 6, ap_south 2, eu_west 2, reporting 2, failover 1) | adding lines from a `*replica*` log service: 16 (3 support records added). File-origin based: 307, an over-count, because replica capture files also hold a `customer_data_primary` table | an RP-a account linked in window: DEV 2 (05, 16), test 11 | yes (form 1) |
| Replica drift: replica state ≠ primary state for the same resource | — | **0**: 291 resources have both kinds of rows, and their states always agree. The drift DEV shows (case_05, 16) is a replica table holding an account row that no primary table has | — | — | new |
| Tombstones | 11 distinct (9 PII, 9 clean observations) | in evidence: 10 distinct, 18 observations (9 PII, 9 clean); 5 resources PII only, 5 clean only, none both | in any input (evidence + activity): 11 distinct | linked in window, state at `audit_at`: DEV clean 1 (case_31); test PII 4, clean 4, no state 1 | yes (11 = any input) |
| Negation / NA requests | DEV 0, test 10 | `intent.py` NA (keyword rules tuned to the visible texts, verify A3): DEV 0, test 10 | a CLASSIFY_REQUEST row naming the user's account: DEV 0, test 10, the same 10. A CLASSIFY row in the submit window −75…−44 min: DEV 2, test 16, which over-matches cases in the same batch | of the 10: 6 contain deletion words under a negation or keep phrase (the trap proper), 4 carry only keep phrases. Authorized texts with a negation match: 0 | yes |
| User-linked units in post-audit files | DEV 6 | DEV 6, test 197 | with a pre-audit line inside the post-audit file: DEV 6, test 179. Any user-linked line after `audit_at`: DEV 1, test 42 | — | yes |
| Connector repopulation / RESTORE_BACKUP / replication SYNC rows | 31 / 1 / 56 | 31 / 1 / 56 | — | — | yes |
| CHECK_DATA_FLOW / CHECK_RESTORE_ACCESS rows | 89 / 28 | 89 / 28 | — | — | yes |

---

## NOT DONE / open
Status of the first run's list after the follow-up:
- B4 → **done** (Q2): reproduced.
- Q7 system and phone-region signals → **done** (Q7): 0 separations; phone region has no input basis.
- Report 15 §6.4 trap counts → **done** (trap table): all reproduce under a stated definition.
- One-to-one-aware S5 → **done** (Q3): implemented and measured.
- Option C's state rule (ABSENT vs a finding for an account deleted after `audit_at`) → **still UNKNOWN as a data question**: there is no DEV analogue. The developer has since ruled it (T27: VERIFY_RECORD_ABSENT with an empty citation).
- `notes/forensics/__pycache__/` → unchanged. It was written by the first run, before `dont_write_bytecode` was set, is gitignored, and still holds only that 01:37 file; the follow-up wrote no bytecode.

Open after the follow-up:
- **S5 order.** No input signal and no DEV case supports any order (Q3, Q7). Which sort key the pick states is the developer's choice (T29).
- **Holdout inputs in the batch pass (T32).** Not measured here, because this brief excludes holdout inputs. They would change the 13 S5 groups only if a sample case shares one of their batches; T31 candidate 1 measures that.

---

## Follow-up 2: rule candidates (`g2f2-0242`)

- **Brief:** T31 (developer turn 2026-10-25T01:58:39+05:30). There are six candidates from the developer's outside comparison (T17). Each is tested as a **hypothesis**, with at least two forms where the wording leaves room. **Nothing is adopted; keep or revert is the developer's call.**
- **Runs.** Every script runs with `python3 -I notes/forensics/<script>.py --run g2f2-0242`. Outputs go to `runs/g2f2-0242/` (JSON plus each script's stdout). Run ID = `g2f2-<script>-0242`.
  - Each script was run twice under random hash seeds (`-I` ignores `PYTHONHASHSEED`), and the 8 JSON outputs are byte-identical.
  - No bytecode was written: `notes/forensics/__pycache__` still holds only the first run's file.
- **Holdout lock.**
  - DEV gold is read only through `devgold.py`.
  - The 10 holdout request *inputs* (`g2f2_lib.load_holdout_inputs`: request file only, never gold) enter **H1 only**: the batch pass, the H1 joint analytics, and the H1 anchors that H2 and the cross-check reuse. Only aggregate counts are reported for them.
  - `grep` finds no holdout case ID in any output.
  - The raw search in item 6 skips `sample_output.csv` and drops holdout rows of `sample_deletion_requests.csv` on their first CSV field.
- **Labels:** SEEN = computed in the named run. INFERRED = reasoned from SEEN facts. UNKNOWN = the data cannot settle it.

### Baselines (stated explicitly)
**Row, step and field baseline: the prototype DEV replay.**
- `g2f2_lib.solve2` is a line-for-line copy of `solver.solve()` with hook points. With no hooks it equals the prototype on **540 of 540** DEV+test cases, both without and with the hand vision table (SEEN, `g2f2-g2f2_baseline-0242`).
- DEV: 22/22 status, 20/22 exact (misses 18 and 20), 132/134 steps (132 predicted), 908/938 fields, 74/76 resources. This equals `g2-q2_reconcile-0137` (the script asserts it).

**Account baseline: T4 + T26 + T27 + T28 + T29 (`g2f2_lib.AcctEngine`, default options).** I had to implement T26–T29 to get it. Its counts come first.
- **T4 core:** S1–S4b equal `g2-acct_stages-0137` on all **491** cases the first run resolved at those stages (0 differ; the script asserts it).
- **T26 (Option A):** DEV case_01, 02 and 07 get `account_001`/`002`/`007`, 3/3 correct. Test: 0.
- **T27 (narrow C):** the join is own email or phone → log trace → account, at any line time. Test: 6 cases (33, 35, 39, 50, 52, 55).
  - case_33 and case_52 share `account_2373` (user_18), which T29 allows.
  - Each pick is flagged; its verification is cited `""`.
- **T28:** test cases 45, 53, 61 and 63 are omitted and flagged. DEV case_08 has no account (T26's known miss).
- **T29:** S5 is a one-to-one matching per person. Ties are ordered by (`requested_at`, lower-case email). That order is my stated choice; no order has support (Q3).
  - 27 picks, 27 distinct.
  - 14 of them differ from the first run's independent picks.
- **NA requests** run through the stages as in `acct_stages.py`. Excluding them changes 0 authorized picks.

| Account baseline (`g2f2-g2f2_baseline-0242`) | S1 | S2 | T26 | S3 | S4 D17 | S4b | S5 (flagged) | T27 (flagged) | none (T28) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV (22), correct / resolved | 11/11 | 7/7 | 3/3 | — | — | — | — | — | 1 (case_08) |
| Test, deletion-authorized (508) | 236 | 157 | 0 | 2 | 64 | 12 | 27 | 6 | 4 |

- **Baseline DEV rows** (the harness with these accounts injected wherever they differ from the prototype's): 22/22 status, 19/22 exact, 131/134 steps, 899/938 fields.
  - The only difference from the prototype: case_08 loses `VERIFICATION account_service account_008 VERIFY_RECORD_ABSENT ABSENT ""`.
  - 29 test rows differ from the prototype's: the 6 T27 cases, plus 23 where the prototype picks a different account (its −76…+9 window, its in-evidence preference, or an independent guess). All 9 cases named in H1 are among the 23.

### H1. Global account assignment per deletion batch (would amend T4 step 3)
**Script and terms.** `g2f2_h1_batch.py`; cross-check `g2f2_h1x_slotgrid.py`.
- **Batch** = every request with the same `reported_at`, across DEV, holdout inputs and test.
- A (request, account delete row) pair **qualifies** when all of these hold:
  - (i) the row is in −75…−44 min;
  - (ii) its result matches the reported status;
  - (iii) every identifier-linked deletion-worker row of the request's job fits the candidate's 30-s grid (prototype `sig_match`; vacuous with no such row);
  - the owner filter passes.
- One owner per person.

**Variants:**
- V1 = H1 as worded, with unique-first propagation and then S5 matching.
- V2 = V1, but a pick is made only when it holds in **every** maximum matching.
- V3 = V1 without holdout inputs.
- V4 = V1 with D17 back as the S4 tie-break.
- V5 = V1 with own rows linked at any line time up to `audit_at`.
- V6 = V1 as one global pass.

**Batch shape** (SEEN, all request files):
- 215 of 250 batches have exactly one account delete row per request in −75…−44 min.
- 8 have more rows than requests; 27 have fewer. The 25 single-request batches with no row are DEV 5 (hand-built), holdout 3 and test 17 (12 authorized, 5 NA).
- No two batches' windows overlap (0 batch pairs under 31 min apart), so a per-batch pass and a global pass see the same candidates.

| Variant (`g2f2-g2f2_h1_batch-0242`) | Test picks changed vs baseline (508) | DEV picks changed (22) | DEV correct | Stage relabels only (test) |
|---|---:|---:|---:|---|
| V1 H1 | **0** | **0** | 21/22 | 77 (S4→S2 64, S4b→S3 12, S3→S2 1) |
| V2 forced | 0 | 0 | 21/22 | 235 (relabelled S3_forced) |
| V3, V5, V6 | 0 | 0 | 21/22 | 77 each |
| V4 | 0 | 0 | 21/22 | 0 |

- **D17 as a qualifier** drops at least one candidate in 66 test cases. It never empties a candidate set and never drops the baseline pick (SEEN).
- **The cross-check grid** (H2's per-slot bands in place of the 30-s grid, `g2f2-g2f2_h1x_slotgrid-0242`) changes 0 picks under the baseline and under H1. The 27 S5 cases stay 27: 15 have no own worker rows, and 12 have only after rows, so none has an own policy row for a slot band to act on.
  - Full-mask test (identifier links hidden, owner filter off, the identifier-linked account as the label): S5 is 2/13 under every grid.
  - With the slot grid, D17 resolves 78/78 (band: 77/77) and S4b 27/27 (28/28): one tie-break moves a stage, and every one is still correct.
- **Holdout competitors (aggregate only):**
  - 8 batches contain holdout inputs; 5 of them hold 12 test requests, and 4 hold 5 DEV requests.
  - They change 0 DEV and 0 test account picks.
  - In 2 NA test cases (536, 539) the candidate set is emptied, which is irrelevant because NA outputs `[]`.
  - Holdout stages: S1 2, S2 5, T26 1, none 2.
- **The 9 named test cases:** every variant gives the **same account as the baseline**. The prototype gives a different account in all 9 (SEEN; its −76…+9 window and in-evidence preference take a batch peer's or the next batch's row).

| Case | Batch (test) | Reported | Baseline = every H1 variant | Prototype |
|---|---|---|---|---|
| 157 | 3 | NOT_STARTED | account_2154 (S4b) | account_1992 (guess) |
| 192 | 2 | PARTIALLY_COMPLETE | account_6608 (S4 D17) | account_9317 (in-evidence) |
| 224 | 3 | COMPLETE | account_7605 (S4 D17) | account_669 (guess) |
| 230 | 3 | COMPLETE | account_8165 (S4b) | account_8936 (guess) |
| 275 | 3 | COMPLETE | account_2352 (S4b) | account_731 (in-evidence, next batch) |
| 287 | 3 | COMPLETE | account_4485 (S2) | account_6575 (in-evidence) |
| 290 | 3 | COMPLETE | account_7177 (S2) | account_731 (in-evidence, next batch) |
| 304 | 2 | PARTIALLY_COMPLETE | account_4771 (S4b) | account_7907 (guess) |
| 359 | 3 | NOT_STARTED | account_6445 (S4b) | account_7118 (guess) |

**Joint analytics** ("assign each account together with the analytics that fit its job"). Each assigned account's 30-s grid claims identifier-free worker rows, and T5's limits are applied per person.

| Anchors | Test claims / kept | DEV gold identifier-free analytics kept |
|---|---|---|
| V0 baseline (no holdout inputs) | 138 / 85 | 4/4 |
| V3 H1 without holdout inputs | 138 / 85 | 4/4 |
| **V1 H1 with holdout inputs** (also V2) | 138 / 85 | **3/4: case_21 loses `analytics_5335`** |

- **Why case_21 loses it (SEEN):** the only other submit row in that batch whose grid fits `analytics_5335` sits at residual 39 s, and the batch pass assigns it to a sample-input competitor. The 30-s band accepts 39; the record then has two claimants and T5 drops it.
- **The row effect, if T5 runs with sample inputs as competitors (T32's shipped setup) under the 30-s band:** DEV case_21 loses `VERIFICATION analytics_platform analytics_5335 VERIFY_RECORD_ANONYMIZED ANONYMIZED evidence_92`, and its row becomes inexact. Under H2's slot band that row does not fit (slot 0 band = 40–41 s), and case_21 keeps it (H2 table).
- Test pairs kept change in 0 test cases between V0 and V1.

**Experiment line H1:** hypothesis "a batch-wide one-to-one assignment with D17 as a qualifier (plus sample inputs as competitors) changes account picks" → change V1 or V2 → **delta 0 DEV and 0 test picks**; flips: none. Joint analytics with sample inputs under the 30-s band: DEV −1 step (case_21); test 0.

### H2. Identifier-free analytics by policy slot (would amend T5)
**Script.** `g2f2_h2_analytics.py`.

**Slots (SEEN, inputs only).**
- "Policy action completed" rows sit in five minute bins before `reported_at`: [−29,−28), [−22,−21), [−15,−14), [−8,−7) and [−3,−2).
- The slot is the row's **position in its job's policy sequence**:
  - legal hold, tombstone or analytics first;
  - then support redact;
  - then flow disable;
  - then backup block.
- In one S1 job that has both a legal hold and an analytics row, every later row shifts one slot (support to slot 2, flow to 3, backup to 4).

| Slot | S1 jobs: residual mod 60 (rows) | S2 jobs | Minute range seen (S1) |
|---|---|---|---|
| 0 (−29) | 40–41 (4) | 40–41 (5) | −28.87…−28.10 |
| 1 (−22) | 10–11 (19) | 10 (8) | −21.98…−21.12 |
| 2 (−15) | 39–40 (20) | 39–40 (8) | −14.98…−14.15 |
| 3 (−8) | 9–10 (20) | 9 (8) | −7.97…−7.02 |
| 4 (−3) | 39 (1) | — | −2.90 |

- Every one of 93 identifier-linked policy rows sits inside its slot's 2-s band. The 30-s band (residual mod 30 in 9–11) is the union of these bands. This is the Q4 correction above.
- **After rows** follow a chain, with consecutive own rows exactly 37.0 or 38.97 half-minutes apart (62/70 gaps). Their mod-60 phase depends on chain position: the first row is at 52 s in 94 of 161 cases, and at 21–22 s in 58. So after rows have **no** slot rule (SEEN).
- **Population:** the identifier-free worker rows with evidence are **125, all ANONYMIZE policy rows** (124 in slot 0, 1 in slot 1). No identifier-free after row has evidence, so the after-row phase never matters for analytics.

**Matching forms.**
- `band`: the prototype rule.
- `slot`: the slot's measured band.
- `slotpm`: slot parity, ±1 s.

**Limits:**
- all claims;
- L1: per-person exclusivity;
- L2: never anchored on an S5 pick;
- M: one-to-one matching, keeping only pairs present in every maximum matching;
- NF: only cases with no finding.

Anchors are the baseline (V0) accounts. "Rows vs reference" means: the harness with V0 accounts and the prototype signature, compared with the same harness under the form.

| Form / limit (`g2f2-g2f2_h2_analytics-0242`) | Test claims | Records with >1 person | Test pairs kept | DEV TP / FP / FN | Test rows changed vs reference (steps removed) | Prototype analytics steps removed / added (test cases) |
|---|---:|---:|---:|---|---|---|
| band / all (prototype rule) | 138 | 20 | 138 | 4 / 0 / 0 | 0 | 9 / 7 (11): anchor differences only |
| band / L1 + L2 (= T5 as ruled) | 138 | 20 | 85 | 4 / 0 / 0 | 49 (53) | 55 / 0 (51) |
| slot / all | 122 | 4 | 122 | 4 / 0 / 0 | 16 (16) | 25 / 7 (27) |
| **slot / M (H2 as worded: one-to-one after accounts)** | 122 | 4 | **114** | 4 / 0 / 0 | 24 (24) | **33 / 7 (35)** |
| slot / M + L2 | 122 | 4 | 101 | 4 / 0 / 0 | 37 (37) | 39 / 0 (39) |
| slot / L1 + L2 + NF | 122 | 4 | 100 | 4 / 0 / 0 | 38 (38) | 40 / 0 (40) |
| slotpm / M | 126 | 8 | 110 | 4 / 0 / 0 | 28 (28) | 37 / 7 (39) |

- **Prototype analytics steps:** the prototype has 140 signature analytics steps in 136 test cases, plus 4 on DEV.
- **The 7 "added" steps** come from account anchors (baseline vs prototype accounts), not from the analytics rule.
- **M equals L1** in every form: one-to-one matching recovers no multi-claimed record here.
- **With the first run's anchors** (independent S5), L1 alone gave 85 (Q4). With one-to-one S5 picks, L1 gives 98 and L1 + L2 gives 85. The anchors differ; this is not a contradiction.
- **With holdout competitors** (V1 anchors): band and slotpm lose case_21 (DEV FN 1, see H1), while **slot keeps 4/4**.
- **Every DEV row is unchanged** under every V0 form (19/22 exact on the baseline accounts; 131 steps; 899 fields).

**The no-findings (NF) test.** DEV cannot test it.
- Under every form, 0 DEV claims fall in a case with findings.
- DEV's 4 identifier-free gold analytics are all in COMPLETE cases (03, 21, 26, 27).
- DEV's 5 identifier-linked gold analytics (findings in 11, 18, 22, 30; and case_12's contact record) each have a **FAILED after row** and no policy row.
- On test, the claims that fall in cases with findings are: band 17, slot 6, slotpm 10. After L1 + L2, NF removes 1 more pair in each form.

**How DEV gold credits analytics** (SEEN; gold via `devgold.py`):

| DEV analytics | Linked by | Worker row | Observed state | Gold |
|---|---|---|---|---|
| 03 analytics_9406, 21 analytics_5335, 26 analytics_4566, 27 analytics_4574 | none (identifier-free) | policy, ANONYMIZE SUCCESS, slot 0, residual **41 s** on the case's own account | ANONYMIZED (evidence_94 / 92, also post-audit evidence_02) | `VERIFY_RECORD_ANONYMIZED`, cites the case's single file; all 4 cases COMPLETE |
| 11 analytics_2034, 18 analytics_037, 22 analytics_4440, 30 analytics_3697 | identifier (user_32, 50, 51, 30) | after, ANONYMIZE FAILED | IDENTIFIABLE | EXPOSED_PII → ANONYMIZE → VERIFY_ANONYMIZED |
| 12 analytics_9914 | identifier (old email hash) | after, DELETE FAILED | PRESENT (contact lookup) | REMAINING → DELETE → VERIFY_ABSENT |

**backup_3120** (batch 2026-09-02T12:00: DEV case_24 and case_26 plus 2 test requests).
- `backup_3120`, `support_4715` and `data_flow_6244` are **identifier-linked to user_26** (case_26's person).
- `backup_3120`'s residual is 9 s on case_26's grid and 11 s on case_24's. Both fit the 30-s band; only 9 s fits slot 3's band (9–10). `support_4715` (12 s) and `data_flow_6244` (42 s) fit neither band on case_24's grid.
- `analytics_4566` (identifier-free, slot 0) is at 41 s on case_26's grid (fits both forms) and at 43 s on case_24's (fits neither).
- Gold: case_26 has `VERIFY_RESTORE_BLOCKED backup_3120` and `VERIFY_RECORD_ANONYMIZED analytics_4566`, both citing evidence_92; case_24 has neither.
- The identifier link already keeps `backup_3120` out of case_24 (the `others()` filter), so no DEV row depends on the grid here. It is a SEEN example of the 30-s band accepting another job's row, which the slot band rejects.

**Experiment line H2:** hypothesis "identifier-free analytics match their job by the policy slot's own mod-60 band" → change slot / M on baseline anchors → delta: DEV 0 (4/4 kept, 0 FP); test kept pairs 85 (T5 as ruled) → 114, multi-person records 20 → 4. Against the prototype: 33 analytics steps removed and 7 added in 35 cases. With sample-input competitors, the slot form keeps DEV case_21 where the 30-s band loses it (+1 DEV step against that setup). Flips: none on DEV.

### H3. Absence by omission from scoped snapshots
**Script and terms.** `g2f2_h3_omission.py`.
- An omission is (time, file) for a resource missing from a snapshot whose declared scope covers its system, with file `captured_at` ≤ `audit_at`.
- **Sources:**
  - 11 SQL inventory files with `snapshot_scope` (78 system listings; some files omit systems, and evidence_90 scopes only `account_service`);
  - 113 JSON bundle snapshots, of which 3 are empty (all `account_service` `customer_profiles`: evidence_07, 31, 51).
- **Forms:**
  - `sql`;
  - `sql_replica_aware`: an omission never overrides a resource that has a replica-table copy;
  - `sql_strict`: replica-aware, and the SQL `support_records` table, which lists messages, never covers an attachment;
  - `json_empty`;
  - `json_all`: every snapshot read as a full listing;
  - `sql+json_empty`.
- **Combine rules:** (a) `latest` (prototype R6 plus omissions) or (b) `severe` (any violating observation at any time wins).
- **Inputs:** the prototype's accounts, without vision on DEV; test counts are given both without and with the vision table.

| Form / rule (`g2f2-g2f2_h3_omission-0242`) | DEV status / exact / steps / fields | DEV rows changed | Test rows changed (with vision) | Status flips (with vision) |
|---|---|---|---|---|
| (b) severe, no omission (= prototype "any violation") | 21 / 19 / 126 / 879 | case_26 | 9 | COMPLETE→INCOMPLETE 9 |
| (b) severe, every omission form | 21 / 19 / 126 / 879 | case_26 | 9 | COMPLETE→INCOMPLETE 9 |
| (a) latest, `sql` | 21 / 19 / 129 / 891 | **case_05** | 2 (34, 126) | INCOMPLETE→COMPLETE 1 |
| (a) latest, `sql_replica_aware` | 22 / 20 / 132 / 908 | none | 2 (34, 126) | INCOMPLETE→COMPLETE 1 |
| **(a) latest, `sql_strict`** | 22 / 20 / 132 / 908 | none | **1 (126)** | INCOMPLETE→COMPLETE 1 |
| (a) latest, `json_empty` | 22 / 20 / 132 / 908 | none | 0 | — |
| (a) latest, `json_all` | 22 / 20 / 132 / 908 | none | 0 | — |
| (a) latest, `sql+json_empty` | 21 / 19 / 129 / 891 | case_05 | 2 | INCOMPLETE→COMPLETE 1 |

**DEV contradictions (SEEN):**
- **(b) severe flips case_26 COMPLETE → INCOMPLETE** under every form. The stale 09-09 ACTIVE snapshot of `account_5684` beats the 09-15 404, and the row is −6 / +8 steps. This is the known 19/22 ablation (R6).
- **`sql` (a) flips hand-built case_05 INCOMPLETE → COMPLETE.** evidence_90 (primary inventory, 09-05T07:18, scoped to `account_service`) omits `account_005`, and that omission is later than the failover-replica row (evidence_54, 09-02T22:45).
  - Row change: the finding/remediation for `account_005` is removed, and its verification is now cited `evidence_54`.
  - Domain logic: a primary inventory cannot show that a replica copy is gone, hence the replica-aware form.

**Without vision** (inputs only), `sql`, `sql_replica_aware`, `sql_strict` and `json_all` also add 6 showcase steps (cases 35, 39, 50, 52, 53, 55). They give a default ABSENT to image-only resources that have no state without the PNG facts. With the vision table these vanish (INFERRED: an artefact of not reading the PNGs).

**DEV case_31** is unchanged in every form. The empty evidence_51 profile snapshot (09-15T12:00 = `audit_at`) gives ABSENT, the same as the default ABSENT (R8); the row stays COMPLETE, citing evidence_51. Consistent, but it does not discriminate.

**Test case_126:**
- `requested_at` 08-03T10:00, `audit_at` 08-17T10:00.
- `account_8819`'s only observation is PRESENT in a 08-11 snapshot, on a companion line inside post-audit `evidence_12` (captured 08-19).
- `evidence_87` (captured 08-17T09:42:50, at or before `audit_at`) scopes `account_service` and lists only `account_6673`.
- The prototype reports `FINDING account_8819 REPORT_REMAINING_RECORD evidence_87`, citing a file that does not contain the record. It is the **only** prototype finding, DEV or test, whose cited file lacks the resource (DEV 0, test 1; SEEN).
- Under `sql_strict` (a), the row becomes COMPLETE with three verifications citing evidence_87.

**case_34** (only in `sql` and `sql_replica_aware`): `support_9538`, an attachment observed IDENTIFIABLE on 09-15 in evidence_01, is not in the 09-16 inventory's `support_records`. Its finding and remediation drop out, and the status stays INCOMPLETE.

**Experiment line H3:**
- Hypothesis: a scoped snapshot at or before `audit_at` without the record is a dated ABSENT.
- Change (a) latest + `sql_strict` → delta: DEV 0; test 1 row (case_126 INCOMPLETE → COMPLETE).
- Change (b) severe → delta: DEV −1 exact (case_26 flips); test 9 COMPLETE → INCOMPLETE.
- Unscoped `sql` (a) → DEV −1 exact (case_05 flips).

### H4. Support category from the deletion worker's action
**Script.** `g2f2_h4_support.py`.

**Input cross-tab over every support resource (SEEN, no gold):**

| Prototype cue category × worker action | DELETE_RECORD | REDACT_RECORD | none |
|---|---:|---:|---:|
| SUPPORT_ATTACHMENT (cue seen) | 21 | 0 | 1 (support_001, DEV hand-built PDF) |
| SUPPORT_MESSAGE (no cue) | **8** | 163 | 2 |

- Wherever both are visible, the worker action matches the cue: 184/184.
- The 21 cued attachments carry their cue in a **separate** unit: a `ticket_attachments` replica table or bundle snapshot, or an `attachment_pii_scan` log line. Their ticket/message units look exactly like the targets' units.
- **The 8 uncued DELETE records:**
  - 7 are targets: `support_4541`, `5742`, `5750`, `6560`, `7432`, `8341` and `9474`. Each has only message-like units (`export:tickets`, `support_ticket_read_completed`, `support_records`) and one FAILED after row (SEEN).
  - The 8th, `support_002`, carries a contact query, a deletion-marker check and a SUCCESS row in the hand-built wording. It is in no predicted row (SEEN).

**DEV agreement:**
- 6 DEV support records have no cue. Every one has a REDACT worker row, and gold redacts every one: 6/6 agree, 0 disagree.
- The one DEV attachment (case_07 `support_001`) has a cue (PDF text layer) and no worker row.
- So **no DEV case has the targeted pattern** (no cue, DELETE worker), and DEV cannot test the hypothesis's DELETE branch.

**Forms:** cue at any time vs at or before `audit_at`, crossed with worker rows at any time, at or before `audit_at`, or inside the case's template windows.
- All 6 forms give the same result: **DEV 0 rows changed** (20/22, 132, 908).
- **Test: 7 rows changed** (47, 95, 143, 251, 287, 347, 443), with no status flip. Each one support record changes `REPORT_EXPOSED_PII → REDACT_RECORD → VERIFY_RECORD_REDACTED` to `REPORT_REMAINING_RECORD → DELETE_RECORD → VERIFY_RECORD_ABSENT`.
  - case_251: `support_4541`; case_347: `support_9474`; case_443: `support_8341`.

**Basis:** the input agreement is a data basis. The rule text (rule_05 REDACT, rule_06 DELETE) supports only the mapping, not the inference from the worker action, so the inference rests on DOMAIN LOGIC ONLY: the worker chose the operation for the category it holds. Whether gold treats the 7 as attachments is UNKNOWN.

**Experiment line H4:** hypothesis "with no cue, the worker's DELETE means attachment" → change (any form) → delta: DEV 0; test 7 rows (3 steps each re-typed); flips: none.

### Item 5 (report only). Audit records in DEV gold
**Script.** `g2f2_h5_audit.py`.
- **Not every DEV gold row has an `audit_record` step.** 17 of 22 have exactly one. The 5 without one are **case_01, 02, 05, 07 and 08**, exactly the hand-built set (SEEN).

**How each DEV audit record is linked:**
- Every linked unit joins on the person's **`user_id`**: in `subject_reference` 14 times, `correlation_key` 2, a trace-joined `*_started` line 3, and a flat-row `subject_reference` 1.
- Every linked line is at or after `requested_at` and at or before `audit_at`.

| Route | Cases (record, file) |
|---|---|
| Linked line in a file captured at or before `audit_at` (12) | 03 (2016, evidence_94 log); 11 (9394, evidence_03 handover); 12 (2945), 15 (1596), 17 (1797) and 19 (6793), all evidence_01 log; 16 (9528) and 22 (3482), evidence_05 replica table; 21 (3737), 26 (5416) and 27 (3830), evidence_92 export (also on 09-15 lines in post-audit evidence_02); 31 (6909, evidence_51 bundle) |
| Only a pre-audit line inside a post-audit file (companion, R4) (3) | 09 (4902, evidence_06 log, line 09-16T08:52); 24 (7095) and 30 (1707), evidence_02 bundle, line 09-15T12:00 |
| In no input (2) | 18 (6645), 20 (5569): U1 and U2, unchanged |

- **No DEV audit record is linked only by a line after `audit_at`.** So DEV has no example that would decide whether T27 extends to audit records, and post-audit linking would not recover U1/U2: no line anywhere names them (SEEN).
- **Test supplement** (inputs only), over 508 authorized cases:
  - 416 have an audit link in [`requested_at`, `audit_at`].
  - **8 have one only on a line after `audit_at`**: 33, 35, 39, 46, 50, 52, 53 and 55, the showcase cases plus case_46.
  - 84 have neither.
  - case_46's post-audit-only record is `audit_record_1797`, which is DEV case_17's gold audit record (same person, user_17; its line is 09-15, about 6 months after case_46's `audit_at`).

### Item 6 (no rule change). Test case_46 for the open questions
**Script.** `g2f2_h6_case46.py`. No proposal.
- **The request:** user_17 (`leonie.g9352@outlook.com`). `requested_at` 2026-03-08T03:00, `reported_at` 03-09T21:00 (COMPLETE), `audit_at` 03-11T08:00. The same person's DEV case_17 has `requested_at` 08-19 and `audit_at` 09-15.
- **What names `tombstone_17`:**
  - one text input, `activity_4011` (LINK_RESOURCE_IDENTITY, 03-10T06:07:01, +2.13 d after `requested_at`, −1.08 d before `audit_at`), with details "Data catalog linked tombstone_17 (user_17) to leonie.g9352@outlook.com and user_17";
  - the PNG `evidence_42` (`deleted_account_reference_20260310.png`, identity_service, captured 03-10T06:00:00, +2.12 d / −1.08 d). The hand vision table reads it as a retained reference with no direct identifiers, and its ID comes from `activity_4011`.
  - No other file names it (raw search, PDF text layers included).
- **For DEV case_17**, these inputs are −162 d before its `requested_at`, which is why case_17's gold omits `tombstone_17` (Q6).
- **The other pre-audit file holding a user_17 unit** is `evidence_67` (resource lookup log, captured 03-10T06:18:01): `account_6523`'s `profile_lookup_completed`, 404.
- **Prototype row:**
  - With vision: COMPLETE, `VERIFY_RECORD_ABSENT account_6523` and `VERIFY_RECORD_REDACTED tombstone_17`, both citing evidence_67 (F = the latest of evidence_42 06:00 and evidence_67 06:18).
  - Without vision: only the account step; the tombstone has no state.
- **Open question:**
  - The one-file-per-case citation gives the tombstone step a file that does not show it, as in DEV case_01, 02 and 31.
  - Whether gold cites evidence_67 for both steps, cites evidence_42 for the tombstone, or has no tombstone step is UNKNOWN.

### Candidate rules table (data first; nothing adopted)
| Candidate | Basis | DEV explained | DEV contradicted |
|---|---|---|---|
| H1 batch-wide one-to-one, D17 as qualifier, sample inputs as competitors | Data: 215/250 batches have one submit row per request; picks identical to T4 in every form. DOMAIN LOGIC: one account per person per batch. | 21/22 accounts, the same as the baseline (case_08: none) | 0 (accounts). With T5 analytics under the 30-s band: case_21 −1 step |
| H2 slot band for identifier-free analytics, one-to-one after accounts | Data: 93/93 identifier-linked policy rows in their slot's 2-s band. **No domain basis** (generator timing, as D17). | 4/4 identifier-free analytics | 0 |
| H2 NF (analytics only in no-finding cases) | DEV vacuous (0 claims in cases with findings). DOMAIN LOGIC weak. | — | 0 (untested) |
| H3 omission, (a) latest, `sql_strict` | Data: case_126 is the only finding citing a file that lacks the record. DOMAIN LOGIC: a scoped inventory without the record shows it absent there. | 31 (consistent, not discriminating) | 0 (the unscoped `sql` form contradicts case_05) |
| H3 (b) severe | — | — | **case_26** |
| H4 worker action decides support category when no cue is visible | Data: 184/184 agreement where both are visible. **DOMAIN LOGIC ONLY** for the inference. | 6/6 (REDACT branch) | 0 (DELETE branch untested) |

### Corrections to earlier G2 findings (re-measured; both values kept)
1. **Q4 / Summary 10 / Q7, mod-60:** "no input basis" (`g2-q7_mod60-0137`) → stable per policy slot, 93/93 (`g2f2-g2f2_h2_analytics-0242`). Marked in place.
2. **Not contradicted, only conditional:** Q4's "D17 limits cost 0 DEV analytics (4/4 kept)" holds without holdout inputs (`g2f2-g2f2_h1_batch-0242`, V0 and V3). With sample inputs as competitors (T32), the 30-s band with per-person exclusivity keeps 3/4.

### Open after follow-up 2
- **The S5 order** (unchanged from the first follow-up).
- **H4 targets:** whether gold treats the 7 uncued DELETE support records as attachments (no DEV case).
- **H3 sub-forms:** replica copies and attachments under SQL scope; DEV settles the replica case (case_05) and not the attachment case (case_34).
- **case_46:** which file gold cites, and whether a tombstone step exists.
- **UNEXPLAINED list:** U1/U2 (`audit_record_6645`/`5569`) and U4 (case_08's account) are unchanged. Item 5 adds that no line, post-audit or not, names U1 or U2.
