"""G2 follow-up, task 2 (T16): input signals for the true account ties left at S5 under the T4 order.

Run: python3 -I -B notes/forensics/f2_ties.py [--run g2f-0152]
Writes runs/<run>/f2_ties.json. Tie cases and their remaining candidates come from s5_one_to_one.stages_s1_s4b
(base T4, NA cases excluded; identical to the first run's S5 set, SEEN in s5_one_to_one.py's assertion).
Test signals use inputs only. Validity checks use two label sources:
  pseudo : identifier-linked (S1) accounts on DEV + test inputs (no gold);
  gold   : DEV gold accounts via devgold.py (holdout rows dropped before steps_json is parsed).
Nothing is keyed on a case ID, file name or row position. A signal 'separates' a tie case when it keeps exactly one
of the case's remaining candidates. Signals:
  SYS-a  source/target system of the candidates' delete rows differs within the case.
  SYS-b  a candidate has any other activity row (any event type), and that row's systems.
  SYS-c  a candidate has an evidence observation in a system/collection that the user's own linked units also have.
  REG-a  phone country code -> region: association on identifier-linked units, vs a permutation baseline.
  REG-b  a candidate has any region-bearing observation (log-line region= field, or a regional replica table).
  REG-c  candidate region equals the user's own linked units' regions, or the phone code's majority region.
  FIFO   earlier requested_at -> earlier account delete row, on co-batched pairs with both accounts known.
  LAG    correlation of (reported_at - requested_at) with the account delete offset (S1 accounts).
  GAP    correlation of the account delete offset with the same job's policy/after row offsets (S1 jobs).
  FILE   candidate observed in the case's citation file F (latest pre-audit file holding a user-linked unit).
  OBST   inside F, the candidate observation's time is nearest to one of the user's own units (vs other users').
  SUFX   candidate account number equals the number of another resource linked to the user.
  EDIG   the digits in the user's email local part occur in the candidate account number.
  UIDO   (diagnostic, not admissible under D3: ID order has no domain basis) user_id number order -> row order.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from types import SimpleNamespace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import (DATASET, RUNS, T, World, act_template, TEMPLATE_WINDOWS, account_delete_rows,  # noqa: E402
                    gold_account, load_cases, off_min)
import s5_one_to_one as S  # noqa: E402
from identity import resolve_email  # noqa: E402
from intent import authorizes_deletion  # noqa: E402
from logparse import parse_line  # noqa: E402


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 3) if sx and sy else None


def phone_cc(phone: str) -> str:
    m = re.match(r"^\+(\d{1,3})\s", phone.strip())
    return m.group(1) if m else "?"


def log_regions(W) -> dict:
    """resource_id -> list of (region, line ts, file_id) from log lines' region= field (re-parsed; extract.py drops it).
    The region of a *_started line is carried to the completed line of the same trace."""
    out = defaultdict(list)
    for fid, row in W.manifest.items():
        p = DATASET / row["file_path"]
        if p.suffix.lower() != ".log":
            continue
        recs = [r for r in (parse_line(x) for x in p.open(encoding="utf-8")) if r]
        tr_region = {}
        for r in recs:
            if r["trace"] and r["kv"].get("region"):
                tr_region.setdefault(r["trace"], r["kv"]["region"])
        for r in recs:
            rid = r["kv"].get("resource_id")
            reg = r["kv"].get("region") or tr_region.get(r["trace"])
            if rid and reg:
                out[rid].append((reg, r["ts"], fid))
    return out


def unit_regions(u, LR) -> set:
    regs = {reg for reg, ts, fid in LR.get(u.resource_id, []) if fid == u.file_id and ts == u.ts}
    m = re.search(r"replica_(ap_south|eu_west|us_east|eu_central)", u.table or "")
    if m:
        regs.add(m.group(1).replace("_", "-") + "*")
    return regs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2f-0152")
    a = ap.parse_args()
    W = World()
    cases, gold = load_cases()
    ADR = account_delete_rows(W)
    auth = {q["case_id"]: authorizes_deletion(q["request_text"])[0] for q in cases}
    o = SimpleNamespace(window=(-75.0, -44.0), no_result=False, no_owner=False, scope="devtest", band_pad=0,
                        mask_s1=False, na_mode="exclude")
    info, d2 = S.stages_s1_s4b(W, cases, ADR, o)
    ties = sorted((c for c, d in info.items() if d["stage"] is None and d2[c]), key=lambda c: int(c[5:]))
    LR = log_regions(W)
    R: dict = {"tie_cases": len(ties), "tie_cases_list": ties}
    # where region information exists at all: log lines with a region= field, per file, and their values
    reg_lines, reg_files, reg_vals = 0, Counter(), Counter()
    for fid, row in W.manifest.items():
        pth = DATASET / row["file_path"]
        if pth.suffix.lower() != ".log":
            continue
        for line in pth.open(encoding="utf-8"):
            r = parse_line(line)
            if r and r["kv"].get("region"):
                reg_lines += 1
                reg_files[fid] += 1
                reg_vals[r["kv"]["region"]] += 1
    R["REG_log_lines"] = dict(lines_with_region=reg_lines, log_files_with_region=len(reg_files),
                              log_files_total=sum(1 for r in W.manifest.values() if r["file_path"].endswith(".log")),
                              values=dict(reg_vals),
                              batch_trace_files_with_region=sum(1 for f in reg_files if "resource_lookup_trace" in W.manifest[f]["file_path"]))
    uid_of = {c: d["uid"] for c, d in info.items()}

    def own_units(c):
        d = info[c]
        q = d["q"]
        return [u for u in W.units if d["uid"] in u.users and q["requested_at"] <= u.ts <= q["audit_at"]]

    def cand_row(c, rid):
        return {x["resource_id"]: x for x in info[c]["inwin"]}[rid]

    def F_of(c):
        d = info[c]
        q = d["q"]
        link_res = {u.resource_id for u in W.link_units if d["uid"] in u.users}
        fs = sorted({u.file_id for u in W.units if u.file_id and (d["uid"] in u.users or u.resource_id in link_res)
                     and W.manifest[u.file_id]["captured_at"] <= q["audit_at"]}, key=lambda f: W.manifest[f]["captured_at"])
        return fs[-1] if fs else None

    sep = Counter()
    rows = []
    # validity label sets
    s1 = {c: d["pick"] for c, d in info.items() if d["stage"] == "S1_identifier"}
    s2 = {c: d["pick"] for c, d in info.items() if d["stage"] == "S2_timed_unique"}
    goldacc = {c: gold_account(gold[c])[0] for c in gold if gold_account(gold[c])}

    # --- REG-a validity: phone code vs region on identifier-linked units. Two forms: log-line region= only
    #     (form 'log'), and log-line plus regional-replica table tags (form 'all', tags end in '*').
    #     Baseline: the same purity after permuting phone codes across users (fixed seed, 500 draws).
    import random
    per_user = defaultdict(Counter)
    for c, d in info.items():
        for u in own_units(c):
            for reg in unit_regions(u, LR):
                per_user[d["uid"]][reg] += 1
    users = sorted(per_user)
    codes = [phone_cc(W.people[u].current["phone"]) for u in users]

    def purity(code_list, form):
        ct = defaultdict(Counter)
        for u, cc in zip(users, code_list):
            for reg, n in per_user[u].items():
                if form == "log" and reg.endswith("*"):
                    continue
                ct[cc][reg] += n
        tot = sum(sum(v.values()) for v in ct.values())
        return (sum(max(v.values()) for v in ct.values() if v) / tot if tot else None), tot, ct

    rng = random.Random(20261025)
    R["REG_a_validity"] = {}
    for form in ("log", "all"):
        obs, tot, ct = purity(codes, form)
        draws = []
        for _ in range(500):
            sh = codes[:]
            rng.shuffle(sh)
            draws.append(purity(sh, form)[0])
        allreg = Counter()
        for v in ct.values():
            allreg.update(v)
        R["REG_a_validity"][form] = dict(
            users=len(users), lines=tot, phone_codes=len(ct), region_values=sorted(allreg),
            purity_by_phone_code=round(obs, 3), permuted_mean=round(statistics.mean(draws), 3),
            permuted_share_ge_observed=round(sum(1 for x in draws if x >= obs) / len(draws), 3),
            table={k: dict(v) for k, v in sorted(ct.items())})
    _, _, ct = purity(codes, "log")
    cc_major = {cc: v.most_common(1)[0][0] for cc, v in ct.items() if v}

    for c in ties:
        d = info[c]
        q = d["q"]
        cands = sorted(d2[c])
        own = own_units(c)
        own_sys = {(u.system, u.kind) for u in own}
        own_regs = set().union(*[unit_regions(u, LR) for u in own]) if own else set()
        p = W.people[d["uid"]]
        cc = phone_cc(p.current["phone"])
        F = F_of(c)
        info_c = []
        for rid in cands:
            r = cand_row(c, rid)
            other_rows = [x for x in W.acts_by_res.get(rid, []) if x is not r]
            ev = W.by_res.get(rid, [])
            regs = set().union(*[unit_regions(u, LR) for u in ev]) if ev else set()
            num = re.search(r"(\d+)$", rid).group(1)
            own_nums = {re.search(r"(\d+)$", u.resource_id).group(1) for u in own
                        if u.resource_id and re.search(r"(\d+)$", u.resource_id) and u.resource_id != rid}
            em_digits = re.findall(r"\d{2,}", q["email"].split("@")[0])
            inF = [u for u in ev if u.file_id == F]
            obst = None
            if inF:
                fu = [u for u in W.file_units[F] if u.resource_id != rid and u.users]
                if fu:
                    t0 = T(inF[0].ts)
                    near = min(fu, key=lambda u: abs((T(u.ts) - t0).total_seconds()))
                    obst = d["uid"] in near.users
            info_c.append(dict(
                rid=rid, offset=round(off_min(r, d["rep"]), 2), systems=(r["source_system"], r["target_system"]),
                other_rows=[(x["event_type"], x["source_system"], x["target_system"]) for x in other_rows],
                ev=[(u.file_id, u.system, u.kind) for u in ev], ev_sys_match=any((u.system, u.kind) in own_sys for u in ev),
                regions=sorted(regs), region_match_own=bool(regs & own_regs),
                region_match_phone=bool(cc in cc_major and cc_major[cc] in regs),
                in_F=bool(inF), obst_nearest_own=obst, suffix_match=num in own_nums,
                email_digits_in_id=any(dg in num for dg in em_digits)))

        def one(key):
            return sum(1 for x in info_c if x[key]) == 1

        sep["SYS_a_systems_differ"] += len({x["systems"] for x in info_c}) > 1
        sep["SYS_b_any_other_row"] += any(x["other_rows"] for x in info_c)
        sep["SYS_c_separates"] += one("ev_sys_match")
        sep["REG_b_any_candidate_region"] += any(x["regions"] for x in info_c)
        sep["REG_b_own_units_with_region"] += bool(own_regs)
        sep["REG_c_own_region_separates"] += one("region_match_own")
        sep["REG_c_phone_region_separates"] += one("region_match_phone")
        sep["FILE_any_candidate_in_F"] += any(x["in_F"] for x in info_c)
        sep["FILE_separates"] += one("in_F")
        sep["OBST_separates"] += sum(1 for x in info_c if x["obst_nearest_own"]) == 1
        sep["SUFX_separates"] += one("suffix_match")
        sep["SUFX_any"] += any(x["suffix_match"] for x in info_c)
        sep["EDIG_separates"] += one("email_digits_in_id")
        sep["EDIG_any"] += any(x["email_digits_in_id"] for x in info_c)
        rows.append(dict(case=c, uid=d["uid"], phone_cc=cc, requested_at=q["requested_at"], reported_at=q["reported_at"],
                         F=F, own_regions=sorted(own_regs), cands=info_c))
    R["separations_over_tie_cases"] = dict(sep)

    # --- FIFO / UIDO on co-batched pairs (labels: S1 only; S1+S2; DEV gold with any known partner)
    def acc_time(c, rid):
        r = [x for x in ADR if x["resource_id"] == rid and -76 <= off_min(x, info[c]["rep"]) <= 9]
        return r[0]["_t"] if r else None

    def pairs(labels):
        by = defaultdict(list)
        for c, rid in labels.items():
            if auth.get(c) and acc_time(c, rid):
                by[info[c]["q"]["reported_at"]].append((c, rid))
        out = Counter()
        for grp in by.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    (c1, r1), (c2, r2) = grp[i], grp[j]
                    t1, t2 = acc_time(c1, r1), acc_time(c2, r2)
                    q1, q2 = info[c1]["q"], info[c2]["q"]
                    if q1["requested_at"] != q2["requested_at"]:
                        out["fifo_concordant" if (q1["requested_at"] < q2["requested_at"]) == (t1 < t2) else "fifo_discordant"] += 1
                    else:
                        out["fifo_same_requested_at"] += 1
                    u1, u2 = int(uid_of[c1].split("_")[1]), int(uid_of[c2].split("_")[1])
                    out["uid_concordant" if (u1 < u2) == (t1 < t2) else "uid_discordant"] += 1
        return dict(out)

    def pairs_dev(labels):
        """pairs with at least one DEV member (DEV label = gold account)"""
        by = defaultdict(list)
        for c, rid in labels.items():
            if auth.get(c) and acc_time(c, rid):
                by[info[c]["q"]["reported_at"]].append((c, rid))
        out = Counter()
        for grp in by.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    (c1, r1), (c2, r2) = grp[i], grp[j]
                    if info[c1]["q"]["_set"] != "dev" and info[c2]["q"]["_set"] != "dev":
                        continue
                    t1, t2 = acc_time(c1, r1), acc_time(c2, r2)
                    q1, q2 = info[c1]["q"], info[c2]["q"]
                    if q1["requested_at"] == q2["requested_at"]:
                        out["fifo_same_requested_at"] += 1
                    else:
                        out["fifo_concordant" if (q1["requested_at"] < q2["requested_at"]) == (t1 < t2) else "fifo_discordant"] += 1
        return dict(out)

    test_lab = {c: v for c, v in {**s1, **s2}.items() if info[c]["q"]["_set"] == "test"}
    R["FIFO_UIDO"] = dict(S1_pairs=pairs(s1), S1_S2_pairs=pairs({**s1, **s2}),
                          DEV_pairs_gold_labels=pairs_dev({**test_lab, **goldacc}))
    # --- LAG and GAP on S1 jobs
    lag, off, gx, gy = [], [], defaultdict(list), defaultdict(list)
    dw = [x for x in W.acts if x["source_system"] == "deletion_worker"]
    for c, rid in s1.items():
        t = acc_time(c, rid)
        if not t or not auth[c]:
            continue
        d = info[c]
        o_acc = (t - d["rep"]).total_seconds() / 60
        lag.append((d["rep"] - T(d["q"]["requested_at"])).total_seconds() / 3600)
        off.append(o_acc)
        for x in dw:
            if x["resource_id"] in d["linked_res"] and not x["resource_id"].startswith("account_"):
                tp = act_template(x)
                lo, hi = TEMPLATE_WINDOWS[tp]
                if lo <= off_min(x, d["rep"]) <= hi:
                    gx[tp].append(o_acc)
                    gy[tp].append(off_min(x, d["rep"]))
    R["LAG"] = dict(n=len(lag), pearson_lag_vs_offset=pearson(lag, off))
    R["GAP"] = {tp: dict(n=len(gx[tp]), pearson_submit_vs_row=pearson(gx[tp], gy[tp])) for tp in gx}
    # --- FILE / OBST / SUFX / EDIG validity: how often the labelled account has the property, vs the other
    #     in-window result-matched rows of the same case (the would-be competitors before one-to-one)
    def validity(labels, name):
        hit_true = hit_other = n_true = n_other = 0
        sx_true = sx_other = ed_true = ed_other = 0
        for c, rid in labels.items():
            if not auth.get(c):
                continue
            d = info[c]
            F = F_of(c)
            own = own_units(c)
            own_nums = {re.search(r"(\d+)$", u.resource_id).group(1) for u in own
                        if u.resource_id and re.search(r"(\d+)$", u.resource_id) and not u.resource_id.startswith("account_")}
            em_digits = re.findall(r"\d{2,}", d["q"]["email"].split("@")[0])
            comp = {r["resource_id"] for r in d["matched"]} - {rid}
            for r in [rid] + sorted(comp):
                inF = any(u.file_id == F for u in W.by_res.get(r, []))
                num = re.search(r"(\d+)$", r).group(1)
                sx = num in own_nums
                ed = any(dg in num for dg in em_digits)
                if r == rid:
                    n_true += 1
                    hit_true += inF
                    sx_true += sx
                    ed_true += ed
                else:
                    n_other += 1
                    hit_other += inF
                    sx_other += sx
                    ed_other += ed
        return {f"{name}_label_n": n_true, f"{name}_label_in_F": hit_true, f"{name}_others_n": n_other,
                f"{name}_others_in_F": hit_other, f"{name}_label_suffix": sx_true, f"{name}_others_suffix": sx_other,
                f"{name}_label_emaildigits": ed_true, f"{name}_others_emaildigits": ed_other}

    R["FILE_SUFX_EDIG_validity"] = {**validity(s2, "S2"), **validity({c: v for c, v in goldacc.items()}, "DEVgold")}
    # fairer FILE test: cases that had >= 2 unowned, result-matched candidates and were resolved by one-to-one or D17
    # (pseudo-accuracy of those stages is 26/26 and 1/1 under the S1-masked test in s5_one_to_one.py): is the pick
    # observed in F (or in any evidence file) more often than the losing unowned candidates?
    fv = Counter()
    for c, d in info.items():
        if d["stage"] not in ("S3_one_to_one", "S4_d17", "S4b_one_to_one_after_d17") or not auth[c]:
            continue
        F = F_of(c)
        for r in d["cand"]:
            role = "pick" if r == d["pick"] else "loser"
            fv[f"{role}_n"] += 1
            fv[f"{role}_in_F"] += any(u.file_id == F for u in W.by_res.get(r, []))
            fv[f"{role}_in_any_evidence"] += r in W.by_res
    R["FILE_validity_S3_S4"] = dict(fv)
    # S1 accounts: suffix base rate (account number equals another linked resource's number)
    sx = sum(1 for c, rid in s1.items() if auth[c] and re.search(r"(\d+)$", rid).group(1) in
             {re.search(r"(\d+)$", u.resource_id).group(1) for u in own_units(c)
              if u.resource_id and not u.resource_id.startswith("account_") and re.search(r"(\d+)$", u.resource_id)})
    R["SUFX_S1_base_rate"] = f"{sx}/{sum(1 for c in s1 if auth[c])}"
    R["rows"] = rows
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "f2_ties.json").write_text(json.dumps(R, indent=1, default=list))
    print(json.dumps({k: v for k, v in R.items() if k not in ("rows",)}, indent=1, default=list))


if __name__ == "__main__":
    main()
