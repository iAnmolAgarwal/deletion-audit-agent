"""G2 follow-up, task 1: re-measure verify B4 ("121 unlinked analytics records over 240 cases").

Run: python3 -I -B notes/forensics/f1_b4.py [--run g2f-0152]
Writes runs/<run>/f1_b4.json. Test figures use inputs only. The DEV proxy check reads DEV gold through
devgold.py (holdout rows dropped before steps_json is parsed). Holdout request rows are dropped by
common.load_cases (asserts 22 DEV + 518 test).

Where the two source definitions come from (read from the source scripts, not from their outputs):
  report 14 a17_planproj.py : ANONYMIZE_RECORD rows with reported_result SUCCESS whose resource is linked to no
                              user, 25..35 min before the reported_at of some *generated* test case. Counts records.
  verify 14_15 anal.py      : deletion_worker ANONYMIZE_RECORD rows (any result) at offset -35..-25 min whose
                              resource is linked to no user AND has an evidence observation, per generated test
                              case. Counts cases, records, records claimed by >1 case, cases owning >=1 record outright.
Definitions applied here (every one on every row alike; no case ID, file name or row position is a signal):
  generated   = deletion-authorized test case (intent.py) that is not 'showcase'. Showcase is the input-derived set
                from the first run (q2_extra.py): authorized test cases whose T4 account stage is NONE or whose
                identifier-linked account delete row lies outside -75..-44 min (runs/g2-0137 outputs, inputs only).
  unlinked    = W.res_users[resource] is empty (no unit anywhere links the resource to any user, any time).
  offset      = (event_time - reported_at) in minutes; window inclusive.
  Forms: D14 (report 14), DV (verify), DV_succ (verify + SUCCESS only), DV_nev (verify without the evidence filter),
         DT (policy template window -31..-2 instead of -35..-25, verify filters), DA (DV over all 508 authorized
         test cases, showcase included).
Reach of the D17 offset rule over the DV case set is measured two ways:
  proto  = the prototype solver's own job_signature links (solver.solve, no vision facts, prototype account order);
  t4     = the first run's q4 claims anchored on the T4 picks (runs/g2-0137/acct_stages_base.json), all claims and
           with L1+L2 (single-case exclusivity, never anchored on an S5 pick).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
from collections import defaultdict  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, TEMPLATE_WINDOWS, act_template, account_delete_rows, load_cases, off_min  # noqa: E402
import solver  # noqa: E402
from identity import resolve_email  # noqa: E402
from intent import authorizes_deletion  # noqa: E402


def showcase_set(cases) -> set[str]:
    J = json.loads((RUNS / "g2-0137" / "acct_stages_base.json").read_text())["cases"]
    Q2 = json.loads((RUNS / "g2-0137" / "q2.json").read_text())
    outl = {c for _, c in Q2["B1_offsets"]["outside"]}
    return {q["case_id"] for q in cases if q["_set"] == "test" and authorizes_deletion(q["request_text"])[0]
            and (J[q["case_id"]]["stage"] == "NONE" or q["case_id"] in outl)}


def measure(W, scope, rows, lo, hi, need_ev: bool, succ_only: bool) -> dict:
    claims: dict[str, set] = defaultdict(set)
    for q in scope:
        rep = T(q["reported_at"])
        for a in rows:
            m = off_min(a, rep)
            if not (lo <= m <= hi):
                continue
            if succ_only and a["reported_result"] != "SUCCESS":
                continue
            rid = a["resource_id"]
            if W.res_users.get(rid):
                continue
            if need_ev and rid not in W.by_res:
                continue
            claims[rid].add(q["case_id"])
    cases = set().union(*claims.values()) if claims else set()
    multi = {r for r, v in claims.items() if len(v) > 1}
    owners = {c for c in cases if any(claims[r] == {c} for r in claims)}
    return dict(records=len(claims), cases=len(cases), records_multi_claimed=len(multi),
                cases_owning_one_outright=len(owners), _cases=sorted(cases, key=lambda x: int(x[5:])),
                _claims={r: sorted(v) for r, v in claims.items()})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2f-0152")
    a = ap.parse_args()
    W = World()
    cases, gold = load_cases()
    test = [q for q in cases if q["_set"] == "test"]
    auth = [q for q in test if authorizes_deletion(q["request_text"])[0]]
    show = showcase_set(cases)
    gen = [q for q in auth if q["case_id"] not in show]
    an_all = [x for x in W.acts if x["event_type"] == "ANONYMIZE_RECORD"]
    an_dw = [x for x in an_all if x["source_system"] == "deletion_worker"]
    R = dict(n_test=len(test), n_authorized=len(auth), n_showcase=len(show), n_generated=len(gen),
             anonymize_rows=len(an_all), anonymize_rows_deletion_worker=len(an_dw))
    forms = {
        "D14_report14": (gen, an_all, -35, -25, False, True),
        "DV_verify": (gen, an_dw, -35, -25, True, False),
        "DV_succ": (gen, an_dw, -35, -25, True, True),
        "DV_nev": (gen, an_dw, -35, -25, False, False),
        "DT_policy_window": (gen, an_dw, TEMPLATE_WINDOWS["policy"][0], TEMPLATE_WINDOWS["policy"][1], True, False),
        "DA_all_authorized": (auth, an_dw, -35, -25, True, False),
    }
    full = {}
    for name, (scope, rows, lo, hi, ev, sc) in forms.items():
        full[name] = measure(W, scope, rows, lo, hi, ev, sc)
        R[name] = {k: v for k, v in full[name].items() if not k.startswith("_")}
        R[name]["window_min"] = [lo, hi]
    # edge inclusivity check for DV: open interval vs closed
    eps = 1e-9
    R["DV_open_interval"] = {k: v for k, v in measure(W, gen, an_dw, -35 + eps, -25 - eps, True, False).items()
                             if not k.startswith("_")}
    # template mix inside the DV window
    R["DV_rows_by_template"] = {}
    for q in gen:
        rep = T(q["reported_at"])
        for x in an_dw:
            if -35 <= off_min(x, rep) <= -25 and not W.res_users.get(x["resource_id"]) and x["resource_id"] in W.by_res:
                R["DV_rows_by_template"][act_template(x)] = R["DV_rows_by_template"].get(act_template(x), 0) + 1
    # evidence state of DV records (are they anonymized in evidence?)
    st = defaultdict(int)
    for rid in full["DV_verify"]["_claims"]:
        sts = {solver.unit_state(u) for u in W.by_res[rid]}
        st["|".join(sorted(s for s in sts if s))] += 1
    R["DV_record_evidence_states"] = dict(st)
    # reach of the D17 offset rule over the DV case set
    dv_cases = set(full["DV_verify"]["_cases"])
    proto_sig = set()
    for q in gen:
        res = solver.solve(q, W, solver.Opts())
        if any(m.startswith("job_signature") for ms in res.trace.get("links", {}).values() for m in ms):
            proto_sig.add(q["case_id"])
    q4 = json.loads((RUNS / "g2-0137" / "acct_stages_base.json").read_text())["cases"]
    # re-derive the q4 claim sets (same rule as q4_d17.py) to get per-case reach
    ADR = account_delete_rows(W)
    dw = [x for x in W.acts if x["source_system"] == "deletion_worker"]
    claims = defaultdict(set)
    anchor_stage = {}
    for q in auth:
        c = q["case_id"]
        v = q4[c]
        if not v["pick"]:
            continue
        rep = T(q["reported_at"])
        rows = [r for r in ADR if r["resource_id"] == v["pick"] and -76 <= off_min(r, rep) <= 9]
        if not rows:
            continue
        A = (rows[0]["_t"] - rep).total_seconds() % 60
        anchor_stage[c] = v["stage"]
        for x in dw:
            rid = x["resource_id"]
            if x is rows[0] or act_template(x) == "submit" or rid.startswith("account_"):
                continue
            lo, hi = TEMPLATE_WINDOWS[act_template(x)]
            if not (lo <= off_min(x, rep) <= hi):
                continue
            if W.res_users.get(rid) or rid not in W.by_res:
                continue
            if not any(u.ts <= q["audit_at"] for u in W.by_res[rid]):
                continue
            if solver.sig_match(x, rep, A):
                claims[rid].add(c)
    multi = {r for r, v in claims.items() if len(v) > 1}
    t4_all = {c for r, v in claims.items() for c in v}
    t4_l12 = {c for r, v in claims.items() for c in v if r not in multi and anchor_stage.get(c) != "S5_flagged"}
    R["reach_over_DV_cases"] = dict(
        dv_cases=len(dv_cases),
        proto_signature_cases_in_generated=len(proto_sig), proto_reach=len(proto_sig & dv_cases),
        proto_outside_dv=len(proto_sig - dv_cases),
        t4_all_claim_cases_in_authorized=len(t4_all), t4_all_reach=len(t4_all & dv_cases),
        t4_L1L2_cases=len(t4_l12), t4_L1L2_reach=len(t4_l12 & dv_cases))
    # DEV check of the DV proxy (gold via devgold, holdout dropped before parsing): claimed records vs gold analytics
    dev = [q for q in cases if q["_set"] == "dev"]
    dvd = measure(W, dev, an_dw, -35, -25, True, False)
    gold_an = {(c, s["resource_id"]) for c in gold for s in gold[c]["steps"] if s["system_id"] == "analytics_platform"}
    gold_an_free = {p for p in gold_an if not W.res_users.get(p[1])}
    pairs = {(c, r) for r, cs in dvd["_claims"].items() for c in cs}
    R["DEV_DV_proxy"] = dict(dev_cases_flagged=dvd["cases"], records=dvd["records"], claim_pairs=len(pairs),
                             pairs_in_gold=len(pairs & gold_an), pairs_not_in_gold=len(pairs - gold_an),
                             gold_identifier_free_analytics=len(gold_an_free),
                             gold_identifier_free_found=len(gold_an_free & pairs),
                             flagged=sorted(dvd["_cases"]), in_gold=sorted(pairs & gold_an),
                             not_in_gold=sorted(pairs - gold_an))
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    out = dict(R)
    out["DV_claims"] = full["DV_verify"]["_claims"]
    (RUNS / a.run / "f1_b4.json").write_text(json.dumps(out, indent=1, default=list))
    print(json.dumps(R, indent=1, default=list))


if __name__ == "__main__":
    main()
