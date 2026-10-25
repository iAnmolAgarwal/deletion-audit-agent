"""``usage_report.md``: what the final output's model replies cost, and what the final run sent.

Everything is computed from artifacts, never typed:

* the run's call log ``runs/<run>/calls.jsonl`` (GM's ``JsonlCallLog``: one line per cache read,
  send attempt and reply check, each with its ``key``, ``event``, ``outcome``, ``from_cache``,
  flattened ``usage``, settled ``cost_usd`` and ``run_id``);
* the reply cache ``cache/replies/<key[:2]>/<key>.json``: each entry stores the model, the
  ORIGINAL ``usage`` of the reply and ``bought_by_run``;
* the project ledger ``cache/ledger.jsonl`` (one line per settled send: ``key``, ``cost_usd``);
* the buying runs' own call logs, for the cost each reply was settled at;
* the price table ``deletion_audit.model.prices.PRICES`` (the budget guard's own), for the
  price basis and an independent re-pricing of every reply's stored usage.

**(a) Replies the output used.** Every call of the run that delivered a reply (a ``cache_hit``
or a ``send`` with outcome ``ok``) is followed to its cache entry. Distinct replies are summed by
the run that bought them, cache hits bought by earlier runs included: tokens from the entry's
original usage; cost as settled in the buying run's call log, re-priced from the usage, and
summed from the ledger lines for that key. Any disagreement is listed as a cross-check failure.

**(b) The run's own calls.** Send attempts against cache hits, failures by event, error class
and HTTP status, and their cost; per-request averages; per-model totals.

**Totals and averages.** Total tokens = input + output + cache read + cache write tokens (thinking
tokens are part of output tokens, so they are not added again). "Per request" is per reply in
part (a) (each reply cost one model request in the run that bought it) and per successful send in
part (b). Per-model rows and an overall row are given in both parts.

**The organiser's field list** (``notes/ORGANISER_README.md`` line 97, read as data, T111/T113):
:data:`ORGANISER_FIELDS`, each rendered as one row of the "Required fields" table with its value
and the section that holds it. ``code/evaluation/tests/test_improvements.py`` checks every row is
present and filled in a generated report.

**Cross-checks** (each reported, never raised): (1) per reply, settled vs re-priced vs ledger;
(2) the run's send cost vs the ledger lines for the keys it sent; (3) the whole ledger vs every
send in every ``runs/*/*calls*.jsonl``; (4) the run's ``usage.json``, when present, vs the call
log. A line naming another run, or a malformed line, is listed and left out of every sum.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEY_RE: re.Pattern[str] = re.compile(r"[0-9a-f]{64}", re.ASCII)
EVENTS: tuple[str, ...] = ("cache_hit", "replay_miss", "send", "reply_check", "budget", "error")
OUTCOMES: tuple[str, ...] = ("ok", "retry", "repair", "give_up", "failed")
TOKEN_FIELDS: tuple[str, ...] = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                 "cache_creation_input_tokens", "output_tokens_details.thinking_tokens")
PER_MILLION = 1_000_000
COST_TOLERANCE = 1e-9
CALL_LOG_GLOB = "*calls*.jsonl"
PROVIDER = "Anthropic (Messages API)"
TOTAL_PARTS: tuple[str, ...] = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                "cache_creation_input_tokens")
ORGANISER_SOURCE = "notes/ORGANISER_README.md:97"
ORGANISER_FIELDS: tuple[str, ...] = (
    "Final full-dataset run", "Model providers and names", "Model calls", "Input and output tokens",
    "Total and average tokens per request", "Estimated total and per-request cost", "Per-model and overall totals")


@dataclass(frozen=True)
class Call:
    """One call-log line, type-checked."""

    line_no: int
    run_id: str
    key: str
    event: str
    outcome: str
    from_cache: bool
    error_class: str | None
    status: int | None
    usage: Mapping[str, int]
    cost_usd: float


@dataclass(frozen=True)
class Price:
    """USD per million tokens (a copy of one ``ModelPrice``)."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


