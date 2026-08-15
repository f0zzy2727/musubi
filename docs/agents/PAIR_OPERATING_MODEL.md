<!-- musubi-managed: this file is updated by `bootstrap.sh` from the musubi repo. To fork it, delete this marker; the bootstrap will then warn and diff instead of overwriting. -->

# The Two-Agent Pattern

**Audience:** another agent pair adopting this operating model.
**Status:** field-tested. Distilled from running daily on a multi-tenant production codebase.
**Companion to:** `AGENT_COLLAB_RUNBOOK.md` (the normative protocol). This doc is the *why*; the runbook is the *what*.

---

## What this is

A working pattern between one human lead and two AI coding agents — one in each terminal pane — collaborating on a shared codebase with shared commit access. It has been running daily for months on real production codebases, surviving pane crashes, model swaps, parallel cycles, and the inevitable drift of multi-agent coordination.

The pattern is opinionated. It encodes specific lessons from real incidents: rules that didn't work, gates that did, classes of failure that recurred until they were structurally prevented. Where you see *"every X must Y"*, there is usually a postmortem behind it.

The pattern is **tool-agnostic in principle, tool-specific in practice.** The principles transfer to any pair of capable coding agents. The exact filenames, message templates, and trigger words are illustrative; what matters is having them, not having ours.

---

## How to load this

For a receiving pair (one human lead + two AI agents):

1. **Both agents read this doc end-to-end** before adopting anything. The pattern is a system; cherry-picking parts gives you the failure modes without the protections.
2. **The human lead picks names, paths, and tools.** Use musubi's defaults (Opus / Coda) or pick your own — the orchestrator reads names from `musubi.toml`.
3. **Each agent gets a project-rules file** at the repo root that the agent's harness auto-loads (Claude Code reads `CLAUDE.md`; Codex reads `AGENTS.md`). Both files must have parity on rules — different framings, same content.
4. **Create your durable state surface** in the repo. The musubi bootstrap installs all of these for you:
   - **Collaboration runbook** (`docs/agents/AGENT_COLLAB_RUNBOOK.md`) — protocol authority: message format, state vocabulary, slice lifecycle.
   - **Current-state capsule** (`docs/agents/current-state.md`) — single durable source of truth for live coordination state.
   - **Handoff log** (`docs/agents/agent-handoff.md`) — per-slice writeup template.
   - **Comms file path** (default: `docs/agents/comms/active.txt`, gitignored).
   - **Archive directory** (`docs/agents/archive/`) — committed copies of closed-cycle comms logs.
5. **Pick a single resume trigger word** that warms a fresh session deterministically. Musubi ships `/open-sesame` as a slash-command template that runs the runbook's startup checklist end-to-end.
6. **Run a small first cycle** — a doc edit, a single-file refactor — purely to exercise the pattern before applying it to anything that matters. The first cycle is for the protocol, not the output.

A receiving pair that does steps 1–6 in order, in one sitting, before starting real work, will save themselves the months of tuning that produced this doc.

---

## 1. The shape of the system

**One human lead. Two asymmetric agents. Shared commit access. No agent pushes without explicit human approval.**

The human owns priorities, scope, acceptance, and every push. The agents are peers with commit authority but no autonomous deploy. The human is a *gate*, not a *relay* — they are not in the loop on every message; the agents resolve coordination themselves and surface decisions, blockers, and push approvals.

**Asymmetry between agents is a feature.**

| Role | Default disposition |
|---|---|
| Agent A (e.g. Opus / Claude Code) | Product framing, design critique, broad codebase reasoning, cross-system synthesis. |
| Agent B (e.g. Coda / Codex CLI) | Surgical patches, integration skeptic, "suspicious adult in the room" when a summary is too cheerful. |

The friction between the two is the value. A pair with identical dispositions cross-reviews each other's work as a formality. A pair where one is paid to find bugs in the other's optimism catches real bugs in real review rounds.

---

## 2. The communication contract

### One file is authority. The relay is just an alert.

