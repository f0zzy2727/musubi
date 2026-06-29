#!/usr/bin/env bash
# launch_setup_fix.sh — one-command launcher for the musubi setup repair.
#
# Opens an interactive agent session in your musubi folder and tells it to run
# the /musubi-setup-fix routine: audit every musubi*.toml, apply the mechanical
# fixes, then interview you to fill in real vision/architecture/shared rules and
# wire each app's context_docs — with your approval before any write.
#
# Usage (from anywhere):
#   bash scripts/launch_setup_fix.sh                   # all apps, 'claude'
#   bash scripts/launch_setup_fix.sh codex             # all apps, 'codex'
#   bash scripts/launch_setup_fix.sh -c musubi.toml    # ONE app only
#   bash scripts/launch_setup_fix.sh -c musubi.toml codex
#
# Notes:
#   - Run with your musubi tmux sessions DOWN — this edits docs/configs those
#     sessions read.
#   - It is interactive on purpose (it asks you questions and waits for
#     approval); do not run it headless.

set -u

CLI="claude"; SCOPE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -c) shift; SCOPE="$1" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) CLI="$1" ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MUSUBI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL="templates/claude-commands/musubi-setup-fix.md"

if ! command -v "$CLI" >/dev/null 2>&1; then
  echo "ERROR: '$CLI' not found on PATH. Install it, or pass the other CLI:" >&2
  echo "  bash scripts/launch_setup_fix.sh claude   |   bash scripts/launch_setup_fix.sh codex" >&2
  exit 1
fi
if [ -n "$SCOPE" ] && [ ! -f "$MUSUBI_ROOT/$SCOPE" ]; then
  echo "ERROR: -c config not found: $SCOPE (path is relative to the musubi folder)" >&2
  exit 1
fi
if [ ! -f "$MUSUBI_ROOT/$SKILL" ]; then
  echo "ERROR: skill file missing: $SKILL (run 'git pull' in the musubi folder)" >&2
  exit 1
fi

cd "$MUSUBI_ROOT" || exit 1

# Confirm sessions-down, since this mutates files the live sessions read.
if [ -n "$SCOPE" ]; then
  printf 'This repairs musubi setup for ONLY: %s (and edits its docs/configs).\n' "$SCOPE"
else
  printf 'This repairs musubi setup across ALL apps and edits docs/configs.\n'
fi
printf 'Make sure the affected musubi tmux session(s) are DOWN. Continue? [y/N] '
read -r ans </dev/tty 2>/dev/null || ans=""
case "$ans" in y|Y|yes) ;; *) echo "aborted."; exit 0 ;; esac

if [ -n "$SCOPE" ]; then
  SCOPE_LINE="Work ONLY on the config $SCOPE — do NOT read, audit, or modify any \
other musubi*.toml or its project. When the routine calls setup-fix.sh OR \
doctor.sh, pass -c $SCOPE (doctor defaults to musubi.toml otherwise — the wrong app)."
else
  SCOPE_LINE="Work across every musubi*.toml in this folder."
fi

PROMPT="You are running the musubi setup repair from $MUSUBI_ROOT. \
Read the file $SKILL in full, then execute it now, beginning with the audit \
(Step 1). Follow its iron rules: never invent-and-commit intent, back up before \
every overwrite, and show me each draft and config edit for approval before \
writing. $SCOPE_LINE"

# Interactive session seeded with the prompt (NOT headless -p).
exec "$CLI" "$PROMPT"
