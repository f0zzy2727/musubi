#!/usr/bin/env bash
# classify-slice.sh — mechanical slice-lane classifier (protocol-1 Tier 1).
#
# Reads the staged file set + LOC and emits one of three protocol lanes:
#
#   tiny        docs / comments / README / dependency bumps only, ≤20 LOC,
#               ≤2 files, no state file / schema / UI / CI. One-line claim +
#               diff; no review, no completion message, no capsule update.
#   lightweight bigger doc/dep changes, or a single small (≤20 LOC) code
#               change. Optional review; no GO baton; no Findings block.
#   heavy       anything touching a state file, CI/workflow, schema migration,
#               or user-visible UI; OR a multi-file / >20 LOC code change; OR
#               >300 LOC. Full protocol. Default lane when in doubt.
#
# Lane selection is MECHANICAL, not judgement — that is the binding constraint
# from IA-QUEUE protocol-1. The classification is meant to be pasted verbatim
# into the slice acceptance receipt. @LEAD can promote a lane (e.g. tiny ->
# heavy); agents must not silently demote.
#
# Usage:
#   scripts/classify-slice.sh                      # classify the staged set
#   scripts/classify-slice.sh --files a.md b.ts    # classify an explicit set
#   scripts/classify-slice.sh --loc 12 --files a.md
#   scripts/classify-slice.sh --format json
#
# Exit codes:
#   0  classification printed
#   2  invalid arguments
#
# No config file by design: the trigger patterns live here so the lane logic
# is auditable in one place and identical across every project that vendors
# musubi. Mirrors the conventions of classify-slice-disciplines.py (the v0.3
# discipline scope sensor) — same input shape, machine-readable JSON output.

set -euo pipefail

FORMAT="text"
FILES=()
LOC=""
FILES_EXPLICIT=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --files)
      shift
      FILES_EXPLICIT=true
      while [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; do
        FILES+=("$1")
        shift
      done
      ;;
    --loc)
      LOC="${2:-}"
      shift 2
      ;;
    --format)
      FORMAT="${2:-text}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "classify-slice: unknown argument '$1'" >&2
      echo "usage: $0 [--files <f>...] [--loc <n>] [--format text|json]" >&2
      exit 2
      ;;
  esac
done

# Default to the staged set when no explicit --files were given.
if [ "$FILES_EXPLICIT" = false ]; then
  while IFS= read -r path; do
    [ -n "$path" ] && FILES+=("$path")
  done < <(git diff --cached --name-only 2>/dev/null || true)
fi

# Default LOC from the staged numstat (added + deleted) when not supplied.
if [ -z "$LOC" ]; then
  if [ "$FILES_EXPLICIT" = false ]; then
    LOC="$(git diff --cached --numstat 2>/dev/null \
      | awk '{ a += ($1 == "-" ? 0 : $1); d += ($2 == "-" ? 0 : $2) } END { print a + d + 0 }')"
  else
    LOC=0
  fi
fi
LOC="${LOC:-0}"

FILE_COUNT="${#FILES[@]}"

# --- pattern classifiers (case-insensitive via lowercased copy) -----------

# State files the protocol tracks — editing these is never tiny/light.
is_state_file() {
  case "$1" in
    *current-state.md|*agent-todo.md|*agent-handoff.md|*active.txt|*rules-ledger.yml) return 0 ;;
  esac
  return 1
}

is_ci_file() {
  case "$1" in
    .github/workflows/*|*/.github/workflows/*|*.gitlab-ci.yml|*/ci/*.yml|*/ci/*.yaml) return 0 ;;
  esac
  return 1
}

is_schema_file() {
  case "$1" in
    *migrations/*|*/migrate/*|*.sql|*prisma/schema*|*alembic/versions/*|*/schema/*) return 0 ;;
  esac
  return 1
}

is_ui_file() {
  case "$1" in
    *.tsx|*.jsx|*.vue|*.svelte) return 0 ;;
  esac
  return 1
}

# Docs + dependency manifests — eligible for the tiny lane.
is_doc_or_dep() {
  case "$1" in
    *.md|*.markdown|*.txt|*.rst|*README*|*LICENSE*|*CHANGELOG*) return 0 ;;
    *.lock|*/package.json|package.json|*go.mod|*go.sum|*Cargo.toml|*Gemfile|*.gitignore) return 0 ;;
  esac
  return 1
}

