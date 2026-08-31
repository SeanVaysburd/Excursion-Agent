#!/usr/bin/env bash
# Pre-push secrets audit: scans EVERY blob in EVERY commit, not just the
# worktree (a key committed and later removed would pass a worktree grep).
#
# Two passes:
#   1. value scan  -- the actual secret values loaded from .env, read into
#      shell variables and never echoed or put on a command line
#   2. pattern scan -- value-independent shapes (sk-ant-*, oauth tokens)
#
# Exit 0 = clean. Any hit prints the offending commit:path and exits 1.

set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

# ---- pass 1: loaded values (never echoed) ---------------------------------
if [[ -f .env ]]; then
  while IFS='=' read -r name value; do
    [[ "$name" =~ (_API_KEY|_TOKEN|_SECRET)$ ]] || continue
    [[ ${#value} -ge 8 ]] || continue
    # grep every blob in history for the value; -F fixed string, quiet
    if hits=$(git grep -I -F --name-only "$value" $(git rev-list --all) -- 2>/dev/null | head -3); then
      if [[ -n "$hits" ]]; then
        echo "SECRET VALUE FOUND IN HISTORY (${name}):"
        echo "$hits"
        fail=1
      fi
    fi
  done < <(grep -E '^[A-Z_]+=' .env)
fi

# ---- pass 2: shape patterns across all history ----------------------------
for pattern in 'sk-ant-[A-Za-z0-9_-]{16,}' 'sk-ant-oat[A-Za-z0-9_-]{8,}'; do
  if hits=$(git grep -I -E --name-only "$pattern" $(git rev-list --all) -- 2>/dev/null | head -3); then
    if [[ -n "$hits" ]]; then
      echo "SECRET-SHAPED STRING IN HISTORY (pattern ${pattern}):"
      echo "$hits"
      fail=1
    fi
  fi
done

# ---- worktree hygiene ------------------------------------------------------
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo ".env is TRACKED -- must never be"; fail=1
fi
git check-ignore -q .env || { echo ".env is not gitignored"; fail=1; }

if [[ $fail -eq 0 ]]; then
  echo "secrets scan: CLEAN (all commits, values + patterns, worktree hygiene)"
fi
exit $fail
