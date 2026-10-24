"""Run directory artifacts: ``runs/<run_id>/`` config with hashes, flips, README.

Every number the evaluation reports comes from a file written here, so it carries a run ID,
the command that produced it, the code hash and the input hashes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from .gold import GoldCase
from .paths import REPO_ROOT, RUNS

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FLIP_METRICS: tuple[str, ...] = ("status_ok", "row_exact", "order_exact", "citation_set_exact")


def now_ist() -> str:
    """Current time, ISO-8601 in IST."""
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(obj: Any) -> str:
    """sha256 of the canonical JSON form (sorted keys, compact)."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode())


def code_hash(package_dir: Path | None = None) -> str:
    """sha256 over the evaluation package's own .py files (tests excluded), by name order."""
    pkg = package_dir or Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(pkg.glob("*.py")):
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def gold_hash(gold: Mapping[str, GoldCase]) -> str:
    """Hash of the loaded (DEV) gold only. The raw file is never hashed: it holds holdout bytes."""
    return canonical_hash({cid: [g.status, g.steps] for cid, g in sorted(gold.items())})


def git_head() -> str | None:
    """The repo's HEAD commit, read-only; None if git is unavailable."""
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_dir(run_id: str) -> Path:
    """``runs/<run_id>/``, created if needed. Run IDs are plain names, never paths."""
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise ValueError(f"bad run id {run_id!r}")
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8")


def flips(prev_cases: Iterable[Mapping[str, Any]], cur_cases: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per-case changes of the boolean case metrics between two scored runs."""
    prev = {c["case_id"]: c for c in prev_cases}
    out = []
    for c in cur_cases:
        p = prev.get(c["case_id"])
        if p is None:
            out.append({"case_id": c["case_id"], "metric": "<new case>", "prev": None, "now": None})
            continue
        for m in FLIP_METRICS:
            if bool(p.get(m)) != bool(c.get(m)):
                out.append({"case_id": c["case_id"], "metric": m, "prev": bool(p.get(m)), "now": bool(c.get(m))})
    return out


def load_score(run_id: str) -> dict[str, Any]:
    """Read ``runs/<run_id>/score.json``."""
    return json.loads((RUNS / run_id / "score.json").read_text(encoding="utf-8"))
