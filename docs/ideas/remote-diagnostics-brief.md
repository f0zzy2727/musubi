# Remote diagnostics — product/extension brief

*Captured 2026-06-29. Idea + design discussion between John and Claude. Not yet
built. Status: concept, pre-grilling.*

## Origin

Dogfooded from a live pain. Diagnosing Michael's voice-reclone incident meant
John acting, by hand, as a remote troubleshooting agent over a zipped debug
bundle (`scripts/collect-debug-bundle.sh`). The idea is to **automate that exact
loop**: an agent on one musubi install helps troubleshoot another install,
remotely.

## What it is (one line)

A **remote, read-only field-support channel for musubi**: a helper agent reads a
redacted diagnostic feed from a remote musubi install, forms a diagnosis, and
hands fixes back to the *local* human — who acts on their own machine. Async,
evidence-grounded, human-gated, telemetry-only.

It is an **extension of musubi**, not a new framework — it reuses comms/capsule,
the operator gate, the third-agent (Oya) pattern, and the existing
`collect-debug-bundle` + `redact-bundle` plumbing.

## The core contract (LOCKED design intent)

> **Remote = read-only telemetry from a declared allowlist, via a fixed request
> verb set, redacted on egress, with NO writes ever.**

This single constraint removes the hardest problem (remote code execution / the
asymmetric-deference risk at network scale). The remote agent is a *reader of a
dashboard*, not an SSH session. Fixes flow back as advice; the local human acts.

Three things that make "read-only" actually safe (read-only ≠ leak-proof):

1. **Declared diagnostics allowlist — and nothing else.** The remote can see
   exactly the `collect-debug-bundle` surfaces: comms / capsule / current-state,
   oya-log / operator-actions / rules-ledger, doctor output, tmux scrollback,
   config tomls (redacted). Source code, `.env`, keys, arbitrary paths are *not
   on the list = unreachable*. The allowlist is the boundary, not the agent's
   judgement.
2. **Inbound is a fixed verb menu, not free-form.** e.g. `get capsule`,
   `get last 200 comms`, `get oya-log`, `run doctor`. Unrecognised request =
   ignored. A poisoned channel cannot ask for anything off-menu.
3. **Redaction mandatory on egress.** Telemetry holds secrets (cf. sec-1).
   `redact-bundle` runs on everything before it touches the channel.

Scope is therefore **one grant: "telemetry-read."** No permission matrix needed
for v1. (Future scopes — live-Oya read, propose-patch — are separate, later,
separately-gated slices. The dangerous "nudge his Oya / send-keys / auto-apply"
version is explicitly OUT.)

## The five trust tenets (John's, 2026-06-29)

These are not separate features — they are the **trust UX**, and they are the
moat (the plumbing is easy; safe-by-construction is the product).

| Tenet | What it is | Mechanism |
|---|---|---|
| Human permission exchange | mutual, revocable, per-session consent | pairing handshake — code exchanged out-of-band, grant not default |
| Encryption on the shared file | the folder host (Dropbox) never reads contents | symmetric key; channel holds only ciphertext |
| Simple to set up | one command, no config | one skill + one short code |
| Obvious it's running | never silent | persistent badge / pane: *"remote diagnostics: read-only, telemetry only"* |
| Simple to tear down | instant disconnect, no residue | one command: stop + wipe key + optional shred channel |

**The tension (simple vs secure) dissolves via the pairing-code pattern**
(magic-wormhole / Signal-style): one human-exchanged short string carries
*consent + key + channel address* at once, so encryption and permission cost no
extra setup steps.

```
helper:  /remote-diag start  ->  prints code "7-otter-anvil"  (code = key + channel id; never hits Dropbox)
         (operator reads code to the other party out-of-band — call/text)
remote:  /remote-diag join 7-otter-anvil
         -> paired, channel encrypted, consent recorded. One code did all three.
teardown: /remote-diag stop  -> channel dead, key wiped, no residue.
```

## Transport

- **Shared folder as the bus.** File drop = message, auto-sync = transport, no
  NAT, no server. Dropbox / Google Drive / Syncthing all work.
- **Abstract it.** The skill reads/writes a `channel/` dir; the user picks what
  syncs it. Avoids a Dropbox-vs-git religious decision.
- **git bus vs Dropbox:** git gives an audit trail + atomic commits + diffs
  (musubi lives on receipts) but needs pull/push; Dropbox is zero-config and
  auto-syncs (free wake signal) but has no history and risks conflict
  copies/races on concurrent writes. **Lean: git as the receipts-keeping
  default, Dropbox as easy-mode fallback.** (Also sidesteps the `transport-1`
  wake-up blocker — sync/poll is the wake signal.)

## Setup model

A **skill** (`/remote-diagnostics` or `/remote-diag`) is the installer/onboarding:
run `claude` or `codex` in the musubi folder, invoke the skill, it does the
pairing handshake and stands up the channel. Skills are already musubi's
packaging unit.

## Failure modes named

1. **Shared folder = backdoor** — anyone with write access can drop a poisoned
   file. → inbound propose/read-only, fixed verbs, identified/signed, never
   auto-acted.
2. **Secret leak via sync** — a synced folder is a publish action. → mandatory
   redaction on egress.
3. **Races / conflict copies** (Dropbox) — concurrent writes. → git, or
   per-sender subdirs.
4. **Cross-org correlated blindspot** — two teams' agents agreeing on a wrong
   frame (the reclone lesson, one level up). → human gate each end.

## "How crazy" — honest scoring

- Transport + skill + shared folder: **not crazy, ~this-week buildable** on
  existing parts.
- Read-only telemetry channel: **the sane, sellable core.**
- Live cross-machine Oya tap (read): bold but fine *if read-only* — later slice.
- Auto-executing remote suggestions: **the only actually-crazy version — OUT.**

## Why it matters (positioning)

It's a **product**, not just a feature — managed/remote musubi support — and the
**trust model is the moat**. LUGHa's thesis is judgement-transfer; this is
judgement-transfer *across machines*. The feature that lets people turn it on is
that it's safe by construction.

## MVP slice

Skill + shared `channel/` dir. Egress = redacted bundle/telemetry on a fixed
verb menu. Inbound = read requests only, off-menu ignored, no writes. Pairing
code = consent + key + setup. Visible badge while live. One-command teardown.
Live-Oya *read* is a fast-follow; any *write* path is a separate, later,
separately-gated decision.

## Next step

Run through `/office-hours` forcing-questions (or `/grill-me`) to find the
narrowest sellable wedge and pressure-test the transport-vs-trust tradeoff
*before* any code.
