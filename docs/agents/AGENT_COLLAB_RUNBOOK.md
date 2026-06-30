<!-- musubi-managed: this file is updated by `bootstrap.sh` from the musubi repo. To fork it, delete this marker; the bootstrap will then warn and diff instead of overwriting. -->

# Agent Collaboration Runbook

**Version:** 1.10
**Last updated:** 2026-05-30
**Status:** Active

Two AI agents. One human lead. A shared codebase. This runbook defines how the three of you work together without stepping on each other, losing context, or turning the human into a full-time message broker.

> **This is the core runbook — the per-cycle discipline, always loaded.** Consult-occasionally detail (full definitions, branching, planning chain, validation standards, escalation, drift handling, memory discipline, tone, changelog) lives in [`AGENT_COLLAB_RUNBOOK_REFERENCE.md`](AGENT_COLLAB_RUNBOOK_REFERENCE.md), which is **not** auto-loaded — read it when a slice touches one of those topics. The operative default for each is summarised in [Reference (load on demand)](#reference-load-on-demand) below, so the rule you need every cycle is always in context.

---

## Contents

1. [The Crew](#the-crew)
2. [System Overview](#system-overview)
3. [Comms Protocol](#comms-protocol)
4. [Canonical Files](#canonical-files)
5. [Task Board Protocol](#task-board-protocol)
6. [Current-State Capsule](#current-state-capsule)
7. [Execution Protocol](#execution-protocol)
8. [Review Pattern](#review-pattern)
9. [Mechanical Gates](#mechanical-gates)
10. [Rule Quality](#rule-quality)
11. [Preserve Deliberate State](#preserve-deliberate-state)
12. [Final Gate](#final-gate)
13. [Handoff Expectations](#handoff-expectations)
14. [Startup and Recovery](#startup-and-recovery)
15. [Practical Defaults](#practical-defaults)
16. [Reference (load on demand)](#reference-load-on-demand)

---

## The Crew

| Name | Handle | Role | Tool |
|---|---|---|---|
| **[Your Name]** | `@LEAD` | Human lead. Owns priorities, scope, acceptance, deploy. | Brain |
| **Agent A** | `@OPUS` | Builder, reviewer, architect. Default-leans toward product framing, design critique, broad codebase reasoning, cross-system synthesis. | Claude Code CLI |
| **Agent B** | `@CODA` | Builder, reviewer, parallel executor. Default-leans toward surgical patches, integration-skeptic, the "suspicious adult in the room" when a summary is too cheerful. | Codex CLI |

> **Agent names are configurable.** `Opus` and `Coda` are defaults. To rename them, update `musubi.toml` — the orchestrator reads names, handles, and CLI commands from there. The names used throughout this runbook will reflect whatever you set in the config. Use handles in comms headers and when directly addressing each other. First names otherwise.

**Asymmetry between the two agents is a feature, not a bug.** A pair with identical dispositions cross-reviews each other's work as a formality. A pair where one is paid to find bugs in the other's optimism catches real bugs in real review rounds. Lean into the difference rather than smoothing it out.

---

## System Overview

The human lead runs both agents in adjacent terminal panes via the musubi orchestrator. Messages flow like this:

```
Agent A writes to comms file, ends with <OVER>
  -> Orchestrator detects <OVER>, relays message to Agent B's pane
    -> Agent B reads, acts, writes reply with <OVER>
      -> Orchestrator relays back to Agent A
        -> Repeat until the work is done
```

The relayed pane message is the **alert**. The comms file is the **authority**. When a message is relayed, the receiving agent must read the full comms file before acting — not just the relayed snippet. Context matters and the file has all of it.

### The `<OVER>` Convention

Every message in the comms file ends with `<OVER>` on its own line. This is the turn signal. It tells the orchestrator the agent is done and the message is ready to relay.

No `<OVER>` means still composing. Do not relay half-finished messages.

---

## Comms Protocol

### The comms file

```text
docs/agents/comms/active.txt
```

> Path is configurable in `musubi.toml`; relative paths resolve from the project root. The default lives inside the repo so it survives reboots, but `docs/agents/comms/` is gitignored — only the archived copy at `docs/agents/archive/` (written at cycle close) is committed. Absolute paths like `/tmp/agent_comms.txt` still work if you want the file to be ephemeral.

This file is the append-only transcript of all agent-to-agent communication. It serves as coordination log, plan review comments, sequencing decisions, implementation sync notes, and the definitive record of who said what and when.

Do not use product docs as a dumping ground for inter-agent chatter. That is what this file is for.

### Communication discipline

Communication is support work, not the work itself.

**Send a message when:**
- Ownership changes
- A slice lands and is ready for review
- Validation completes — pass or fail
- A real blocker appears
- A decision needs to be recorded
- A `GO: yes` handoff assigns work to a named owner

**Do not send a message to:**
- Acknowledge receipt unless silence would create real ambiguity
- Restate intent without a concrete artifact behind it
- Report progress that is not a delta

A promised next step is not a completed step. Do not send updates describing work you are about to do. Send updates describing work you have done.

Any claim that work is underway must include at least one observable item:
- command run
- file created or edited
- diff summary
- validation output
- named running process

If none of those exist, the agent must report `claimed`.

Do not let a relay message interrupt active implementation unless it changes scope, ownership, or safety. Finish the current unit of work, then read and respond.

### Write rules

- **Append only.** Never overwrite or delete previous messages.
- After every comms write, immediately verify with `tail` that your new message is physically at the end of the file. If it is not, treat that as a tooling failure and correct it before doing anything else.
- Add a visual separator before each new message:

```text
---------------------------------------------------
```

- Use this header format exactly:

```text
[@OPUS] [YYYY-MM-DD] [HH:MM UTC]
[@CODA] [YYYY-MM-DD] [HH:MM UTC]
```

- Include the full message header block immediately under the timestamp:

```text
Type: Update | Review Request | Review Result | Decision | Blocker | Receipt
Subject: one line describing the message
Reply required: yes | no | only-if-blocker
GO: yes | no
GO owner: <agent name> | both | none
GO action: <first concrete action, or none>
```

- End every message with `<OVER>` on its own line.
- Keep timestamps in chronological order.
- Use handle form (`@OPUS`, `@CODA`) when directly addressing the other agent.
- Every `Update`, `Review Request`, `Review Result`, or `Blocker` message must use this body structure:

```text
Action:
[exact command run, exact edit made, or "claimed" if no concrete execution]

Evidence:
[file paths, diff summary, command output summary, validation summary, PID/process name, or "none"]

Result:
[execution state: claimed / started / blocked / spawned / confirmed_running / completed
 OR verdict (review/validation): pass / fail]

Next:
[next concrete action only]
```

Narrative status without this structure is non-compliant.

### Orchestrator-enforced guards

The orchestrator inspects every message before relaying. Two guards refuse the relay and nudge the writer instead:

**Ack-of-ack guard.** When three consecutive messages share an idle `Result:` value (`NOT STARTED`, `claimed` with no transition, `holding`, `awaiting…`), the orchestrator refuses the third relay and asks the writer to either claim a slice with a concrete first action or name a real blocker. The streak resets the moment a non-idle Result lands (`started`, `spawned`, `completed`, `blocked — <reason>`).

**Capsule-staleness guard.** When a `Review Request`, `Decision`, or `Blocker` message is written without the capsule (`docs/agents/current-state.md`) having been updated in the last two minutes, the orchestrator refuses the relay and asks the writer to update the capsule first. This enforces the *capsule-before-comms invariant* mechanically rather than relying on reviewer catch.

Both guards print a clear `[WATCHER]` line in the orchestrator window and post a nudge into the writer's pane. They are mechanical and do not require human intervention.

### Reply discipline

**`Reply required: no`** means do not append a reply, *even if the relay layer's default prompt says to reply.* Agent judgment follows the field. This rule exists because relay prompts are generic and the field is specific.

**`Reply required: only-if-blocker`** means reply only for overlap, blockers, safety issues, or material corrections.

**Exception:** if the human lead specifically asks for a reply on a message marked `Reply required: no`, the human's direction wins.

### The GO baton

**`GO: yes` is an execution baton.** It names an owner, a file surface (via the slice or the message), and a first concrete action. The named owner begins immediately unless a real blocker exists — they do not wait for peer acknowledgement. The peer replies only for overlap, blocker, or safety issue.

This means: if you see `GO: yes` and you are the owner, you start. If you see `GO: yes` and you are not the owner, your default response is silence (read it, note it, keep working on your own slice).

### Proof blocks

Any message claiming `spawned` or `confirmed_running` must include a proof block with at least one machine-checkable field beyond `state` and `checked_at`:

```text
state: spawned | confirmed_running
pid: <pid-or-none>
terminal: <terminal-id-or-none>
subagent: <subagent-id-or-none>
worktree: <path-or-none>
command: <active-command-or-none>
checked_at: <ISO-8601 UTC time>
```

If no proof can be produced, downgrade the claim.

### A complete message

```text
---------------------------------------------------
[@OPUS] [2026-01-01] [10:00 UTC]
Type: Update
Subject: Slice 1 started — widget API scaffold created
Reply required: only-if-blocker
GO: no
GO owner: none
GO action: none

@CODA

Action:
Created `src/api/widget.ts` and updated `src/components/Widget.tsx`

Evidence:
- Files changed:
  - src/api/widget.ts
  - src/components/Widget.tsx
- Diff summary:
  - added widget API route scaffold
  - connected component submit path to new route

Result:
started

Next:
Run type checks and add widget API test scaffold

<OVER>
```

### Message types

| Type | Use when |
|---|---|
| **Update** | Something changed. State what changed and what is next. |
| **Review Request** | A slice is ready for peer review. State what to look at and what feedback is needed. |
| **Review Result** | Review is complete. State approved, changes requested, or findings with specifics. |
| **Decision** | A decision has been taken. State the decision and its impact on the plan, board, or execution. |
| **Blocker** | Work cannot continue. State what is blocked and what is needed to unblock it. |
| **Receipt** | A state transition with nothing to deliberate (tiny/lightweight lane only). A one-line confirmation — `Result:` + a verification pointer — in place of a full Update's Action/Evidence/Next prose. |

If none of those apply, you probably should not be sending a message yet.

**Receipt class (protocol-1 weight reduction).** On the tiny and lightweight
lanes, a completed slice that produced nothing requiring peer judgement may be
acknowledged with a Receipt instead of a full Update. A Receipt carries only
the header, `Result:` (e.g. `completed`), and a single verification pointer
(commit sha, test name, or "diff is the evidence"). It MUST NOT be used on the
heavy lane, for Review Results, or for any state a reviewer needs prose to
assess. This is the runbook's answer to the "long comms message where a
receipt would do" accidental-weight pattern — the reconstructed rules-ledger
fire data confirmed the load-bearing review disciplines (Findings block, bug-
path gate) earn their keep, so weight is cut only on the messages that never
needed it.

```text
[@CODA] [2026-05-29] [14:02 UTC]
Type: Receipt
Lane: tiny
Result: completed — typo fix in README, sha a1b2c3d. Diff is the evidence.
<OVER>
```

### Writing method

Avoid shell heredocs for multi-line messages containing backticks, apostrophes, or quotes — they will corrupt the content silently. Use a Python append or a write tool that preserves literal text exactly. When writing to the comms file, append at true EOF only; never use a patch operation that could match an earlier `<OVER>` block.

The goal is boring reliability. Nobody should have to debug punctuation while debugging the product.

### Comms archive

The active comms file is append-only during a work cycle. Completed cycles get archived into the repo so the history is durable across reboots and reviewable later.

There are two archive paths — one human-driven, one automatic — and they coexist:

```text
docs/agents/archive/agent_comms_YYYY-MM-DD_feature-slug.txt   ← manual, at cycle close
docs/agents/archive/agent_comms_YYYY-MM-DD_HHMMSS.txt          ← auto-rotated by orchestrator on startup
```

**Manual archive (cycle close).** Archive when a cycle is complete — improvement agreed, plan agreed, build/review/doc sync done — not just when the file gets long. Workflow:

1. Keep the active comms file as the single source of truth during a cycle
2. When the cycle is complete, copy it into `docs/agents/archive/` with a `_feature-slug.txt` suffix
3. Commit the archive file
4. Clear or reset the active file for the next cycle

Do not archive mid-slice unless both agents explicitly agree the thread is finished.

**Auto-rotation (orchestrator startup).** The orchestrator rotates `active.txt` on every fresh launch so the active file does not grow unbounded across sessions and bloat agent warm-start context. Auto-rotated archives use a `_HHMMSS` timestamp suffix and are not tied to a cycle close — they capture whatever was in flight at the moment the orchestrator restarted. Treat them as **session boundaries**, not cycle boundaries.

When `active.txt` is empty on warm start because the orchestrator just rotated it, the most recent auto-rotated archive carries the prior session's transcript. The runbook's [Startup and Recovery](#startup-and-recovery) checklist (item 6) points agents at it. The structured handoff and capsule capture intent; the archive captures texture.

### Managed-doc rotation policy

`agent-handoff.md`, `agent-todo.md`, and `current-state.md` accrete entries across cycles. Left unrotated they cross Claude Code's ~40k-char performance threshold, after which every warm start loads hundreds of KB of stale managed-doc context before any work begins.

**Mechanism (cycle close):**
- Archive all but the **last 1–2 cycle sections** of `agent-handoff.md` to `docs/agents/archive/handoff-archive-<date>.md`. Same pattern for `agent-todo.md` (precedent: `agent-todo-archive-*.md`).
- Reset `current-state.md` to capsule-discipline length — the capsule is a *current-state* snapshot, not a log; completed-cycle rows belong in the handoff archive, not the capsule.
- Choose the retained-section count (`N`) to fit the cycle cadence; 1–2 is the default.

**Enforcement (orchestrator boot).** The orchestrator size-guards these docs on startup — it warns above 40k chars and, above 100k chars, **offers to rotate the doc in place** (`Rotate now? [y/N]`): on yes it archives the full doc to `docs/agents/archive/` and trims the active copy to its preamble plus the two most-recent cycle sections, then continues launching. Decline (or a non-interactive run) and it refuses to launch with an actionable error. The guard catches what this rotation policy was meant to prevent; honour the policy at cycle close and the guard never fires.

---

## Canonical Files

| File | Purpose |
|---|---|
| `docs/improvements/` | Improvement ideas, problem framing, possible solution directions |
| `docs/implementations/` | Execution-ready implementation plans with defined slices |
| `docs/agents/agent-todo.md` | Shared task board and ownership |
| `docs/agents/agent-handoff.md` | Structured handoffs after completed slices |
| `docs/agents/current-state.md` | **Live capsule** — current cycle, active slices, owners, blocked items, last verified HEAD |
| `docs/agents/comms/active.txt` | Append-only agent-to-agent comms transcript (active cycle, gitignored) |
| `docs/agents/archive/` | Archived comms logs for completed cycles |
| `docs/agents/AGENT_COLLAB_RUNBOOK.md` | This file — protocol authority |
| `docs/agents/PAIR_OPERATING_MODEL.md` | Patterns + adoption guide (the *why* behind the runbook) |
| `docs/operator/DEV_STRATEGY.md` | Operator-facing — daily/weekly cadence for AI-assisted development; not auto-imported into agent context |

If a decision affects execution and is not reflected in the implementation plan, task board, handoff, or capsule, it is not settled enough to act on.

---

## Task Board Protocol

```text
docs/agents/agent-todo.md
```

Status keys:
- `[ ]` pending
- `[~]` in progress — include branch name (or `main` if direct-to-main)
- `[x]` done — include validation summary
- `[!]` blocked — include cause and what is needed to unblock

Rules:
- Only approved implementation-plan slices go on the board
- Assign explicit ownership (`— Opus` or `— Coda`)
- Keep sequencing and dependencies explicit — if Slice 3 gates on Slice 2, say so
- If slices can run in parallel safely, mark them as such (the launch matrix is the source of truth)
- Update the board as work progresses — a stale board is worse than no board

**Board footer** — keep a small current-state block at the bottom of the todo:

```markdown
---
## Current State
- Opus: [active slice or idle]
- Coda: [active slice or idle]
- Awaiting review: yes / no
- Safe to start next slice: yes / no
- Last updated: [timestamp]
```

The fuller version of this lives in the [Current-State Capsule](#current-state-capsule). The board footer is a quick-glance subset.

---

## Current-State Capsule

```text
docs/agents/current-state.md
```

A single durable file describing live coordination state. The capsule answers, in one read, *"what is happening right now?"*

**Required sections:**

```markdown
# Current State — [project name]

**Last verified HEAD:** <commit-sha-and-message>
**Last updated:** <ISO-8601 UTC>
**Active cycle:** <cycle name or "none">

## Active slices

| Agent | Slice | State | Branch | Started | Notes |
|---|---|---|---|---|---|

## Review queue

| Slice | Reviewer | Requested | Notes |
|---|---|---|---|

## Blocked items

| Slice | Owner | Blocker | Needs |
|---|---|---|---|

## Locked decisions this session

| Decision | Date set | Source-of-truth | Why locked |
|---|---|---|---|

<!-- Decisions whose value must NOT be re-derived from the diff. Read this table at
     resume BEFORE touching any judgement-carrying file, so a value someone locked
     earlier isn't silently "normalised" back. Migrate durable locks to
     docs/agents/LOCKED_DECISIONS.md at cycle close. -->

## Dirty worktree exceptions

[Files known to be dirty for a legitimate reason — e.g., a long-running migration in progress]

## Merge / push order

[If multiple slices are queued for push, the order they should land in]
```

### The capsule-before-comms invariant

**The capsule is updated *before* the comms message it describes.**

Sequence matters: capsule first, comms second. This means the comms message is *reporting* reality, not promising it. Inverting the order is one of the recurring drift modes.

If you would say "I just moved Slice 3 to `completed` in the capsule" in your comms message, the capsule edit must already be on disk before you write the message. The peer agent reading the comms file should be able to verify the claim by reading the capsule directly.

### Capsule timestamps must come from `date -u`

**Every capsule timestamp (`Last updated`, `Started`, review queue `Requested`, blocked-item entries) is taken from a live `date -u '+%Y-%m-%dT%H:%M UTC'` invocation at write time. Never from recall, working memory, or the timestamp on an earlier comms message.**

The capsule is the audit trail. Out-of-sequence or invented timestamps degrade the trail's value for retrospective reconstruction (which review came first? did the v2 row predate the v1 review it was responding to?) and for diagnosing capsule-before-comms violations after the fact.

**Why this is a rule, not a guideline:** the 2026-05-15 Oya spike on the framework's reference codebase caught three independent timestamp-drift instances in one session, all in the `@OPUS` stream — including one v2 review-queue row stamped 13:23 UTC that could not possibly be correct because the v1 review it was responding to was at 14:16 UTC. The entries' content was correct; the timestamps were transcribed from memory. The same failure mode as the machine-derived-counts discipline applied to time: a value transcribed from a non-authoritative source instead of derived from the authoritative one.

**Mechanism:**
- Before writing or updating any capsule row, run `date -u '+%Y-%m-%dT%H:%M UTC'` and use that exact string.
- For an event that already happened (a comms message you posted 8 minutes ago), use the header timestamp of that comms message — that header is itself authoritative because it was written at the time of the event.
- Do NOT reuse a `Last updated` value from elsewhere in the capsule. Each row has its own write time.
- A reviewer who finds two capsule rows where the later row's timestamp predates the earlier row's referenced event should treat both as suspect until re-derived.

---

## Execution Protocol

### Lane choice (tiny, lightweight, or heavy)

Every slice is one of three lanes, declared in the slice acceptance receipt.
Protocol weight scales with risk: heavy work gets the full ceremony, trivial
work gets almost none, and the lane is chosen **mechanically** — not by
judgement — so it can't be quietly gamed.

**Run the classifier, don't eyeball it.** Stage your change, then:

```bash
scripts/classify-slice.sh            # reads the staged set + LOC
```

Paste the emitted `Lane:` value verbatim into the acceptance receipt. The
classifier reads the staged files + LOC against fixed trigger patterns
(state files, CI/workflow, schema, UI, code size) and is the authority for
the lane. `@LEAD` may **promote** a lane (e.g. tiny → heavy) when judgement
says the mechanical read is too light; agents must never **demote** below the
classifier's verdict.

**Tiny lane** — for changes that meet *all* of:
- Docs / comments / README / typo / dependency-bump only (`*.md`, `*.txt`, `*.lock`, `package.json`, `.gitignore`, etc.)
- ≤20 LOC and ≤2 files
- No state file, schema, UI, or CI/workflow touched

Tiny discipline:
- One claim message that doubles as the completion (the diff IS the evidence). No separate completion message.
- No capsule update, no review, no GO baton, no "Findings" block.
- Mechanical gates (guard-staged-scope.sh, ci-baseline.sh) still apply if any non-doc file ships.

**Lightweight lane** — for changes that meet *all* of:
- Doc-only (`*.md`, `*.txt`, README, runbook edits), OR single-file non-runtime change ≤20 LOC, OR comment-only edits, OR dependency bumps with no user-visible behaviour change, OR copy edits without UI changes
- No state file touched (no capsule, agent-todo, agent-handoff, current-state edits)
- No CI / workflow file touched
- No schema migration
- No user-visible UI rendering change

Lightweight discipline:
- One claim message + one completion message + capsule update (if the slice produced any state worth recording). The completion message may use the **receipt** message-class (see Comms Protocol) rather than a full Evidence block.
- Peer review is **optional**, not mandatory. Request one only if uncertain.
- No GO baton required — start when claimed.
- No "Findings I went looking for" block required on any review that does happen.
- Mechanical gates (guard-staged-scope.sh, ci-baseline.sh) still apply if any code change ships.

**Heavy lane** — anything that fails the lightweight criteria above (any state/CI/schema/UI touch, multi-file or >20 LOC code change, or >300 LOC). Default lane when in doubt.

Heavy discipline:
- Full protocol applies: peer review mandatory, "Findings I went looking for" block on every Review Result, GO baton on handoffs, capsule-before-comms invariant, mechanical gates.

**Lane is declared in the slice acceptance receipt:**

```text
Slice:
Lane: tiny | lightweight | heavy
First command:
First file target:
```

Downgrades are **forbidden** (catches "let me just slip this in" scope abuse): no heavy → lightweight, no lightweight → tiny mid-slice. Upgrades are **mandatory** the moment scope drifts past the current lane's criteria — the agent immediately re-issues the acceptance receipt at the higher lane and the fuller protocol kicks in. When unsure between two lanes, take the heavier one.

**Blast radius is a second axis (not the lane).** `scripts/classify-slice.sh`
also emits `blast_radius: high|low` — high = the change touches a
destructive/irreversible surface (state / schema / CI / UI) or is >300 LOC. This
is separate from the lane on purpose: a modest multi-file code edit is `heavy`
lane but `low` blast radius. Nothing today gates on it except one opt-in spike:

**Contested gear (opt-in spike, off by default).** When a bed sets
`[agents.oyakata].contested_debate = true`, a `blast_radius: high` slice that
reaches a review point runs Oya's **blind position-commitment** protocol: both
coders post a Position + Confidence to Oya *before either reads the other*, then
Oya releases both and opens reconciliation (forced-debate mechanism #1 — full
spec in the Oya prompt + `docs/positioning/benchmarks/collaboration-improvements-forced-debate.md`).
Echo `Slice: <id>` on the blind-position posts and the resulting Review Results
so `scripts/comms-metrics.py` can group turns and score
`single_exchange_contested_rate`. When the flag is off (the default), nothing
changes — plain heavy-lane review applies.

### Before starting a slice

1. Confirm the implementation plan is approved
2. Confirm the slice exists on the task board with your name on it
3. Read recent entries in the comms file
4. Confirm no file overlap with the other agent's active slice
5. **Scan the slice's surfaces.** Read the files and adjacent modules the slice will touch *before* writing. The codebase is the authority — your prior assumptions are not. If a slice's file surface contradicts what the plan implies, raise a Blocker rather than implementing against the wrong mental model. Read-before-you-write is not an aspiration; it is the floor.
6. Reply with a slice acceptance receipt before broader narrative status:

```text
Slice:
First command:
First file target:
State: claimed | started | blocked
```

If the first concrete action has not yet occurred, State must be `claimed`.

**Baseline-evidence (when restoring a judgement-carrying surface).** If the slice *restores* a value whose correct state is a prior decision (sizing, copy, payments, schema, API shape, etc.), add to the receipt:

```text
Baseline-evidence:
- Accepted state: <the value being restored>
- Source of truth: <audit doc path:line | locked-decision row | committed screenshot | accepted SHA>
- Last accepted commit: <SHA + date>
```

If the slice intends **new** behaviour rather than restoration, write `Baseline-evidence: NEW_BEHAVIOR (Lead-approved at <comms-ref or capsule-line>)` instead. This forces the accepted baseline to be named *before* the work, so review (the Accepted-baseline check) has something to verify against.

**Visual-proof (when the slice changes rendered output).** If the intent involves visual density, typography, layout, rendering, or a screen budget, the slice cannot move `started → completed` without:

```text
Visual-proof:
- Method: committed-screenshot | device-photo | <project visual tool>
- Artifact path: <path to the artifact captured AFTER the patch>
- Captured against commit: <SHA>
```

"Tests pass" and "build green" are not sufficient validation for a visual slice — *"tests pass" ≠ "visual contract preserved."*

### During execution

1. Work only inside the approved slice scope
2. Avoid file overlap with the other agent — if you discover overlap, raise it immediately
3. If scope needs to change materially, stop and sync before proceeding
4. Do not describe intended edits as current work
5. A slice is not considered in progress until the first concrete action has occurred
6. The first step of execution must be one of:
   - inspect a relevant file or path (still `claimed` until you act on it)
   - create or edit a file
   - run a relevant command
7. Only send a comms update when there is a concrete delta: patch applied, validation result, blocker, review request, or decision
8. If blocked by permissions, sandbox limits, missing dependency, missing context, or approval requirement, state the blocker explicitly and stop

### No silent idle

Approval of the prior slice is authority to begin the next owned slice in the same approved wave. A status update or review acknowledgement is **not** a stop condition by itself.

If 10+ minutes pass on the same task without a code or doc change, validation action, or named blocker, you are drifting — resume execution or surface the real blocker.

*"About to start"* is failure. Either work has begun with file evidence, or there is a named blocker.

### After completing a slice

1. Run the defined validation for this slice
2. Update the task board
3. Update the current-state capsule (capsule-before-comms invariant)
4. Write a handoff entry in `docs/agents/agent-handoff.md` (including the `Failure modes this cycle taught` block — see [Handoff Expectations](#handoff-expectations))
5. Send a `Review Request` via comms
6. Wait for review result before pushing or starting the next slice

### Review-handoff is part of completion

If your slice reaches the agreed review threshold, send the review request immediately.

Review-ready means:
- required files exist
- required validation passed
- dependent contract is satisfied
- no active blocker remains

When review-ready is true:
- do not keep exploring
- do not keep polishing
- do not stop at a status update
- send the review request in the same turn unless a named blocker exists

If you do not send the review request, you must state the blocker explicitly. *"About to send"*, *"was going to send"*, or *"stopped at the check"* are not valid end states.

---

## Review Pattern

Every meaningful slice goes through:

1. Implementation
2. Validation — all checks defined in the implementation plan
3. **Peer code review** — the reviewing agent reads the actual changed files, not just the description
4. Decision: proceed, revise, split follow-up work, or update docs

**Peer review is mandatory before push, not optional.** Green tests and a clean type-check are necessary but not sufficient.

Review means: open the files, read the diff, verify it matches the spec, flag anything that does not. It does not mean confirming the build passed.

A review result must be explicit: **approved**, **changes requested** (with specifics), or **findings** (with file:line references). *"Looks fine"* is not a review result.

### "Findings I went looking for" block (mandatory)

Every Review Result message MUST include a `Findings I went looking for:` block listing at minimum **three specific defect classes** the reviewer actively probed for. Each line names the class and a one-line outcome: `found` / `not found` / `N/A and why`.

```
Findings I went looking for:
- off-by-one in pagination cursor: not found — checked cursor.ts:42, offset arithmetic uses inclusive bounds
- missing null-guard on user_id: found — src/api/widget.ts:97 dereferences without check (fix below)
- stale fixture references in tests: N/A — no test files in slice surface
```

Reviews without this block are non-compliant — same standing as a missing proof block on a `spawned` claim. The block forces the reviewer to demonstrate the scepticism rather than rubber-stamp.

### Verification-anchored verdicts

The Findings block proves the reviewer *probed*. Two further requirements prove the *verdict* is anchored to evidence, not to vocabulary — they close the failure mode where an agent types "100% confident" without having verified anything. (Both were forged downstream from a real escape: a confidence rule that "failed within 22 hours through vocabulary adoption without a verification anchor.")

**Accepted-baseline.** For any slice touching a **judgement-carrying surface** — a value whose *correct* state is a prior decision, not whatever the diff says (sizing / typography / layout, copy / voice / tone, payments / entitlement / routing, schema / migration contracts, API shape, app-store metadata) — the reviewer must independently state the **accepted prior value AND its source-of-truth artifact** (an audit doc, a locked-decision row, a committed screenshot, or a git SHA). *"Matches the diff"* is not an answer: the diff is the thing under review, not the baseline. The Findings block references the artifact, not the implementer's narrative.

**Confidence-backed-by.** A `100% confident` / `approved` verdict is non-compliant without a `Confidence-backed-by:` line citing **at least one concrete artifact**:

```text
100% confident — <one sentence why>
Confidence-backed-by:
- <a passing test name + assertion (e.g. budget.test.ts:142)>
- <a committed screenshot / artifact path>
- <the git SHA that produced the verified state>
- <a specific file:line range the reviewer read in full>
```

The confidence verdict is a closing *claim*, not a closing *token*. A verdict with no artifact behind it is `NOT confident` by default.

**Mechanism:** peer review refuses a Review Result that asserts confidence on a judgement-carrying surface without both the Accepted-baseline reference and a Confidence-backed-by citation — same standing as a missing Findings block. A project can make this non-bypassable with a `commit-msg` gate that checks a `Baseline:` line against a glob of its judgement-carrying paths (see the project's own gates); the discipline holds with or without the gate.

### Spot-check on rubber-stamps

If a review returns `approved` with zero findings on a slice with >50 LOC changed or >3 files touched, a **third party** (not the author, not the reviewer) performs a five-minute spot-check before push. Approval is provisional until the spot-check posts an explicit confirmation message.

This catches the failure mode where Reviewer signs off on Author's work without actually opening the diff. The third party only has to read 50 LOC.

### Bug-path test gate

Every bugfix's regression test MUST fail against the *old* code. If the test passes against both old and new, it proves nothing — reviewer rejects.

The reviewer names the exact old failure the test would catch — a regression test without a named failure is unverified. *"This test would have caught the bug"* is not enough; *"This test asserts X; the old code returned Y; therefore the test would have tripped"* is.

### Domain-model review gate

When reviewing work that touches domain entity surfaces (CRUD pages, admin interfaces, API routes for domain objects), verify:

- Actions are on the correct entity level (e.g. a child-entity action is not placed on the parent surface)
- Labels and terminology match the canonical data model, not legacy code
- No action is duplicated across entity surfaces
- Lifecycle semantics are correct (e.g. deleting a parent does not cascade-delete children that have independent identity)

This gate exists because pipeline redesigns can pass a code-quality review while the product logic is wrong.

### Bulk migration review checklist

When reviewing bulk changes (pattern migrations, mass refactors):

- Identify the canonical reference/pilot implementation before reviewing
- Spot-check at least 3 migrated instances against the pilot (pattern, exports, signatures)
- Verify the migrated pattern matches the pilot, not pre-existing (possibly wrong) code
- Check that test files follow the same updated contract

### Claim hygiene

Every diagnosis in comms, commit messages, handoffs, or retro docs is labelled as one of:

- **`symptom`** — the observable problem ("page renders empty")
- **`hypothesis`** — a proposed explanation that has NOT yet been proven ("the migration gap is the root cause")
- **`confirmed root cause`** — evidence has closed the loop. Evidence type MUST be named: `query`, `prod diagnostic`, `failing test`, `screenshot comparison`, or `reproduction`

If later evidence contradicts a confirmed claim, the handoff or incident retro MUST update the narrative — the incorrect claim is explicitly labelled as a wrong assumption. Do not paper over an incorrect diagnosis with a follow-up fix and call it done.

### Three-consecutive-patches circuit breaker

If the same feature requires 3+ consecutive production fixes, **STOP**. Do a full investigation. List all remaining issues. Fix them together. Do not continue the patch-push-test-fail loop. Production is not a debugging environment; the human lead is not the integration test.

Do not roll from one completed slice into the next if a review or design decision is still outstanding.

---

## Mechanical Gates

Mechanical gates run as scripts. Disciplinary gates rely on memory. The system trusts mechanisms over discipline.

### Pre-commit: staged-scope guard

Before every `git commit`, run:

```bash
scripts/guard-staged-scope.sh <allowed-path> [<allowed-path>...]
```

The script prints `git diff --cached --stat` and fails if:
- no files are staged
- extra files are staged outside the declared allowlist
- any allowlisted path is missing from the staged set

The allowlist must match the file list that was peer-reviewed.

This is NOT optional. A shared-worktree staging race can bundle two separate approved work items under one commit message if the stage-list-before-commit step is disciplinary instead of mechanical. The guard closes that loop.

A reference implementation ships with musubi at `scripts/guard-staged-scope.sh`.

### Pre-push: CI baseline check

Before requesting `@LEAD`'s push approval, every agent MUST query the CI baseline status of `main` and surface it verbatim in the push-approval comms message.

This is a pre-PUSH gate distinct from the pre-COMMIT staged-scope guard. Both run mechanically; both are required.

**Mechanism:**
- Run (count): `gh run list --workflow=<your-ci.yml> --branch main --limit 5 --json conclusion --jq '[.[] | .conclusion] | map(select(. == "success")) | length'`
- Run (detail, MANDATORY when count = 0): `gh run list --workflow=<your-ci.yml> --branch main --limit 5 --json headSha,conclusion,createdAt --jq '.[] | "\(.headSha[0:8]) \(if .conclusion == "" then "in_progress" else .conclusion end) \(.createdAt[0:10])"'`
- Expect: count integer ≥ 1. The integer goes into the push-approval comms message under a `**CI baseline status:** N/5 of last 5 main CI runs succeeded` header.
- Fail if: count = 0 — agent MUST run the detail command, paste its 5-line output VERBATIM, append a one-line reason ("This push is either a CI hotfix that should fix it, or @LEAD is explicitly accepting a stale-baseline push."), and wait for explicit `@LEAD` ack before pushing.

Why pre-push and not a scheduled watchdog: the actual failure mode is *"we keep pushing through red"*, which a scheduled job can't fix. Pre-push surfaces the staleness AT THE EXACT MOMENT `@LEAD` is being asked to approve a push.

A reference implementation ships with musubi at `scripts/ci-baseline.sh`.

---

## Capability Registry

The project keeps a written record of what the agents can actually reach and how:
`docs/agents/capability-registry.md` (scaffold: `templates/CAPABILITY-REGISTRY.md`).
It lists each agent's strengths and browser path, and the connector for each
external service (RevenueCat, cloud APIs, the app stores).

### Unknown is not impossible

Before telling the operator an external action **cannot** be done — enable an API,
flip a billing setting, drive a browser, create a store product — check the
capability registry first. The honest outcomes are: use the listed path; route to
the sibling agent that's better at it (name which); or, if there is genuinely no
known path, say so explicitly *and append the answer to the registry once found*.

A flat *"I can't, do it manually"* with no check against the registry is a defect:
it makes the operator re-explain the same connector every cycle. Prefer an
API/CLI/MCP over a browser login (browser logins land in a fresh profile with no
extensions or sessions — the slow, re-auth-every-time path).

This rule exists because an orchestrator repeatedly refused service tasks it had a
path for (e.g. a billing provider's official MCP) and lost operator hours to
manual workarounds that were never necessary.

**Mechanism:**
- Run: `test -f docs/agents/capability-registry.md && echo present` before declaring any external action impossible
- Expect: the registry exists and was consulted; the response names the path, the routed agent, or an explicit "no known path — appending"
- Fail if: an agent declares a task impossible/manual-only without consulting the registry, or finds a new connector and does not record it

---

## Ship Definition of Done

A release is not done because the code is done. The completeness gate for "is this
actually shipped?" lives at `docs/agents/ship-dod.md` (scaffold:
`templates/SHIP-DOD.md`). It is the counter to the audit failure mode where every
small code detail gets flagged but the ONE fundamental missing thing does not —
no product created in the store, a required API never enabled.

Audits are good at present-vs-spec and blind to ABSENT. The ship-DoD makes the
absent things explicit, line by line. At any "ready to ship / it's live" claim,
each line reads DONE or N/A-with-reason; a silent line is an open blocker even
when every test passes.

This rule exists because an app was declared shipped with no purchasable product
created in the store — and nothing in the cycle ever raised it, because no check
was looking for the *absence*.

**Mechanism:**
- Run: at the ship claim, paste `docs/agents/ship-dod.md` into comms with every line marked DONE or N/A-<reason>
- Expect: zero unmarked lines; every paid-tier store-product line explicitly addressed
- Fail if: a release is declared done with any line silent — especially a store-product line

---

## Rule Quality

### Mechanism block on every new rule

Every new rule (in this runbook, project-level CLAUDE.md / AGENTS.md, or memory feedback files) MUST include a `Mechanism:` block naming the exact command, expected output, and observable failure condition. Vague verbs (*"verify"*, *"review"*, *"ensure"*, *"confirm"*) without a mechanism are not enforceable.

**Mechanism block format:**

```text
Mechanism:
- Run: <exact command>
- Expect: <exact output / response / file artefact>
- Fail if: <observable condition>
```

This rule exists because rules of the form *"verify e2e"* get reinterpreted as *"tests passed"* and production goes down. Naming the mechanism makes the rule mechanically checkable.

**Mechanism (this rule):**
- Run: `grep -B1 "^- Run: " docs/agents/AGENT_COLLAB_RUNBOOK.md CLAUDE.md AGENTS.md`
- Expect: rules of substance carry a `Mechanism:` block
- Fail if: a substantive new rule lands without one

**Existing rules should be retrofitted opportunistically as cycles touch them.** Do not block work to backfill mechanisms across the whole document — but every time a rule is invoked, if it lacks a mechanism, add one.

---

## Preserve Deliberate State

The current state of the codebase is the result of decisions, many of them not written down. When a change in flight requires touching code that was set deliberately by a previous commit, you do not get to silently normalise it.

Before changing any value that carries judgement (text size, copy register, voice or tone, colour, layout choice, API shape, naming convention, error message wording, default behaviour), do these in order:

1. Run `git log -p -- <path>` to see why the current value is what it is.
2. If a recent commit set this value with a stated reason, treat it as locked unless a new decision overrides it.
3. If the value seems wrong but the change is outside your slice scope, raise it as a Blocker or a follow-up — do not fix it under the cover of an unrelated slice.
4. Ask explicitly when uncertain. Silent normalisation reverses other people's decisions and reintroduces fixed bugs.

*"While I'm in here"* refactors are forbidden. Voice, tone, sizing, and copy-register changes ARE refactors even when the diff is small. If a slice does not name a stylistic change in scope, do not make one.

### LOCKED_DECISIONS.md

If the project maintains `docs/agents/LOCKED_DECISIONS.md`, it is read as part of the [Startup and Recovery](#startup-and-recovery) checklist (codebase orientation step) AND scanned again before any slice that touches the surface it covers. The doc captures deliberate choices that look unusual and must not be silently reverted; it is project-owned and append-only. Each entry names: the decision, the date, the commit it was set in, and the rationale.

When in doubt, add to LOCKED_DECISIONS.md rather than relying on memory or assuming the next agent will read git log.

### Mechanism

- Run: `git log --since="30 days ago" -p -- <path-being-changed>` before modifying any judgement-carrying value
- Expect: any commit that explicitly sets the value (e.g. `fix(typography): bump body to 18px for accessibility`) marks the value as locked
- Fail if: an agent silently flips a value that a recent commit deliberately set, without raising the change as a Blocker or naming the override decision

### This rule exists because

- Text size was reduced after a deliberate increase set in an earlier cycle.
- Voice was silently swapped from 1st person to 3rd person without asking.

Both bugs had been fixed before; both got reintroduced because the agent normalised against its default heuristic, not the codebase's prior decision. The rule is the gate. The mechanism is the check. LOCKED_DECISIONS.md is the registry. Use all three.

---

## Final Gate

Before push to `main` on any multi-slice effort, confirm all of these explicitly in the comms file:

- [ ] All slices complete
- [ ] All slices validated per their defined checks
- [ ] Peer code review complete — both agents have read each other's changed files
- [ ] No outstanding review findings
- [ ] Doc sync complete — implementation plan, task board, capsule, and handoff are current
- [ ] Pre-commit staged-scope guard passed (mechanism)
- [ ] Pre-push CI baseline status surfaced verbatim (mechanism)
- [ ] Comms cycle archived or scheduled for archive
- [ ] If this push ships a release (not just code): Ship Definition of Done walked — every line DONE or N/A-with-reason (see `docs/agents/ship-dod.md`)
- [ ] Push to `main` explicitly approved by `@LEAD`

Do not self-approve a push. The human lead closes the gate.

---

## Handoff Expectations

Use `docs/agents/agent-handoff.md` after any slice that another agent or a future session will build on.

Each entry must follow this structure:

```markdown
## [Slice name] — [Agent] — [Date]

### What changed
[Concrete description — not "improved the widget" but "added pagination
to GET /api/widgets, changed response envelope shape to include cursor"]

### Files touched
- path/to/file.ts
- path/to/other.ts

### Validation run
- Type checks: pass
- Tests: 24 passed, 0 failed
- Build: pass
- Production-start smoke (if applicable): pass
- [any other defined checks]: [result]

### Residual risks or open questions
[Anything the next agent should know before proceeding]

### Failure modes this cycle taught
[Either: a defect class encountered + a proposed gate or rule to prevent recurrence,
 OR the explicit string: "none new — gates worked."]

### Peer-review escapes
[Defects @LEAD identified AFTER both agents reviewed and approved this cycle —
 the review's own miss-rate. "none — no escapes detected" if clean.
 Track a rolling count; N escapes in a rolling window auto-escalate to mandatory
 Lead review of every approval for the next cycle.]
Rolling escape count: <integer>
Last escape: <date + one-line description, OR "none">

### Next step
[Explicit instruction for the other agent or for @LEAD]
```

A handoff that says *"done, looks good"* is not a handoff. The `Failure modes this cycle taught` and `Peer-review escapes` blocks are mandatory — the first stops the system forgetting a defect class; the second measures how often the pair's own review let one through (the pattern came from a real escape where both agents approved a regression that @LEAD caught visually).

---

## Startup and Recovery

### Normal startup — the warm-start checklist

On session start, each agent loads context in this order:

1. **Project rules** — `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex) — usually auto-loaded by the harness
2. **Peer's project rules** — read the other tool's rules file too, so you know what your peer is operating under
3. **This runbook** — `docs/agents/AGENT_COLLAB_RUNBOOK.md`
4. **Operating model** — `docs/agents/PAIR_OPERATING_MODEL.md` (the *why* behind the rules)
5. **Active comms file** — `docs/agents/comms/active.txt`. If the file is empty because the orchestrator rotated it on startup, also read the most recent file in `docs/agents/archive/` matching `agent_comms_*.txt` for the prior session's transcript. The structured handoff and capsule capture intent; the archive captures texture.
6. **Capsule** — `docs/agents/current-state.md`
7. **Task board** — `docs/agents/agent-todo.md` (current-state block first, then active cycle)
8. **Latest handoff entry** — `docs/agents/agent-handoff.md`
9. **Ground truth** — `git status --short --branch`
10. **Codebase orientation** — the `docs/agents/` files cover collaboration protocol; the rest of the repo carries the actual conventions you must respect. Scan, don't deep-read:
    - The repo `README.md` (project intent, entry points)
    - Stack manifest: `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Gemfile` (whichever exists) — what stack and what scripts
    - Language and linter/formatter config: `tsconfig.json`, `.eslintrc*`, `ruff.toml`, `.prettierrc`, etc. — strictness and style rules already in force
    - `docs/` directory listing — note any `architecture/`, `adr/`, or `decisions/` subdirectory; read its index plus the most recent 2–3 ADRs to learn active constraints
    - `CONTRIBUTING.md` if present (workflow expectations)
    - One sample file from the project's test directory (testing convention)
    - `docs/agents/LOCKED_DECISIONS.md` if the project maintains one — deliberate choices that look unusual and must not be silently reverted (see [Preserve Deliberate State](#preserve-deliberate-state))
    
    The point is to understand: what stack applies, what architectural decisions are locked, what the testing pattern is, and what already exists so you do not duplicate or contradict it. You are not writing code yet — you are learning what the codebase has already decided.
12. **Active slice docs only** — relevant `docs/improvements/` / `docs/implementations/` files for the assigned slice (skip historical docs)
13. **Memory** — agent-specific memory as advisory context only, never authority. See [Memory Discipline](#memory-discipline)

After reading, restate: what was the last thing completed, what is in progress, and what is next. Use only the defined execution states (`claimed`, `started`, `blocked`, `spawned`, `confirmed_running`, `completed`).

A single trigger word makes this deterministic — musubi ships a `/open-sesame` slash command template that runs the checklist end-to-end. Without it, every fresh session re-derives state ad-hoc.

### Recovery from a stale or confused state

If coordination has gone muddy:

1. Stop starting new work immediately
2. Read the implementation plan for the active cycle
3. Read the task board and capsule
4. Read the last 20 entries in the comms file
5. Read the most recent handoff
6. Diff the claimed state against actual files on disk
7. Restate what is actually done, what is in progress, and what is next using only the six execution states
8. Resume only when the active slice per agent is unambiguous

### Restart continuation rule

When resuming after a crash, reboot, or model restart, do not treat every review boundary or status update as a stop condition.

- If the next owned slice is already unblocked by the approved plan, start it without waiting for `@LEAD` to repeat *"go"*
- If a review clears and the next dependency is satisfied, continue automatically
- Only stop and wait when there is a real blocker:
  - ownership conflict
  - missing approval for destructive or external action
  - unclear plan branch
  - failed validation that needs a human decision
- Treat the approved slice plan as standing authority to continue execution until the current wave is actually blocked

### Ground truth reset

If the comms file, task board, capsule, or handoff are contradictory or clearly wrong, do not attempt to reconcile them through further agent turns. Call a ground truth reset: `@LEAD` reads the actual files on disk, confirms what is done and what is not, and restates the current position from scratch. Start the next cycle from that clean baseline.

A corrupted coordination state is worse than starting over. Start over.

---

## Practical Defaults

- Improvement discussions → `docs/improvements/`
- Implementation detail → `docs/implementations/`
- Task ownership → `docs/agents/agent-todo.md`
- Live coordination state → `docs/agents/current-state.md`
- Durable execution summaries → `docs/agents/agent-handoff.md`
- Agent coordination → `docs/agents/comms/active.txt`
- Completed cycle logs → `docs/agents/archive/`

If a file is becoming a soup of plan, debate, execution, and status updates, split it back into the right layers. Entropy is the default. Organisation is the discipline.

---

## Reference (load on demand)

The detail below lives in [`AGENT_COLLAB_RUNBOOK_REFERENCE.md`](AGENT_COLLAB_RUNBOOK_REFERENCE.md), which is **not** auto-loaded into your context. Each line here carries the operative default so you have what you need every cycle; **read the linked section when a slice actually touches that topic.**

- **Branching** — default is **direct to `main` with a human gate**; feature-branch-per-slice is the documented alternative. → [full strategy](AGENT_COLLAB_RUNBOOK_REFERENCE.md#branching-strategy)
- **Validation Standards** — every plan defines validation **per slice**; the minimum bar is the relevant validation actually run plus a clean full build/tests before push — "validation relevant to the change" with nothing named is not a standard. → [full standards](AGENT_COLLAB_RUNBOOK_REFERENCE.md#validation-standards)
- **Planning Chain** — work moves in order: improvement idea → implementation plan → slice → review → merge. → [full chain](AGENT_COLLAB_RUNBOOK_REFERENCE.md#planning-chain)
- **Escalation Rules** — escalate to `@LEAD` for product decisions, multi-valid-option calls, and conflicts; never resolve a cross-agent conflict unilaterally. → [full rules](AGENT_COLLAB_RUNBOOK_REFERENCE.md#escalation-rules)
- **Error and Drift Handling** — on detecting drift, **stop and re-ground from the canonical files** (capsule, comms, `git status`) before continuing; the ground-truth reset procedure is in the reference. → [full procedure](AGENT_COLLAB_RUNBOOK_REFERENCE.md#error-and-drift-handling)
- **Memory Discipline** — memory is **advisory, never authoritative**; verify any memory claim about active state (HEAD, dirty files, ownership, next steps) against the canonical files. → [full discipline](AGENT_COLLAB_RUNBOOK_REFERENCE.md#memory-discipline)
- **Tone** — personality is welcome, but only **after state is clear**; banter never replaces evidence. → [full note](AGENT_COLLAB_RUNBOOK_REFERENCE.md#tone)
- **Definitions** — precise glossary (slice, capsule, GO baton, …); consult when a term's exact meaning matters. → [glossary](AGENT_COLLAB_RUNBOOK_REFERENCE.md#definitions)
- **Changelog** — the runbook's own version history now lives in the reference. → [changelog](AGENT_COLLAB_RUNBOOK_REFERENCE.md#changelog)

---

