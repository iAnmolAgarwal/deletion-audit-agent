"""G2 Q1/Q3/Q4: the T4 primary-account order, stage by stage, on DEV and on the 518 test inputs.

Run:  python3 -I notes/forensics/acct_stages.py [--window LO,HI] [--no-result] [--no-owner] [--scope devtest|split]
                                              [--band-pad S] [--fallback10] [--tag NAME]
Writes runs/g2-<HHMM>/acct_stages_<tag>.json and prints a summary.

Definitions (stated, applied to every row alike; nothing keyed on case IDs, files or row positions):
  account delete row = system_activity row with event_type DELETE_RECORD and target_system account_service.
  offset            = (event_time - reported_at) in minutes.
  S1 identifier link = an account_service/profile_service unit linked to the request's user (current or
                       historical identifier) with line time in [requested_at, audit_at].
  S2 timed rule      = account delete rows with LO <= offset <= HI (default -75..-44, inclusive) and
                       reported_result == map(reported_status); optionally (--owner, default on) excluding
                       accounts identifier-linked (any time) to a different user.
  S3 one-to-one      = global over the scope: S1 accounts and every unique candidate are removed from other
                       cases' candidate sets, repeated to a fixed point.
  S4 D17 tie-break   = keep candidates whose 60-s phase A fits every non-submit deletion-worker row of the
                       case's own identifier-linked resources (prototype sig_match bands); then S3 again.
  S5 D18 flagged pick= the candidate closest to offset -60 min (prototype tie order), flagged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import (RUNS, T, World, STATUS_TO_RESULT, act_template, TEMPLATE_WINDOWS, account_delete_rows,  # noqa: E402
                    gold_account, id_linked_accounts, load_cases, off_min)
import solver  # noqa: E402
from identity import resolve_email  # noqa: E402


def own_after_rows(W, q, linked_res: set, rep):
    dw = [a for a in W.acts if a["source_system"] == "deletion_worker"]
    out = []
    for a in dw:
        if a["resource_id"] not in linked_res or act_template(a) == "submit":
            continue
        lo, hi = TEMPLATE_WINDOWS[act_template(a)]
        if lo <= off_min(a, rep) <= hi:
            out.append(a)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="-75,-44")
    ap.add_argument("--no-result", action="store_true")
    ap.add_argument("--no-owner", action="store_true")
    ap.add_argument("--scope", default="devtest", choices=["devtest", "split"])
    ap.add_argument("--band-pad", type=int, default=0, help="widen D17 bands by S seconds each side (negative narrows)")
    ap.add_argument("--fallback10", action="store_true", help="option: if S2 empty, take rows within +-10 min (result-matched first)")
    ap.add_argument("--tag", default="base")
    ap.add_argument("--run", default="g2-0137")
    a = ap.parse_args()
    LO, HI = (float(x) for x in a.window.split(","))
    if a.band_pad:
        solver.SIG_BANDS["policy"] = (9 - a.band_pad, 11 + a.band_pad)
        solver.SIG_BANDS["after"] = (20 - a.band_pad, 22 + a.band_pad)

    W = World()
    cases, gold = load_cases()
    ADR = account_delete_rows(W)
    info = {}
    for q in cases:
        uid = resolve_email(q["email"], W.idx)
        rep = T(q["reported_at"])
        want = STATUS_TO_RESULT.get(q["reported_status"])
        il = id_linked_accounts(W, uid, q, "window") if uid and uid != "AMBIGUOUS" else set()
        linked_res = {u.resource_id for u in W.units if uid in u.users and u.resource_id
                      and q["requested_at"] <= u.ts <= q["audit_at"]}
        inwin = [r for r in ADR if LO <= off_min(r, rep) <= HI]
        matched = [r for r in inwin if a.no_result or r["reported_result"] == want]
        owned_ok = [r for r in matched if a.no_owner or not (W.res_users.get(r["resource_id"], set()) - {uid})]
        near10 = [r for r in ADR if -10 <= off_min(r, rep) <= 10]
        after_audit_user = [r for r in ADR if r["event_time"] > q["audit_at"]
                            and uid in W.res_users.get(r["resource_id"], set())]
        info[q["case_id"]] = dict(q=q, uid=uid, rep=rep, want=want, il=sorted(il), linked_res=linked_res,
                                  inwin=inwin, matched=matched, cand={r["resource_id"] for r in owned_ok},
                                  near10=near10, after_audit_user=after_audit_user, stage=None, pick=None, flag=False)

    def scope_ids(cid):
        if a.scope == "devtest":
            return list(info)
        s = info[cid]["q"]["_set"]
        return [c for c in info if info[c]["q"]["_set"] == s]

    # S1
    for c, d in info.items():
        if d["il"]:
            d["stage"], d["pick"] = "S1_identifier", d["il"][0]
            d["n_il"] = len(d["il"])
    # fallback option (applies only where S2 is empty and no S1)
    for c, d in info.items():
        if d["stage"] is None and not d["cand"] and a.fallback10:
            fb = [r for r in d["near10"] if not (W.res_users.get(r["resource_id"], set()) - {d["uid"]})]
            fm = [r for r in fb if r["reported_result"] == d["want"]] or fb
            d["cand"] = {r["resource_id"] for r in fm}
            d["fallback"] = True
    d2 = {c: set(d["cand"]) for c, d in info.items() if d["stage"] is None}
    pre_121 = {c: len(v) for c, v in d2.items()}

    def one_to_one(stage_name):
        changed = True
        while changed:
            changed = False
            taken = defaultdict(set)
            for c, d in info.items():
                if d["pick"]:
                    taken[d["q"]["_set"] if a.scope == "split" else "all"].add(d["pick"])
            for c, cs in d2.items():
                if info[c]["stage"]:
                    continue
                key = info[c]["q"]["_set"] if a.scope == "split" else "all"
                new = cs - taken[key]
                if new != cs:
                    d2[c] = new
                    info[c].setdefault("removed_by_121", set()).update(cs - new)
                    changed = True
                if len(d2[c]) == 1:
                    info[c]["stage"], info[c]["pick"] = stage_name, next(iter(d2[c]))
                    changed = True

    one_to_one("S2S3_timed_unique")
    # distinguish S2 unique before any removal vs S3 made unique
    for c, d in info.items():
        if d["stage"] == "S2S3_timed_unique":
            d["stage"] = "S2_timed_unique" if pre_121[c] == 1 else "S3_one_to_one"
    # S4 D17
    for c, cs in d2.items():
        d = info[c]
        if d["stage"] or len(cs) < 2:
            continue
        own = own_after_rows(W, d["q"], d["linked_res"], d["rep"])
        if not own:
            d["d17"] = "no_own_rows"
            continue
        rows = {r["resource_id"]: r for r in d["inwin"]}
        fit = set()
        for rid in cs:
            A = (rows[rid]["_t"] - d["rep"]).total_seconds() % 60
            if all(solver.sig_match(o, d["rep"], A) for o in own):
                fit.add(rid)
        d["d17"] = f"fit {len(fit)}/{len(cs)}"
        if fit and len(fit) < len(cs):
            d2[c] = fit
            if len(fit) == 1:
                d["stage"], d["pick"] = "S4_d17", next(iter(fit))
    one_to_one("S4b_one_to_one_after_d17")
    # S5
    for c, cs in d2.items():
        d = info[c]
        if d["stage"]:
            continue
        if not cs:
            d["stage"] = "NONE"
            continue
        rows = {r["resource_id"]: r for r in d["inwin"] + d["near10"]}
        pick = sorted(cs, key=lambda r: abs(off_min(rows[r], d["rep"]) + 60))[0]
        d["stage"], d["pick"], d["flag"] = "S5_flagged", pick, True
        d["tie_size"] = len(cs)

    # no-candidate classification (before one-to-one): S1 absent and S2 empty
    def reason(d):
        if d["stage"] == "S1_identifier":
            return None
        if pre_121.get(d["q"]["case_id"], 0) > 0 and not d.get("fallback"):
            return None
        rep = d["rep"]
        if not d["inwin"]:
            if d["near10"]:
                return "d_row_within_10min_only"
            if d["after_audit_user"]:
                return "b_user_rows_only_after_audit"
            anyrow = [r for r in ADR if -180 <= off_min(r, rep) <= 180]
            return "a_no_row_in_window" if anyrow else "a0_no_row_within_3h"
        if not d["matched"]:
            return "c_result_mismatch"
        return "e_all_matched_owned_by_other_user"

    out = {"args": vars(a), "cases": {}}
    for c, d in info.items():
        g = gold_account(gold[c]) if d["q"]["_set"] == "dev" else None
        out["cases"][c] = dict(set=d["q"]["_set"], stage=d["stage"], pick=d["pick"], flag=d["flag"],
                               il=d["il"], n_inwin=len(d["inwin"]), n_matched=len(d["matched"]),
                               cand_pre121=pre_121.get(c), removed_by_121=sorted(d.get("removed_by_121", [])),
                               d17=d.get("d17"), tie_size=d.get("tie_size"), reason=reason(d),
                               fallback=d.get("fallback", False), gold=g,
                               correct=(None if g is None else (d["pick"] in g)))
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    p = RUNS / a.run / f"acct_stages_{a.tag}.json"
    p.write_text(json.dumps(out, indent=1, default=str))

    for s in ("dev", "test"):
        rows = [v for v in out["cases"].values() if v["set"] == s]
        st = Counter(v["stage"] for v in rows)
        print(f"== {s} ({len(rows)}) stages:", dict(sorted(st.items())))
        if s == "dev":
            for k in sorted(st):
                ok = sum(1 for v in rows if v["stage"] == k and v["correct"])
                print(f"   {k}: {st[k]} resolved, {ok} correct")
        rs = Counter(v["reason"] for v in rows if v["reason"])
        print(f"   no-candidate reasons:", dict(rs))
    print("written", p)


if __name__ == "__main__":
    main()
