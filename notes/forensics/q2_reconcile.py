"""G2 Q2: reconcile report 15 with verify/14_15 by re-running the prototype solver (read-only import).

Run: python3 -I notes/forensics/q2_reconcile.py [--run g2-0137]
Writes runs/<run>/q2.json. The prototype is imported, never modified; its out/ folder is not touched.
Gold: research/prototype/devgold.py (holdout rows dropped before parsing).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, account_delete_rows, load_cases, off_min, id_linked_accounts  # noqa: E402
import solver  # noqa: E402
from solver import Opts, solve, validate  # noqa: E402
from score import aggregate, score_case  # noqa: E402
from vision_facts import vision_units  # noqa: E402  (hand table; used only to reproduce report-15 test figures)
from identity import resolve_email  # noqa: E402


def dev_score(W, cases, gold, opts):
    rows = []
    for q in sorted((c for c in cases if c["_set"] == "dev"), key=lambda r: r["case_id"]):
        res = solve(q, W, opts)
        g = gold[q["case_id"]]
        sc = score_case(res.status, res.steps, g["status"], g["steps"])
        sc["case_id"] = q["case_id"]
        sc["exact"] = sc["status_ok"] and sc["steps_ok"]
        rows.append(sc)
    return aggregate(rows), rows


def test_run(W, cases, opts):
    out = {}
    for q in (c for c in cases if c["_set"] == "test"):
        out[q["case_id"]] = solve(q, W, opts)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2-0137")
    a = ap.parse_args()
    cases, gold = load_cases()
    W = World()
    Wv = World(vision_units=vision_units())
    R = {}
    agg, rows = dev_score(W, cases, gold, Opts())
    R["dev_all"] = agg
    R["dev_inexact"] = [r["case_id"] for r in rows if not r["exact"]]
    agg2, rows2 = dev_score(W, cases, gold, Opts(use_signature=False))
    R["dev_nosig"] = agg2
    R["dev_nosig_inexact"] = [r["case_id"] for r in rows2 if not r["exact"]]
    # +-1 s band (verify finding 6)
    base_bands = dict(solver.SIG_BANDS)
    tv_base = test_run(Wv, cases, Opts())
    for name, pad in (("wide1", 1), ("narrow1", -1)):
        solver.SIG_BANDS.update({"policy": (9 - pad, 11 + pad), "after": (20 - pad, 22 + pad)})
        ag, rw = dev_score(W, cases, gold, Opts())
        tv = test_run(Wv, cases, Opts())
        changed = sum(1 for c in tv if tv[c].steps != tv_base[c].steps)
        R[f"band_{name}"] = dict(dev_case_exact=ag["case_exact"], dev_inexact=[r["case_id"] for r in rw if not r["exact"]],
                                 test_cases_changed=changed)
        solver.SIG_BANDS.clear(); solver.SIG_BANDS.update(base_bands)
    # test-level figures (with vision, as report 15 sec 6.3)
    acc_cases, ana_cases = defaultdict(set), defaultdict(set)
    guesses, methods, sig_ana_cases, anch_guess = 0, Counter(), set(), set()
    no_acc, multi_file = [], []
    for c, res in tv_base.items():
        if res.status == "NOT_APPLICABLE":
            continue
        tr = res.trace
        if tr.get("guesses"):
            guesses += 1
        accs = [s["resource_id"] for s in res.steps if s["system_id"] == "account_service"]
        if not accs:
            no_acc.append(c)
        for r in set(accs):
            acc_cases[r].add(c)
        files = {s["evidence_id"] for s in res.steps if s["evidence_id"]}
        if len(files) > 1:
            multi_file.append(c)
        acc_guess = False
        for rid, ms in tr["links"].items():
            for m in ms:
                if rid.startswith("account_") and not m.startswith("identifier"):
                    methods[m] += 1
                    if "GUESS" in m:
                        acc_guess = True
        for rid, ms in tr["links"].items():
            if any(m.startswith("job_signature") for m in ms):
                ana_cases[rid].add(c)
                sig_ana_cases.add(c)
                if acc_guess:
                    anch_guess.add(c)
    sh_acc = {r: v for r, v in acc_cases.items() if len(v) > 1}
    sh_ana = {r: v for r, v in ana_cases.items() if len(v) > 1}
    R["test"] = dict(guess_cases=guesses, account_methods=dict(methods), no_account_step=sorted(no_acc, key=lambda x: int(x[5:])),
                     multi_file_cases=multi_file, shared_accounts=len(sh_acc), shared_account_cases=len(set().union(*sh_acc.values())) if sh_acc else 0,
                     shared_analytics=len(sh_ana), shared_analytics_claims=sum(len(v) for v in sh_ana.values()),
                     sig_analytics_cases=len(sig_ana_cases), sig_analytics_resources=len(ana_cases),
                     sig_anchored_on_guess=len(anch_guess))
    # --no-signature: does the account tie-break still use the signature? (verify finding 3)
    tv_ns = test_run(Wv, cases, Opts(use_signature=False))
    R["test_nosig_account_signature_cases"] = sum(1 for r in tv_ns.values()
                                                 if any("+signature" in m for ms in r.trace["links"].values() for m in ms))
    # B1: identifier-linked account delete offsets on test (generated + showcase)
    ADR = account_delete_rows(W)
    offs = []
    for q in (c for c in cases if c["_set"] == "test"):
        uid = resolve_email(q["email"], W.idx)
        il = id_linked_accounts(W, uid, q, "window")
        rep = T(q["reported_at"])
        for r in ADR:
            if r["resource_id"] in il:
                offs.append((round(off_min(r, rep), 2), q["case_id"]))
    inb = [o for o in offs if -75 <= o[0] <= -44]
    R["B1_offsets"] = dict(n=len(offs), in_75_44=len(inb), min_in=min(o[0] for o in inb), max_in=max(o[0] for o in inb),
                           outside=[o for o in offs if not (-75 <= o[0] <= -44)])
    p = RUNS / a.run / "q2.json"
    p.write_text(json.dumps(R, indent=1, default=list))
    print(json.dumps(R, indent=1, default=list)[:6000])


if __name__ == "__main__":
    main()
