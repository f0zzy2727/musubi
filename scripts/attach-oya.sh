#!/usr/bin/env bash
#
# attach-oya.sh — attach the Oya supervisor pane to a running musubi session.
#
# This is the pane-attach helper for the Oya v0.1 active-mode third agent.
# It assumes musubi is already running (started by launch_musubi.sh or
# launch_musubi_tmux.sh). It polls for the tmux session, adds a top pane
# running `claude --model opus`, copies the Oya prompt to the clipboard,
# and prints next-step instructions.
#
# Normal usage is via the main launcher:
#
#   ./launch_musubi.sh --with-oya            # iTerm2 launcher + Oya
#   ./launch_musubi_tmux.sh --with-oya       # tmux launcher + Oya
#
# The main launcher invokes this script after kicking off the musubi session.
# Direct invocation also works once the session is up — useful for adding Oya
# to a pair-only session mid-cycle:
#
#   ./scripts/attach-oya.sh                          # default musubi.toml
#   ./scripts/attach-oya.sh /path/to/other-musubi.toml
#
# The project the agents work on is read from [project].path in the musubi.toml.
# That same path becomes the working-directory reference for the Oya log.
#
# What it does (idempotent — safe to re-run):
#   1. Sanity-checks dependencies (tmux, claude) + musubi.toml + project path
#      (detects a clipboard tool if available — pbcopy/wl-copy/xclip/xsel/clip.exe
#      — but soft-fails when none is present; the tmux paste-buffer is the
#      primary auto-paste path and works without a clipboard tool)
#   2. Polls for the musubi tmux session (up to 60s; errors if it never comes up)
#   3. Enables pane-border-status with titles
#   4. Labels Opus + Coda panes
#   5. Writes a scoped .claude/settings.local.json that pre-approves Oya's
#      startup-tool set (no permission prompts during init)
#   6. Splits a third pane above (top, full-width, ~30% height) running `claude`
#   7. Labels the new pane as Oyakata; copies the v0.1 prompt to the clipboard
#   8. Prints next-step instructions
#
# This script does NOT launch musubi. If the session isn't up within the timeout,
# it errors out — start musubi separately (or use `launch_musubi.sh --with-oya`).
#
# See:
#   docs/operator/oyakata-prompt-v0.1.md           — Oya v0.1 active-mode prompt
#   docs/operator/internal/OYAKATA-DESIGN-DRAFT.md — design history (author notebook)

set -euo pipefail

# --- Config -------------------------------------------------------
MUSUBI_ROOT="${MUSUBI_ROOT:-$HOME/Dev/musubi.repo}"
CONFIG_TOML="${1:-$MUSUBI_ROOT/musubi.toml}"
SESSION="${MUSUBI_SESSION:-musubi}"
PROMPT_FILE="$MUSUBI_ROOT/docs/operator/oyakata-prompt-v0.1.md"
SESSION_WAIT_SECONDS=60
OYAKATA_TITLE="OYAKATA · 親方 · master craftsman"
OPUS_TITLE="OPUS · Anthropic"
CODA_TITLE="CODA · OpenAI"

# Oya pane height as a percentage of the window. She carries the most context
# (vision/architecture custodian + discipline referee), so she gets a roomier
# pane than the pair. Override with OYA_PANE_HEIGHT=NN (a bare number, no %).
OYA_PANE_HEIGHT="${OYA_PANE_HEIGHT:-38}"

# Optional per-pane background tint (opt-in, set by the launcher's --pane-tint
# flag → MUSUBI_PANE_TINT=1). When on, the orchestrator tints Opus + Coda and
# this script tints Oya, so the three panes contrast slightly. OYA_TINT_BG is
# the tmux colour for Oya's pane; tuned for dark terminals.
OYA_TINT_BG="${OYA_TINT_BG:-colour236}"

# --- Helpers ------------------------------------------------------
# Log format mirrors the orchestrator's [HH:MM:SS] [COMPONENT] message convention
# so attach + orchestrator output reads as one coherent boot stream.
die() { echo "[$(date +%H:%M:%S)] [ATTACH] ERROR: $*" >&2; exit 1; }
log() { echo "[$(date +%H:%M:%S)] [ATTACH] $*"; }

