#!/bin/zsh

# launch_musubi.sh — macOS + iTerm2 convenience launcher.
#
# This script is one of two launchers. Pick the one that fits your environment:
#
#   * launch_musubi.sh        — macOS + iTerm2 (this file). Spawns one iTerm
#                               window for the tmux attach. Adds nothing over
#                               launch_musubi_tmux.sh except the iTerm window.
#   * launch_musubi_tmux.sh   — cross-platform (Linux / WSL / macOS without
#                               iTerm2). Runs the orchestrator in the current
#                               terminal; you attach tmux yourself in another
#                               terminal. This is the first-class supported
#                               path on Linux/WSL.
#
# Both behave identically once the orchestrator is up — same gates, same
# auto-spawn Oya, same logs. iTerm2 is a convenience layer on macOS; not
# required on any platform.
#
# Usage:
#   ./launch_musubi.sh                          # uses musubi.toml
#   ./launch_musubi.sh /path/to/musubi.toml
#   ./launch_musubi.sh /path/to/musubi.toml session_name
#   ./launch_musubi.sh --pane-tint              # tint each pane bg for contrast
#
# Flow:
#   1. Set up venv + install deps (idempotent).
#   2. Open ONE iTerm window that will `tmux attach -t <session>` once the
#      orchestrator has created the session.
#   3. Run the orchestrator IN THE CURRENT TERMINAL (foreground). Its
#      [HH:MM:SS] [COMPONENT] log stream stays visible here — gates, Oya
#      spawn, relay test, watcher, all in one place.
#
# Oya enablement is driven by [agents.oyakata].enabled in your musubi.toml.
# The orchestrator handles Oya spawning automatically when that's true — no
# separate flag or launcher needed.
#
# The Oya layer is cross-platform as of 2026-05-28: scripts/attach-oya.sh
# probes for pbcopy / wl-copy / xclip / xsel / clip.exe in preference order
# and soft-fails (warns + continues) when no clipboard tool is available.
# The tmux paste-buffer is the primary auto-paste mechanism; the system
# clipboard is a fallback for manual paste in the rare case the tmux path
# fails. Linux/WSL Oya works without any clipboard tool, just with the
# manual-paste fallback unavailable.

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
      sed -n '3,22p' "$0"
      exit 0 ;;
    -*)
      echo "launch_musubi: unknown flag: $arg" >&2
      echo "Run with --help for usage." >&2
      exit 2 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

# --- Config ---
ORCHESTRATOR_DIR="$(cd "$(dirname "$0")" && pwd)"  # always relative to script location
VENV_PATH="$ORCHESTRATOR_DIR/.venv"
REQUIREMENTS="$ORCHESTRATOR_DIR/requirements.txt"
# Read positionals via `set --` so indexing is identical under zsh and bash.
# This file's shebang is zsh, whose arrays are 1-based — an earlier 0-based
# `${POSITIONAL[0]}` silently broke it: [0] was empty (so CONFIG fell back to
# the default musubi.toml, loading the WRONG project) and [1] held the config
# path (so it landed in SESSION and tmux rejected the periods). Positional
# parameters $1/$2 after `set --` are 1-based and identical across both shells.
set -- "${POSITIONAL[@]}"
CONFIG="${1:-}"
# When no config is named and several musubi*.toml exist, ask which session to
# start (rather than silently defaulting to musubi.toml and maybe launching the
# wrong project). pick-config.sh prompts only on multiple-and-no-arg; with one
# config (or an explicit arg) it returns silently — backward compatible.
if [ -z "$CONFIG" ]; then
  CONFIG=$("$ORCHESTRATOR_DIR/scripts/pick-config.sh" "" "$ORCHESTRATOR_DIR")
fi
# Session name precedence MUST mirror the orchestrator's
# (session_override or cfg["tmux"]["session_name"]), because the iTerm window
# below attaches to $SESSION while the orchestrator names the session from the
# config. If they disagree you get NO tmux window: the orchestrator builds
# (say) 'unhinged' from the toml, but the attach targets the default 'musubi'
# which never exists. So: explicit 2nd arg wins; else read [tmux].session_name
# from the config; else fall back to 'musubi'. (Field bug 2026-06-08: a
# multi-instance operator launched a custom-session toml without the 2nd arg
# and got a running orchestrator with no visible window.)
SESSION="${2:-}"
if [ -z "$SESSION" ]; then
  SESSION=$(awk -F'"' '/^[[:space:]]*session_name[[:space:]]*=/{print $2; exit}' "$CONFIG" 2>/dev/null || true)
  [ -n "$SESSION" ] || SESSION="musubi"
fi

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

# --- Environment check ---
echo "Checking environment..."

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install it from https://python.org and try again."
    exit 1
fi

if ! command -v tmux &>/dev/null; then
    echo "Error: tmux not found. Install it with: brew install tmux"
    exit 1
fi

if [[ ! -d "$VENV_PATH" ]]; then
    echo "No venv found — creating one..."
    python3 -m venv "$VENV_PATH"
fi

echo "Installing dependencies..."
"$VENV_PATH/bin/pip" install --quiet --upgrade pip
if ! "$VENV_PATH/bin/pip" install --quiet -r "$REQUIREMENTS"; then
    echo "Error: failed to install dependencies from $REQUIREMENTS"
    exit 1
fi

echo "Environment ready."

# --- Spawn ONE iTerm window for the tmux attach (visual pane interaction).
# The orchestrator runs in THIS terminal so you see its log stream live and
# can hit Enter at any gate to skip the wait.
osascript <<EOF
tell application "iTerm2"
    activate
    create window with default profile
    tell current session of current window
        write text "sleep 4 && tmux attach -t ${SESSION}"
    end tell
end tell
EOF

echo ""
echo "iTerm window opened (will tmux attach in 4s)."
echo "Orchestrator starting in THIS terminal — watch the [HH:MM:SS] [COMPONENT] stream."
echo "Ctrl+C here to stop the watcher; iTerm window stays for inspection."
echo ""

# --- Run orchestrator in foreground here, so its output is visible. ---
# Build argv to match the orchestrator's CLI shape: config first, optional
# session name second.
ARGS=("$CONFIG")
[ "$SESSION" != "musubi" ] && ARGS+=("$SESSION")

exec "$VENV_PATH/bin/python3" "$ORCHESTRATOR_DIR/orchestrator.py" "${ARGS[@]}"
