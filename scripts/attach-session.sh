#!/usr/bin/env bash
#
# attach-session.sh — resilient tmux attach for the launcher's iTerm window.
#
# Why this exists (field bug 2026-06-22): the launcher used to run a one-shot
#   sleep 4 && tmux attach -t <session>
# in the spawned iTerm window. That races against the orchestrator's
# orphan-cleanup path: if a stale "musubi" session already exists (e.g. after a
# reboot, or a Ctrl+C'd launch left two dropped-to-shell panes), the window
# attaches to that OLD corpse at +4s. Moments later the orchestrator classifies
# it as an orphan, KILLS it, and creates a fresh session of the same name. The
# one-shot attach is now dead, the new session has no client, and the
# orchestrator stalls 60s on its "waiting for a tmux client to attach" gate
# before starting the agents headless — the operator sees nothing.
#
# This script instead waits for the session, attaches, and RE-ATTACHES if the
# session it was on is killed and recreated — while still exiting cleanly when
# the operator detaches on purpose (Ctrl-b d). The two cases are told apart by
# tmux's #{session_created} epoch: a recreated session has a newer stamp, an
# intentional detach leaves the same session (same stamp) running.
#
# Usage: attach-session.sh <session-name>

set -u

SESSION="${1:?usage: attach-session.sh <session-name>}"

# How long to keep waiting for the session to (re)appear before giving up, so a
# never-launched session doesn't spin forever in the operator's window.
MAX_WAIT_SECS="${MUSUBI_ATTACH_MAX_WAIT:-120}"

session_created() {
    tmux display-message -p -t "$SESSION" '#{session_created}' 2>/dev/null
}

waited=0
while true; do
    # Wait for the session to exist (initial creation, or recreation after an
    # orphan cleanup).
    while ! tmux has-session -t "$SESSION" 2>/dev/null; do
        if [ "$waited" -ge "$MAX_WAIT_SECS" ]; then
            echo "attach-session: session '$SESSION' never appeared after ${MAX_WAIT_SECS}s — giving up." >&2
            echo "(attach manually once it's up: tmux attach -t $SESSION)" >&2
            exit 1
        fi
        sleep 1
        waited=$((waited + 1))
    done

    created_before="$(session_created)"
    tmux attach -t "$SESSION"

    # attach returned: either the operator detached, or the session was killed.
    # If the same session is still running (same creation epoch), the operator
    # detached intentionally — stop. Otherwise it was killed (and maybe already
    # recreated by the orchestrator's orphan path) — loop and re-attach.
    created_after="$(session_created)"
    if [ -n "$created_after" ] && [ "$created_after" = "$created_before" ]; then
        break
    fi
    # Reset the wait budget: the session genuinely existed, we're now waiting on
    # a recreate, which should be near-instant.
    waited=0
done