Active cycle communication goes to a single append-only file (default: `docs/agents/comms/active.txt`). The musubi orchestrator forwards messages between panes when it detects a turn marker. The pane relay is the *doorbell*; the file is the *conversation*. When a message arrives, read the whole file, not the relayed snippet.

### Every message has shape.

```
---------------------------------------------------
[@AGENT] [YYYY-MM-DD] [HH:MM UTC]
Type: Update | Review Request | Review Result | Decision | Blocker
Subject: one-line subject
Reply required: yes | no | only-if-blocker
GO: yes | no
GO owner: <agent name> | both | none
GO action: <first concrete action, or none>

@<recipient>

Action:
[exact command run, exact edit made, or "claimed" if no concrete execution]

Evidence:
[file paths, diff summary, command output, validation summary, PID, or "none"]

Result:
[claimed | started | blocked | spawned | confirmed_running | completed | pass | fail]

Next:
[next concrete action only]

<OVER>
```

**`<OVER>` on its own line is the turn marker.** No `<OVER>` means still composing — do not relay half-finished messages.

**Reply discipline beats orchestrator nags.** When `Reply required: no`, you do not append a reply, *even if the relay layer's default prompt says to reply.* Agent judgment follows the field. This rule exists because relay prompts are generic and the field is specific. The exception is explicit human direction: if the human lead specifically asks for a reply on a message marked `Reply required: no`, the human's direction wins.

**`GO: yes` is an execution baton.** It names an owner, a file surface, and a first concrete action. The named owner begins immediately unless a real blocker exists — they do not wait for peer acknowledgement. The peer replies only for overlap, blocker, or safety issue.

### State vocabulary is enforced

Six words describe execution state, and only six:

- `claimed` — slice assigned. No execution implied.
- `started` — concrete action has occurred (file edited, command run, test executed).
- `blocked` — cannot proceed because of a named constraint.
- `spawned` — a real child execution context exists. Requires a proof block (PID, terminal, worktree).
- `confirmed_running` — previously spawned context still exists when re-checked. Requires fresh evidence.
- `completed` — artifact exists and validation/review threshold met.

For `Review Result` and validation messages, the `Result` field carries a verdict (`pass` or `fail`) instead of an execution state — same field, different content type per message type.

**Forbidden phrases unless paired with evidence:** *"about to"*, *"prepping"*, *"gearing up"*, *"in the middle of"*, *"working on"*, *"handling"*, *"on disk"*.

Status inflation is a protocol violation, not a stylistic choice. Reading files is exploration, not `started`. A completed one-shot command is not evidence of a running job. When uncertain, report the lower state — `claimed` over `started`, `started` over `spawned`, `spawned` over `confirmed_running` unless fresh evidence exists.

### Send a message when

Ownership changes · a slice lands and is review-ready · validation completes (pass or fail) · a real blocker appears · a decision must be recorded · a `GO: yes` handoff assigns work.

### Do not send a message to

Acknowledge receipt unless silence creates real ambiguity · restate intent without a concrete artifact behind it · report progress that is not a delta. **Communication is support work, not the work itself.**

---

## 3. The work unit

**A slice, not a task.**

A slice has all of:

- Named owner.
- Entry condition (what must be true to start).
- Exit condition (what must be true to call it done).
- Bounded file surface.
- Explicit validation step.
- A row in a launch matrix indicating what it can run alongside and what it must sequence after.

If you cannot write that row, the slice is not ready to execute. The launch matrix is a hard gate, not paperwork.

**Default to parallel.** Slices run in parallel unless the matrix explicitly marks a dependency or file overlap. If dependency is unclear, mark sequential — false parallelism is worse than conservative sequencing.

**Intra-slice parallelism is expected, not a bonus.** Implementation plans break each slice into sub-tasks, marking which are independent. Independent sub-tasks run concurrently (parallel tool calls, sub-agents, worktrees). Each sub-task validates its own output before the slice's overall validation runs.

**Branching:** direct-to-main with a human gate is the default. Feature branches only when the work is genuinely risky or two slices touch overlapping files. Conflicts go to the human, never resolved unilaterally.

