"""G2 follow-up 2, hypothesis 1: global account assignment per deletion batch (would amend T4 step 3).

Run: python3 -I notes/forensics/g2f2_h1_batch.py --run g2f2-HHMM
Writes runs/<run>/h1_batch.json.

Batch = every request (DEV, holdout INPUTS, test) with the same reported_at. Holdout inputs join only here, by the
developer's instruction (T32); their gold is never opened, and only aggregate counts are reported for them.
A candidate (request, account delete row) qualifies when (i) the row is in -75..-44 min of reported_at, (ii) its result
matches the reported status, (iii) every identifier-linked deletion-worker row of the request's job fits the
candidate's 30-s grid (prototype sig_match; vacuous when the request has no such row), plus the owner filter
(an account identifier-linked to a different person never qualifies). One owner per person (T29).
Variants (nothing keyed on case IDs, files or row positions; every order is named):
  V0 baseline   : T4 + T26..T29, global pass, D17 as S4 tie-break, no holdout inputs.
  V1 H1         : batch pass, D17 as qualifier, holdout inputs, unique-first propagation, then S5 matching.
  V2 H1-forced  : as V1, but the pass assigns an account only when it is the request's pick in every maximum matching.
  V3            : V1 without holdout inputs.
  V4            : V1 with D17 back as the S4 tie-break (isolates 'D17 as qualifier').
  V5            : V1 with own rows linked at any line time <= audit_at (second form of condition iii).
  V6            : V1 with a global pass instead of per batch (isolates 'per batch').
Joint analytics: each assigned account's grid A attaches the identifier-free deletion-worker rows that fit it
(prototype attach rule: non-submit row in its template window, resource linked to nobody, with admissible
evidence <= audit_at); T5 limits applied per person (a record claimed by two people is dropped; never anchored
on an S5 pick).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from dataclasses import replace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import (RUNS, T, World, AcctEngine, AcctOpts, Hooks, solve2, row_diff, gold_account,  # noqa: E402
                      load_cases, load_holdout_inputs, act_template, TEMPLATE_WINDOWS, off_min, sig_match)
from solver import Opts  # noqa: E402
from score import aggregate, score_case  # noqa: E402

NAMED = ["case_157", "case_192", "case_224", "case_230", "case_275", "case_287", "case_290", "case_304", "case_359"]


def analytics_claims(W, info: dict, picks: dict) -> dict:
    """case -> {rid: (activity_id, anchor_stage)} identifier-free rows that fit the case's assigned account grid."""
    dw = [a for a in W.acts if a["source_system"] == "deletion_worker"]
    out = {}
    for c, d in info.items():
        if not d["pick"] or d["pick_row"] is None or not picks[c]["auth"]:
            continue
        q, rep = d["q"], d["rep"]
        audit = q["audit_at"]
        A = (d["pick_row"]["_t"] - rep).total_seconds() % 60
        got = {}
        for a in dw:
            t = act_template(a)
            if t == "submit" or a["resource_id"] == d["pick"]:
                continue
            lo, hi = TEMPLATE_WINDOWS[t]
            if not (lo <= off_min(a, rep) <= hi):
                continue
            rid = a["resource_id"]
            if W.res_users.get(rid) or rid not in W.by_res:
                continue
            if not any(u.ts <= audit for u in W.by_res[rid]):
                continue
            if sig_match(a, rep, A):
                got[rid] = (a["activity_id"], d["stage"])
        if got:
            out[c] = got
    return out


def t5_filter(claims: dict, picks: dict) -> dict:
    """T5 + T29: drop records claimed by more than one person, and claims anchored on an S5 pick."""
    owners = defaultdict(set)
    for c, g in claims.items():
        for rid in g:
            owners[rid].add(picks[c]["person"])
    out = {}
    for c, g in claims.items():
        keep = {rid: v for rid, v in g.items() if len(owners[rid]) == 1 and v[1] != "S5_flagged"}
        if keep:
            out[c] = keep
    return out


