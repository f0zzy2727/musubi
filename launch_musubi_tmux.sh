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

# --- Native Windows guard (Git Bash / MSYS / Cygwin) ---
# Musubi's runtime is tmux + libtmux, which don't run on native Windows. WSL
# reports as 'Linux' (uname) and works unchanged; this only trips Git Bash /
# MSYS / Cygwin shells, where a launch would fail deep in the relay.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "musubi: native Windows is not supported (the runtime is tmux + libtmux)." >&2
    echo "        Run musubi under WSL2 instead: install WSL, clone the repo inside" >&2
    echo "        your Linux home, and launch from the WSL shell. See the README." >&2
    exit 2
    ;;
esac

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
CONFIG="${POSITIONAL[0]:-}"
# When no config is named and several musubi*.toml exist, ask which session to
# start instead of silently defaulting. Prompts only on multiple-and-no-arg;
# one config (or an explicit arg) returns silently — backward compatible.
if [ -z "$CONFIG" ]; then
  CONFIG=$("$ORCHESTRATOR_DIR/scripts/pick-config.sh" "" "$ORCHESTRATOR_DIR")
fi
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

# --- Environment / key defence (keys-1) ---
# Load the project's .env (if present) so the orchestrator and every spawned
# pane inherit the API keys — the panes get only the environment we hand them,
# and a key missing here is why Codex reports it is "sandboxed". Then warn,
# operator-readably, if a coder CLI needs a key that still isn't set.
# shellcheck source=scripts/env-preflight.sh
. "$ORCHESTRATOR_DIR/scripts/env-preflight.sh"
PROJECT_PATH=$(awk -F'"' '/^[[:space:]]*path[[:space:]]*=/{print $2; exit}' "$CONFIG" 2>/dev/null || true)
load_project_env "$PROJECT_PATH" "$ORCHESTRATOR_DIR" || true
warn_missing_keys "$CONFIG"

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
