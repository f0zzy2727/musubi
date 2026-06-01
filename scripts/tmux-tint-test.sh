#!/usr/bin/env bash
# tmux-tint-test.sh — TEMP visual harness for the --pane-tint feature.
#
# Builds the same 3-pane layout the orchestrator produces (Oya top full-width,
# Opus bottom-left, Coda bottom-right) with throwaway log-like content — NO
# agents, NO orchestrator. Use it to dial in the pane background tints and the
# Oya pane height before wiring final values into the real launchers.
#
# Usage:
#   ./scripts/tmux-tint-test.sh                 # defaults (current shipped values)
#   OPUS_BG=colour233 CODA_BG=colour236 OYA_BG=colour238 ./scripts/tmux-tint-test.sh
#   OYA_H=42 ./scripts/tmux-tint-test.sh        # try a taller Oya pane
#   TINT=0 ./scripts/tmux-tint-test.sh          # no tint (baseline for comparison)
#
# It kills + recreates the test session each run, then attaches you to it.
# Detach with Ctrl-b d. Tear down with:  tmux kill-session -t tinttest
#
# Try hues instead of greys, e.g.:
#   OPUS_BG="#161a22" CODA_BG="#22161a" OYA_BG="#101010" ./scripts/tmux-tint-test.sh
set -euo pipefail

SESSION="tinttest"
OYA_H="${OYA_H:-38}"
TINT="${TINT:-1}"
# Defaults spread wide on purpose so contrast is obvious — dial back to taste.
# Opus + Coda sit side-by-side (the pair you most need to tell apart), so they
# get the biggest gap; Oya sits between them.
OPUS_BG="${OPUS_BG:-colour232}"   # darkest  (#080808)
CODA_BG="${CODA_BG:-colour240}"   # lightest (#585858)
OYA_BG="${OYA_BG:-colour236}"     # mid      (#303030)

command -v tmux >/dev/null || { echo "tmux not found" >&2; exit 1; }

# Fill a pane with a title banner + dummy log lines so the background tint is
# visible both behind text and in the empty space below it. The pane's own
# interactive shell keeps it alive after the command finishes — no exec needed.
fill() {
  cat <<EOF
clear; printf '\033[1m%s\033[0m\n\n' "$1"; for i in \$(seq 1 12); do echo "  [10:04:0\$i] [DUMMY] sample log line \$i — the quick brown fox jumps over"; done; echo; echo "  (background tint preview — Ctrl-b d to detach)"
EOF
}

tmux kill-session -t "$SESSION" 2>/dev/null || true

# Pane 0 = Opus (left)
tmux new-session -d -s "$SESSION" -x 220 -y 50
p_opus=$(tmux display-message -p -t "$SESSION":0.0 "#{pane_id}")

# Split right = Coda
p_coda=$(tmux split-window -t "$SESSION":0.0 -h -P -F "#{pane_id}")

# Split Oya on top, full-width — mirrors attach-oya.sh's -bvf -l NN%
p_oya=$(tmux split-window -t "$SESSION":0.0 -bvf -l "${OYA_H}%" -P -F "#{pane_id}")

# Titles (pane-border-status, like the real session)
tmux set -t "$SESSION" pane-border-status top
tmux select-pane -t "$p_oya"  -T "OYAKATA · 親方 · master craftsman"
tmux select-pane -t "$p_opus" -T "OPUS · Anthropic"
tmux select-pane -t "$p_coda" -T "CODA · OpenAI"

# Tints
if [ "$TINT" = "1" ]; then
  tmux select-pane -t "$p_opus" -P "bg=$OPUS_BG"
  tmux select-pane -t "$p_coda" -P "bg=$CODA_BG"
  tmux select-pane -t "$p_oya"  -P "bg=$OYA_BG"
  echo "tint ON  — Opus=$OPUS_BG  Coda=$CODA_BG  Oya=$OYA_BG  (Oya height ${OYA_H}%)"
else
  echo "tint OFF — baseline (Oya height ${OYA_H}%)"
fi

# Content
tmux send-keys -t "$p_oya"  "$(fill 'OYAKATA  (top, full-width)')" C-m
tmux send-keys -t "$p_opus" "$(fill 'OPUS  (bottom-left)')" C-m
tmux send-keys -t "$p_coda" "$(fill 'CODA  (bottom-right)')" C-m

tmux select-pane -t "$p_opus"
tmux attach -t "$SESSION"
