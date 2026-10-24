"""G2 Q2 extra: B2 (no identifier-linked account) and B3 (no audit record anywhere) on the 518 test inputs.

Run: python3 -I notes/forensics/q2_extra.py [--run g2-0137]
'showcase' here = the authorized test cases whose identifier-linked account delete offsets fall outside -75..-44
(B1 outliers) or whose timed rule finds no candidate (acct_stages NONE); everything else authorized = 'generated'.
"""
import argparse, json, sys
sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, World, load_cases
from identity import resolve_email
ap = argparse.ArgumentParser(); ap.add_argument("--run", default="g2-0137"); a = ap.parse_args()
W = World(); cases, _ = load_cases()
J = json.loads((RUNS / a.run / "acct_stages_base.json").read_text())["cases"]
F = json.loads((RUNS / a.run / "q1_q3.json").read_text())["features"]
Q2 = json.loads((RUNS / a.run / "q2.json").read_text())
outl = {c for _, c in Q2["B1_offsets"]["outside"]}
show = {c for c, v in J.items() if v["set"] == "test" and F[c]["authorized"] and (v["stage"] == "NONE" or c in outl)}
gen = [q for q in cases if q["_set"] == "test" and F[q["case_id"]]["authorized"] and q["case_id"] not in show]
no_il = sum(1 for q in gen if J[q["case_id"]]["stage"] != "S1_identifier")
def has_audit(q, form):
    uid = resolve_email(q["email"], W.idx)
    for u in W.units:
        if uid in u.users and u.system == "security_service":
            if form == "any" or (form == "pre_audit" and u.ts <= q["audit_at"]) or (form == "window" and q["requested_at"] <= u.ts <= q["audit_at"]):
                return True
    return False
out = dict(showcase=sorted(show, key=lambda x: int(x[5:])), generated=len(gen), generated_no_identifier_account=no_il)
for form in ("window", "pre_audit", "any"):
    out[f"no_audit_{form}_generated"] = sum(1 for q in gen if not has_audit(q, form))
    out[f"no_audit_{form}_showcase"] = sum(1 for q in cases if q["case_id"] in show and not has_audit(q, form))
(RUNS / a.run / "q2_extra.json").write_text(json.dumps(out, indent=1))
print(out)