# --- Sanity checks ------------------------------------------------
command -v tmux   >/dev/null || die "tmux not installed"
command -v claude >/dev/null || die "claude CLI not on PATH (npm i -g @anthropic-ai/claude-code, or check your PATH)"
[ -f "$PROMPT_FILE" ] || die "prompt file not found: $PROMPT_FILE"
[ -f "$CONFIG_TOML" ] || die "musubi.toml not found at $CONFIG_TOML (pass an explicit path as the first arg)"

# --- Clipboard tool detection (cross-platform) --------------------
# Tries platform-appropriate tools in preference order and exports a single
# CLIPBOARD_CMD that reads stdin and copies to the system clipboard. Used
# below as a *fallback* — the primary auto-paste path is tmux load-buffer +
# paste-buffer, which works without any clipboard tool. We still try to
# populate the system clipboard so the operator can manually paste if the
# tmux path ever fails (rare; <2.0 versions or weird TUI states).
#
# Empty CLIPBOARD_CMD means "no clipboard tool available" — the script
# still runs; only the manual-paste fallback is unavailable. This unblocks
# Linux/WSL Oya (the prior pbcopy hard-fail blocked it entirely).
detect_clipboard_cmd() {
  if command -v pbcopy >/dev/null 2>&1; then
    # macOS
    echo "pbcopy"
  elif command -v wl-copy >/dev/null 2>&1; then
    # Wayland
    echo "wl-copy"
  elif command -v xclip >/dev/null 2>&1; then
    # X11
    echo "xclip -selection clipboard"
  elif command -v xsel >/dev/null 2>&1; then
    # X11 alternative
    echo "xsel --clipboard --input"
  elif command -v clip.exe >/dev/null 2>&1; then
    # WSL — Windows clipboard
    echo "clip.exe"
  else
    echo ""
  fi
}
CLIPBOARD_CMD=$(detect_clipboard_cmd)
if [ -z "$CLIPBOARD_CMD" ]; then
  log "no clipboard tool found (tried pbcopy / wl-copy / xclip / xsel / clip.exe) — auto-paste will rely on tmux paste-buffer only; manual Cmd+V fallback unavailable"
fi

# Extract project path from [project].path (for the cycle-close hint below)
TARGET=$(awk -F'"' '/^path[[:space:]]*=[[:space:]]*"/ {print $2; exit}' "$CONFIG_TOML")
[ -n "$TARGET" ] || die "could not parse [project].path from $CONFIG_TOML"
[ -d "$TARGET" ] || die "[project].path from $CONFIG_TOML is not a directory: $TARGET"
log "config: $CONFIG_TOML"
log "project: $TARGET"