def price_table() -> tuple[dict[str, Price], str]:
    """The budget guard's price table and its stated source (first docstring paragraph)."""
    from deletion_audit.model import prices as prices_mod

    table = {m: Price(p.input, p.output, p.cache_write_5m, p.cache_write_1h, p.cache_read)
             for m, p in prices_mod.PRICES.items()}
    source = " ".join((prices_mod.__doc__ or "").strip().split("\n\n")[1:2]).replace("\n", " ").strip()
    return table, source


def _finite(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def flatten_usage(usage: Any, prefix: str = "") -> dict[str, int]:
    """Nested usage objects joined by ``.``; integer counts only (labels such as tiers are dropped)."""
    out: dict[str, int] = {}
    if not isinstance(usage, Mapping):
        return out
    for k, v in usage.items():
        name = f"{prefix}{k}"
        if isinstance(v, Mapping):
            out.update(flatten_usage(v, name + "."))
        elif isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[name] = v
    return out


def reprice(model: str, usage: Mapping[str, int], table: Mapping[str, Price]) -> float | None:
    """USD for ``usage`` at ``model``'s prices (the budget guard's formula); None for an unpriced model.

    Cache writes use the 5-minute and 1-hour breakdown when present; otherwise every cache-write
    token is priced at the 1-hour rate.
    """
    p = table.get(model)
    if p is None:
        return None
    five = usage.get("cache_creation.ephemeral_5m_input_tokens")
    hour = usage.get("cache_creation.ephemeral_1h_input_tokens")
    if five is None and hour is None:
        writes = usage.get("cache_creation_input_tokens", 0) * p.cache_write_1h
    else:
        writes = (five or 0) * p.cache_write_5m + (hour or 0) * p.cache_write_1h
    total = (usage.get("input_tokens", 0) * p.input + writes + usage.get("cache_read_input_tokens", 0) * p.cache_read
             + usage.get("output_tokens", 0) * p.output)
    return total / PER_MILLION


def read_calls(path: Path) -> tuple[list[Call], list[str]]:
    """Every well-formed line of a call log, and a problem per malformed one."""
    calls: list[Call] = []
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [f"{path.name}: missing"]
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"{path.name}: unreadable ({type(exc).__name__})"]
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"{path.name} line {n}: not JSON")
            continue
        if not isinstance(raw, Mapping):
            problems.append(f"{path.name} line {n}: not an object")
            continue
        bad = [k for k, ok in (
            ("run_id", isinstance(raw.get("run_id"), str)),
            ("key", isinstance(raw.get("key"), str) and KEY_RE.fullmatch(raw["key"]) is not None),
            ("event", raw.get("event") in EVENTS), ("outcome", raw.get("outcome") in OUTCOMES),
            ("from_cache", isinstance(raw.get("from_cache"), bool)), ("cost_usd", _finite(raw.get("cost_usd"))),
            ("usage", isinstance(raw.get("usage", {}), Mapping))) if not ok]
        if bad:
            problems.append(f"{path.name} line {n}: bad field(s) {bad}")
            continue
        status = raw.get("status")
        calls.append(Call(n, raw["run_id"], raw["key"], raw["event"], raw["outcome"], raw["from_cache"],
                          raw.get("error_class") if isinstance(raw.get("error_class"), str) else None,
                          status if isinstance(status, int) and not isinstance(status, bool) else None,
                          flatten_usage(raw.get("usage", {})), float(raw["cost_usd"])))
    return calls, problems


def read_ledger(path: Path) -> tuple[list[tuple[str, float]], list[str]]:
    """``(key, cost_usd)`` per ledger line, and a problem per malformed one."""
    out: list[tuple[str, float]] = []
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [f"{path.name}: missing"]
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"ledger line {n}: not JSON")
            continue
        if not isinstance(raw, Mapping) or not isinstance(raw.get("key"), str) or not _finite(raw.get("cost_usd")):
            problems.append(f"ledger line {n}: needs a key and a finite cost_usd >= 0")
            continue
        out.append((raw["key"], float(raw["cost_usd"])))
    return out, problems


