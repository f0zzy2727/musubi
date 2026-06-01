#!/usr/bin/env bash
# launch_musubi_tmux.sh — first-class cross-platform launcher (Linux, WSL,
# macOS without iTerm2). This is the primary supported path on non-macOS
# environments.
#
# This launcher sets up the venv, installs deps, and runs the orchestrator
# in the current terminal. No iTerm-specific code, no osascript, no
# clipboard dependency. When the orchestrator prints
#
#   Attach in another terminal with: tmux attach -t <session_name>
#
# open a second terminal and run that command yourself.
#
# Oya (the optional third agent) is cross-platform as of 2026-05-28:
# scripts/attach-oya.sh probes for pbcopy / wl-copy / xclip / xsel /
# clip.exe and soft-fails if none are present. The tmux paste-buffer
# is the primary auto-paste path and works without any clipboard tool.
# Linux operators may want to `apt install xclip` (or wl-copy on Wayland)
# for the manual-paste fallback, but it's not required for Oya to launch.
#
# Usage:
#   ./launch_musubi_tmux.sh                          # uses musubi.toml
#   ./launch_musubi_tmux.sh /path/to/musubi.toml     # custom config
#   ./launch_musubi_tmux.sh /path/to/musubi.toml session_name
#   ./launch_musubi_tmux.sh --pane-tint              # tint each pane bg for contrast
#
# Oya (the optional third agent) is driven by [agents.oyakata].enabled = true
# in your musubi.toml — the orchestrator auto-spawns the Oya pane via
# scripts/attach-oya.sh once the pair CLIs are up. No flags needed here.

set -euo pipefail

# --- Parse flags ---
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --with-oya)
      echo "Note: --with-oya is deprecated. Oya is driven by [agents.oyakata].enabled in musubi.toml."
      ;;
    --pane-tint)
      # Give each pane a slightly different dark-grey background so the
      # column/row boundaries read at a glance. Opt-in; honoured by the
      # orchestrator (Opus + Coda) and attach-oya.sh (Oya).
      export MUSUBI_PANE_TINT=1
      ;;
    --help|-h)
      sed -n '3,18p' "$0"
      exit 0 ;;
    -*)
      echo "launch_musubi_tmux: unknown flag: $arg" >&2
      echo "Run with --help for usage." >&2
      exit 2 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

ORCHESTRATOR_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PATH="$ORCHESTRATOR_DIR/.venv"
REQUIREMENTS="$ORCHESTRATOR_DIR/requirements.txt"
CONFIG="${POSITIONAL[0]:-musubi.toml}"
SESSION="${POSITIONAL[1]:-}"

# --- cwd defence (orch-6) ---
# Catch stale-handle / iCloud-sync failure mode BEFORE we spawn any Node-based
# agent CLI, which would otherwise crash with EPERM uv_cwd and a Node stack
# trace that's unactionable for a non-engineer operator.
# shellcheck source=scripts/cwd-preflight.sh
. "$ORCHESTRATOR_DIR/scripts/cwd-preflight.sh"
preflight_cwd || exit 1
# Re-anchor cwd to the orchestrator dir so the orchestrator process and any
# downstream agent spawns inherit a known-good cwd, not whatever stale handle
# the parent shell may have been carrying.
cd "$ORCHESTRATOR_DIR" || {
    echo "ERROR: cannot cd to orchestrator dir $ORCHESTRATOR_DIR — folder moved or unmounted?" >&2
    exit 1
}
# Warn (don't block) if the operator's invocation dir is iCloud-synced.
# The project path itself (read later from $CONFIG) gets the same check
# inside orchestrator.py before agents are spawned.
warn_icloud_path "$ORCHESTRATOR_DIR"

echo "Checking environment..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Install Python 3.11+ and try again." >&2
    exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux not found." >&2
    echo "  macOS:   brew install tmux" >&2
    echo "  Debian:  sudo apt install tmux" >&2
    echo "  Fedora:  sudo dnf install tmux" >&2
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "No venv found — creating one..."
    python3 -m venv "$VENV_PATH"
fi

echo "Installing dependencies..."
"$VENV_PATH/bin/pip" install --quiet --upgrade pip
if ! "$VENV_PATH/bin/pip" install --quiet -r "$REQUIREMENTS"; then
    echo "Error: failed to install dependencies from $REQUIREMENTS" >&2
    exit 1
fi

echo "Environment ready."
echo ""
echo "Starting the orchestrator in this terminal."
echo "When it prints 'Attach in another terminal with: tmux attach -t ...',"
echo "open a second terminal and run that command before pressing Enter here."
echo ""

# Build argv: pass SESSION only if set, so argparse's nargs="?" sees the right shape.
ARGS=("$CONFIG")
[ -n "$SESSION" ] && ARGS+=("$SESSION")

# exec replaces this shell so signals (Ctrl+C) route straight to the orchestrator.
# Oya spawning (if enabled in musubi.toml) is handled by the orchestrator
# itself via scripts/attach-oya.sh — see start_musubi / spawn_oya_if_enabled
# in orchestrator.py.
exec "$VENV_PATH/bin/python3" "$ORCHESTRATOR_DIR/orchestrator.py" "${ARGS[@]}"