# --- lane decision --------------------------------------------------------

REASONS=()
HEAVY=false
has_code=false
all_doc_or_dep=true

for f in "${FILES[@]:-}"; do
  [ -z "$f" ] && continue
  # State files are also *.md, so check them BEFORE is_doc_or_dep.
  if is_state_file "$f"; then
    HEAVY=true; REASONS+=("state file: $f"); all_doc_or_dep=false; continue
  fi
  if is_ci_file "$f"; then
    HEAVY=true; REASONS+=("CI/workflow file: $f"); all_doc_or_dep=false; continue
  fi
  if is_schema_file "$f"; then
    HEAVY=true; REASONS+=("schema/migration: $f"); all_doc_or_dep=false; continue
  fi
  if is_ui_file "$f"; then
    HEAVY=true; REASONS+=("user-visible UI: $f"); all_doc_or_dep=false; continue
  fi
  if ! is_doc_or_dep "$f"; then
    has_code=true
    all_doc_or_dep=false
  fi
done

if [ "$LOC" -gt 300 ]; then
  HEAVY=true; REASONS+=("diff size: ${LOC} LOC (> 300)")
fi

# A code change is only lightweight if it's a single file and ≤20 LOC; anything
# larger or multi-file is heavy (matches the runbook's lightweight criteria).
if [ "$has_code" = true ]; then
  if [ "$FILE_COUNT" -gt 1 ] || [ "$LOC" -gt 20 ]; then
    HEAVY=true; REASONS+=("code change: ${FILE_COUNT} file(s), ${LOC} LOC (lightweight allows single-file ≤20 LOC)")
  fi
fi

if [ "$FILE_COUNT" -eq 0 ]; then
  LANE="lightweight"
  REASONS+=("no files staged/provided — defaulting to lightweight; classify again once staged")
elif [ "$HEAVY" = true ]; then
  LANE="heavy"
elif [ "$all_doc_or_dep" = true ] && [ "$LOC" -le 20 ] && [ "$FILE_COUNT" -le 2 ]; then
  LANE="tiny"
  REASONS+=("docs/deps only, ${LOC} LOC, ${FILE_COUNT} file(s)")
else
  LANE="lightweight"
  if [ "$all_doc_or_dep" = true ]; then
    REASONS+=("docs/deps only but exceeds tiny thresholds (${LOC} LOC, ${FILE_COUNT} files)")
  else
    REASONS+=("single small code change (${FILE_COUNT} file, ${LOC} LOC)")
  fi
fi

# --- output ---------------------------------------------------------------

if [ "$FORMAT" = "json" ]; then
  printf '{\n'
  printf '  "lane": "%s",\n' "$LANE"
  printf '  "loc": %s,\n' "$LOC"
  printf '  "file_count": %s,\n' "$FILE_COUNT"
  printf '  "reasons": ['
  first=true
  for r in "${REASONS[@]:-}"; do
    [ -z "$r" ] && continue
    if [ "$first" = true ]; then first=false; else printf ', '; fi
    printf '"%s"' "$(printf '%s' "$r" | sed 's/"/\\"/g')"
  done
  printf ']\n'
  printf '}\n'
else
  echo "=== Slice lane classification ==="
  echo "Lane: ${LANE}"
  echo "Files: ${FILE_COUNT} | LOC: ${LOC}"
  echo "Why:"
  for r in "${REASONS[@]:-}"; do
    [ -z "$r" ] && continue
    echo "  - $r"
  done
  echo ""
  echo "Paste 'Lane: ${LANE}' into the slice acceptance receipt."
  echo "(@LEAD may promote the lane; agents must not silently demote.)"
fi
