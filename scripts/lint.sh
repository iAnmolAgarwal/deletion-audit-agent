#!/usr/bin/env bash
# Lint the repo's Python code: ruff, then mypy, over code/ (or the paths given).
# Usage: scripts/lint.sh [path ...]     e.g. scripts/lint.sh code/deletion_audit/model
# Exits non-zero when either tool reports a problem; both always run.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin"
if [ "$#" -eq 0 ]; then set -- "$ROOT/code"; fi
cd "$ROOT" || exit 2
status=0
echo "== ruff check $*"
"$PY/ruff" check --config "$ROOT/ruff.toml" "$@" || status=1
echo "== mypy $*"
"$PY/mypy" --config-file "$ROOT/mypy.ini" "$@" || status=1
exit "$status"
