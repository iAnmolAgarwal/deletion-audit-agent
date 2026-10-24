#!/usr/bin/env bash
# Secret and forbidden-path scan of the staged diff (developer decision D19).
#
# Runs from .git/hooks/pre-commit on every commit, and can be run by hand.
# It prints labels, file names and counts only, never the matched text, so a
# real key is never echoed. Exit status 1 on any hit blocks the commit.
#
# Checks, on lines added by the staged diff:
#   1. "sk-ant-" followed by 20+ key characters;
#   2. ANTHROPIC_API_KEY= followed by a value: a dotenv/shell assignment at line
#      start with any non-empty value, or a key-like token of 8+ characters
#      anywhere (so prose that quotes the pattern name does not trip it);
#   3. private-key headers;
#   4. the exact key value from .env (compared, never printed).
# And on the staged file list: forbidden paths and files over 5 MB.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

KEY_TOKEN='sk-ant-[A-Za-z0-9_-]{20,}'
ENV_ASSIGN="(^[[:space:]]*(export[[:space:]]+)?ANTHROPIC_API_KEY=[^[:space:]#])|(ANTHROPIC_API_KEY=[\"']?[A-Za-z0-9_-]{8,})"
PRIVATE_KEY='-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----'
FORBIDDEN='^runs/|(^|/)(\.?cache|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)/|\.py[cod]$|agent-trace|^\.claude/settings\.local\.json$|^\.claude/\.log_guard_|(^|/)\.env$|(^|/)\.env\.'
MAX_BYTES=5242880

fail=0
report() { printf '  %-34s %s\n' "$1" "$2"; }

files=()  # bash 3.2 (macOS) has no mapfile
while IFS= read -r line; do files+=("$line"); done < <(git diff --cached --name-only --diff-filter=ACMR)
echo "secret-scan: ${#files[@]} staged file(s)"

added_lines() { # staged added lines of one file, without the leading "+"
  git diff --cached -U0 --no-color -- "$1" | awk '/^\+/ && !/^\+\+\+ /{print substr($0, 2)}'
}

scan() { # label, extended regex
  local label="$1" pattern="$2" hits="" f n
  for f in ${files[@]+"${files[@]}"}; do
    n=$(added_lines "$f" | grep -cE -e "$pattern" || true)
    [ "$n" -gt 0 ] && hits+="$f ($n line(s)) "
  done
  if [ -n "$hits" ]; then report "$label" "HIT in $hits"; fail=1; else report "$label" "clean"; fi
}

scan "sk-ant- key token (20+ chars)" "$KEY_TOKEN"
scan "ANTHROPIC_API_KEY= with a value" "$ENV_ASSIGN"
scan "private-key header" "$PRIVATE_KEY"

keyval=""
if [ -f .env ]; then
  keyval="$(sed -n 's/^[[:space:]]*\(export[[:space:]]*\)\{0,1\}ANTHROPIC_API_KEY=//p' .env | head -n 1 | tr -d "\"' ")"
fi
if [ -z "$keyval" ]; then
  report "exact .env key value" "skipped (no value in .env)"
elif git diff --cached --no-color | grep -qF -- "$keyval"; then
  report "exact .env key value" "HIT (value not shown)"; fail=1
else
  report "exact .env key value" "clean"
fi
unset keyval

bad=""
for f in ${files[@]+"${files[@]}"}; do
  [ "$f" = ".env.example" ] && continue
  printf '%s\n' "$f" | grep -qE -e "$FORBIDDEN" && bad+="$f "
done
if [ -n "$bad" ]; then report "forbidden paths" "HIT: $bad"; fail=1; else report "forbidden paths" "clean"; fi

big=""
for f in ${files[@]+"${files[@]}"}; do
  size=$(git cat-file -s ":$f")
  [ "$size" -gt "$MAX_BYTES" ] && big+="$f ($size bytes) "
done
if [ -n "$big" ]; then report "files over 5 MB" "HIT: $big"; fail=1; else report "files over 5 MB" "clean"; fi

if [ "$fail" -ne 0 ]; then echo "secret-scan: FAIL (commit blocked)"; exit 1; fi
echo "secret-scan: PASS"
