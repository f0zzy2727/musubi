#!/usr/bin/env sh
#
# pick-config.sh — choose which musubi config (and therefore which session) to
# start, when more than one exists. POSIX sh so both launchers (zsh + bash) and
# the operator scripts can share ONE implementation.
#
# Prints the chosen config path to STDOUT (and nothing else, so it's safe in
# `CONFIG=$(pick-config.sh)`); all prompts go to STDERR.
#
# Rules:
#   - explicit config given as $1  -> echo it, no prompt
#   - exactly one musubi*.toml     -> echo it, no prompt
#   - several, and stdin is a tty  -> numbered prompt, echo the choice
#   - several, no tty (scripted)   -> echo musubi.toml if present, else the
#                                     first candidate (never hang a headless run)
#   - none                         -> echo musubi.toml (the launcher reports the
#                                     missing-file error with its usual message)
#
# Usage:
#   pick-config.sh [explicit-config] [search-dir]
#     explicit-config : if non-empty, returned as-is
#     search-dir      : where to look for musubi*.toml (default: cwd)
#
set -eu

EXPLICIT="${1:-}"
DIR="${2:-.}"

if [ -n "$EXPLICIT" ]; then
  printf '%s\n' "$EXPLICIT"
  exit 0
fi

# Gather candidates: musubi*.toml, excluding the shipped *.example template.
# Build a newline-separated list (POSIX-portable; no arrays).
candidates=""
count=0
for f in "$DIR"/musubi*.toml; do
  [ -f "$f" ] || continue
  case "$f" in
    *.example) continue ;;
  esac
  candidates="${candidates}${f}
"
  count=$((count + 1))
done

if [ "$count" -eq 0 ]; then
  printf '%s\n' "$DIR/musubi.toml"
  exit 0
fi

if [ "$count" -eq 1 ]; then
  printf '%s\n' "$candidates" | sed '/^$/d'
  exit 0
fi

# Several candidates. Without a tty we can't prompt — pick a stable default and
# warn, rather than hang a scripted/headless run.
if [ ! -t 0 ]; then
  if [ -f "$DIR/musubi.toml" ]; then
    printf 'pick-config: multiple configs, no tty — defaulting to musubi.toml\n' >&2
    printf '%s\n' "$DIR/musubi.toml"
  else
    printf 'pick-config: multiple configs, no tty — defaulting to first candidate\n' >&2
    printf '%s\n' "$candidates" | sed '/^$/d' | head -1
  fi
  exit 0
fi

# Interactive: list each config with its session name + project path so the
# choice is "which session", not "which filename".
printf '\nMultiple musubi configs found — which session do you want to start?\n\n' >&2
i=0
printf '%s' "$candidates" | sed '/^$/d' | while IFS= read -r f; do
  i=$((i + 1))
  sn=$(awk -F'"' '/^[[:space:]]*session_name[[:space:]]*=/{print $2; exit}' "$f" 2>/dev/null || true)
  [ -n "$sn" ] || sn="musubi"
  pp=$(awk -F'"' '/^[[:space:]]*path[[:space:]]*=/{print $2; exit}' "$f" 2>/dev/null || true)
  printf '  %d) %-28s  session: %-12s  %s\n' "$i" "$(basename "$f")" "$sn" "${pp:-?}" >&2
done
printf '\n  choice [1-%d]: ' "$count" >&2

read -r choice || { printf 'pick-config: no choice read\n' >&2; exit 1; }
case "$choice" in
  ''|*[!0-9]*) printf 'pick-config: not a number: %s\n' "$choice" >&2; exit 1 ;;
esac
if [ "$choice" -lt 1 ] || [ "$choice" -gt "$count" ]; then
  printf 'pick-config: out of range: %s\n' "$choice" >&2
  exit 1
fi

printf '%s\n' "$candidates" | sed '/^$/d' | sed -n "${choice}p"