# Verify [agents.oyakata].enabled = true — without this the orchestrator won't
# relay events to Oya's pane and she'll be alive but blind. The prompt's
# relay-path-vigilance rule would eventually flag this, but failing fast here
# saves the operator a debugging detour.
if ! awk '
  /^\[agents\.oyakata\]/ { in_oya=1; next }
  /^\[/ { in_oya=0 }
  in_oya && /^[[:space:]]*enabled[[:space:]]*=[[:space:]]*true/ { found=1 }
  END { exit !found }
' "$CONFIG_TOML"; then
  die "[agents.oyakata].enabled is not true in $CONFIG_TOML — the orchestrator will not relay events to Oya. Uncomment / set the block (see musubi.toml.example) and re-run."
fi
log "agents.oyakata.enabled = true (orchestrator will relay)"

# --- Step 1: wait for musubi session to be up ---------------------
# We never launch musubi from here. The main launcher is responsible for that.
# If the session never comes up within the timeout, error out with a clear hint.
if tmux has-session -t "$SESSION" 2>/dev/null; then
  log "session $SESSION already up — proceeding"
else
  log "polling for session $SESSION (up to ${SESSION_WAIT_SECONDS}s)..."
  waited=0
  while [ "$waited" -lt "$SESSION_WAIT_SECONDS" ]; do
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      pane_count=$(tmux list-panes -t "$SESSION" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
      [ "$pane_count" -ge 2 ] && break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  tmux has-session -t "$SESSION" 2>/dev/null \
    || die "session $SESSION did not come up within ${SESSION_WAIT_SECONDS}s. Start musubi first (e.g. ./launch_musubi.sh), then re-run, or use ./launch_musubi.sh --with-oya."
  log "session up after ${waited}s"
fi

# --- Step 2: enable pane-border-status (idempotent) ---------------
tmux set-option -t "$SESSION" pane-border-status top
tmux set-option -t "$SESSION" pane-border-format " #{?pane_active,#[bold],}#{pane_title} "

# --- Step 3: check if Oya pane already exists ---------------------
# Primary check: pane_current_path. Oya's pane runs in $MUSUBI_ROOT, which is
# distinct from the pair's pane cwd ($TARGET). pane_title is unreliable here
# because Claude Code's TUI overwrites the title with response headlines as
# soon as the agent starts processing — the canonical "OYAKATA ·" title
# survives only a few seconds before being replaced.
all_panes_paths=$(tmux list-panes -t "$SESSION" -F "#{pane_id} #{pane_current_path}" 2>/dev/null || true)
if echo "$all_panes_paths" | grep -qE "${MUSUBI_ROOT//\//\\/}(/| |$)"; then
  log "Oya pane already exists (matched by pane_current_path under $MUSUBI_ROOT)"
  OYAKATA_EXISTED=1
else
  # Fallback to title check (back-compat).
  all_panes_titled=$(tmux list-panes -t "$SESSION" -F "#{pane_id} #{pane_title}" 2>/dev/null || true)
  if echo "$all_panes_titled" | grep -q "OYAKATA"; then
    log "Oya pane already exists (matched by title)"
    OYAKATA_EXISTED=1
  else
    OYAKATA_EXISTED=0
  fi
fi

# --- Step 4: label existing Opus + Coda panes ---------------------
# Before any Oya split, the only panes are Opus + Coda. After the split, both keep
# their pane IDs and titles. So we label by pane ID, not by index — index can shift.
if [ "$OYAKATA_EXISTED" -eq 0 ]; then
  # Capture in order so first = Opus (top-left), second = Coda (top-right or right)
  opus_id=$(tmux list-panes -t "$SESSION" -F "#{pane_id}" | sed -n '1p')
  coda_id=$(tmux list-panes -t "$SESSION" -F "#{pane_id}" | sed -n '2p')
  [ -n "$opus_id" ] && tmux select-pane -t "$opus_id" -T "$OPUS_TITLE"
  [ -n "$coda_id" ] && tmux select-pane -t "$coda_id" -T "$CODA_TITLE"
  log "labelled Opus ($opus_id) + Coda ($coda_id)"
fi

# --- Step 5: pre-approve Oya's startup tools ----------------------
# Generate a scoped .claude/settings.local.json in Oya's cwd. Lists exactly the
# tools her startup checklist needs (Read on the project + musubi files, Edit on her
# log + comms, Bash on tmux read commands + date + ls/wc/pwd). No broader
# trust granted. Without this, operator has to ack "Do you want to proceed?"
# for every tool the first time Oya invokes it — exactly the friction the
# 2026-05-18 streamlining pass was meant to kill.
#
# Deliberately NOT granted: Bash(cat/head/tail/grep/rg:*). Those are unscoped —
# `cat ~/.ssh/id_rsa` would run with no prompt. Oya reads file CONTENTS via the
# path-scoped Read tool above (Read($TARGET/**), Read($MUSUBI_ROOT/**)); ad-hoc
# searching falls back to a one-time permission prompt. Mirrors the
# scripts/oya-pretooluse.py allowlist, which defers the same commands.
oyakata_cwd="$MUSUBI_ROOT/docs/operator"
OYA_CLAUDE_DIR="$oyakata_cwd/.claude"
mkdir -p "$OYA_CLAUDE_DIR"
cat > "$OYA_CLAUDE_DIR/settings.local.json" <<JSON
{
  "permissions": {
    "allow": [
      "Read($TARGET/**)",
      "Read($MUSUBI_ROOT/**)",
      "Edit($TARGET/docs/agents/oyakata-log.md)",
      "Edit($TARGET/docs/agents/comms/active.txt)",
      "Edit($TARGET/docs/agents/asymmetry/**)",
      "Edit($TARGET/docs/agents/rules-ledger.yml)",
      "Edit($TARGET/docs/agents/shadow-review/**)",
      "Edit($TARGET/docs/agents/operator-critique/**)",
      "Edit($TARGET/docs/agents/oyakata-pending/**)",
      "Write($TARGET/docs/agents/oyakata-log.md)",
      "Write($TARGET/docs/agents/asymmetry/**)",
      "Write($TARGET/docs/agents/rules-ledger.yml)",
      "Write($TARGET/docs/agents/shadow-review/**)",
      "Write($TARGET/docs/agents/operator-critique/**)",
      "Write($TARGET/docs/agents/oyakata-pending/**)",
      "Read($TARGET/docs/agents/oyakata-pending/**)",
      "Bash(tmux list-panes:*)",
      "Bash(tmux capture-pane:*)",
      "Bash(tmux list-sessions:*)",
      "Bash(date:*)",
      "Bash(ls:*)",
      "Bash(wc:*)",
      "Bash(pwd)"
    ]
  }
}
JSON
log "wrote scoped Oya permissions to $OYA_CLAUDE_DIR/settings.local.json"

# --- Step 6: add Oya pane (idempotent) ----------------------------
if [ "$OYAKATA_EXISTED" -eq 0 ]; then
  log "adding Oya pane (top, full-width, ~${OYA_PANE_HEIGHT}% height) running claude --model opus ..."
  # split-window flags:
  #   -b  before (above when paired with -v)
  #   -v  vertical split (one pane above the other)
  #   -f  FULL-width relative to the window (not just the target pane) — without
  #       this, splitting :0.0 stacks the new pane above Opus only and leaves Coda
  #       intact in the right column.
  #   -l NN%   new pane is NN% of available height (OYA_PANE_HEIGHT, default 38)
  #   -c <dir> starting directory — set to docs/operator/ (no CLAUDE.md there)
  #            so claude does NOT auto-load the project's CLAUDE.md and adopt the
  #            Opus identity. Oya uses absolute paths to read the project's files.
  #            ALSO: .claude/settings.local.json in this dir pre-approves her
  #            startup-tool set (see Step 5 above).
  #   -P -F    print pane_id of the newly-created pane
  # Claude Code 2.1+ accepts `--model opus` as an alias for the latest Opus
  # (currently Opus 4.8). Oya runs on Opus because the supervisor role is
  # judgement-heavy — vision/architecture custody and engineering-discipline
  # refereeing benefit from the strongest reasoning, not the cheapest. Falls
  # back to -p NN syntax on tmux < 2.4.
  oyakata_id=$(tmux split-window -t "$SESSION":0.0 -bvf -l "${OYA_PANE_HEIGHT}%" -c "$oyakata_cwd" \
                                 -P -F "#{pane_id}" "claude --model opus" 2>/dev/null \
              || tmux split-window -t "$SESSION":0.0 -bvf -p "$OYA_PANE_HEIGHT" -c "$oyakata_cwd" \
                                   -P -F "#{pane_id}" "claude --model opus")
  # Give claude's TUI time to fully boot (banner draw, .claude/settings.local.json
  # load, ready-to-receive-input). Too short and the paste-buffer below races
  # against the TUI init and the prompt is lost.
  sleep 5
  tmux select-pane -t "$oyakata_id" -T "$OYAKATA_TITLE"
  # Optional contrast tint (opt-in via launcher --pane-tint → MUSUBI_PANE_TINT=1).
  if [ "${MUSUBI_PANE_TINT:-0}" = "1" ]; then
    tmux select-pane -t "$oyakata_id" -P "bg=$OYA_TINT_BG" 2>/dev/null \
      && log "Oya pane tinted ($OYA_TINT_BG)" \
      || log "Oya pane tint skipped (tmux rejected bg style)"
  fi
  log "Oya pane created: $oyakata_id (model: opus; cwd: $oyakata_cwd)"
  FRESH_OYA=1
else
  existing_id=$(echo "$all_panes_titled" | grep "OYAKATA" | awk '{print $1}')
  oyakata_id="$existing_id"
  log "Oya pane exists at: $existing_id (claude session still running there)"
  FRESH_OYA=0
fi

# --- Step 7: auto-paste + auto-submit the v0.1 prompt -------------
# For a fresh Oya pane: load the ## Prompt section into a tmux paste-buffer,
# paste it into the Oya pane (bracketed paste — preserves newlines), then send
# Enter to submit. No manual Cmd+V required. The system clipboard
# ($CLIPBOARD_CMD, detected above) is populated as a redundant fallback for
# the rare case where paste-buffer fails (tmux < 2.0 or weird TUI). On Linux
# without xclip/wl-copy/xsel the fallback is skipped — tmux paste-buffer is
# the only path and is sufficient for normal operation.
#
# Path templating: the committed prompt uses <PROJECT_PATH> and <MUSUBI_ROOT>
# placeholders so the file in git doesn't ship anyone's hardcoded paths. We
# substitute them with $TARGET (from [project].path in musubi.toml) and
# $MUSUBI_ROOT at paste/copy time. The | delimiter for sed avoids escaping
# slashes in absolute paths.
substitute_paths() {
  sed -e "s|<PROJECT_PATH>|$TARGET|g" -e "s|<MUSUBI_ROOT>|$MUSUBI_ROOT|g"
}

prompt_lines=$(sed -n '/^## Prompt/,$p' "$PROMPT_FILE" | wc -l | tr -d ' ')
if [ -n "$CLIPBOARD_CMD" ]; then
  # shellcheck disable=SC2086  # $CLIPBOARD_CMD may legitimately contain args (e.g. "xclip -selection clipboard")
  sed -n '/^## Prompt/,$p' "$PROMPT_FILE" | substitute_paths | $CLIPBOARD_CMD
  log "prompt copied to clipboard via '$CLIPBOARD_CMD' (${prompt_lines} lines, paths substituted; manual paste fallback ready)"
else
  log "prompt NOT copied to clipboard (no tool available); auto-paste via tmux paste-buffer is the only path"
fi

if [ "$FRESH_OYA" -eq 1 ]; then
  log "auto-pasting prompt into Oya pane $oyakata_id ..."
  sed -n '/^## Prompt/,$p' "$PROMPT_FILE" | substitute_paths | tmux load-buffer -b oya-prompt -
  # -p wraps the content in bracketed-paste control codes when the TUI has
  # requested them (Claude Code 2.x does). That preserves newlines as content
  # rather than each one submitting a partial message.
  tmux paste-buffer -p -t "$oyakata_id" -b oya-prompt
  sleep 1
  tmux send-keys -t "$oyakata_id" Enter
  tmux delete-buffer -b oya-prompt 2>/dev/null || true
  log "prompt submitted — Oya will run startup checklist + emit READY"
else
  log "Oya pane already running; not re-pasting prompt"
fi

# --- Done ---------------------------------------------------------
# Skip the trailing cheat-sheet when invoked by the orchestrator
# (OYA_QUIET_BANNER=1); the orchestrator owns the boot narrative there.
if [ "${OYA_QUIET_BANNER:-0}" != "1" ]; then
  cat <<EOF

────────────────────────────────────────────────────────────
 Oya attached (v0.1 active mode)

 Layout:
   ┌─────────────────────────────────────────┐
   │  OYAKATA · 親方 · master craftsman      │   ← top (~30%), full width
   ├────────────────────┬────────────────────┤
   │  OPUS · Anthropic  │  CODA · OpenAI     │   ← bottom (~70%), split half-half
   └────────────────────┴────────────────────┘

 Next:
   1. Attach to musubi (skip if you're already attached):
        tmux attach -t ${SESSION}

   2. The Oya prompt has been auto-pasted and submitted. Watch the top pane:
      Oya runs the startup checklist and emits "Startup complete. Ready."
      followed by her READY block in the log.

   3. Run the cycle as normal. Talk to Opus + Coda the way you do today.
      You may also talk to Oya directly in her pane (active mode).

 If Oya did NOT auto-start (paste raced the TUI boot):
   - Focus the Oya pane and Cmd+V — the prompt is in your clipboard as fallback.

 At cycle close:
   less ${TARGET}/docs/agents/oyakata-log.md
────────────────────────────────────────────────────────────
EOF
fi
