"""G2 follow-up, task 3: re-measure report 15 sec 6.4 trap counts from inputs only, with stated definitions.

Run: python3 -I -B notes/forensics/f3_traps.py [--run g2f-0152]
Writes runs/<run>/f3_traps.json. No gold is read. Request rows: DEV (22, holdout dropped by common.load_cases) and
test (518). File-level counts (decoys, replica-only resources, tombstones) use no request row at all, so no holdout
row enters them; they may include resources whose owner is a holdout user, which cannot be known without opening
holdout rows, and was not done. Case-scoped counts cover DEV + test only.

Report 15 sec 6.4 values being re-measured: historical request email DEV 1 / test 100; decoy evidence emails 22
(15 '.jr' look-alikes); replica-only rows 13, all accounts; tombstones 11 distinct (9 PII, 9 clean observations);
negation-trap requests DEV 0 / test 10. Extra rows of the same table are re-measured too (upper-case email,
post-audit files, connector/restore/replication rows, check rows).

Definitions (each applied to every row alike; nothing keyed on case IDs, file names or row positions):
  HE-a  request email (lower-cased) is not the user's current email.
  HE-b  the request email was replaced (user_audit_log old_value) at or before requested_at.
  HE-c  the request email was replaced at or before audit_at.
  UC    the request email contains an upper-case letter.
  DC-a  distinct e-mail strings in the raw text of every non-PNG evidence file (logs, JSON, SQL, TXT, PDF text layer)
        that match no current or historical email of any user.
  DC-b  distinct e-mail strings among extracted identifier fields (extract.py unit ids) that match no user.
        Look-alike classes: 'jr' (local part = a real local part + '.jr' / '_jr' / 'jr', same domain); 'near'
        (edit distance <= 2 to a real email, not 'jr'); 'other'.
  RP-a  resource whose every evidence observation is a row of an SQL table whose name contains 'replica'
        (and which has >= 1 such row). Split by identifier-linked or not.
  RP-b  RP-a, plus log lines emitted by a service whose name contains 'replica' count as replica rows.
  RP-o  broad form: a manifest origin containing 'replica' marks every row of that file as a replica row
        (these capture files also hold a customer_data_primary table, so this form over-counts; shown for contrast).
  RP-c  'drift': a resource with rows in both replica and non-replica sources (RP-b sources) whose states differ.
  TB-a  distinct tombstone_* resources with an evidence observation; observations split PII vs clean (unit_state).
  TB-b  distinct tombstone_* IDs anywhere in the inputs (evidence units + activity rows).
  NG-a  request text classified NOT_APPLICABLE by intent.py (keyword + negation rules; tuned to visible texts).
  NG-b  case matched to a CLASSIFY_REQUEST 'non-deletion' activity row, by (i) the row's account linked to the case's
        user at any time, or (ii) the row time in the account submit window, -75..-44 min from reported_at
        (a first form, 0..120 min after reported_at, matched no NA case and 11 authorized cases; superseded).
  NG-c  NG-a texts that contain deletion vocabulary before negation scoping (the trap proper) vs none.
  NG-d  deletion-authorized texts in which a negation pattern matched (a negation present, still authorised).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import DATASET, RUNS, T, World, load_cases  # noqa: E402
import intent  # noqa: E402
from extract import pdf_text  # noqa: E402
from identity import resolve_email  # noqa: E402
from logparse import parse_line  # noqa: E402
from solver import unit_state  # noqa: E402

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def lev(a: str, b: str, cap: int = 3) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2f-0152")
    a = ap.parse_args()
    W = World()
    cases, _ = load_cases()
    R: dict = {}
    people = W.people
    all_emails = {e for p in people.values() for e in p.emails}

    # ---------------------------------------------------------------- historical / upper-case request email
    he = Counter()
    for q in cases:
        s = q["_set"]
        em = q["email"].strip().lower()
        uid = resolve_email(q["email"], W.idx)
        p = people[uid]
        repl = [h for h in p.history if h[2] == "email" and h[3].lower() == em]
        he[(s, "n")] += 1
        he[(s, "HE_a_not_current")] += em != p.current["email"].lower()
        he[(s, "HE_b_replaced_by_requested_at")] += any(h[1] <= q["requested_at"] for h in repl)
        he[(s, "HE_c_replaced_by_audit_at")] += any(h[1] <= q["audit_at"] for h in repl)
        he[(s, "HE_replaced_after_audit_at_only")] += bool(repl) and not any(h[1] <= q["audit_at"] for h in repl)
        he[(s, "UC_uppercase")] += q["email"] != q["email"].lower()
        he[(s, "unresolved")] += uid is None
    R["historical_email"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(he.items())}

    # ---------------------------------------------------------------- decoy emails
    raw = defaultdict(set)  # email -> files
    for fid, row in W.manifest.items():
        p = DATASET / row["file_path"]
        suf = p.suffix.lower()
        if suf == ".png":
            continue
        txt = pdf_text(p) if suf == ".pdf" else p.read_text(encoding="utf-8", errors="ignore")
        for e in EMAIL.findall(txt):
            raw[e.lower()].add(fid)
    ext = defaultdict(set)
    for u in W.units:
        for i in u.ids:
            if "@" in i:
                ext[i].add(u.file_id or u.attrs.get("activity_id", "activity"))

    def classify(e):
        loc, dom = e.split("@", 1)
        for r in all_emails:
            rl, rd = r.split("@", 1)
            if rd == dom and loc in (rl + ".jr", rl + "_jr", rl + "jr"):
                return "jr", r
        best = min(all_emails, key=lambda r: lev(e, r))
        return ("near", best) if lev(e, best) <= 2 else ("other", None)

    for name, src in (("DC_a_raw_text", raw), ("DC_b_extracted_ids", ext)):
        dec = sorted(e for e in src if e not in all_emails)
        cls = {e: classify(e) for e in dec}
        R[name] = dict(distinct_emails=len(src), decoys=len(dec), by_class=dict(Counter(c for c, _ in cls.values())),
                       files_with_decoy=len({f for e in dec for f in src[e]}),
                       decoys_list=[(e, cls[e][0], cls[e][1], sorted(src[e])) for e in dec])
    # case-scoped: DEV/test cases whose user has a look-alike decoy ('jr' or 'near') in some evidence file
    dec_raw = {e: classify(e) for e in raw if e not in all_emails}
    cs = Counter()
    for q in cases:
        uid = resolve_email(q["email"], W.idx)
        mine = people[uid].emails
        hit = [e for e, (c, r) in dec_raw.items() if c in ("jr", "near") and r in mine]
        if hit:
            cs[q["_set"]] += 1
            pre = any(W.manifest[f]["captured_at"] <= q["audit_at"] for e in hit for f in raw[e])
            cs[q["_set"] + "_in_pre_audit_file"] += pre
    R["DC_case_scoped_lookalike_of_own_email"] = dict(cs)

    # ---------------------------------------------------------------- replica-only / drift
    rep_service_lines = set()  # (file_id, ts, resource_id) of log lines from a *replica* service
    for fid, row in W.manifest.items():
        p = DATASET / row["file_path"]
        if p.suffix.lower() != ".log":
            continue
        for line in p.open(encoding="utf-8"):
            r = parse_line(line)
            if r and r["service"] and "replica" in r["service"] and r["kv"].get("resource_id"):
                rep_service_lines.add((fid, r["ts"], r["kv"]["resource_id"]))

    def is_rep(u, form: str) -> bool:
        if "replica" in (u.table or ""):
            return True
        if form == "origin" and u.file_id and "replica" in W.manifest[u.file_id]["origin"]:
            return True
        return form in ("logs", "origin") and (u.file_id, u.ts, u.resource_id) in rep_service_lines

    for name, form in (("RP_a_replica_only", "table"), ("RP_b_replica_only_with_replica_logs", "logs"),
                       ("RP_o_replica_only_by_file_origin", "origin")):
        only, both = [], []
        for rid, us in W.by_res.items():
            us = [u for u in us if u.file_id]
            if not us:
                continue
            flags = [is_rep(u, form) for u in us]
            if all(flags):
                only.append(rid)
            elif any(flags):
                both.append(rid)
        linked = [r for r in only if W.res_users.get(r)]
        R[name] = dict(n=len(only), by_prefix=dict(Counter(r.rsplit("_", 1)[0] for r in only)),
                       identifier_linked=len(linked), linked_by_prefix=dict(Counter(r.rsplit("_", 1)[0] for r in linked)),
                       resources=sorted(only), mixed_n=len(both),
                       tables=dict(Counter(u.table or W.manifest[u.file_id]["origin"] for r in only for u in W.by_res[r] if u.file_id)))
    drift = []
    for rid, us in W.by_res.items():
        us = [u for u in us if u.file_id]
        r_st = {unit_state(u) for u in us if is_rep(u, "logs")} - {None}
        p_st = {unit_state(u) for u in us if not is_rep(u, "logs")} - {None}
        if r_st and p_st and r_st != p_st:
            drift.append(rid)
    R["RP_c_drift_state_differs"] = dict(n=len(drift), by_prefix=dict(Counter(r.rsplit("_", 1)[0] for r in drift)),
                                         resources=sorted(drift))
    # case-scoped: DEV/test cases with an RP-a resource identifier-linked in [requested_at, audit_at]
    rpa = set(R["RP_a_replica_only"]["resources"])
    cs = Counter()
    for q in cases:
        uid = resolve_email(q["email"], W.idx)
        if any(uid in u.users and u.resource_id in rpa and q["requested_at"] <= u.ts <= q["audit_at"] for u in W.units):
            cs[q["_set"]] += 1
    R["RP_case_scoped_linked_in_window"] = dict(cs)

    # ---------------------------------------------------------------- tombstones
    tb_units = [u for u in W.units if u.resource_id and u.resource_id.startswith("tombstone_") and u.file_id]
    st = Counter(unit_state(u) for u in tb_units)
    per = defaultdict(set)
    for u in tb_units:
        per[u.resource_id].add(unit_state(u))
    R["TB_a_evidence"] = dict(distinct=len(per), observations=len(tb_units), observation_states=dict(st),
                              resources_with_pii_obs=sum(1 for v in per.values() if "PII_TOMBSTONE" in v),
                              resources_with_clean_obs=sum(1 for v in per.values() if "CLEAN_TOMBSTONE" in v),
                              resources_with_both=sum(1 for v in per.values() if {"PII_TOMBSTONE", "CLEAN_TOMBSTONE"} <= v))
    ids_any = {u.resource_id for u in W.units if u.resource_id and u.resource_id.startswith("tombstone_")}
    ids_any |= {x["resource_id"] for x in W.acts if x["resource_id"].startswith("tombstone_")}
    R["TB_b_any_input"] = dict(distinct=len(ids_any))
    cs = Counter()
    for q in cases:
        uid = resolve_email(q["email"], W.idx)
        lk = {u.resource_id for u in W.units if uid in u.users and u.resource_id and u.resource_id.startswith("tombstone_")
              and q["requested_at"] <= u.ts <= q["audit_at"]}
        for rid in lk:
            obs = [u for u in W.by_res[rid] if u.ts <= q["audit_at"] and unit_state(u)]
            if not obs:
                cs[q["_set"] + "|no_state"] += 1
                continue
            last = max(u.ts for u in obs)
            sts = {unit_state(u) for u in obs if u.ts == last}
            cs[q["_set"] + "|" + ("PII" if "PII_TOMBSTONE" in sts else "clean")] += 1
    R["TB_case_scoped_linked_in_window_state_at_audit"] = dict(cs)

    # ---------------------------------------------------------------- negation / NA
    cl_rows = [x for x in W.acts if x["event_type"] == "CLASSIFY_REQUEST"]
    ng = Counter()
    na_detail = []
    for q in cases:
        s = q["_set"]
        ok, why = intent.authorizes_deletion(q["request_text"])
        uid = resolve_email(q["email"], W.idx)
        rep = T(q["reported_at"])
        by_owner = any(uid in W.res_users.get(x["resource_id"], set()) for x in cl_rows)
        by_time = any(-75 <= (x["_t"] - rep).total_seconds() / 60 <= -44 for x in cl_rows)
        by_time_after = any(0 <= (x["_t"] - rep).total_seconds() / 60 <= 120 for x in cl_rows)
        has_del_word = bool(intent.DELETE_WORDS.search(q["request_text"]))
        neg_matched = any(re.search(pt, q["request_text"], re.I) for pt in intent.NEGATED)
        ng[(s, "NG_a_intent_NA")] += not ok
        ng[(s, "NG_b_i_classify_row_owner")] += by_owner
        ng[(s, "NG_b_ii_classify_row_time")] += by_time
        ng[(s, "NG_a_and_b_ii")] += (not ok) and by_time
        ng[(s, "NG_a_and_b_i")] += (not ok) and by_owner
        ng[(s, "NG_b_ii_first_form_0_120_after")] += by_time_after
        ng[(s, "NG_c_NA_with_deletion_word")] += (not ok) and has_del_word
        ng[(s, "NG_c_NA_without_deletion_word")] += (not ok) and not has_del_word
        ng[(s, "NG_d_authorised_with_negation_match")] += ok and neg_matched
        ng[(s, "keep_phrase")] += bool(intent.KEEP.search(q["request_text"]))
        if not ok or by_time or by_owner:
            na_detail.append(dict(case=q["case_id"], set=s, intent_ok=ok, why=why, by_owner=by_owner, by_time=by_time,
                                  del_word=has_del_word, status=q["reported_status"]))
    R["negation"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(ng.items())}
    R["negation_detail"] = na_detail
    R["classify_rows"] = len(cl_rows)

    # ---------------------------------------------------------------- other sec 6.4 rows
    acts = Counter()
    for x in W.acts:
        d = x["details"]
        if x["event_type"] == "SYNC_RECORD" and "repopulated" in d:
            acts["connector_repopulation_rows"] += 1
        if x["event_type"] == "RESTORE_BACKUP":
            acts["restore_backup_rows"] += 1
        if x["event_type"] == "SYNC_RECORD" and "Replication worker" in d:
            acts["replication_sync_rows"] += 1
        if x["event_type"] == "CHECK_DATA_FLOW":
            acts["check_data_flow_rows"] += 1
        if x["event_type"] == "CHECK_RESTORE_ACCESS":
            acts["check_restore_access_rows"] += 1
    R["activity_trap_rows"] = dict(acts)
    pa = Counter()
    for q in cases:
        uid = resolve_email(q["email"], W.idx)
        post = {u.file_id for u in W.units if u.file_id and uid in u.users and W.manifest[u.file_id]["captured_at"] > q["audit_at"]}
        post_pre_lines = {u.file_id for u in W.units if u.file_id and uid in u.users and W.manifest[u.file_id]["captured_at"] > q["audit_at"]
                          and u.ts <= q["audit_at"]}
        pa[(q["_set"], "user_linked_unit_in_post_audit_file")] += bool(post)
        pa[(q["_set"], "pre_audit_line_inside_post_audit_file")] += bool(post_pre_lines)
        pa[(q["_set"], "user_linked_line_after_audit_at")] += any(uid in u.users and u.ts > q["audit_at"] for u in W.units)
    R["post_audit"] = {f"{k[0]}|{k[1]}": v for k, v in sorted(pa.items())}
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "f3_traps.json").write_text(json.dumps(R, indent=1, default=list))
    for k, v in R.items():
        if k in ("negation_detail",):
            continue
        if isinstance(v, dict) and "decoys_list" in v:
            v = {kk: vv for kk, vv in v.items() if kk != "decoys_list"}
        if isinstance(v, dict) and "resources" in v and len(v["resources"]) > 20:
            v = {kk: vv for kk, vv in v.items() if kk != "resources"}
        print(k, json.dumps(v, default=list))


if __name__ == "__main__":
    main()
