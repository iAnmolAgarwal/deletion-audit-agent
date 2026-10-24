"""G2 follow-up 2, hypothesis 3: absence by omission from scoped snapshots captured at or before audit_at.

Run: python3 -I notes/forensics/g2f2_h3_omission.py --run g2f2-HHMM
Writes runs/<run>/h3_omission.json.

An omission observation of resource R (system S) is (time, file): a snapshot in a file with manifest
captured_at <= audit_at, whose declared scope covers S, and which has no row for R. It reads as ABSENT at that time.
Source forms (each applied to every resource alike; no case ID, file name or row position is a signal):
  sql        : SQL inventory files with a snapshot_scope table. S is covered when snapshot_scope lists S; the typed
               table for S (extract.SQL_TABLE_SYSTEM) is the listing; time = that scope row's captured_at.
  json_empty : JSON bundle snapshots with zero records; S = data_store; collection must be the resource's
               collection type (support: conversations for messages, ticket_attachments for attachments).
  json_all   : every JSON bundle snapshot read as a full listing of its (data_store, collection) at its captured_at.
  sql+json_empty : both.
  sql_replica_aware : sql, but an omission never overrides a resource that has a replica-table copy (a primary
               inventory's scope does not cover replica stores).
  sql_strict : sql_replica_aware, and a support attachment is never covered by the SQL support_records table
               (that table lists messages).
Combine rules (state at audit_at over identifier, companion and omission observations, all <= audit_at):
  latest : the latest observation by record time wins; same-time conflicts go to the violating state (prototype R6).
  severe : any violating observation at any time wins; otherwise the latest.
The 'severe' rule with no omission source is also run (it is the prototype's 'any_violation' ablation).
Row effects: solve2 (prototype rules, prototype accounts) with the omission hook vs the prototype replay.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import RUNS, DATASET, World, Hooks, solve2, row_diff, load_cases  # noqa: E402
from extract import SQL_TABLE_SYSTEM, SERVICE_FROM_RID, load_sql  # noqa: E402
from solver import Opts, unit_state  # noqa: E402
from score import aggregate, score_case  # noqa: E402
from vision_facts import vision_units  # noqa: E402  (hand table; test-side count only, as report 15 sec 6)

COLL_OF = {"account_service": "customer_profiles", "search_service": "customer_search_documents",
           "analytics_platform": "customer_analytics_reports", "backup_service": "backup_catalog",
           "export_service": "customer_export_jobs", "integration_service": "connector_configurations",
           "security_service": "security_audit_events", "identity_service": "deleted_customer_references"}


def system_of(rid: str) -> str | None:
    return next((s for p, s in SERVICE_FROM_RID if rid.startswith(p)), None)


def is_attachment(W, rid: str) -> bool:
    for u in W.by_res.get(rid, []):
        a = u.attrs
        if (a.get("event") == "attachment_pii_scan" or u.kind.endswith("ticket_attachments")
                or a.get("record_type") == "SUPPORT_ATTACHMENT" or a.get("attachment") or a.get("file")):
            return True
    return False


def scoped_listings(W) -> dict:
    """form -> list of (system, collection_or_None, ts, file_id, file_captured, listed_ids)."""
    out = defaultdict(list)
    for fid, row in W.manifest.items():
        p = DATASET / row["file_path"]
        cap = row["captured_at"]
        if p.suffix == ".sql":
            text = p.read_text(encoding="utf-8")
            if "snapshot_scope" not in text:
                continue
            con = load_sql(text)
            scope = dict(con.execute("select origin_system, captured_at from snapshot_scope").fetchall())
            for t, sysid in SQL_TABLE_SYSTEM.items():
                if sysid not in scope:
                    continue
                listed = {r[0] for r in con.execute(f'select resource_id from "{t}"')}
                out["sql"].append((sysid, None, scope[sysid], fid, cap, listed))
            con.close()
        elif p.suffix == ".json":
            d = json.loads(p.read_text(encoding="utf-8"))
            for snap in d.get("snapshots", []):
                if snap["collection"] == "operational_record_history":
                    continue
                listed = {r.get("resource_id") for r in snap["records"]}
                ent = (snap["data_store"], snap["collection"], snap["captured_at"], fid, cap, listed)
                out["json_all"].append(ent)
                if not snap["records"]:
                    out["json_empty"].append(ent)
    out["sql+json_empty"] = out["sql"] + out["json_empty"]
    return out


def omission_units(W, listings: list, rids: set, skip_attachments: bool = False) -> dict:
    om = defaultdict(list)
    for rid in rids:
        s = system_of(rid)
        if not s:
            continue
        att = is_attachment(W, rid) if s == "support_platform" else False
        if skip_attachments and att:
            continue  # sql_strict: the SQL support_records table lists messages, not attachments
        for sysid, coll, ts, fid, cap, listed in listings:
            if sysid != s or rid in listed:
                continue
            if coll is not None:
                want = ("ticket_attachments" if att else "support_conversations") if s == "support_platform" else COLL_OF.get(s)
                if coll != want:
                    continue
            om[rid].append((ts, fid, cap))
    return dict(om)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    W = World()
    R: dict = {}
    L = scoped_listings(W)
    R["listings"] = {k: len(v) for k, v in L.items()}
    R["sql_scope_files"] = sorted({x[3] for x in L["sql"]})
    R["json_empty_snapshots"] = [(x[0], x[1], x[2], x[3]) for x in L["json_empty"]]
    proto = {q["case_id"]: solve2(q, W, Opts(), Hooks()) for q in cases}
    rids = {u.resource_id for u in W.units if u.resource_id} | {x["resource_id"] for x in W.acts}
    dev = sorted((q for q in cases if q["_set"] == "dev"), key=lambda r: r["case_id"])
    results = {}
    Wv = World(vision_units=vision_units())
    proto_v = {q["case_id"]: solve2(q, Wv, Opts(), Hooks()) for q in cases if q["_set"] == "test"}
    for form in ("none", "sql", "sql_replica_aware", "sql_strict", "json_empty", "json_all", "sql+json_empty"):
        base_form = "sql" if form in ("sql_replica_aware", "sql_strict") else form
        om = omission_units(W, L[base_form], rids, skip_attachments=(form == "sql_strict")) if form != "none" else {}
        for rule in ("latest", "severe"):
            if form == "none" and rule == "latest":
                continue
            hk = Hooks(omission=rule, omission_units=om, omission_replica_aware=(form in ("sql_replica_aware", "sql_strict")))
            res = {q["case_id"]: solve2(q, W, Opts(), hk) for q in cases}
            res_v = {q["case_id"]: solve2(q, Wv, Opts(), hk) for q in cases if q["_set"] == "test"}
            tch_v = sorted((c for c in res_v if row_diff(proto_v[c], res_v[c])), key=lambda s: int(s[5:]))
            sc = []
            for q in dev:
                g = gold[q["case_id"]]
                s = score_case(res[q["case_id"]].status, res[q["case_id"]].steps, g["status"], g["steps"])
                s["case_id"] = q["case_id"]
                s["exact"] = s["status_ok"] and s["steps_ok"]
                sc.append(s)
            ag = aggregate(sc)
            tch = [q["case_id"] for q in cases if q["_set"] == "test" and row_diff(proto[q["case_id"]], res[q["case_id"]])]
            st_flip = Counter(f"{proto[c].status}->{res[c].status}" for c in tch if proto[c].status != res[c].status)
            kinds = Counter()
            for c in tch:
                for d in row_diff(proto[c], res[c]):
                    kinds[re.sub(r" [a-z_]+_\d+ ", " <rid> ", d.split(" \"")[0]).rsplit(" ", 2)[0]] += 1
            results[f"{form}|{rule}"] = dict(
                dev_status_exact=ag["status_exact"], dev_case_exact=ag["case_exact"], dev_step_tp=ag["step_tp"],
                dev_step_pred=ag["step_pred"], dev_field_hits=ag["field_hits"],
                dev_inexact=[s["case_id"] for s in sc if not s["exact"]],
                dev_row_changes={q["case_id"]: row_diff(proto[q["case_id"]], res[q["case_id"]]) for q in dev
                                 if row_diff(proto[q["case_id"]], res[q["case_id"]])},
                test_cases_changed=len(tch), test_status_flips=dict(st_flip), test_change_kinds=dict(kinds.most_common(12)),
                test_cases=sorted(tch, key=lambda s: int(s[5:])),
                test_cases_changed_with_vision=tch_v,
                test_status_flips_with_vision=dict(Counter(f"{proto_v[c].status}->{res_v[c].status}" for c in tch_v if proto_v[c].status != res_v[c].status)),
                case_126=dict(status=res["case_126"].status, steps=[f"{s['phase']} {s['resource_id']} {s['operation']} {s['evidence_id']}" for s in res["case_126"].steps],
                              state=res["case_126"].trace["state"]),
                case_31=dict(status=res["case_31"].status, steps=[f"{s['phase']} {s['resource_id']} {s['operation']} {s['evidence_id']}" for s in res["case_31"].steps]))
            if form != "none":
                audit_of = {q["case_id"]: q["audit_at"] for q in dev}
                obs = {}
                for c in gold:
                    d = {}
                    for st in gold[c]["steps"]:
                        rid = st["resource_id"]
                        hits = [(t, f) for t, f, cap in om.get(rid, []) if t <= audit_of[c] and cap <= audit_of[c]]
                        if hits:
                            d[rid] = sorted(set(hits))
                    if d:
                        obs[c] = d
                results[f"{form}|{rule}"]["omission_obs_for_dev_gold_resources"] = obs
    R["forms"] = results
    # diagnostic: prototype findings whose cited file holds no observation of the resource (with vision on test)
    diag = {"dev": [], "test": []}
    for q in cases:
        c = q["case_id"]
        r = proto[c] if q["_set"] == "dev" else proto_v[c]
        Wx = W if q["_set"] == "dev" else Wv
        for st in r.steps:
            if st["phase"] != "FINDING":
                continue
            fids = {u.file_id for u in Wx.by_res.get(st["resource_id"], []) if u.file_id}
            if st["evidence_id"] not in fids:
                diag[q["_set"]].append(f"{c} {st['resource_id']} cites {st['evidence_id']}")
    R["prototype_findings_citing_a_file_without_the_resource"] = {k: dict(n=len(v), rows=v) for k, v in diag.items()}
    R["prototype_case_126"] = dict(status=proto["case_126"].status, steps=[f"{s['phase']} {s['resource_id']} {s['operation']} {s['evidence_id']}" for s in proto["case_126"].steps])
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h3_omission.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps({k: R[k] for k in ("listings", "sql_scope_files", "json_empty_snapshots", "prototype_case_126")}, default=str))
    for k, v in results.items():
        vv = {x: y for x, y in v.items() if x not in ("test_cases", "omission_obs_for_dev_gold_resources")}
        print(k, json.dumps(vv, default=str)[:2500])


if __name__ == "__main__":
    main()
