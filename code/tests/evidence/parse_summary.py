"""Run parse_all over dataset/ and write runs/gp-<HHMM>/parse_summary.json.

Run from the repo root: ``python3 code/tests/evidence/parse_summary.py``. HHMM is the
current Asia/Kolkata wall-clock time. The summary holds counts, statuses and reasons only,
no record content.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from deletion_audit.evidence import EvidenceIndex, parse_all  # noqa: E402
from deletion_audit.evidence.interpret import system_from_prefix  # noqa: E402

DATASET = REPO_ROOT / "dataset"


def summarize(index: EvidenceIndex) -> dict[str, Any]:
    """Per-family counts, every non-OK file, and cross-checks on the observations."""
    families: dict[str, dict[str, Any]] = defaultdict(lambda: {"files": 0, "file_ids": [], "observations": 0,
                                                     "scopes": 0, "failures": 0, "statuses": Counter()})
    for fp in index.files.values():
        row = families[fp.family or "(none)"]
        row["files"] += 1
        row["file_ids"].append(fp.file_id)
        row["observations"] += len(fp.observations)
        row["scopes"] += len(fp.scopes)
        row["failures"] += 0 if fp.ok else 1
        row["statuses"][fp.status] += 1
    observations = index.observations()
    prefix_disagreements = sum(1 for o in observations
                               if system_from_prefix(o.resource_id)
                               and system_from_prefix(o.resource_id) != o.system_id)
    return {
        "dataset": str(DATASET.relative_to(REPO_ROOT)),
        "files": len(index.files),
        "observations": len(observations),
        "scopes": len(index.scopes()),
        "status_counts": dict(Counter(fp.status for fp in index.files.values())),
        "families": {name: {**row, "statuses": dict(row["statuses"])}
                     for name, row in sorted(families.items())},
        "not_ok": [{"file_id": fp.file_id, "path": fp.path, "family": fp.family,
                    "status": fp.status, "detail": fp.detail} for fp in index.failures()],
        "checks": {
            "observations_without_resource_id": sum(1 for o in observations if o.resource_id is None),
            "observations_without_system_id": sum(1 for o in observations if o.system_id is None),
            "system_id_disagrees_with_resource_prefix": prefix_disagreements,
            "observations_with_scope": sum(1 for o in observations if o.scope is not None),
            "system_ids": dict(Counter(str(o.system_id) for o in observations)),
        },
    }


def main() -> int:
    """Write the summary and print where it went."""
    now = dt.datetime.now(ZoneInfo("Asia/Kolkata"))
    out_dir = REPO_ROOT / "runs" / f"gp-{now:%H%M}"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"generated_at": now.isoformat(timespec="seconds"), **summarize(parse_all(DATASET))}
    path = out_dir / "parse_summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
