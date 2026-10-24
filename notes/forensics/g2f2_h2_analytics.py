"""G2 follow-up 2, hypothesis 2: identifier-free analytics by policy slot (would amend T5).

Run: python3 -I notes/forensics/g2f2_h2_analytics.py --run g2f2-HHMM
Writes runs/<run>/h2_analytics.json.

Definitions (inputs only; nothing keyed on case IDs, files or row positions):
  job anchor A    : offset (s) of the case's assigned account delete row from reported_at (accounts from the V0
                    baseline, T4 + T26..T29; H1's V1 as a second anchor set).
  policy slot     : the minute bin before reported_at a 'Policy action completed' row falls in:
                    slot0 [-29,-28) min, slot1 [-22,-21), slot2 [-15,-14), slot3 [-8,-7), slot4 [-3,-2).
  residual        : (row offset - A) mod 60 s.
Slot bands are MEASURED here on identifier-linked policy rows of S1 jobs (test + DEV inputs; the record's owner is
known from identifiers, so no gold is used), then applied to identifier-free rows.
Matching forms for an identifier-free analytics policy row and a case:
  band   : prototype rule, residual mod 30 in 9..11 and the row inside the policy window -31..-2 min.
  slot   : the row's slot exists and residual is in that slot's measured band (exact min..max of S1 residuals).
  slotpm : slot parity, +-1 s (even slots 39..41, odd slots 9..11).
Limits (per person, T29): all claims; L1 drop a record claimed by more than one person; L2 drop claims anchored on an
S5 pick; M one-to-one matching (each case at most one record, each record one person; a pair is kept only when it is in
every maximum matching); NF keep claims only for cases whose steps (without analytics) have no finding.
Row effects: solve2 with the V0 accounts injected and (a) the prototype's signature analytics anchored on them vs
(b) each H2 form.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from dataclasses import replace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import (RUNS, T, World, AcctEngine, AcctOpts, Hooks, solve2, row_diff, gold_account,  # noqa: E402
                      load_cases, load_holdout_inputs, act_template, off_min)
from solver import Opts  # noqa: E402
from score import aggregate, score_case  # noqa: E402

SLOTS = [(-29, -28), (-22, -21), (-15, -14), (-8, -7), (-3, -2)]


def slot_of(o_min: float):
    for i, (lo, hi) in enumerate(SLOTS):
        if lo <= o_min < hi:
            return i
    return None


def measure_slots(W, eng) -> dict:
    """Per-slot residual distribution of identifier-linked policy rows, S1 jobs (and S2 jobs separately)."""
    dw = [a for a in W.acts if a["source_system"] == "deletion_worker" and act_template(a) == "policy"]
    out = {}
    for stage in ("S1_identifier", "S2_timed_unique"):
        res = defaultdict(Counter)
        by_action = defaultdict(Counter)
        offs = defaultdict(list)
        for c, d in eng.info.items():
            if d["stage"] != stage or d["pick_row"] is None or d["q"]["_set"] == "holdout":
                continue
            rep = d["rep"]
            A = (d["pick_row"]["_t"] - rep).total_seconds()
            if not (-75 <= A / 60 <= -44):
                continue
            linked = {u.resource_id for u in W.units if d["uid"] in u.users and u.resource_id}
            for a in dw:
                if a["resource_id"] not in linked:
                    continue
                o = (a["_t"] - rep).total_seconds()
                if not (-31 * 60 <= o <= -2 * 60):
                    continue
                s = slot_of(o / 60)
                res[s][int((o - A) % 60)] += 1
                by_action[f"{a['event_type']}:{a['target_system']}"][s] += 1
                offs[s].append(round(o / 60, 2))
        out[stage] = dict(residual_by_slot={str(k): dict(sorted(v.items())) for k, v in sorted(res.items(), key=lambda x: str(x[0]))},
                          slot_by_action={k: {str(s): n for s, n in v.items()} for k, v in by_action.items()},
                          minute_range_by_slot={str(k): (min(v), max(v)) for k, v in offs.items()})
    # after rows of S1 jobs: residual by position in the job's own after-row chain, and gaps between consecutive rows
    dwa = [a for a in W.acts if a["source_system"] == "deletion_worker" and act_template(a) == "after"]
    pos, gaps = Counter(), Counter()
    for c, d in eng.info.items():
        if d["stage"] != "S1_identifier" or d["pick_row"] is None or d["q"]["_set"] == "holdout":
            continue
        rep = d["rep"]
        A = (d["pick_row"]["_t"] - rep).total_seconds()
        if not (-75 <= A / 60 <= -44):
            continue
        linked = {u.resource_id for u in W.units if d["uid"] in u.users and u.resource_id}
        mine = sorted((a for a in dwa if a["resource_id"] in linked and 5 <= off_min(a, rep) <= 135), key=lambda a: a["_t"])
        prev = None
        for k, a in enumerate(mine):
            x = (a["_t"] - rep).total_seconds() - A
            pos[f"{k}:{int(x % 60)}"] += 1
            if prev is not None:
                gaps[str(round((x - prev) / 30, 2))] += 1
            prev = x
    out["after_rows_S1"] = dict(position_residual60=dict(sorted(pos.items())), gap_in_30s_units=dict(sorted(gaps.items())))
    bands = {}
    for s, cnt in out["S1_identifier"]["residual_by_slot"].items():
        ks = [int(x) for x in cnt]
        bands[int(s) if s != "None" else None] = (min(ks), max(ks))
    out["measured_bands_S1"] = {str(k): v for k, v in bands.items()}
    return out, bands


def free_rows(W):
    """Identifier-free analytics policy rows with evidence (the population the prototype attaches)."""
    return [a for a in W.acts if a["source_system"] == "deletion_worker" and act_template(a) != "submit"
            and not W.res_users.get(a["resource_id"]) and a["resource_id"] in W.by_res]


def fits(form: str, a, rep, A_s: float, bands: dict) -> bool:
    o = (a["_t"] - rep).total_seconds()
    r = (o - A_s) % 60
    if form == "band":
        if not (-31 * 60 <= o <= -2 * 60):
            return False
        return 9 <= (o - A_s) % 30 <= 11
    s = slot_of(o / 60)
    if s is None:
        return False
    if form == "slot":
        if s not in bands:
            return False
        lo, hi = bands[s]
        return lo <= r <= hi
    if form == "slotpm":
        return (39 <= r <= 41) if s % 2 == 0 else (9 <= r <= 11)
    raise ValueError(form)


def claims(W, eng, form: str, bands: dict, rows) -> dict:
    out = defaultdict(dict)
    for c, d in eng.info.items():
        if not d["pick"] or d["pick_row"] is None or not eng.auth[c]:
            continue
        rep = d["rep"]
        A_s = (d["pick_row"]["_t"] - rep).total_seconds()
        audit = d["q"]["audit_at"]
        for a in rows:
            rid = a["resource_id"]
            if not any(u.ts <= audit for u in W.by_res[rid]):
                continue
            if fits(form, a, rep, A_s, bands):
                out[c][rid] = d["stage"]
    return dict(out)


def limit(cl: dict, eng, mode: str, status: dict | None = None) -> dict:
    person = {c: eng.info[c]["person"] for c in eng.info}
    owners = defaultdict(set)
    for c, g in cl.items():
        for rid in g:
            owners[rid].add(person[c])
    if mode == "all":
        return {c: set(g) for c, g in cl.items()}
    if mode in ("L1", "L1L2", "L1L2NF"):
        out = {}
        for c, g in cl.items():
            keep = {rid for rid, st in g.items() if len(owners[rid]) == 1 and (mode == "L1" or st != "S5_flagged")}
            if mode == "L1L2NF" and status.get(c) != "COMPLETE":
                keep = set()
            if keep:
                out[c] = keep
        return out
    if mode in ("M", "ML2"):
        # one-to-one matching per connected component; keep pairs present in every maximum matching
        edges = {c: sorted(rid for rid, st in g.items() if mode == "M" or st != "S5_flagged") for c, g in cl.items()}
        edges = {c: e for c, e in edges.items() if e}
        parent = {c: c for c in edges}

        def f(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        by_r = defaultdict(list)
        for c, e in edges.items():
            for rid in e:
                by_r[rid].append(c)
        for lst in by_r.values():
            for x in lst[1:]:
                parent[f(x)] = f(lst[0])
        comps = defaultdict(list)
        for c in edges:
            comps[f(c)].append(c)
        out = {}
        for comp in comps.values():
            comp = sorted(comp, key=lambda c: (eng.info[c]["q"]["requested_at"], eng.info[c]["q"]["email"].lower()))
            best, sols = -1, []
            for combo in itertools.product(*[edges[c] + [None] for c in comp]):
                seen = {}
                okk = True
                for c, p in zip(comp, combo):
                    if p is None:
                        continue
                    if p in seen and seen[p] != person[c]:
                        okk = False
                        break
                    seen[p] = person[c]
                if not okk:
                    continue
                n = sum(1 for p in combo if p)
                if n > best:
                    best, sols = n, [combo]
                elif n == best:
                    sols.append(combo)
            for i, c in enumerate(comp):
                vals = {s[i] for s in sols}
                if len(vals) == 1 and None not in vals:
                    out[c] = {next(iter(vals))}
        return out
    raise ValueError(mode)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    hold = load_holdout_inputs()
    W = World()
    R: dict = {}
    e0 = AcctEngine(W, cases, AcctOpts())
    e1 = AcctEngine(W, cases + hold, replace(AcctOpts(), scope="batch", d17="qualify", with_holdout_inputs=True))
    meas, bands = measure_slots(W, e0)
    R["slot_measurement"] = meas
    from g2f2_lib import SLOT_BANDS
    assert {k: tuple(v) for k, v in bands.items()} == SLOT_BANDS, (bands, SLOT_BANDS)  # library copy = measurement
    rows = free_rows(W)
    R["free_rows_with_evidence"] = dict(n=len(rows), by=dict(Counter(f"{act_template(x)}:{x['event_type']}:{x['target_system']}" for x in rows)))
    # slot of each free row relative to the nearest following batch time (all request files' reported_at)
    reps = sorted({T(q["reported_at"]) for q in cases})  # DEV + test batches only (holdout inputs join H1 only)
    import bisect
    fslots = Counter()
    for x in rows:
        i = bisect.bisect_left(reps, x["_t"])
        fslots[str(slot_of((x["_t"] - reps[i]).total_seconds() / 60)) if i < len(reps) else "none"] += 1
    R["free_rows_with_evidence"]["by_slot"] = dict(fslots)

    # status without analytics, from the harness with the V0 accounts (for the NF test)
    proto = {q["case_id"]: solve2(q, W, Opts(), Hooks()) for q in cases}

    def acc_hooks(eng):
        acc, rws, empty = {}, {}, set()
        for c, d in eng.info.items():
            if d["q"]["_set"] == "holdout" or proto[c].status == "NOT_APPLICABLE" or d["stage"] == "S1_identifier":
                continue
            pa = sorted({s["resource_id"] for s in proto[c].steps if s["system_id"] == "account_service"})
            if [d["pick"]] == pa or (d["pick"] is None and not pa):
                continue
            acc[c], rws[c] = d["pick"], d["pick_row"]
            if d["stage"] == "T27_narrowC":
                empty.add((c, d["pick"]))
        return acc, rws, empty
    acc0, rows0, empty0 = acc_hooks(e0)
    # (a) reference: V0 accounts + prototype signature analytics anchored on them
    ref = {q["case_id"]: solve2(q, W, Opts(), Hooks(accounts=acc0, account_rows=rows0, empty_cite=empty0)) for q in cases}
    noana = {q["case_id"]: solve2(q, W, Opts(), Hooks(accounts=acc0, account_rows=rows0, empty_cite=empty0, analytics={}))
             for q in cases}
    status_noana = {c: r.status for c, r in noana.items()}
    ref_ana = {c: {s["resource_id"] for s in r.steps if s["system_id"] == "analytics_platform"
                   and any(m.startswith("job_signature") for m in r.trace["links"].get(s["resource_id"], ()))}
               for c, r in ref.items()}
    proto_ana = {c: {s["resource_id"] for s in r.steps if s["system_id"] == "analytics_platform"
                     and any(m.startswith("job_signature") for m in r.trace["links"].get(s["resource_id"], ()))}
                 for c, r in proto.items()}
    setof = {q["case_id"]: q["_set"] for q in cases}
    R["prototype_signature_analytics"] = dict(
        prototype_own_accounts=dict(test_cases=sum(1 for c, v in proto_ana.items() if v and setof[c] == "test"),
                                    test_steps=sum(len(v) for c, v in proto_ana.items() if setof[c] == "test"),
                                    dev={c: sorted(v) for c, v in proto_ana.items() if setof[c] == "dev" and v}),
        on_V0_accounts=dict(test_cases=sum(1 for c, v in ref_ana.items() if v and setof[c] == "test"),
                            test_steps=sum(len(v) for c, v in ref_ana.items() if setof[c] == "test")))
    gold_free = {}
    for c, g in gold.items():
        for s in g["steps"]:
            if s["system_id"] == "analytics_platform" and not W.res_users.get(s["resource_id"]):
                gold_free.setdefault(c, set()).add(s["resource_id"])
    R["dev_gold_identifier_free_analytics"] = {c: sorted(v) for c, v in gold_free.items()}

    results = {}
    for anchor_name, eng in (("V0", e0), ("V1_H1", e1)):
        for form in ("band", "slot", "slotpm"):
            cl = claims(W, eng, form, bands, rows)
            for mode in ("all", "L1", "L1L2", "M", "ML2", "L1L2NF"):
                kept = limit(cl, eng, mode, status_noana)
                tag = f"{anchor_name}|{form}|{mode}"
                test_k = {c: v for c, v in kept.items() if eng.info[c]["q"]["_set"] == "test"}
                dev_k = {c: v for c, v in kept.items() if eng.info[c]["q"]["_set"] == "dev"}
                tp = sum(len(v & gold_free.get(c, set())) for c, v in dev_k.items())
                fp = sum(len(v - gold_free.get(c, set())) for c, v in dev_k.items())
                fn = sum(len(gold_free[c] - dev_k.get(c, set())) for c in gold_free)
                own = defaultdict(set)
                for c, g in cl.items():
                    for rid in g:
                        own[rid].add(eng.info[c]["person"])
                results[tag] = dict(
                    claims_test=sum(len(g) for c, g in cl.items() if eng.info[c]["q"]["_set"] == "test"),
                    records_multi_person=len([r for r, v in own.items() if len(v) > 1]),
                    kept_test_pairs=sum(len(v) for v in test_k.values()), kept_test_cases=len(test_k),
                    kept_holdout_pairs=sum(len(v) for c, v in kept.items() if eng.info[c]["q"]["_set"] == "holdout"),
                    dev_tp=tp, dev_fp=fp, dev_fn=fn,
                    dev_fp_detail={c: sorted(v - gold_free.get(c, set())) for c, v in dev_k.items() if v - gold_free.get(c, set())},
                    dev_fn_detail={c: sorted(gold_free[c] - dev_k.get(c, set())) for c in gold_free if gold_free[c] - dev_k.get(c, set())},
                    claims_in_cases_with_findings_test=sum(len(g) for c, g in cl.items() if eng.info[c]["q"]["_set"] == "test" and status_noana.get(c) == "INCOMPLETE"),
                    claims_in_cases_with_findings_dev=sum(len(g) for c, g in cl.items() if eng.info[c]["q"]["_set"] == "dev" and status_noana.get(c) == "INCOMPLETE"))
                if anchor_name == "V0":
                    results[tag]["_kept"] = {c: sorted(v) for c, v in kept.items()}
    # row-level: each V0 form vs the reference (prototype signature on V0 accounts)
    for tag, v in results.items():
        if not tag.startswith("V0|"):
            continue
        kept = {c: set(x) for c, x in v.pop("_kept").items()}
        hk = Hooks(accounts=acc0, account_rows=rows0, empty_cite=empty0, analytics=kept)
        changed_test, changed_dev, step_add, step_rem = [], {}, 0, 0
        sc = []
        for q in cases:
            c = q["case_id"]
            r2 = solve2(q, W, Opts(), hk)
            d = row_diff(ref[c], r2)
            if d:
                if q["_set"] == "test":
                    changed_test.append(c)
                else:
                    changed_dev[c] = d
                step_add += sum(1 for x in d if x.startswith("step added"))
                step_rem += sum(1 for x in d if x.startswith("step removed"))
            if q["_set"] == "dev":
                g = gold[c]
                s = score_case(r2.status, r2.steps, g["status"], g["steps"])
                s["exact"] = s["status_ok"] and s["steps_ok"]
                s["case_id"] = c
                sc.append(s)
        ag = aggregate(sc)
        v["rows_vs_reference"] = dict(test_cases_changed=len(changed_test), steps_added=step_add, steps_removed=step_rem,
                                      dev_changed=changed_dev, dev_case_exact=ag["case_exact"], dev_step_tp=ag["step_tp"],
                                      dev_field_hits=ag["field_hits"], dev_inexact=[s["case_id"] for s in sc if not s["exact"]])
        # compare analytics sets with the prototype's own signature analytics (prototype accounts)
        ch = [c for c in set(kept) | {c for c, x in proto_ana.items() if x} if setof.get(c) == "test" and kept.get(c, set()) != proto_ana.get(c, set())]
        v["test_cases_whose_analytics_differ_from_prototype"] = len(ch)
        v["prototype_analytics_steps_removed_test"] = sum(len(proto_ana.get(c, set()) - kept.get(c, set())) for c in ch)
        v["analytics_steps_added_vs_prototype_test"] = sum(len(kept.get(c, set()) - proto_ana.get(c, set())) for c in ch)
    R["forms"] = results
    # DEV gold credit: how each DEV gold analytics step is found (identifier link vs signature), with its row
    credit = {}
    dw = [x for x in W.acts if x["source_system"] == "deletion_worker"]
    for c, g in sorted(gold.items()):
        for s in g["steps"]:
            if s["system_id"] != "analytics_platform":
                continue
            rid = s["resource_id"]
            linked = sorted(W.res_users.get(rid, set()))
            d = e0.info[c]
            rep = d["rep"]
            rws = [x for x in dw if x["resource_id"] == rid]
            info = []
            for x in rws:
                o = (x["_t"] - rep).total_seconds()
                A_s = (d["pick_row"]["_t"] - rep).total_seconds() if d["pick_row"] is not None else None
                info.append(dict(activity=x["activity_id"], template=act_template(x), event=x["event_type"], result=x["reported_result"],
                                 offset_min=round(o / 60, 2), slot=slot_of(o / 60),
                                 residual60=(int((o - A_s) % 60) if A_s is not None else None)))
            obs = sorted({(u.file_id, u.ts[:19], str(__import__('solver').unit_state(u))) for u in W.by_res.get(rid, []) if u.file_id})
            credit.setdefault(c, []).append(dict(step=f"{s['phase']} {s['operation']} {rid} cite={s['evidence_id'] or '-'}",
                                                 identifier_linked_to=linked, worker_rows=info, observations=obs,
                                                 case_status=g["status"]))
    R["dev_gold_analytics_credit"] = credit
    # backup_3120 / analytics_4566 / other rows of the 09-02 batch: fit per DEV job under each form
    batch_rows = {}
    for c in ("case_24", "case_26"):
        d = e0.info[c]
        rep = d["rep"]
        A_s = (d["pick_row"]["_t"] - rep).total_seconds()
        for x in dw:
            o = (x["_t"] - rep).total_seconds()
            if -31 * 60 <= o <= -2 * 60 and act_template(x) == "policy":
                batch_rows.setdefault(x["resource_id"], {})[c] = dict(
                    offset_min=round(o / 60, 2), slot=slot_of(o / 60), residual60=int((o - A_s) % 60),
                    band=fits("band", x, rep, A_s, bands), slot_fit=fits("slot", x, rep, A_s, bands),
                    linked_to=sorted(W.res_users.get(x["resource_id"], set())))
    R["batch_2026-09-02T12_policy_rows"] = batch_rows
    R["dev_people"] = {c: e0.info[c]["uid"] for c in ("case_24", "case_26")}
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h2_analytics.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps({k: R[k] for k in ("slot_measurement", "free_rows_with_evidence", "prototype_signature_analytics",
                                        "dev_gold_identifier_free_analytics")}, indent=1, default=str)[:6000])
    for tag, v in R["forms"].items():
        print(tag, json.dumps(v, default=str)[:900])


if __name__ == "__main__":
    main()