---

## 4. The review contract

**Peer review is mandatory before push. Green tests are necessary, not sufficient.**

Review means: open the diff, read the actual code, verify it matches the spec, flag specifics with file references. *"Looks fine"* is not a review result. A result must be **approved**, **changes requested** (with specifics), or **findings** (with file:line).

**Bug-path test gate.** Every bugfix's regression test must fail against the *old* code. If the test passes against both old and new, it proves nothing — reviewer rejects. A test that doesn't exercise the fixed branch is decoration. The reviewer names the exact old failure the test would catch — a regression test without a named failure is unverified.

**Cross-review actually finds bugs.** In one representative ~3.5h cycle on a production codebase: 4 distinct real bugs caught by review (a budget calculation that ignored a suffix; an aesthetic implication of an early design pivot; stale story descriptions contradicting the final implementation; a sub-pixel overflow only visible in a real browser). Every one of these would have shipped without the review pass. The review pass is where most of the quality lives.

**Entity-model review gate** (for any change touching domain objects). Verify: actions are on the correct entity level; labels match the canonical data model not legacy code; no action is duplicated across entity surfaces; lifecycle semantics are correct (deletion, cascading, ownership). This gate exists because pipeline redesigns can pass a code-quality review while the product logic is wrong.

**Claim hygiene.** Every diagnosis is labelled `symptom` / `hypothesis` / `confirmed root cause`. Confirmed root causes name evidence type (`query`, `prod diagnostic`, `failing test`, `screenshot comparison`, `reproduction`). If later evidence contradicts a confirmed claim, the handoff or retro updates the narrative — the incorrect claim is explicitly labelled as a wrong assumption.

---

## 5. Durable state

**Three files survive crashes and reboots.**

| File | Purpose |
|---|---|
| `docs/agents/AGENT_COLLAB_RUNBOOK.md` | Protocol authority. Read first on every session resume. |
| `docs/agents/current-state.md` | Live capsule — current cycle, active slices, owners, blocked items, last verified HEAD. Updated *before* the corresponding comms message, not after. |
| `docs/agents/agent-handoff.md` | Per-slice writeup with what changed, files touched, validation run, residual risks, **failure modes this cycle taught**, next step. |

Plus archived comms in `docs/agents/archive/` per closed cycle.

**The capsule is updated before the comms message it describes.** Sequence matters: capsule first, comms second. This means the comms message is *reporting* reality, not promising it. Inverting the order is one of the recurring drift modes, alongside status inflation and stale dirty-state assumptions.

**Memory is advisory, never authoritative.** Each agent has its own memory store. Both can read both. Any claim from memory about active state (HEAD, dirty files, ownership, validation) is verified against the canonical files before being repeated. Memory entries carry a `kind: rule | observation` and `verified_at: <date>` so staleness is visible. A 30+ day-old observation is verified against current state before reuse, or flagged as expired.

**One trigger word for warm starts.** A fresh session reads, in order: agent's project rules (usually auto-loaded by the harness) → peer's project rules → runbook → operating model → dev strategy → comms file → current-state capsule → latest handoff entry → ground truth (`git status`) → relevant active-slice docs → memory (advisory, last) → restate to user → ask. Memory goes last because it is point-in-time observation, not live ground truth. The trigger word makes this deterministic; without it, every fresh session re-derives state ad-hoc.

---

## 6. The gates that prevent regression

These are mechanical, not disciplinary. A discipline is a hope; a mechanism is a check.

**Mechanism block on every rule.**

```
Mechanism:
- Run: <exact command>
- Expect: <exact output>
- Fail if: <observable condition>
```

Vague verbs (`verify`, `ensure`, `confirm`) are unenforceable. Every rule names a command, expected output, and observable failure condition. This rule exists because rules of the form *"verify e2e"* get reinterpreted as *"tests passed"* — and production goes down.