def read_entry(cache_root: Path, key: str) -> tuple[dict[str, Any] | None, str | None]:
    """A reply cache entry's model, original usage and buying run; or (None, why)."""
    path = cache_root / key[:2] / f"{key}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "no reply cache entry"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"cache entry unreadable ({type(exc).__name__})"
    if not isinstance(raw, Mapping) or raw.get("key") != key:
        return None, "cache entry does not name its own key"
    model, buyer = raw.get("model"), raw.get("bought_by_run")
    if not isinstance(model, str) or not isinstance(buyer, str) or not isinstance(raw.get("usage"), Mapping):
        return None, "cache entry lacks model, usage or bought_by_run"
    return {"model": model, "bought_by_run": buyer, "usage": flatten_usage(raw["usage"]),
            "written_at": raw.get("written_at")}, None


def _tokens(usages: Iterable[Mapping[str, int]]) -> dict[str, int]:
    tot: Counter[str] = Counter()
    for u in usages:
        for f in TOKEN_FIELDS:
            tot[f] += int(u.get(f, 0))
    return {**{f: tot[f] for f in TOKEN_FIELDS}, "total_tokens": sum(tot[f] for f in TOTAL_PARTS)}


def _per(t: Mapping[str, Any], cost: float | None, n: int) -> dict[str, Any] | None:
    """Per-request averages over ``n`` requests (None when there is none)."""
    if not n:
        return None
    return {"requests": n, "input_tokens": t["input_tokens"] / n, "output_tokens": t["output_tokens"] / n,
            "total_tokens": t["total_tokens"] / n, "cost_usd": None if cost is None else cost / n}


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= COST_TOLERANCE


def _buying_cost(runs_root: Path, buyer: str, key: str) -> tuple[float | None, str | None]:
    """The settled cost of the send that bought ``key``, from the buying run's own call logs."""
    d = runs_root / buyer
    if not d.is_dir():
        return None, f"buying run {buyer} has no folder under runs/"
    hits = []
    for p in sorted(d.glob(CALL_LOG_GLOB)):
        calls, _ = read_calls(p)
        hits += [c for c in calls if c.key == key and c.event == "send" and c.outcome == "ok" and not c.from_cache
                 and c.run_id == buyer]
    if len(hits) != 1:
        return None, f"buying run {buyer}'s call logs hold {len(hits)} successful sends of this key (expected 1)"
    return hits[0].cost_usd, None


