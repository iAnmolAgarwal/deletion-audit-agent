"""G2 follow-up, task 4: a one-to-one-aware S5 (D18 flagged pick) for the T4 account order.

Run: python3 -I -B notes/forensics/s5_one_to_one.py [--run g2f-0152]
Writes runs/<run>/s5_one_to_one.json and prints a summary.

Stages S1..S4b are a faithful re-implementation of notes/forensics/acct_stages.py (first run, g2-0137). The script
first re-runs them with the first run's S5 ('independent') and asserts that stage and pick equal the saved
runs/g2-0137/acct_stages_<tag>.json for every case (tags base, noresult, noowner, split).

S5 modes (only cases still unresolved after S4b with >= 1 candidate enter S5):
  independent : the first run's rule: each case takes the candidate closest to offset -60 min (ties: resource ID string).
  greedy      : cases are taken in a stated order; each takes the closest-to--60 candidate that no case has already
                taken (S1..S4b picks and earlier S5 picks, within the scope). A case with no candidate left gets no
                pick ('S5_exhausted', flagged).
  matching    : per connected component of S5 cases (cases sharing a candidate), the assignment that (1) gives the
                most cases a pick, (2) minimises the total |offset + 60|, (3) then prefers the stated order
                lexicographically. Brute force (components are small).
Orders (none encodes an answer; no case ID, file name or row position is used):
  req_asc      : requested_at ascending, then lower-case email.
  req_desc     : requested_at descending, then lower-case email descending (the exact reverse of req_asc).
  email_sha    : sha256(lower-case email), a content-keyed neutral order.
  fewest_first : number of remaining candidates, then requested_at, then email.
NA handling: 'include' = NA cases (intent.py) run through every stage, as in the first run; 'exclude' = they take
no account (an NA case outputs [] and authorises no deletion job).
Evaluations:
  test      : distinct picks, duplicate accounts (picked by > 1 authorized case, all stages), exhausted cases.
  DEV       : S5 resolved/correct under the first run's S5 ablation (--no-result), and under an S1-masked stress test
              (identifier links hidden for every case), against DEV gold (devgold.py, holdout dropped before parsing).
  pseudo    : on the 518 test inputs, with S1 masked, how often S2..S5 recover the account that the identifier link
              gives (the S1 account is the label; inputs only, no gold). 'mask_s1' still lets the owner filter use
              identifier links to drop accounts owned by another user; 'mask_s1_noowner' switches that off too, so
              no identifier link is used for accounts at all (the full mask).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import hashlib  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from types import SimpleNamespace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import (RUNS, T, World, STATUS_TO_RESULT, act_template, TEMPLATE_WINDOWS, account_delete_rows,  # noqa: E402
                    gold_account, id_linked_accounts, load_cases, off_min)
import solver  # noqa: E402
from identity import resolve_email  # noqa: E402
from intent import authorizes_deletion  # noqa: E402

ORDERS = ("req_asc", "req_desc", "email_sha", "fewest_first")


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


def stages_s1_s4b(W, cases, ADR, o) -> tuple[dict, dict]:
    """acct_stages.py S1..S4b, same semantics. o: window, no_result, no_owner, scope, band_pad, mask_s1, na_mode."""
    LO, HI = o.window
    bands = dict(solver.SIG_BANDS)
    if o.band_pad:
        solver.SIG_BANDS["policy"] = (9 - o.band_pad, 11 + o.band_pad)
        solver.SIG_BANDS["after"] = (20 - o.band_pad, 22 + o.band_pad)
    info = {}
    for q in cases:
        if o.na_mode == "exclude" and not authorizes_deletion(q["request_text"])[0]:
            continue
        uid = resolve_email(q["email"], W.idx)
        rep = T(q["reported_at"])
        want = STATUS_TO_RESULT.get(q["reported_status"])
        il = id_linked_accounts(W, uid, q, "window") if uid and uid != "AMBIGUOUS" else set()
        linked_res = {u.resource_id for u in W.units if uid in u.users and u.resource_id
                      and q["requested_at"] <= u.ts <= q["audit_at"]}
        inwin = [r for r in ADR if LO <= off_min(r, rep) <= HI]
        matched = [r for r in inwin if o.no_result or r["reported_result"] == want]
        owned_ok = [r for r in matched if o.no_owner or not (W.res_users.get(r["resource_id"], set()) - {uid})]
        near10 = [r for r in ADR if -10 <= off_min(r, rep) <= 10]
        info[q["case_id"]] = dict(q=q, uid=uid, rep=rep, want=want, il=sorted(il), linked_res=linked_res,
                                  inwin=inwin, matched=matched, cand={r["resource_id"] for r in owned_ok},
                                  near10=near10, stage=None, pick=None, flag=False)
    for c, d in info.items():
        if d["il"] and not o.mask_s1:
            d["stage"], d["pick"] = "S1_identifier", d["il"][0]
    d2 = {c: set(d["cand"]) for c, d in info.items() if d["stage"] is None}
    pre = {c: len(v) for c, v in d2.items()}

    def key(c):
        return info[c]["q"]["_set"] if o.scope == "split" else "all"

    def one_to_one(stage_name):
        changed = True
        while changed:
            changed = False
            taken = defaultdict(set)
            for c, d in info.items():
                if d["pick"]:
                    taken[key(c)].add(d["pick"])
            for c, cs in d2.items():
                if info[c]["stage"]:
                    continue
                new = cs - taken[key(c)]
                if new != cs:
                    d2[c] = new
                    changed = True
                if len(d2[c]) == 1:
                    info[c]["stage"], info[c]["pick"] = stage_name, next(iter(d2[c]))
                    changed = True

    one_to_one("S2S3_timed_unique")
    for c, d in info.items():
        if d["stage"] == "S2S3_timed_unique":
            d["stage"] = "S2_timed_unique" if pre[c] == 1 else "S3_one_to_one"
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
            if all(solver.sig_match(x, d["rep"], A) for x in own):
                fit.add(rid)
        d["d17"] = f"fit {len(fit)}/{len(cs)}"
        if fit and len(fit) < len(cs):
            d2[c] = fit
            if len(fit) == 1:
                d["stage"], d["pick"] = "S4_d17", next(iter(fit))
    one_to_one("S4b_one_to_one_after_d17")
    solver.SIG_BANDS.clear()
    solver.SIG_BANDS.update(bands)
    return info, d2


def cost(info, c, rid) -> float:
    d = info[c]
    rows = {r["resource_id"]: r for r in d["inwin"] + d["near10"]}
    return abs(off_min(rows[rid], d["rep"]) + 60)


def order_key(info, d2, name):
    def k(c):
        q = info[c]["q"]
        em = q["email"].strip().lower()
        if name == "req_asc":
            return (q["requested_at"], em)
        if name == "req_desc":
            return tuple(-ord(ch) for ch in q["requested_at"]) + tuple(-ord(ch) for ch in em)
        if name == "email_sha":
            return (hashlib.sha256(em.encode()).hexdigest(),)
        if name == "fewest_first":
            return (len(d2[c]), q["requested_at"], em)
        raise ValueError(name)
    return k


def apply_s5(info, d2, mode: str, order: str | None, scope: str) -> dict:
    """Return {case: (stage, pick)} for every case (S1..S4b copied, S5 decided here)."""
    res = {c: (d["stage"], d["pick"]) for c, d in info.items()}
    s5 = [c for c, d in info.items() if d["stage"] is None]
    for c in s5:
        if not d2[c]:
            res[c] = ("NONE", None)
    s5 = [c for c in s5 if d2[c]]

    def skey(c):
        return info[c]["q"]["_set"] if scope == "split" else "all"

    taken = defaultdict(set)
    for c, d in info.items():
        if d["pick"]:
            taken[skey(c)].add(d["pick"])
    if mode == "independent":
        for c in s5:
            pick = sorted(d2[c], key=lambda r: (cost(info, c, r), r))[0]
            res[c] = ("S5_flagged", pick)
        return res
    k = order_key(info, d2, order)
    if mode == "greedy":
        for c in sorted(s5, key=k):
            left = d2[c] - taken[skey(c)]
            if not left:
                res[c] = ("S5_exhausted", None)
                continue
            pick = sorted(left, key=lambda r: (cost(info, c, r), r))[0]
            taken[skey(c)].add(pick)
            res[c] = ("S5_flagged", pick)
        return res
    if mode == "matching":
        # connected components over shared candidates
        comp_of, comps = {}, []
        for c in s5:
            hit = {comp_of[x] for x in s5 if x in comp_of and (d2[x] & d2[c])}
            if not hit:
                comps.append({c})
                comp_of[c] = len(comps) - 1
                continue
            base = min(hit)
            for h in sorted(hit - {base}, reverse=True):
                comps[base] |= comps[h]
                for x in comps[h]:
                    comp_of[x] = base
                comps[h] = set()
            comps[base].add(c)
            comp_of[c] = base
        for comp in (x for x in comps if x):
            cs = sorted(comp, key=k)
            avail = {c: sorted(d2[c] - taken[skey(c)], key=lambda r: (cost(info, c, r), r)) for c in cs}
            best, best_key = None, None
            options = [avail[c] + [None] for c in cs]
            for combo in itertools.product(*options):
                picked = [p for p in combo if p]
                if len(picked) != len(set(picked)):
                    continue
                n = len(picked)
                tot = sum(cost(info, c, p) for c, p in zip(cs, combo) if p)
                lex = tuple((avail[c] + [None]).index(p) for c, p in zip(cs, combo))
                kk = (-n, round(tot, 6), lex)
                if best_key is None or kk < best_key:
                    best, best_key = combo, kk
            for c, p in zip(cs, best):
                res[c] = ("S5_flagged", p) if p else ("S5_exhausted", None)
                if p:
                    taken[skey(c)].add(p)
        return res
    raise ValueError(mode)


def summarise(info, res, auth, gold, labels=None) -> dict:
    out = {}
    for s in ("dev", "test"):
        cs = [c for c in res if info[c]["q"]["_set"] == s and auth[c]]
        st = Counter(res[c][0] for c in cs)
        s5 = [c for c in cs if res[c][0] in ("S5_flagged", "S5_exhausted")]
        picks = [res[c][1] for c in cs if res[c][1]]
        cnt = Counter(picks)
        dup = {r: n for r, n in cnt.items() if n > 1}
        s5p = [res[c][1] for c in s5 if res[c][1]]
        row = dict(n=len(cs), stages=dict(sorted(st.items())), s5_cases=len(s5), s5_with_pick=len(s5p),
                   s5_distinct_picks=len(set(s5p)), s5_exhausted=st.get("S5_exhausted", 0),
                   duplicate_accounts_all_stages=len(dup), cases_on_duplicate_accounts=sum(dup.values()))
        if s == "dev":
            row["s5_correct"] = sum(1 for c in s5 if res[c][1] and res[c][1] in gold_account(gold[c]))
            row["all_correct"] = sum(1 for c in cs if res[c][1] and res[c][1] in gold_account(gold[c]))
            row["s5_cases_list"] = sorted(s5)
        if labels is not None:
            lab = [c for c in cs if c in labels]
            row["pseudo_labelled"] = len(lab)
            row["pseudo_all_correct"] = sum(1 for c in lab if res[c][1] == labels[c])
            row["pseudo_s5"] = sum(1 for c in lab if res[c][0] in ("S5_flagged", "S5_exhausted"))
            row["pseudo_s5_correct"] = sum(1 for c in lab if res[c][0] == "S5_flagged" and res[c][1] == labels[c])
            row["pseudo_by_stage"] = {k: f"{sum(1 for c in lab if res[c][0] == k and res[c][1] == labels[c])}/"
                                         f"{sum(1 for c in lab if res[c][0] == k)}"
                                      for k in sorted({res[c][0] for c in lab})}
        out[s] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2f-0152")
    a = ap.parse_args()
    W = World()
    cases, gold = load_cases()
    ADR = account_delete_rows(W)
    auth = {q["case_id"]: authorizes_deletion(q["request_text"])[0] for q in cases}
    R: dict = {}

    def opts(**kw):
        base = dict(window=(-75.0, -44.0), no_result=False, no_owner=False, scope="devtest", band_pad=0,
                    mask_s1=False, na_mode="include")
        base.update(kw)
        return SimpleNamespace(**base)

    # 1. reproduction check against the first run's saved JSON (S5 independent)
    repro = {}
    for tag, kw in (("base", {}), ("noresult", dict(no_result=True)), ("noowner", dict(no_owner=True)),
                    ("split", dict(scope="split"))):
        o = opts(**kw)
        info, d2 = stages_s1_s4b(W, cases, ADR, o)
        res = apply_s5(info, d2, "independent", None, o.scope)
        J = json.loads((RUNS / "g2-0137" / f"acct_stages_{tag}.json").read_text())["cases"]
        diff = [c for c in res if (res[c][0], res[c][1]) != (J[c]["stage"], J[c]["pick"])]
        repro[tag] = dict(cases=len(res), differing=len(diff), first=diff[:5])
        assert not diff, (tag, diff[:5])
    R["reproduces_g2-0137"] = repro

    # 2. test + DEV under each S5 mode/order, NA included and excluded
    pseudo_info, _ = stages_s1_s4b(W, cases, ADR, opts())
    labels = {c: d["pick"] for c, d in pseudo_info.items() if d["stage"] == "S1_identifier"}
    variants = {
        "base": {}, "noresult": dict(no_result=True), "mask_s1": dict(mask_s1=True),
        "mask_s1_noresult": dict(mask_s1=True, no_result=True),
        "mask_s1_noowner": dict(mask_s1=True, no_owner=True),
        "mask_s1_noowner_noresult": dict(mask_s1=True, no_owner=True, no_result=True),
    }
    picks_by = {}
    for vname, kw in variants.items():
        for na in ("include", "exclude"):
            o = opts(na_mode=na, **kw)
            info, d2 = stages_s1_s4b(W, cases, ADR, o)
            for mode, order in [("independent", None)] + [(m, od) for m in ("greedy", "matching") for od in ORDERS]:
                res = apply_s5(info, d2, mode, order, o.scope)
                tag = f"{vname}|na_{na}|{mode}{'|' + order if order else ''}"
                R[tag] = summarise(info, res, auth, gold, labels if vname.startswith("mask_s1") else None)
                picks_by[tag] = {c: res[c] for c in res if res[c][0] in ("S5_flagged", "S5_exhausted")}
    # 3. picks that change between orders (same variant, same mode), and independent vs greedy/matching
    set_of = {q["case_id"]: q["_set"] for q in cases}
    changes = {}

    def diff(t1, t2, s):
        p1, p2 = picks_by[t1], picks_by[t2]
        cs = [c for c in set(p1) | set(p2) if set_of[c] == s and auth[c]]
        return f"{sum(1 for c in cs if p1.get(c) != p2.get(c))}/{len(cs)}"

    for vname in variants:
        for na in ("include", "exclude"):
            for mode in ("greedy", "matching"):
                for o1, o2 in itertools.combinations(ORDERS, 2):
                    for s in ("dev", "test"):
                        changes[f"{vname}|na_{na}|{mode}|{o1}~{o2}|{s}"] = diff(
                            f"{vname}|na_{na}|{mode}|{o1}", f"{vname}|na_{na}|{mode}|{o2}", s)
                for s in ("dev", "test"):
                    changes[f"{vname}|na_{na}|independent~{mode}|req_asc|{s}"] = diff(
                        f"{vname}|na_{na}|independent", f"{vname}|na_{na}|{mode}|req_asc", s)
            for od in ORDERS:
                for s in ("dev", "test"):
                    changes[f"{vname}|na_{na}|greedy~matching|{od}|{s}"] = diff(
                        f"{vname}|na_{na}|greedy|{od}", f"{vname}|na_{na}|matching|{od}", s)
    R["pick_changes_between_orders"] = changes
    # 4. the base S5 groups in full (test, NA included and excluded), for the report
    for na in ("include", "exclude"):
        o = opts(na_mode=na)
        info, d2 = stages_s1_s4b(W, cases, ADR, o)
        rows = []
        for c, d in info.items():
            if d["stage"] is None and d2[c]:
                rows.append(dict(case=c, set=d["q"]["_set"], authorized=auth[c], requested_at=d["q"]["requested_at"],
                                 reported_at=d["q"]["reported_at"], d17=d.get("d17"),
                                 cands=sorted((r, round(off_min({x["resource_id"]: x for x in d["inwin"]}[r], d["rep"]), 2))
                                              for r in d2[c])))
        R[f"base_s5_rows_na_{na}"] = sorted(rows, key=lambda x: (x["reported_at"], x["requested_at"]))
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "s5_one_to_one.json").write_text(json.dumps(R, indent=1, default=list))
    for k, v in R.items():
        if k.startswith("base_s5_rows") or k == "pick_changes_between_orders":
            continue
        print(k, json.dumps(v, default=list))
    print("pick changes:")
    for k, v in changes.items():
        if not v.startswith("0/0"):
            print("  ", k, v)


if __name__ == "__main__":
    main()
