"""G2 Q7: is the job fingerprint stable mod 60 (not only mod 30)? Inputs only: identifier-linked jobs.

Run: python3 -I notes/forensics/q7_mod60.py [--run g2-0137]
For every authorized case whose account is identifier-linked (S1), take its account delete row (A = offset mod 60 s)
and every non-submit deletion_worker row of its own identifier-linked resources in the template windows; count
(row offset - A) mod 60, rounded to the second, per template. Then, for S5 cases where D17 'fit' every candidate,
count how many a mod-60 test with the measured residual set would separate.
"""
import argparse, json, sys
from collections import Counter
sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, act_template, TEMPLATE_WINDOWS, account_delete_rows, load_cases, off_min
from identity import resolve_email
ap = argparse.ArgumentParser(); ap.add_argument("--run", default="g2-0137"); a = ap.parse_args()
W = World(); cases, _ = load_cases(); ADR = account_delete_rows(W)
J = json.loads((RUNS / a.run / "acct_stages_base.json").read_text())["cases"]
F = json.loads((RUNS / a.run / "q1_q3.json").read_text())["features"]
dw = [x for x in W.acts if x["source_system"] == "deletion_worker"]
res = {"policy": Counter(), "after": Counter()}
def own_rows(q, uid, rep):
    lr = {u.resource_id for u in W.units if uid in u.users and u.resource_id and q["requested_at"] <= u.ts <= q["audit_at"]}
    out = []
    for x in dw:
        t = act_template(x)
        if x["resource_id"] in lr and t != "submit" and not x["resource_id"].startswith("account_"):
            lo, hi = TEMPLATE_WINDOWS[t]
            if lo <= off_min(x, rep) <= hi:
                out.append(x)
    return out
for q in cases:
    c = q["case_id"]; v = J[c]
    if v["stage"] != "S1_identifier" or not F[c]["authorized"]:
        continue
    rep = T(q["reported_at"]); uid = resolve_email(q["email"], W.idx)
    acc = [r for r in ADR if r["resource_id"] == v["pick"] and -76 <= off_min(r, rep) <= 9]
    if not acc:
        continue
    A = (acc[0]["_t"] - rep).total_seconds() % 60
    for x in own_rows(q, uid, rep):
        res[act_template(x)][round(((x["_t"] - rep).total_seconds() - A) % 60)] += 1
print("mod-60 residuals on identifier-linked jobs:", {k: dict(sorted(v.items())) for k, v in res.items()})