**Detection slice per cycle.** Every substantive cycle ships at least one slice dedicated to *detection* — a new gate, a tightened rule, an audit, or a regression-test extension. A slice is observable; *"we'll be more careful next time"* is not. This breaks the recurring pattern of *ship green → user finds defect → add band-aid → repeat*.

**Mechanical pre-push gates.** Before any push to main:

- A **staged-scope guard** that fails if files outside the declared allowlist are staged. Musubi ships a reference at `scripts/guard-staged-scope.sh`.
- A **CI baseline check** that surfaces *"N of last 5 main CI runs succeeded"* verbatim in the push-approval message. If 0/5, the agent must paste the failing run details verbatim and wait for explicit human ack. Musubi ships a reference at `scripts/ci-baseline.sh`.
- A **production-start smoke** (build + serve + curl representative routes) for any change that touches route rendering, layouts, middleware, or runtime config. Catches runtime-only failures that compile cleanly.

**Patch-loop circuit breaker.** Three consecutive production fixes for the same feature → STOP. Full investigation, list every remaining issue, fix together. No using production as a debugger or the human as the integration test.

**Failure-mode capture is mandatory.** Every cycle handoff includes a `Failure modes this cycle taught` block: any new defect class encountered + a proposed gate or rule to prevent recurrence, or the explicit string *"none new — gates worked."* Without this, the system forgets.

---

## 7. The cultural pieces

**Tone matters but never replaces evidence.** Protocol serious, conversation human. Banter is welcome; banter that pads a false progress report is not. The work comes first, the personality lives around it. Wit at the expense of clarity is noise.

**The human owns priorities and closes gates.** No self-approving merges. Cycles close when the human says, not when it feels done. The Definition of Done is concrete and shared:

- Code changes with file-level evidence.
- **A test that has been SEEN TO FAIL without the fix.** Not "a test was added" —
  that phrasing was the loophole, and every defect shipped in the 2026-08-13/14
  window satisfied it. Break the fix (comment the line, restore the old branch),
  watch the test go red, put it back. If it stays green it is not a test of that
  behaviour, whatever it is called. Costs about a minute, and it is the single
  check that would have caught most of what reached an operator. It caught two
  flaws in the tests written the day this rule was added.
- **No source-text assertion standing in for behaviour.** A regex over a file
  proves a string is present. It cannot prove the code runs, runs on the right
  data, or renders anything — 1,930 lines of cockpit JS were "covered" that way
  and had never once been executed. Grep-assertions are fine for *structure*
  (declaration order, a literal that must stay absent) and must say so; behaviour
  is asserted by running it. See `test/helpers/cockpit-dom.mjs`.
- **Residual coverage stated where the test lives.** If a class cannot be tested at
  this layer — jsdom resolves no CSS custom properties, so nothing visual is
  provable there — write that down instead of leaving a check that passes for the
  wrong reason. A test that cannot fail is worse than a missing one, because it is
  counted as coverage.
- CI passes (lint, type-check, test, build).
- Production-start smoke (where applicable) passes.
- Docs updated (ADRs, backlogs, runbook entries).
- Residual risks listed explicitly.
- Handoff with `Failure modes this cycle taught` block.

**Confirm with the human only when:** no approved slice exists for either agent · state files conflict · file ownership is unclear or overlaps · the next action is destructive or external. Otherwise proceed with the slice acceptance receipt — routine context reloads do not require human re-confirmation.

**No silent idle.** Approval of the prior slice is authority to begin the next owned slice in the same approved wave. A status update or review acknowledgement is not a stop condition by itself. If 10+ minutes pass on the same task without a code or doc change, validation action, or named blocker, you are drifting — resume execution or surface the real blocker. *"About to start"* is failure; either work has begun with file evidence, or there is a named blocker.

---

## 8. Three things that make this actually work

If you adopt only three things from this doc:

1. **Evidence-shaped comms.** `Action / Evidence / Result / Next` makes lying about progress structurally awkward. You cannot fill the Evidence line with vibes.
2. **Durable state files updated before the comms message they describe.** The sequence is the invariant. Capsule first, message second. Inverting the order is one of the recurring drift modes.
3. **An asymmetric peer paid to be skeptical.** When the reviewer's job is to find bugs in the other agent's work, *"looks fine"* stops being a viable answer, and the bugs that would have shipped don't.

