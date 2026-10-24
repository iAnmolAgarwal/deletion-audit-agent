"""G2 Q4: D17 (job timing fingerprint) limits for identifier-free analytics, on top of the T4 account picks.

Run: python3 -I notes/forensics/q4_d17.py [--run g2-0137] [--stages base] [--band-pad S]
Reads runs/<run>/acct_stages_<stages>.json; writes runs/<run>/q4_<stages>_pad<S>.json.

Attachment rule (the prototype's form, re-implemented on the T4 picks):
  anchor A    = (account delete row offset from reported_at, in seconds) mod 60, using the case's picked account's
                delete row (S1 identifier-linked accounts use their own delete row in -76..+9 min).
  candidate   = a deletion_worker row in its template window whose resource has evidence, is identifier-linked to
                no user, has an observation at or before audit_at, and whose (offset - A) mod 30 is in the band.
Limits measured:
  L1 single-case exclusivity: drop a record that more than one case claims.
  L2 never anchored on a guessed account: drop claims whose anchor account came from S5 (flagged pick).
  L3 precision: bands widened/narrowed by 1 s (--band-pad).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, act_template, TEMPLATE_WINDOWS, account_delete_rows, load_cases, off_min  # noqa: E402
import solver  # noqa: E402
from identity import resolve_email  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2-0137")
    ap.add_argument("--stages", default="base")
    ap.add_argument("--band-pad", type=int, default=0)
    a = ap.parse_args()
    if a.band_pad:
        solver.SIG_BANDS["policy"] = (9 - a.band_pad, 11 + a.band_pad)
        solver.SIG_BANDS["after"] = (20 - a.band_pad, 22 + a.band_pad)
    W = World()
    cases, gold = load_cases()
    J = json.loads((RUNS / a.run / f"acct_stages_{a.stages}.json").read_text())["cases"]
    feats = json.loads((RUNS / a.run / "q1_q3.json").read_text())["features"]
    ADR = account_delete_rows(W)
    dw = [x for x in W.acts if x["source_system"] == "deletion_worker"]
    claims = defaultdict(set)  # rid -> cases
    meta = {}
    for q in cases:
        c = q["case_id"]
        if not feats[c]["authorized"]:
            continue
        v = J[c]
        if not v["pick"]:
            continue
        rep = T(q["reported_at"])
        rows = [r for r in ADR if r["resource_id"] == v["pick"] and -76 <= off_min(r, rep) <= 9]
        if not rows:
            continue
        acc = rows[0]
        A = (acc["_t"] - rep).total_seconds() % 60
        uid = resolve_email(q["email"], W.idx)
        for x in dw:
            rid = x["resource_id"]
            if x is acc or act_template(x) == "submit" or rid.startswith("account_"):
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
                meta.setdefault(c, {"anchor_stage": v["stage"], "rids": set()})["rids"].add(rid)
    def score(keep):
        dev_tp = dev_fp = 0
        dev_gold_pairs = set()
        for c in (x["case_id"] for x in cases if x["_set"] == "dev"):
            for s in gold[c]["steps"]:
                if s["system_id"] == "analytics_platform":
                    dev_gold_pairs.add((c, s["resource_id"]))
        pred = {(c, r) for r, cs in claims.items() for c in cs if keep(r, c)}
        dpred = {p for p in pred if p[0].startswith("case_") and J[p[0]]["set"] == "dev"}
        tp = len(dpred & dev_gold_pairs)
        fp = len(dpred - dev_gold_pairs)
        tpred = {p for p in pred if J[p[0]]["set"] == "test"}
        return dict(dev_tp=tp, dev_fp=fp, dev_fp_pairs=sorted(dpred - dev_gold_pairs), dev_gold_analytics=len(dev_gold_pairs),
                    dev_found=sorted(dpred & dev_gold_pairs),
                    test_pairs=len(tpred), test_cases=len({p[0] for p in tpred}), test_records=len({p[1] for p in tpred}))
    multi = {r for r, cs in claims.items() if len(cs) > 1}
    guess_anchor = {c for c, m in meta.items() if m["anchor_stage"] == "S5_flagged"}
    R = dict(
        all_claims=score(lambda r, c: True),
        L1_exclusive=score(lambda r, c: r not in multi),
        L2_no_guess_anchor=score(lambda r, c: c not in guess_anchor),
        L1_and_L2=score(lambda r, c: r not in multi and c not in guess_anchor),
        records_multi_claimed=len(multi), claims_on_multi=sum(len(claims[r]) for r in multi),
        multi_claim_sets_dev_involved=sorted([sorted(claims[r]) for r in multi if any(J[c]["set"] == "dev" for c in claims[r])]),
        cases_anchored_on_flagged_pick=len(guess_anchor),
    )
    p = RUNS / a.run / f"q4_{a.stages}_pad{a.band_pad}.json"
    p.write_text(json.dumps(R, indent=1, default=list))
    print(json.dumps(R, indent=1, default=list))


if __name__ == "__main__":
    main()
