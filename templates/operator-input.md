# Operator Input

> **Append-only log of what the operator types TO Oya** — written by the
> console pane (`scripts/operator-console.sh`), one entry per submit. The
> orchestrator watches this file and relays each new entry into Oya's pane,
> the same way it relays comms traffic.
>
> The point: the operator types into the console pane, which has exactly one
> writer, so their keystrokes are never overwritten by the relay `send-keys`
> traffic that lands in Oya's own pane. This is the input half of the operator
> console; `operator-channel.md` is the output half (Oya's replies). Together
> they keep the whole operator↔Oya conversation off the relay-fed pane.

---