The rest is hygiene that keeps these three from rotting.

---

## 9. Adoption checklist

For a receiving pair, in order:

- [ ] Both agents read this doc end-to-end.
- [ ] Human lead chooses agent names (in `musubi.toml`), comms file path, and (optionally) a custom resume trigger word.
- [ ] Run `bootstrap.sh` from the musubi repo against the target project. This installs the runbook, this operating-model doc, the dev-strategy doc, capsule/handoff/todo templates, the staged-scope guard, the CI baseline check, the `/open-sesame` slash command template, and a managed block in CLAUDE.md / AGENTS.md that imports them all.
- [ ] Verify the managed block fired correctly: open CLAUDE.md / AGENTS.md and confirm the `<!-- musubi:start -->` ... `<!-- musubi:end -->` block is present and that the imports resolve.
- [ ] Implement at least one mechanical pre-push gate (the staged-scope guard is the cheapest first one — it ships ready to use).
- [ ] Run a small first cycle (one doc edit or one-file refactor) end-to-end through the pattern before applying it to anything real.
- [ ] After the first cycle, audit: did the message format hold? Did the capsule get updated before each comms message? Did review find anything? If any answer is no, fix the pattern before the next cycle.

---

## 10. Anti-patterns to avoid

- **Treating the comms file as chat.** Decisions belong in docs. Comms is for review, blockers, approvals, and coordination.
- **Self-approving merges.** The human gate is the gate. Removing it removes the protection.
- **Symmetric agents.** Two agents with the same disposition do not cross-review; they cross-validate. Asymmetry is the feature.
- **Adding rules without mechanisms.** A rule without a `Run / Expect / Fail if` block is a wish.
- **Treating memory as authority for active state.** Memory is point-in-time. Verify against canonical files first.
- **Skipping the first small cycle.** The first time you exercise the pattern on something that matters, you discover the pattern is wrong in three places. Discover it on something that does not matter.
- **Letting durable state files drift.** A stale capsule is worse than no capsule. If a slice transition does not also update the capsule, the transition is incomplete.
- **Continuing a patch loop.** Three consecutive production fixes for the same feature without stopping for a full investigation. Each individual patch feels small; the cumulative pattern uses production as a debugger and the human lead as the integration test. Stop after the third — full investigation, list every remaining issue, fix together.

---

## 11. Variations and adaptations

This pattern assumes:

- Two AI agents with comparable code-editing capability.
- One human lead present during work cycles.
- Both agents in adjacent terminal panes with the musubi orchestrator forwarding turn markers.
- A Git-based codebase with CI.

If your setup differs:

- **Three or more agents:** the launch matrix becomes load-bearing. Slice ownership and file-surface boundaries get strict. Comms volume grows quadratically — consider per-pair channels.
- **Async (no human present):** the human gate becomes a queued approval. The agents must be more conservative about destructive actions and surface a daily summary.
- **No external orchestrator:** the human relays manually. Increase batch size of messages — fewer round-trips, more per round.
- **Agents on different tools:** preserve the message format and state vocabulary across tools. Tool-specific quirks belong in each agent's project-rules file (CLAUDE.md / AGENTS.md), not in shared protocol docs.

The principles do not change: evidence-shaped comms, durable state before messages, asymmetric review, mechanical gates.

---

## Provenance

This pattern emerged from running two AI coding agents (Claude Code and Codex CLI) plus one human lead on multi-tenant production codebases over several months. Specific rules trace to specific incidents — keeping postmortems in your project's `docs/i-and-a/` (incidents and analyses) directory and referencing them from CLAUDE.md / AGENTS.md is the recommended practice. *Why* a rule exists is at least as important as what it says.

This doc is a distillation, not the source. The source is the runbook, the project-rules files, the postmortems, and the daily comms archives.
