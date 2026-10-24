"""G2 follow-up 2 (g2f2) shared library.

Parts:
  1. Loaders. DEV + test request rows come from common.load_cases (holdout dropped, DEV gold via devgold.py).
     load_holdout_inputs() returns the 10 holdout *request input* rows only (sample_deletion_requests.csv), for the
     H1 batch pass (developer instruction T32). Holdout gold is never opened: sample_output.csv is read only by
     devgold.py, which drops holdout rows before parsing.
  2. AcctEngine: one general account engine. With the default options it is the ruled baseline:
     T4 (S1 identifier link, S2 timed rule, S3 one-to-one, S4 D17 tie-break, S4b, S5 flagged pick)
     + T26 (Option A: +-10 min, result-matched, only when S1 and S2 are empty)
     + T27 (narrow C: own email/phone joined on a log trace, any line time, identity only)
     + T28 (no account named anywhere -> omitted and flagged)
     + T29 (one-to-one per person: an account taken by person P leaves only other persons' candidate sets).
     Options switch on the H1 batch pass (D17 as a qualifying condition, batch-scoped matching, sample inputs).
  3. solve2(): a copy of research/prototype/solver.py solve() with hooks (account override, analytics override,
     omission observations, support-category override). With no hooks it must reproduce the prototype exactly;
     check_harness() asserts that on all 540 DEV+test cases.
No rule here is keyed on a case ID, file name or row position. Every sort names its key.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import csv  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import itertools  # noqa: E402
import re  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from dataclasses import dataclass, field, replace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import (DATASET, RUNS, T, World, STATUS_TO_RESULT, act_template, TEMPLATE_WINDOWS,  # noqa: E402
                    account_delete_rows, gold_account, id_linked_accounts, load_cases, off_min)
import devgold  # noqa: E402
import solver  # noqa: E402
from solver import (Opts, CaseResult, unit_state, category, VIOLATING, COMPLIANT_VERIFY, STATE_OF,  # noqa: E402
                    OP_ORDER, PHASES, sig_match)
from identity import resolve_email  # noqa: E402
from intent import authorizes_deletion  # noqa: E402


# ----------------------------------------------------------------------------- 1. loaders
def load_holdout_inputs() -> list[dict]:
    """Holdout request INPUT rows (never gold). Used only as unknown competitors in the H1 batch pass (T32)."""
    _, hold = devgold.load_split()
    rows = []
    with open(DATASET / "sample_deletion_requests.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["case_id"] in hold:
                r["_set"] = "holdout"
                rows.append(r)
    assert len(rows) == 10
    return rows


# ----------------------------------------------------------------------------- policy slots (H2)
SLOTS = [(-29, -28), (-22, -21), (-15, -14), (-8, -7), (-3, -2)]  # minute bins before reported_at
# per-slot residual band (row offset - account offset) mod 60 s, measured by g2f2_h2_analytics.py on identifier-linked
# policy rows of S1 jobs (runs/<run>/h2_analytics.json: slot_measurement.measured_bands_S1)
SLOT_BANDS = {0: (40, 41), 1: (10, 11), 2: (39, 40), 3: (9, 10), 4: (39, 39)}


def slot_of(o_min: float):
    for i, (lo, hi) in enumerate(SLOTS):
        if lo <= o_min < hi:
            return i
    return None


# ----------------------------------------------------------------------------- 2. account engine
@dataclass
class AcctOpts:
    window: tuple = (-75.0, -44.0)
    result: bool = True              # S2 result match
    owner: bool = True               # drop accounts identifier-linked (any time) to another person
    option_a: bool = True            # T26
    narrow_c: bool = True            # T27
    d17: str = "tiebreak"            # 'tiebreak' (T4 S4) | 'qualify' (H1 condition iii) | 'off'
    d17_link: str = "window"         # own rows: resources linked in [requested_at, audit_at] | 'pre_audit' (<= audit_at)
    assign: str = "propagate"        # 'propagate' (T4 S3: unique-first fixed point) | 'forced' (edge in every max matching)
    scope: str = "global"            # 'global' (one pass over every request in scope, T4) | 'batch' (per reported_at)
    with_holdout_inputs: bool = False  # H1: holdout request inputs join as unknown competitors
    s5_order: str = "req_asc"        # S5 matching tie order: requested_at, then lower-case email
    na: str = "include"              # NA requests run through the stages ('include', as acct_stages.py) or not
    grid: str = "band30"             # D17 fit: 'band30' (prototype sig_match) | 'slot' (policy rows: per-slot mod-60
                                     # band measured on S1 jobs; after rows: band30) | 'slotpm' (slot parity, +-1 s)
    mask_s1: bool = False            # stress test: identifier links are not used to pick accounts


def order_key(q: dict, name: str):
    em = q["email"].strip().lower()
    if name == "req_asc":
        return (q["requested_at"], em)
    if name == "req_desc":
        return tuple(-ord(ch) for ch in q["requested_at"]) + tuple(-ord(ch) for ch in em)
    if name == "email_sha":
        return (hashlib.sha256(em.encode()).hexdigest(),)
    raise ValueError(name)


class AcctEngine:
    """Account assignment over a set of requests. Result: self.res[case] = dict(stage, pick, flags, ...)."""

    def __init__(self, W: World, reqs: list[dict], o: AcctOpts):
        self.W, self.o = W, o
        self.ADR = account_delete_rows(W)
        self.dw = [a for a in W.acts if a["source_system"] == "deletion_worker"]
        self.auth = {q["case_id"]: authorizes_deletion(q["request_text"])[0] for q in reqs}
        self.reqs = [q for q in reqs if o.na == "include" or self.auth[q["case_id"]]]
        self.info: dict[str, dict] = {}
        self.conflicts: list = []
        self._prepare()
        self._run()

    # -- per-request facts
    def own_rows(self, q, uid, rep) -> list[dict]:
        if self.o.d17_link == "window":
            linked = {u.resource_id for u in self.W.units if uid in u.users and u.resource_id
                      and q["requested_at"] <= u.ts <= q["audit_at"]}
        else:
            linked = {u.resource_id for u in self.W.units if uid in u.users and u.resource_id and u.ts <= q["audit_at"]}
        out = []
        for a in self.dw:
            if a["resource_id"] not in linked or act_template(a) == "submit":
                continue
            lo, hi = TEMPLATE_WINDOWS[act_template(a)]
            if lo <= off_min(a, rep) <= hi:
                out.append(a)
        return out

    def fits(self, row, rep, own) -> bool:
        A = (row["_t"] - rep).total_seconds() % 60
        if self.o.grid == "band30":
            return all(sig_match(x, rep, A) for x in own)
        for x in own:
            o = (x["_t"] - rep).total_seconds()
            s = slot_of(o / 60) if act_template(x) == "policy" else None
            if s is None:
                if not sig_match(x, rep, A):
                    return False
                continue
            r = (o - A) % 60
            if self.o.grid == "slot":
                lo, hi = SLOT_BANDS.get(s, (None, None))
                if lo is None or not (lo <= r <= hi):
                    return False
            else:
                if not ((39 <= r <= 41) if s % 2 == 0 else (9 <= r <= 11)):
                    return False
        return True

    def _prepare(self):
        W, o = self.W, self.o
        LO, HI = o.window
        for q in self.reqs:
            uid = resolve_email(q["email"], W.idx)
            rep = T(q["reported_at"])
            want = STATUS_TO_RESULT.get(q["reported_status"])
            il = sorted(id_linked_accounts(W, uid, q, "window")) if uid and uid != "AMBIGUOUS" else []
            inwin = [r for r in self.ADR if LO <= off_min(r, rep) <= HI]
            near10 = [r for r in self.ADR if -10 <= off_min(r, rep) <= 10]

            def ok(r):
                if o.result and r["reported_result"] != want:
                    return False
                if o.owner and (W.res_users.get(r["resource_id"], set()) - {uid}):
                    return False
                return True
            cand = {r["resource_id"]: r for r in inwin if ok(r)}
            flags = []
            if o.mask_s1:
                il_true, il = il, []
            if not il and not cand and o.option_a:
                fa = {r["resource_id"]: r for r in near10 if r["reported_result"] == want
                      and not (W.res_users.get(r["resource_id"], set()) - {uid})}
                if fa:
                    cand = fa
                    flags.append("T26_optionA")
            own = self.own_rows(q, uid, rep)
            d17_dropped = []
            if o.d17 == "qualify" and not il and own:
                keep = {k: v for k, v in cand.items() if self.fits(v, rep, own)}
                d17_dropped = sorted(set(cand) - set(keep))
                cand = keep
            self.info[q["case_id"]] = dict(q=q, uid=uid, person=uid or ("?" + q["case_id"]), rep=rep, want=want, il=il,
                                           il_label=(il_true if o.mask_s1 else il),
                                           cand=cand, own=own, flags=flags, stage=None, pick=None, pick_row=None,
                                           pre=len(cand), d17_dropped=d17_dropped,
                                           batch=q["reported_at"] if o.scope == "batch" else "all")
            if il and not o.mask_s1:
                d = self.info[q["case_id"]]
                d["stage"], d["pick"] = "S1_identifier", il[0]
                rows = [r for r in self.ADR if r["resource_id"] == il[0]]
                d["pick_row"] = min(rows, key=lambda r: abs(off_min(r, rep) + 60)) if rows else None

    # -- one-to-one helpers (per person, T29)
    def taken_by_others(self, c) -> set:
        d = self.info[c]
        out = set()
        for c2, d2 in self.info.items():
            if d2["pick"] and d2["person"] != d["person"] and d2["batch"] == d["batch"]:
                out.add(d2["pick"])
        return out

    def propagate(self, stage_name: str):
        """Unique-first fixed point; conflict-safe (a unique candidate already taken by another person empties the
        set and is recorded). Cases are visited in requested_at, email order inside each pass."""
        changed = True
        while changed:
            changed = False
            for c in sorted((c for c, d in self.info.items() if d["stage"] is None),
                            key=lambda c: order_key(self.info[c]["q"], "req_asc")):
                d = self.info[c]
                tk = self.taken_by_others(c)
                new = {k: v for k, v in d["cand"].items() if k not in tk}
                if len(new) != len(d["cand"]):
                    d["cand"] = new
                    changed = True
                if len(new) == 1:
                    k = next(iter(new))
                    d["stage"], d["pick"], d["pick_row"] = stage_name, k, new[k]
                    changed = True
                elif not new and d["pre"] > 0 and not d.get("emptied"):
                    d["emptied"] = True
                    self.conflicts.append(c)

    def forced(self, stage_name: str):
        """Per batch component: enumerate maximum matchings of unresolved requests (same person = one node);
        a request whose pick is the same account in every maximum matching takes it."""
        unresolved = [c for c, d in self.info.items() if d["stage"] is None and d["cand"]]
        for comp in self.components(unresolved):
            comp = sorted(comp, key=lambda c: order_key(self.info[c]["q"], "req_asc"))
            tk = {c: self.taken_by_others(c) for c in comp}
            opts = [[k for k in sorted(self.info[c]["cand"]) if k not in tk[c]] + [None] for c in comp]
            best, sols = -1, []
            for combo in itertools.product(*opts):
                if not self._valid(comp, combo):
                    continue
                n = sum(1 for p in combo if p)
                if n > best:
                    best, sols = n, [combo]
                elif n == best:
                    sols.append(combo)
            for i, c in enumerate(comp):
                vals = {s[i] for s in sols}
                if len(vals) == 1 and None not in vals:
                    k = next(iter(vals))
                    d = self.info[c]
                    d["stage"], d["pick"], d["pick_row"] = stage_name, k, d["cand"][k]

    def _valid(self, comp, combo) -> bool:
        seen = {}
        for c, p in zip(comp, combo):
            if p is None:
                continue
            per = self.info[c]["person"]
            if p in seen and seen[p] != per:
                return False
            seen[p] = per
        return True

    def components(self, cs):
        cs = list(cs)
        parent = {c: c for c in cs}

        def f(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        by_acc = defaultdict(list)
        for c in cs:
            for k in self.info[c]["cand"]:
                by_acc[(self.info[c]["batch"], k)].append(c)
        for lst in by_acc.values():
            for x in lst[1:]:
                parent[f(x)] = f(lst[0])
        groups = defaultdict(list)
        for c in cs:
            groups[f(c)].append(c)
        return list(groups.values())

    def d17_tiebreak(self):
        for c, d in self.info.items():
            if d["stage"] or len(d["cand"]) < 2:
                continue
            if not d["own"]:
                d["d17"] = "no_own_rows"
                continue
            fit = {k: v for k, v in d["cand"].items() if self.fits(v, d["rep"], d["own"])}
            d["d17"] = f"fit {len(fit)}/{len(d['cand'])}"
            if fit and len(fit) < len(d["cand"]):
                d["cand"] = fit
                if len(fit) == 1:
                    k = next(iter(fit))
                    d["stage"], d["pick"], d["pick_row"] = "S4_d17", k, fit[k]

    def s5_matching(self):
        """T29 + D18: per component, the assignment with the most picks, then the smallest total |offset+60|,
        then the stated order (s5_order) lexicographically. Every pick is flagged."""
        unresolved = [c for c, d in self.info.items() if d["stage"] is None and d["cand"]]
        for comp in self.components(unresolved):
            comp = sorted(comp, key=lambda c: order_key(self.info[c]["q"], self.o.s5_order))
            tk = {c: self.taken_by_others(c) for c in comp}

            def cost(c, k):
                return abs(off_min(self.info[c]["cand"][k], self.info[c]["rep"]) + 60)
            avail = {c: sorted((k for k in self.info[c]["cand"] if k not in tk[c]), key=lambda k: (cost(c, k), k))
                     for c in comp}
            best, bk = None, None
            for combo in itertools.product(*[avail[c] + [None] for c in comp]):
                if not self._valid(comp, combo):
                    continue
                n = sum(1 for p in combo if p)
                tot = round(sum(cost(c, p) for c, p in zip(comp, combo) if p), 6)
                lex = tuple((avail[c] + [None]).index(p) for c, p in zip(comp, combo))
                kk = (-n, tot, lex)
                if bk is None or kk < bk:
                    best, bk = combo, kk
            for c, p in zip(comp, best):
                d = self.info[c]
                if p:
                    d["stage"], d["pick"], d["pick_row"] = "S5_flagged", p, d["cand"][p]
                    d["flags"].append("D18_pick")
                else:
                    d["stage"] = "S5_exhausted"
                    d["flags"].append("S5_exhausted")

    def narrow_c(self):
        """T27: own email or phone as the lookup key, joined on a log trace to an account resource; any line time."""
        W = self.W
        for c, d in self.info.items():
            if d["pick"] or d["stage"] not in (None, "S5_exhausted"):
                continue
            uid = d["uid"]
            if not uid or uid == "AMBIGUOUS":
                continue
            p = W.people[uid]
            own_keys = p.emails | p.phones
            hits = sorted({u.resource_id for u in W.units if u.resource_id and u.system in ("account_service", "profile_service")
                           and u.kind.startswith("log:") and (u.ids & own_keys)})
            if hits:
                d["stage"], d["pick"] = "T27_narrowC", hits[0]
                d["flags"].append("T27_post_audit_identity_link")
                d["t27_all"] = hits

    def _run(self):
        o = self.o
        if o.assign == "forced":
            self.forced("S3_forced")
            self.propagate("S3_one_to_one")
        else:
            self.propagate("S2S3_timed_unique")
            for c, d in self.info.items():
                if d["stage"] == "S2S3_timed_unique":
                    d["stage"] = "S2_timed_unique" if d["pre"] == 1 else "S3_one_to_one"
        for c, d in self.info.items():
            if "T26_optionA" in d["flags"] and d["stage"] in ("S2_timed_unique", "S3_one_to_one", "S3_forced"):
                d["stage"] = "T26_optionA"
        if o.d17 == "tiebreak":
            self.d17_tiebreak()
            self.propagate("S4b_one_to_one_after_d17")
        self.s5_matching()
        if o.narrow_c:
            self.narrow_c()
        for c, d in self.info.items():
            if d["stage"] is None:
                d["stage"] = "NONE"
            if d["stage"] in ("NONE", "S5_exhausted") and not d["pick"]:
                d["flags"].append("T28_omitted")

    def picks(self) -> dict[str, dict]:
        return {c: dict(stage=d["stage"], pick=d["pick"], flags=list(d["flags"]), set=d["q"]["_set"],
                        auth=self.auth[c], person=d["person"], batch_key=d["q"]["reported_at"])
                for c, d in self.info.items()}


# ----------------------------------------------------------------------------- 3. hookable solve()
@dataclass
class Hooks:
    accounts: dict | None = None        # case -> account id or None (T28 omit); missing key -> prototype logic
    account_rows: dict | None = None    # case -> submit row used as the D17 anchor (None: no anchor)
    empty_cite: set = field(default_factory=set)   # (case, rid) verifications cited "" even in COMPLETE (T27)
    analytics: dict | None = None       # case -> set of identifier-free rids to attach; None -> prototype signature
    omission: str | None = None         # None | 'latest' | 'severe'
    omission_units: dict | None = None  # rid -> list of (ts, file_id, captured) absence observations
    omission_replica_aware: bool = False  # omission never overrides a resource that has a replica-table copy
    support_cat: str | None = None      # None | 'worker'
    cue_form: str = "any"               # attachment cues from units at any time ('any') or <= audit_at ('pre')
    worker_form: str = "any"            # worker rows at any time | 'pre' (<= audit_at) | 'job' (the case's template windows)


SEVERITY = ["PRESENT", "IDENTIFIABLE", "ACTIVE", "PII_TOMBSTONE"]  # violating states (any of them is 'most severe')


def solve2(q: dict, W: World, opts: Opts | None = None, hk: Hooks | None = None) -> CaseResult:
    """research/prototype/solver.py solve(), copied line for line, plus hook points marked HOOK."""
    opts = opts or Opts()
    hk = hk or Hooks()
    tr: dict = {"guesses": [], "model_needed": [], "notes": [], "links": {}}
    cid, audit, rep = q["case_id"], q["audit_at"], T(q["reported_at"])
    ok, why = authorizes_deletion(q["request_text"])
    tr["model_needed"].append(("intent", ok, why))
    if not ok:
        return CaseResult(cid, "NOT_APPLICABLE", [], tr)
    uid = resolve_email(q["email"], W.idx)
    if not uid or uid == "AMBIGUOUS":
        tr["notes"].append("IDENTITY_UNRESOLVED")
        return CaseResult(cid, "FAILED_IDENTITY", [], tr)
    tr["uid"] = uid
    lower = q[opts.discovery_lower] if opts.discovery_lower else "0000"

    def admissible(u) -> bool:
        if u.ts > audit:
            return False
        if not opts.allow_postfile_lines and u.file_id and W.manifest[u.file_id]["captured_at"] > audit:
            return False
        return True

    linked = [u for u in W.units if uid in u.users and lower <= u.ts and admissible(u)]
    res_keys: dict[str, str] = {}
    for u in linked:
        if u.resource_id:
            res_keys.setdefault(u.resource_id, u.system)
            tr["links"].setdefault(u.resource_id, set()).add("identifier:" + (u.file_id or u.attrs.get("activity_id", "")))

    link_res = {u.resource_id for u in W.link_units if uid in u.users}
    linked_files = sorted({u.file_id for u in W.units if u.file_id and (uid in u.users or u.resource_id in link_res)
                           and W.manifest[u.file_id]["captured_at"] <= audit},
                          key=lambda f: W.manifest[f]["captured_at"])
    F = linked_files[-1] if linked_files else None
    if F is None:
        cands = sorted({u.file_id for u in W.units if u.file_id and u.system == "account_service"
                        and W.manifest[u.file_id]["captured_at"] <= audit},
                       key=lambda f: W.manifest[f]["captured_at"])
        F = cands[-1] if cands else None
        tr["notes"].append(f"F fallback (no user-linked file): latest pre-audit account_service file {F}")
    tr["F"] = F

    lo, hi = rep - dt.timedelta(minutes=opts.act_before_min), rep + dt.timedelta(minutes=opts.act_after_min)
    win = [a for a in W.acts if lo <= a["_t"] <= hi]
    dw = [a for a in win if a["source_system"] == "deletion_worker"]
    if opts.template_windows:
        def in_tw(a: dict) -> bool:
            lo_m, hi_m = TEMPLATE_WINDOWS[act_template(a)]
            return lo_m <= (a["_t"] - rep).total_seconds() / 60 <= hi_m
        dw = [a for a in dw if in_tw(a)]

    def others(rid: str) -> set:
        return W.res_users.get(rid, set()) - {uid}

    acc_linked = sorted({r for r, s in res_keys.items() if s == "account_service"})
    acc_rows = [a for a in dw if a["event_type"] == "DELETE_RECORD" and a["target_system"] == "account_service"
                and not others(a["resource_id"])]
    acc_row = None
    if hk.accounts is not None and cid in hk.accounts:  # HOOK: account override
        pick = hk.accounts[cid]
        for r in acc_linked:
            if r != pick:
                res_keys.pop(r, None)
        if pick:
            res_keys[pick] = "account_service"
            tr["links"].setdefault(pick, set()).add("hook_account")
        acc_row = (hk.account_rows or {}).get(cid)
    elif acc_linked:
        for a in acc_rows:
            if a["resource_id"] in acc_linked:
                acc_row = a
        accounts = acc_linked
        for r in accounts:
            tr["links"].setdefault(r, set()).add("identifier")
    else:
        want = STATUS_TO_RESULT.get(q["reported_status"])
        c1 = ([a for a in acc_rows if a["reported_result"] == want] or acc_rows) if opts.account_result_match else list(acc_rows)
        method = "activity_window+result" if any(a["reported_result"] == want for a in acc_rows) else "activity_window"
        if len(c1) > 1:
            inev = [a for a in c1 if a["resource_id"] in W.by_res]
            if inev and len(inev) < len(c1):
                c1, method = inev, method + "+in_evidence"
        if len(c1) > 1:
            own_after = [a for a in dw if a["resource_id"] in res_keys and act_template(a) != "submit"]
            if own_after:
                def fits(acc):
                    A = (acc["_t"] - rep).total_seconds() % 60
                    return all(sig_match(o, rep, A) for o in own_after)
                fit = [a for a in c1 if fits(a)]
                if fit and len(fit) < len(c1):
                    c1, method = fit, method + "+signature"
        if len(c1) > 1:
            c1.sort(key=lambda a: abs((a["_t"] - rep).total_seconds() + 3600))
            tr["guesses"].append(("account", [a["resource_id"] for a in c1]))
            method += "+GUESS"
        accounts = [c1[0]["resource_id"]] if c1 else []
        acc_row = c1[0] if c1 else None
        for r in accounts:
            res_keys[r] = "account_service"
            tr["links"].setdefault(r, set()).add(method)
        if not accounts:
            tr["notes"].append("NO_ACCOUNT_FOUND")
    tr["acc_row"] = acc_row["activity_id"] if acc_row else None

    if hk.analytics is not None:  # HOOK: analytics override
        for rid in sorted(hk.analytics.get(cid, set())):
            if rid not in res_keys:
                res_keys[rid] = "analytics_platform"
                tr["links"].setdefault(rid, set()).add("hook_analytics")
    elif opts.use_signature and acc_row is not None:
        A = (acc_row["_t"] - rep).total_seconds() % 60
        for a in dw:
            rid = a["resource_id"]
            if rid in res_keys or a is acc_row or act_template(a) == "submit":
                continue
            if W.res_users.get(rid):
                continue
            if rid not in W.by_res:
                continue
            if not any(admissible(u) for u in W.by_res[rid]):
                continue
            if sig_match(a, rep, A):
                res_keys[rid] = a["target_system"] if a["target_system"] != "identity_service" else "identity_service"
                tr["links"].setdefault(rid, set()).add("job_signature:" + a["activity_id"])

    findings, verifs = [], []
    tr["state"] = {}
    for rid, sysid in sorted(res_keys.items()):
        obs = [u for u in W.by_res.get(rid, []) if admissible(u) and unit_state(u) is not None]
        if sysid == "integration_service" or sysid == "backup_service":
            obs = [u for u in obs if unit_state(u) is not None]
        cat = category(sysid, W.by_res.get(rid, []))
        if not opts.category_content and cat == "MARKETING_PROFILE" and sysid == "analytics_platform":
            cat = "ANALYTICS_PROFILE"
        if hk.support_cat == "worker" and sysid == "support_platform":  # HOOK: support category
            cue_units = W.by_res.get(rid, []) if hk.cue_form == "any" else [u for u in W.by_res.get(rid, []) if u.ts <= audit]
            cue_cat = category(sysid, cue_units)
            cat = cue_cat
            if cue_cat == "SUPPORT_MESSAGE":  # no attachment cue visible (in the stated form)
                rws = [a for a in W.acts if a["resource_id"] == rid and a["source_system"] == "deletion_worker"]
                if hk.worker_form == "pre":
                    rws = [a for a in rws if a["event_time"] <= audit]
                elif hk.worker_form == "job":
                    rws = [a for a in rws if act_template(a) != "submit"
                           and TEMPLATE_WINDOWS[act_template(a)][0] <= (a["_t"] - rep).total_seconds() / 60 <= TEMPLATE_WINDOWS[act_template(a)][1]]
                acts = {a["event_type"] for a in rws}
                if acts == {"DELETE_RECORD"}:
                    cat = "SUPPORT_ATTACHMENT"
                    tr["notes"].append(f"{rid}: category from worker action DELETE_RECORD")
                elif acts == {"REDACT_RECORD"}:
                    cat = "SUPPORT_MESSAGE"
        # (state, file) pairs; omission observations are added here (HOOK)
        pairs = [(u.ts, unit_state(u), u.file_id) for u in obs]
        if hk.omission and hk.omission_units:
            has_replica = any("replica" in (u.table or "") or "replica" in u.kind for u in obs)
            if not (hk.omission_replica_aware and has_replica):
                for ts, fid, cap in hk.omission_units.get(rid, []):
                    if ts <= audit and cap <= audit:
                        pairs.append((ts, "ABSENT", fid))
        if pairs:
            if hk.omission == "severe":
                states = {s for _, s, _ in pairs}
                viol = [s for s in states if s in VIOLATING.get(cat, {})]
                if viol:
                    state = viol[0]
                else:
                    latest_ts = max(t for t, _, _ in pairs)
                    st2 = {s for t, s, _ in pairs if t == latest_ts}
                    state = sorted(st2)[0]
            else:
                latest_ts = max(t for t, _, _ in pairs)
                last = [p for p in pairs if p[0] == latest_ts] if opts.state_rule == "latest" else pairs
                states = {s for _, s, _ in last}
                viol = [s for s in states if s in VIOLATING.get(cat, {})]
                state = viol[0] if viol else sorted(states)[0]
        else:
            state = "ABSENT" if cat == "USER_PROFILE" else None
            if state:
                tr["notes"].append(f"{rid}: no observation at/before audit -> default ABSENT")
        tr["state"][rid] = (cat, state)
        if state is None:
            tr["notes"].append(f"{rid}: no state")
            continue
        out_sys = "account_service" if sysid == "profile_service" else sysid
        if state in VIOLATING.get(cat, {}):
            fop, rop, vop = VIOLATING[cat][state]
            vfiles = sorted({u.file_id for u in obs if u.file_id and unit_state(u) == state
                             and W.manifest[u.file_id]["captured_at"] <= audit},
                            key=lambda f: W.manifest[f]["captured_at"])
            ev = F if F in vfiles else (vfiles[-1] if vfiles else F)
            findings.append((out_sys, rid, fop, rop, vop, ev))
        else:
            vop = COMPLIANT_VERIFY.get(cat)
            if vop:
                verifs.append((out_sys, rid, vop))

    status = "INCOMPLETE" if findings else "COMPLETE"
    steps = []
    for out_sys, rid, fop, rop, vop, ev in findings:
        steps.append(("FINDING", out_sys, rid, fop, ev or ""))
        steps.append(("REMEDIATION", out_sys, rid, rop, ""))
        steps.append(("VERIFICATION", out_sys, rid, vop, ""))
    for out_sys, rid, vop in verifs:
        ev = F or ""
        if (cid, rid) in hk.empty_cite:
            ev = ""
        steps.append(("VERIFICATION", out_sys, rid, vop, ev if status == "COMPLETE" else ""))

    steps.sort(key=lambda s: (PHASES.index(s[0]), OP_ORDER[s[0]].index(s[3]), s[1], s[2]))
    out = [{"step_no": i + 1, "phase": p, "system_id": s, "resource_id": r, "operation": o,
            "state": STATE_OF[o], "evidence_id": e} for i, (p, s, r, o, e) in enumerate(steps)]
    return CaseResult(cid, status, out, tr)


def check_harness(W: World, cases: list[dict]) -> dict:
    """solve2 with no hooks must equal solver.solve on every case (status and steps)."""
    diff = []
    for q in cases:
        a, b = solver.solve(q, W, Opts()), solve2(q, W, Opts(), Hooks())
        if (a.status, a.steps) != (b.status, b.steps):
            diff.append(q["case_id"])
    assert not diff, diff[:5]
    return dict(cases=len(cases), differing=0)


# ----------------------------------------------------------------------------- row diffs
FIELDS = ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def row_diff(a: CaseResult, b: CaseResult) -> list[str]:
    """Human-readable before -> after differences between two predicted rows."""
    out = []
    if a.status != b.status:
        out.append(f"status {a.status} -> {b.status}")
    ta = [tuple(s[k] for k in FIELDS[1:]) for s in a.steps]
    tb = [tuple(s[k] for k in FIELDS[1:]) for s in b.steps]
    for s in sorted(set(ta) - set(tb)):
        out.append("step removed: " + " ".join(x or '""' for x in s))
    for s in sorted(set(tb) - set(ta)):
        out.append("step added: " + " ".join(x or '""' for x in s))
    if not out and ta != tb:
        out.append("order changed")
    return out
