#!/usr/bin/env bash
#
# operator-console.sh — the operator's INPUT surface for talking to Oya.
#
# Runs in a dedicated pane (added by attach-oya.sh, under the channel pane).
# The operator types messages to Oya HERE, not in Oya's own pane — because
# the orchestrator `send-keys`-relays pair traffic INTO Oya's pane, and that
# overwrites anything the operator is mid-typing there. This pane has exactly
# one writer (the operator), so nothing collides with their keystrokes.
#
# On each submit, the line is appended to operator-input.md with a timestamp
# header. The orchestrator watches that file and relays each new entry into
# Oya's pane (see oyakata.relay_operator_input_to_oyakata). Oya answers and
# mirrors the answer to the operator channel — which the operator reads in the
# channel pane above. So the full loop (type here → Oya → read above) never
# touches the relay-fed pane.
#
# Usage (normally launched by attach-oya.sh, not by hand):
#   operator-console.sh <operator-input.md path>
#
set -euo pipefail

INPUT_FILE="${1:?usage: operator-console.sh <operator-input.md path>}"
mkdir -p "$(dirname "$INPUT_FILE")"

# Box-drawing header so the pane reads as a console, not a dead shell.
bar="────────────────────────────────────────────"
printf '%s\n' "$bar"
printf ' TALK TO OYA  ·  type here, read her replies above\n'
printf ' Your keystrokes land here only — never overwritten by relay traffic.\n'
printf '%s\n\n' "$bar"

# Read loop. `read -r` keeps backslashes literal; the `you →` prompt marks the
# input line. EOF (Ctrl-D) or an empty line just re-prompts; a real line is
# timestamped and appended as one entry, then echoed back as a sent-receipt.
while IFS= read -r -e -p 'you → ' line || [ -n "${line:-}" ]; do
  # Skip blank submits — they would relay an empty message to Oya.
  if [ -z "${line//[[:space:]]/}" ]; then
    continue
  fi
  # Timestamp in the same UTC HH:MM form Oya uses in the channel, so the two
  # logs read as one conversation. The header is the delimiter the orchestrator
  # splits on — keep it exactly `**HH:MM UTC — Operator:**`.
  stamp="$(date -u '+%H:%M UTC')"
  {
    printf '\n**%s — Operator:**\n' "$stamp"
    printf '%s\n' "$line"
  } >> "$INPUT_FILE"
  printf '   ↳ sent to Oya (%s) — watch the channel pane for her reply\n\n' "$stamp"
done