def attribute(calls: Sequence[Call], *, runs_root: Path, cache_root: Path, ledger: Sequence[tuple[str, float]],
              table: Mapping[str, Price]) -> dict[str, Any]:
    """Part (a): every distinct reply the run used, followed to the run that bought it."""
    used: dict[str, int] = {}
    for c in calls:
        if c.outcome == "ok" and c.event in ("cache_hit", "send"):
            used[c.key] = used.get(c.key, 0) + 1
    ledger_by_key: dict[str, float] = {}
    for k, cost in ledger:
        ledger_by_key[k] = ledger_by_key.get(k, 0.0) + cost
    replies: list[dict[str, Any]] = []
    problems: list[str] = []
    for key, uses in used.items():
        entry, why = read_entry(cache_root, key)
        if entry is None:
            problems.append(f"{key[:12]}: {why}")
            replies.append({"key": key, "uses": uses, "error": why})
            continue
        settled, why_cost = _buying_cost(runs_root, entry["bought_by_run"], key)
        repriced = reprice(entry["model"], entry["usage"], table)
        led = ledger_by_key.get(key)
        checks = {"settled_vs_repriced": _close(settled, repriced), "settled_vs_ledger": _close(settled, led)}
        if why_cost:
            problems.append(f"{key[:12]}: {why_cost}")
        for name, ok in checks.items():
            if not ok:
                problems.append(f"{key[:12]} (bought by {entry['bought_by_run']}): {name} disagree "
                                f"(settled {settled}, repriced {repriced}, ledger {led})")
        replies.append({"key": key, "uses": uses, "model": entry["model"], "bought_by_run": entry["bought_by_run"],
                        "tokens": _tokens([entry["usage"]]), "cost_settled_usd": settled,
                        "cost_repriced_usd": repriced, "cost_ledger_usd": led, "checks": checks})
    ok_replies = [r for r in replies if "error" not in r]

    def group(field_name: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in sorted({r[field_name] for r in ok_replies}):
            rs = [r for r in ok_replies if r[field_name] == name]
            out[name] = {"replies": len(rs), "uses": sum(r["uses"] for r in rs), **_tokens(r["tokens"] for r in rs),
                         "cost_settled_usd": _sum(r["cost_settled_usd"] for r in rs),
                         "cost_repriced_usd": _sum(r["cost_repriced_usd"] for r in rs)}
        return out
    total = {"replies": len(ok_replies), **_tokens(r["tokens"] for r in ok_replies),
             "cost_settled_usd": _sum(r["cost_settled_usd"] for r in ok_replies),
             "cost_repriced_usd": _sum(r["cost_repriced_usd"] for r in ok_replies)}
    return {"replies_used": len(used), "uses": sum(used.values()), "replies_unresolved": len(replies) - len(ok_replies),
            "by_buying_run": group("bought_by_run"), "by_model": group("model"), "total": total,
            "per_reply": _per(total, total["cost_settled_usd"], len(ok_replies)),
            "replies": replies, "problems": problems}


def _sum(values: Iterable[float | None]) -> float | None:
    """A sum that is None when any part is unknown (never a partial sum shown as whole)."""
    vals = list(values)
    return None if any(v is None for v in vals) else round(sum(v for v in vals if v is not None), 9)


def own_calls(calls: Sequence[Call], *, cache_root: Path, run_id: str) -> dict[str, Any]:
    """Part (b): what the run itself sent, read and failed, with cost, averages and per-model totals."""
    sends = [c for c in calls if c.event == "send"]
    ok_sends = [c for c in sends if c.outcome == "ok"]
    failures: Counter[str] = Counter()
    failure_cost: dict[str, float] = {}
    for c in calls:
        if c.outcome != "ok" or c.event in ("replay_miss", "budget", "error"):
            label = f"{c.event}:{c.outcome}:{c.error_class or '-'}:{c.status if c.status is not None else '-'}"
            failures[label] += 1
            failure_cost[label] = round(failure_cost.get(label, 0.0) + c.cost_usd, 9)
    per_model: dict[str, dict[str, Any]] = {}
    for c in ok_sends:
        entry, _ = read_entry(cache_root, c.key)
        model = entry["model"] if entry is not None and entry["bought_by_run"] == run_id else "unknown (no entry)"
        slot = per_model.setdefault(model, {"sends_ok": 0, "cost_usd": 0.0, "usages": []})
        slot["sends_ok"] += 1
        slot["cost_usd"] = round(slot["cost_usd"] + c.cost_usd, 9)
        slot["usages"].append(c.usage)
    cost = round(sum(c.cost_usd for c in sends), 9)
    tok = _tokens(c.usage for c in sends)
    n_ok = len(ok_sends)
    return {
        "events": dict(sorted(Counter(f"{c.event}:{c.outcome}" for c in calls).items())),
        "send_attempts": len(sends), "sends_ok": n_ok, "cache_hits": sum(1 for c in calls if c.event == "cache_hit"),
        "failures": {k: {"count": n, "cost_usd": failure_cost[k]} for k, n in sorted(failures.items())},
        "cost_usd": cost, "tokens": tok,
        "per_request": _per(tok, cost, n_ok),
        "per_model": {m: {"sends_ok": v["sends_ok"], "cost_usd": v["cost_usd"], **_tokens(v["usages"])}
                      for m, v in sorted(per_model.items())},
    }


def project_ledger_check(runs_root: Path, ledger: Sequence[tuple[str, float]]) -> dict[str, Any]:
    """Cross-check (3): the whole ledger against every send line in every run's call logs."""
    total_sends = 0.0
    files = 0
    for p in sorted(runs_root.glob(f"*/{CALL_LOG_GLOB}")):
        calls, _ = read_calls(p)
        files += 1
        total_sends += sum(c.cost_usd for c in calls if c.event == "send")
    led = round(sum(c for _, c in ledger), 9)
    return {"ledger_total_usd": led, "call_log_send_total_usd": round(total_sends, 9), "call_logs_read": files,
            "ledger_lines": len(ledger), "agree": _close(led, round(total_sends, 9))}


def usage_json_check(usage: Mapping[str, Any] | None, own: Mapping[str, Any],
                     attributed: Mapping[str, Any]) -> dict[str, Any]:
    """Cross-check (4): the run's ``usage.json`` (when present) against the call-log figures."""
    if usage is None:
        return {"present": False, "mismatches": []}
    expect: dict[str, Any] = {"model_calls": own["send_attempts"], "input_tokens": own["tokens"]["input_tokens"],
                              "output_tokens": own["tokens"]["output_tokens"], "cost_usd": own["cost_usd"]}
    ru = usage.get("replies_used")
    if isinstance(ru, Mapping):
        expect["replies_used.count"] = attributed["total"]["replies"]
        expect["replies_used.cost_usd"] = attributed["total"]["cost_repriced_usd"]
    got = {**{k: usage.get(k) for k in ("model_calls", "input_tokens", "output_tokens", "cost_usd")},
           **({"replies_used.count": ru.get("count"), "replies_used.cost_usd": ru.get("cost_usd")}
              if isinstance(ru, Mapping) else {})}
    mism = []
    for k, v in expect.items():
        g = got.get(k)
        same = abs(float(g) - float(v)) <= 1e-6 if isinstance(g, int | float) and _finite(g) and _finite(v) \
            else g == v
        if not same:
            mism.append({"field": k, "usage_json": g, "call_log": v})
    return {"present": True, "mismatches": mism}


def build_usage(run_id: str, *, runs_root: Path, cache_root: Path, calls_file: str = "calls.jsonl",
                usage: Mapping[str, Any] | None = None, final: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The usage report's data for one run (module docstring).

    ``final`` describes the spec's final run for the organiser's "final full-dataset run" field:
    ``{"run_id", "rows", "test_requests"}`` (rows written by the final run, requests in the test file).
    """
    table, price_source = price_table()
    calls_all, problems = read_calls(runs_root / run_id / calls_file)
    other = [c for c in calls_all if c.run_id != run_id]
    problems += [f"{calls_file} line {c.line_no}: names run {c.run_id}, not {run_id}; left out" for c in other]
    calls = [c for c in calls_all if c.run_id == run_id]
    ledger, lproblems = read_ledger(cache_root / "ledger.jsonl")
    attributed = attribute(calls, runs_root=runs_root, cache_root=cache_root / "replies", ledger=ledger, table=table)
    own = own_calls(calls, cache_root=cache_root / "replies", run_id=run_id)
    sent_keys = sorted({c.key for c in calls if c.event == "send"})
    led_sent = round(sum(cost for k, cost in ledger if k in set(sent_keys)), 9)
    return {
        "run_id": run_id, "calls_file": f"runs/{run_id}/{calls_file}",
        "provider": PROVIDER, "final": dict(final) if final is not None else None,
        "price_basis": {"source": price_source, "module": "code/deletion_audit/model/prices.py",
                        "usd_per_million": {m: vars(p) for m, p in sorted(table.items())}},
        "call_log_problems": problems, "ledger_problems": lproblems,
        "a_replies_used": attributed, "b_own_calls": own,
        "cross_checks": {
            "replies": attributed["problems"],
            "run_sends_vs_ledger": {"run_send_cost_usd": own["cost_usd"], "ledger_cost_for_sent_keys_usd": led_sent,
                                    "keys": len(sent_keys), "agree": _close(own["cost_usd"], led_sent)},
            "project_ledger": project_ledger_check(runs_root, ledger),
            "usage_json": usage_json_check(usage, own, attributed),
        },
    }


def failures_found(u: Mapping[str, Any]) -> list[str]:
    """Every cross-check failure and read problem, one line each (empty when all agree)."""
    cc = u["cross_checks"]
    out = [*u["call_log_problems"], *u["ledger_problems"], *cc["replies"]]
    if not cc["run_sends_vs_ledger"]["agree"]:
        r = cc["run_sends_vs_ledger"]
        out.append(f"run send cost {r['run_send_cost_usd']} differs from the ledger lines for its sent keys "
                   f"{r['ledger_cost_for_sent_keys_usd']}")
    if not cc["project_ledger"]["agree"]:
        p = cc["project_ledger"]
        out.append(f"ledger total {p['ledger_total_usd']} differs from every run's send total "
                   f"{p['call_log_send_total_usd']}")
    out += [f"usage.json {m['field']} = {m['usage_json']}, call log gives {m['call_log']}"
            for m in cc["usage_json"]["mismatches"]]
    return out


# ---- Markdown ----
def _usd(v: Any) -> str:
    return "unknown" if v is None else f"${v:.6f}"


TOKEN_COLS: tuple[str, ...] = (*TOKEN_FIELDS, "total_tokens")


def _tok_cells(t: Mapping[str, int]) -> str:
    return " | ".join(str(t[f]) for f in TOKEN_COLS)


def _avg(per: Mapping[str, Any] | None, what: str) -> str:
    if per is None:
        return f"no {what}, so no average"
    return (f"{per['input_tokens']:.1f} input, {per['output_tokens']:.1f} output, {per['total_tokens']:.1f} total "
            f"tokens and {_usd(per['cost_usd'])} per {what} (over {per['requests']})")


def models_named(u: Mapping[str, Any]) -> list[str]:
    """Every model named in part (a) or part (b)."""
    return sorted(set(u["a_replies_used"]["by_model"]) | set(u["b_own_calls"]["per_model"]))


def organiser_rows(u: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """One (field, value, section) row per :data:`ORGANISER_FIELDS` entry, values from the report data."""
    rid, a, b = u["run_id"], u["a_replies_used"], u["b_own_calls"]
    fin = u.get("final")
    if fin is None:
        final_s = f"run `{rid}`; **the spec named no final run for this usage report**"
    else:
        full = fin["rows"] == fin["test_requests"]
        final_s = (f"run `{rid}`" + ("" if fin["run_id"] == rid else f" (**not** the final run `{fin['run_id']}`)")
                   + f"; the final run wrote {fin['rows']} rows for {fin['test_requests']} test requests "
                   + ("(the full dataset)" if full else "(**not the full dataset**)"))
    t, bt = a["total"], b["tokens"]
    models = models_named(u)
    return [
        (ORGANISER_FIELDS[0], final_s, "this table; report title"),
        (ORGANISER_FIELDS[1], f"{u['provider']}: {', '.join(models) or 'no model reply used or sent by this run'}",
         "Providers and models"),
        (ORGANISER_FIELDS[2], f"(a) {t['replies']} model requests bought the {t['replies']} replies the output used; "
                              f"(b) the run made {b['send_attempts']} send attempts ({b['sends_ok']} returned a reply) "
                              f"and {b['cache_hits']} cache reads", "(a), (b)"),
        (ORGANISER_FIELDS[3], f"(a) {t['input_tokens']} input, {t['output_tokens']} output; (b) {bt['input_tokens']} "
                              f"input, {bt['output_tokens']} output", "(a), (b)"),
        (ORGANISER_FIELDS[4], f"(a) total {t['total_tokens']}; {_avg(a['per_reply'], 'reply')}. (b) total "
                              f"{bt['total_tokens']}; {_avg(b['per_request'], 'successful send')}", "(a), (b)"),
        (ORGANISER_FIELDS[5], f"(a) {_usd(t['cost_settled_usd'])} settled ({_usd(t['cost_repriced_usd'])} re-priced), "
                              "per reply " + (_usd(a['per_reply']['cost_usd']) if a['per_reply'] else 'n/a (no reply)')
                              + f"; (b) {_usd(b['cost_usd'])}, per successful send "
                              + (_usd(b['per_request']['cost_usd']) if b['per_request'] else 'n/a (no successful send)')
                              + ". Estimated from the price table below", "(a), (b), Price basis"),
        (ORGANISER_FIELDS[6], f"{len(a['by_model'])} model(s) in (a), {len(b['per_model'])} in (b); each part has "
                              "a per-model table and an overall total row", "(a), (b)"),
    ]


def render_usage(u: Mapping[str, Any], *, report_id: str, created_at: str, command: str,
                 headline: Sequence[str] = ()) -> str:
    """The Markdown report, rendered from :func:`build_usage`'s dict only (``headline``: generated lines)."""
    rid = u["run_id"]
    a, b, cc = u["a_replies_used"], u["b_own_calls"], u["cross_checks"]
    tok_head = " | ".join(TOKEN_COLS)
    ncol = len(TOKEN_COLS)
    lines = [f"# Usage report `{report_id}`", "", *headline,
             f"Generated {created_at} by `{command}` from `{u['calls_file']}`, the reply cache entries it names, "
             "the buying runs' call logs and `cache/ledger.jsonl` (code/evaluation/usage_report.py). "
             "Every figure names its run. Nothing is typed by hand. Total tokens = input + output + cache read + "
             "cache write tokens.", ""]
    lines += [f"## Required fields ({ORGANISER_SOURCE}, read as data)", "",
              "| field | value | section |", "|---|---|---|"]
    lines += [f"| {f} | {v.replace('|', '/')} | {sec} |" for f, v, sec in organiser_rows(u)]
    lines += ["", "## Providers and models", "", f"- Provider: {u['provider']}.",
              f"- Models of the replies used (run `{rid}`): {', '.join(a['by_model']) or 'none'}.",
              f"- Models of the run's own successful sends: {', '.join(b['per_model']) or 'none'}.", "",
              "## (a) Tokens and cost originally spent on the replies this run used", "",
              f"Run `{rid}` used {a['replies_used']} distinct replies in {a['uses']} uses (cache hits and successful "
              f"sends); {a['replies_unresolved']} could not be followed to a cache entry. Each reply is summed once, "
              "under the run that bought it; tokens are the cache entry's original usage.", "",
              f"| bought by run | replies | uses | {tok_head} | cost settled | cost re-priced |",
              "|---|---:|---:|" + "---:|" * ncol + "---:|---:|"]
    for run, g in a["by_buying_run"].items():
        lines.append(f"| `{run}` | {g['replies']} | {g['uses']} | {_tok_cells(g)} | {_usd(g['cost_settled_usd'])} "
                     f"| {_usd(g['cost_repriced_usd'])} |")
    t = a["total"]
    lines += [f"| **total** | {t['replies']} | {a['uses']} | {_tok_cells(t)} | {_usd(t['cost_settled_usd'])} | "
              f"{_usd(t['cost_repriced_usd'])} |", "",
              f"- Model requests behind these replies: {t['replies']} (one per reply).",
              f"- Per request (per reply): {_avg(a['per_reply'], 'reply')}.", "", "Per model:", "",
              f"| model | replies | uses | {tok_head} | cost settled |",
              "|---|---:|---:|" + "---:|" * ncol + "---:|"]
    lines += [f"| {m} | {g['replies']} | {g['uses']} | {_tok_cells(g)} | {_usd(g['cost_settled_usd'])} |"
              for m, g in a["by_model"].items()]
    lines += [f"| **overall** | {t['replies']} | {a['uses']} | {_tok_cells(t)} | {_usd(t['cost_settled_usd'])} |"]
    lines += ["", f"## (b) Calls made by run `{rid}` itself", "",
              f"- Model calls (send attempts): {b['send_attempts']} ({b['sends_ok']} returned a reply); cache hits: "
              f"{b['cache_hits']}. Cost of the sends: {_usd(b['cost_usd'])}.",
              f"- Events (event:outcome): {b['events'] or '{}'}.",
              f"- Per request (per successful send): {_avg(b['per_request'], 'successful send')}.",
              "", f"| send tokens | {tok_head} |", "|---|" + "---:|" * ncol,
              f"| all send attempts | {_tok_cells(b['tokens'])} |", "",
              "Failures (event:outcome:error class:HTTP status):", ""]
    lines += [f"- `{k}`: {v['count']}, cost {_usd(v['cost_usd'])}" for k, v in b["failures"].items()] or ["- none"]
    lines += ["", "Per model (successful sends):", "", f"| model | sends ok | cost | {tok_head} |",
              "|---|---:|---:|" + "---:|" * ncol]
    lines += [f"| {m} | {v['sends_ok']} | {_usd(v['cost_usd'])} | {_tok_cells(v)} |" for m, v in b["per_model"].items()]
    lines += [f"| **overall (all send attempts)** | {b['sends_ok']} | {_usd(b['cost_usd'])} | "
              f"{_tok_cells(b['tokens'])} |"]
    pb = u["price_basis"]
    lines += ["", "## Price basis", "", f"USD per million tokens, from `{pb['module']}` (the budget guard's table). "
              f"Its stated source: {pb['source']}", "",
              "| model | input | output | cache write 5m | cache write 1h | cache read |",
              "|---|---:|---:|---:|---:|---:|"]
    lines += [f"| {m} | {p['input']} | {p['output']} | {p['cache_write_5m']} | {p['cache_write_1h']} | "
              f"{p['cache_read']} |" for m, p in pb["usd_per_million"].items()]
    rs, pl, uj = cc["run_sends_vs_ledger"], cc["project_ledger"], cc["usage_json"]
    fails = failures_found(u)
    n_reply_problems = len(cc["replies"])
    lines += ["", "## Cross-checks", "",
              "- Per reply, settled cost vs re-priced usage vs ledger: "
              + ("all agree" if not n_reply_problems else f"**{n_reply_problems} problem(s)**") + ".",
              f"- Run `{rid}` send cost {_usd(rs['run_send_cost_usd'])} vs the ledger lines for its {rs['keys']} sent "
              f"key(s) {_usd(rs['ledger_cost_for_sent_keys_usd'])}: {'agree' if rs['agree'] else '**DISAGREE**'}.",
              f"- Whole ledger ({pl['ledger_lines']} lines) {_usd(pl['ledger_total_usd'])} vs every send in "
              f"{pl['call_logs_read']} call log(s) under runs/ {_usd(pl['call_log_send_total_usd'])}: "
              f"{'agree' if pl['agree'] else '**DISAGREE**'}.",
              f"- `usage.json` of `{rid}`: " + ("absent" if not uj["present"] else
                                               "agrees with the call log" if not uj["mismatches"] else
                                               f"**{len(uj['mismatches'])} mismatch(es)**") + ".", ""]
    if fails:
        lines += ["**Cross-check failures and read problems:**", ""] + [f"- {f}" for f in fails] + [""]
    return "\n".join(lines) + "\n"
