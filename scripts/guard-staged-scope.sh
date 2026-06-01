#!/usr/bin/env bash
# guard-staged-scope.sh — pre-commit guard for slice-scope discipline.
#
# Fails if:
#   - no files are staged
#   - any file is staged that is not under one of the declared allowed paths
#   - any allowed path has nothing staged under it (the slice claimed to touch a path but didn't)
#
# Usage:
#   scripts/guard-staged-scope.sh <allowed-path> [<allowed-path>...]
#
# Example:
#   scripts/guard-staged-scope.sh src/components/Widget.tsx src/api/widget.ts tests/widget.test.ts
#
# This is a mechanical gate. Run it before every `git commit` for any slice
# whose file surface was peer-reviewed and approved. The allowlist must match
# the file list in the implementation plan / launch matrix.
#
# The script intentionally has no config file: the allowlist comes from the
# command line so it is visible in shell history, in CI logs, and in any
# wrapper hook that calls it.

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "guard-staged-scope: no allowed paths provided" >&2
  echo "usage: $0 <allowed-path> [<allowed-path>...]" >&2
  exit 2
fi

# Show the operator what's about to be committed, every time. This is the
# single most useful side-effect of the guard: a forced moment of inspection.
echo "=== git diff --cached --stat ==="
git diff --cached --stat
echo "================================"

staged="$(git diff --cached --name-only)"

if [ -z "$staged" ]; then
  echo "guard-staged-scope: FAIL — nothing is staged." >&2
  exit 1
fi

# Build the allowlist as a set of prefixes (for directories) and exact paths.
# A staged path is in scope if it equals an allowed path OR begins with an
# allowed directory prefix (allowed path + '/').
allowed_paths=("$@")

is_allowed() {
  local path="$1"
  local allowed
  for allowed in "${allowed_paths[@]}"; do
    if [ "$path" = "$allowed" ]; then
      return 0
    fi
    case "$path" in
      "$allowed"/*) return 0 ;;
    esac
  done
  return 1
}

extras=()
while IFS= read -r path; do
  [ -z "$path" ] && continue
  if ! is_allowed "$path"; then
    extras+=("$path")
  fi
done <<< "$staged"

if [ "${#extras[@]}" -gt 0 ]; then
  echo "guard-staged-scope: FAIL — files staged outside declared allowlist:" >&2
  for p in "${extras[@]}"; do
    echo "  $p" >&2
  done
  echo "" >&2
  echo "Allowed paths were:" >&2
  for p in "${allowed_paths[@]}"; do
    echo "  $p" >&2
  done
  exit 1
fi

# Inverse check: each declared allowed path should have at least one matching
# staged entry. A slice that promised to touch X but didn't is suspicious —
# either the allowlist is wrong (fix it) or the slice is incomplete (don't
# commit yet).
missing=()
for allowed in "${allowed_paths[@]}"; do
  found=0
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if [ "$path" = "$allowed" ]; then
      found=1; break
    fi
    case "$path" in
      "$allowed"/*) found=1; break ;;
    esac
  done <<< "$staged"
  if [ "$found" -eq 0 ]; then
    missing+=("$allowed")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "guard-staged-scope: FAIL — declared allowed paths with nothing staged:" >&2
  for p in "${missing[@]}"; do
    echo "  $p" >&2
  done
  echo "" >&2
  echo "If a path is genuinely not part of this slice anymore, remove it from the allowlist." >&2
  echo "If the slice is incomplete, finish the missing changes before committing." >&2
  exit 1
fi

echo "guard-staged-scope: OK — staged set matches declared allowlist."
