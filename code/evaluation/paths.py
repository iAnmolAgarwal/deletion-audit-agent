"""Repository paths, derived from this file's location (code/evaluation/paths.py)."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DATASET: Path = REPO_ROOT / "dataset"
SPLIT_JSON: Path = REPO_ROOT / "notes" / "split.json"
RUNS: Path = REPO_ROOT / "runs"

SAMPLE_OUTPUT: Path = DATASET / "sample_output.csv"            # gold: read only through gold.py
SAMPLE_REQUESTS: Path = DATASET / "sample_deletion_requests.csv"
TEST_REQUESTS: Path = DATASET / "deletion_requests.csv"
EVIDENCE_MANIFEST: Path = DATASET / "evidence_files.csv"
SYSTEM_ACTIVITY: Path = DATASET / "system_activity.csv"
USER_AUDIT_LOG: Path = DATASET / "user_audit_log.csv"

HOLDOUT_ACCESS_LOG: Path = RUNS / "HOLDOUT_ACCESS.log"
NUMBERS_MD: Path = Path(__file__).resolve().parent / "NUMBERS.md"