def summary(picks: dict, gold: dict) -> dict:
    out = {}
    for s in ("dev", "test", "holdout"):
        cs = [c for c, p in picks.items() if p["set"] == s and p["auth"]]
        st = Counter(picks[c]["stage"] for c in cs)
        row = dict(n=len(cs), stages=dict(sorted(st.items())))
        own = defaultdict(set)
        for c, p in picks.items():
            if p["pick"] and p["auth"]:
                own[p["pick"]].add(p["person"])
        row["accounts_on_two_people_all_sets"] = len([k for k, v in own.items() if len(v) > 1])
        if s == "dev":
            row["correct"] = sum(1 for c in cs if picks[c]["pick"] in gold_account(gold[c]))
            row["correct_by_stage"] = {k: f"{sum(1 for c in cs if picks[c]['stage'] == k and picks[c]['pick'] in gold_account(gold[c]))}/{st[k]}"
                                       for k in sorted(st)}
        out[s] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    hold = load_holdout_inputs()
    W = World()
    R: dict = {}
    base = AcctOpts()
    V = {
        "V0_baseline": (base, cases),
        "V1_H1": (replace(base, scope="batch", d17="qualify", with_holdout_inputs=True), cases + hold),
        "V2_H1_forced": (replace(base, scope="batch", d17="qualify", with_holdout_inputs=True, assign="forced"), cases + hold),
        "V3_H1_no_holdout": (replace(base, scope="batch", d17="qualify"), cases),
        "V4_H1_d17_tiebreak": (replace(base, scope="batch", with_holdout_inputs=True), cases + hold),
        "V5_H1_link_pre_audit": (replace(base, scope="batch", d17="qualify", with_holdout_inputs=True, d17_link="pre_audit"), cases + hold),
        "V6_H1_global": (replace(base, d17="qualify", with_holdout_inputs=True), cases + hold),
    }
    E, P = {}, {}
    for name, (o, reqs) in V.items():
        E[name] = AcctEngine(W, reqs, o)
        P[name] = E[name].picks()
        R[name] = summary(P[name], gold)
        R[name]["conflicts_emptied"] = dict(Counter(P[name][c]["set"] for c in E[name].conflicts))
    p0 = P["V0_baseline"]
    # changes vs baseline: test and DEV per case; holdout aggregate only
    R["changes_vs_V0"] = {}
    for name in V:
        if name == "V0_baseline":
            continue
        pn = P[name]
        ch = {"dev": [], "test": []}
        for c in p0:
            if c not in pn or not p0[c]["auth"]:
                continue
            if (p0[c]["stage"], p0[c]["pick"]) != (pn[c]["stage"], pn[c]["pick"]):
                ch[p0[c]["set"]].append(dict(case=c, before=(p0[c]["stage"], p0[c]["pick"]), after=(pn[c]["stage"], pn[c]["pick"])))
        R["changes_vs_V0"][name] = dict(
            dev=ch["dev"], test_n=len(ch["test"]),
            test_pick_changed=len([x for x in ch["test"] if x["before"][1] != x["after"][1]]),
            test_stage_only=len([x for x in ch["test"] if x["before"][1] == x["after"][1]]),
            test_kinds=dict(Counter(f"{x['before'][0]} -> {x['after'][0]}" for x in ch["test"])),
            test=sorted(ch["test"], key=lambda x: int(x["case"][5:])))
    # the 9 named cases
    W_batch = defaultdict(Counter)
    for q in cases + hold:
        W_batch[q["reported_at"]][q["_set"]] += 1
    qmap = {q["case_id"]: q for q in cases}
    R["named"] = {}
    for c in NAMED:
        q = qmap[c]
        e0, e1 = E["V0_baseline"].info[c], E["V1_H1"].info[c]
        R["named"][c] = dict(batch_composition=dict(W_batch[q["reported_at"]]), reported_status=q["reported_status"],
                             V0=(e0["stage"], e0["pick"], e0.get("d17")),
                             **{k: (P[k][c]["stage"], P[k][c]["pick"]) for k in V if k != "V0_baseline"},
                             V1_candidates_after_qualify=sorted(E["V1_H1"].info[c]["cand"]) if E["V1_H1"].info[c]["stage"] in ("S5_flagged",) else None,
                             V1_d17_dropped=e1["d17_dropped"])
    # batches with holdout inputs and test/DEV requests: aggregate effect
    hb = {q["reported_at"] for q in hold}
    R["holdout_batches"] = dict(
        batches_with_holdout=len(hb),
        of_which_with_test=len([b for b in hb if W_batch[b]["test"]]),
        of_which_with_dev=len([b for b in hb if W_batch[b]["dev"]]),
        test_requests_in_them=sum(W_batch[b]["test"] for b in hb),
        dev_requests_in_them=sum(W_batch[b]["dev"] for b in hb))
    # batch structure: requests per batch (all request files) vs account delete rows in -75..-44 min
    from g2f2_lib import account_delete_rows
    ADR = account_delete_rows(W)
    shape = Counter()
    for b, comp in W_batch.items():
        rep = T(b)
        n_sub = sum(1 for r in ADR if -75 <= off_min(r, rep) <= -44)
        shape[f"{sum(comp.values())} requests / {n_sub} submit rows"] += 1
    R["batch_shape_all_request_files"] = dict(sorted(shape.items()))
    # cross-batch window overlap (a global pass can mix batches; a batch pass cannot)
    reps = sorted({T(q["reported_at"]) for q in cases + hold})
    ov = sum(1 for i in range(len(reps) - 1) if (reps[i + 1] - reps[i]).total_seconds() < 31 * 60)
    R["batch_pairs_with_overlapping_windows"] = ov
    # joint analytics (T5 limits) under V0 and V1
    for name in ("V0_baseline", "V1_H1", "V2_H1_forced", "V3_H1_no_holdout"):
        cl = analytics_claims(W, E[name].info, P[name])
        kept = t5_filter(cl, P[name])
        R[f"analytics_{name}"] = dict(
            claims_test=sum(len(v) for c, v in cl.items() if P[name][c]["set"] == "test"),
            kept_test=sum(len(v) for c, v in kept.items() if P[name][c]["set"] == "test"),
            kept_dev={c: sorted(v) for c, v in kept.items() if P[name][c]["set"] == "dev"},
            claims_dev={c: sorted(v) for c, v in cl.items() if P[name][c]["set"] == "dev"},
            kept_holdout_n=sum(len(v) for c, v in kept.items() if P[name][c]["set"] == "holdout"))
        R[f"_kept_{name}"] = {c: sorted(v) for c, v in kept.items() if P[name][c]["set"] == "test"}
    k0, k1 = R.pop("_kept_V0_baseline"), R.pop("_kept_V1_H1")
    R.pop("_kept_V2_H1_forced")
    R.pop("_kept_V3_H1_no_holdout")
    diff_cases = sorted({c for c in set(k0) | set(k1) if k0.get(c) != k1.get(c)}, key=lambda s: int(s[5:]))
    R["analytics_T5_V0_vs_V1_test_cases_changed"] = dict(n=len(diff_cases),
                                                         detail={c: (k0.get(c), k1.get(c)) for c in diff_cases})
    # DEV rows: inject V1 accounts where they differ from the prototype's; compare with the prototype replay
    dev = sorted((q for q in cases if q["_set"] == "dev"), key=lambda r: r["case_id"])
    proto = {q["case_id"]: solve2(q, W, Opts(), Hooks()) for q in cases}

    def hooks_for(name):
        acc, rows, empty = {}, {}, set()
        for c, p in P[name].items():
            if p["set"] == "holdout" or proto[c].status == "NOT_APPLICABLE" or p["stage"] == "S1_identifier":
                continue
            pa = sorted({s["resource_id"] for s in proto[c].steps if s["system_id"] == "account_service"})
            if [p["pick"]] == pa or (p["pick"] is None and not pa):
                continue
            acc[c], rows[c] = p["pick"], E[name].info[c]["pick_row"]
            if p["stage"] == "T27_narrowC":
                empty.add((c, p["pick"]))
        return Hooks(accounts=acc, account_rows=rows, empty_cite=empty)
    rowsets = {}
    for name in ("V0_baseline", "V1_H1", "V2_H1_forced"):
        hk = hooks_for(name)
        res = {q["case_id"]: solve2(q, W, Opts(), hk) for q in cases}
        rowsets[name] = res
        sc = []
        for q in dev:
            g = gold[q["case_id"]]
            s = score_case(res[q["case_id"]].status, res[q["case_id"]].steps, g["status"], g["steps"])
            s["case_id"] = q["case_id"]
            s["exact"] = s["status_ok"] and s["steps_ok"]
            sc.append(s)
        R[f"dev_rows_{name}"] = dict(aggregate(sc), inexact=[s["case_id"] for s in sc if not s["exact"]],
                                     diffs_vs_prototype={q["case_id"]: row_diff(proto[q["case_id"]], res[q["case_id"]])
                                                         for q in dev if row_diff(proto[q["case_id"]], res[q["case_id"]])})
    for name in ("V1_H1", "V2_H1_forced"):
        tc = [q["case_id"] for q in cases if q["_set"] == "test" and row_diff(rowsets["V0_baseline"][q["case_id"]], rowsets[name][q["case_id"]])]
        R[f"test_rows_changed_{name}_vs_V0"] = dict(n=len(tc), cases=tc)
        dc = [q["case_id"] for q in dev if row_diff(rowsets["V0_baseline"][q["case_id"]], rowsets[name][q["case_id"]])]
        R[f"dev_rows_changed_{name}_vs_V0"] = dc
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h1_batch.json").write_text(json.dumps(R, indent=1, default=str))
    for k, v in R.items():
        s = json.dumps(v, default=str)
        print(k, s[:3000])


if __name__ == "__main__":
    main()
