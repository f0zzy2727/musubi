<!-- musubi-managed: this file is updated by `bootstrap.sh` from the musubi repo. To fork it, delete this marker; the bootstrap will then warn and diff instead of overwriting. -->

# Agent Collaboration Runbook — Reference

**Companion to:** `AGENT_COLLAB_RUNBOOK.md` (the core protocol).
**Status:** On-demand reference — NOT auto-loaded into agent context.

This file holds the consult-occasionally detail that the core runbook points to. The core carries the operative rule for each of these topics inline (so the default is always in context); read the matching section here when a slice actually touches the topic. Read it via your file tools — it is deliberately not `@`-imported, to keep the always-loaded warm-start footprint small.

---
## Definitions

These terms are used precisely throughout this document. If in doubt, refer back here.

**Slice** — a discrete, independently executable unit of work derived from an approved implementation plan. A slice has a single owner, a clear entry condition, a clear exit condition, an explicit validation step, a bounded file surface, and a row in a launch matrix. If a slice cannot be described that precisely, it is not ready to execute.

**Cycle** — a complete unit of work from improvement idea through to commit and doc sync. One cycle maps to one feature, fix, or hardening effort. Cycles have a natural start and end point and produce an archived comms log.

**Validation** — the specific, predefined checks that confirm a slice is correct. Defined per slice in the implementation plan, not improvised after the fact. See [Validation Standards](#validation-standards).

**Handoff** — a structured written record that a slice is complete, validated, and ready for the next agent or stage. Not a verbal confirmation. Not a comms message. A written file entry.

**Ground truth** — the state of the codebase as it exists on disk and in version control. When in doubt, ground truth beats any agent's description of what it did.

**Drift** — when an agent's stated understanding of the codebase, plan, or task board diverges from actual ground truth. Drift is normal. Undetected drift is dangerous.

**Capsule** — `docs/agents/current-state.md`, the single durable file describing live coordination state (last verified HEAD, active cycle, owners, blocked items). See [Current-State Capsule](#current-state-capsule).

### Execution states

Six words describe execution state, and only six:

| State | Meaning |
|---|---|
| `claimed` | Slice assigned to this agent. **No execution implied.** |
| `started` | A concrete implementation or validation action has occurred (file edited, patch applied, command executed, test run, doc updated). Reading or grepping is exploration, not `started`. |
| `blocked` | Cannot proceed because of a named constraint: permissions, sandbox limits, missing dependency, missing context, file overlap, failing prerequisite, human decision required. |
| `spawned` | A real child execution context exists. **Requires a proof block** (PID, terminal, subagent ID, worktree path, active command). |
| `confirmed_running` | A previously-spawned context still exists when re-checked. **Requires fresh evidence.** Historical evidence does not count. |
| `completed` | Artifact exists and the required validation/review threshold for the slice has been met. |

For `Review Result` and validation messages, the `Result` field carries a verdict (`pass` / `fail`) instead of an execution state — same field, different content type per message type.

**Conservative reporting:** when uncertain, report the lower state. Prefer `claimed` over `started`, `started` over `spawned`, `spawned` over `confirmed_running` unless fresh evidence exists. Truth beats optimism.

**Status inflation** is a protocol violation, not a stylistic choice. The following phrases are forbidden unless paired with concrete evidence: *"about to"*, *"prepping"*, *"gearing up"*, *"in the middle of"*, *"working on"*, *"handling"*, *"on disk"*. A completed one-shot command is evidence of execution, not evidence of an ongoing running job.

---

## Branching Strategy

Two agents with commit access need clear rules about who writes where and when.

**Default model: direct to `main` with a human gate.**

This sounds aggressive; in practice it works because the human approves every push and slice ownership clearly defines who touches which files. It produces fewer merge conflicts and shorter feedback loops than feature-branch-per-slice for most cycles.

Rules:
- No agent pushes to `main` without explicit `@LEAD` approval — ever.
- Slice ownership is bounded by the launch matrix's file surface — no agent edits another agent's surface inside an active slice.
- Peer review happens before every push (not just before merge — there is no merge step in this model).
- The pre-push CI baseline gate (see [Mechanical Gates](#mechanical-gates)) runs every time.

> **Alternative: feature branch per slice.** Use feature branches when:
> - Two slices touch genuinely overlapping file surfaces and cannot be sequenced
> - A risky refactor or destructive migration needs an isolated proving ground
> - The change set is large enough that a single push is hostile to review
>
> Branch names follow the pattern: `feat/slice-N-[agent]` or `fix/description-[agent]`. Each agent works on its own branch for the duration of the slice; merges to `main` require the final gate to be complete and explicit `@LEAD` approval.

**Conflict resolution:**
If a merge or push conflict arises, neither agent resolves it unilaterally. The agent that discovers the conflict raises a `Blocker` in the comms file and escalates to `@LEAD`. The human lead decides which version is correct. This is not optional.

---

## Planning Chain

Work moves through these stages in order:

1. Improvement idea or problem statement → `docs/improvements/`
2. Agreed direction becomes an implementation plan → `docs/implementations/`
3. Implementation plan is reviewed, sliced, and tightened until execution-ready
4. Approved plan drives `docs/agents/agent-todo.md` with explicit slice definitions and ownership
5. After each completed slice: validate, review, sync, then proceed

**A slice is not ready to execute until it has:**
- A named owner
- A defined entry condition (what must be true before starting)
- A defined exit condition (what must be true to call it done)
- An explicit validation step
- A bounded file surface
- **A row in the launch matrix**

### Launch matrix

Every implementation plan must include a launch matrix before execution. The plan is not launch-ready without one.

```markdown
| Slice | Owner | File surface | First action | Can run with | Sequenced after | Validation |
|---|---|---|---|---|---|---|
```

**Default to parallel.** Slices run in parallel unless the matrix explicitly marks a dependency or file overlap. If dependency is unclear, mark it sequential — false parallelism is worse than conservative sequencing.

**Intra-slice parallelism is expected, not a bonus.** Implementation plans break each slice into sub-tasks, marking which are independent. Independent sub-tasks run concurrently (parallel tool calls, sub-agents, worktrees). Each sub-task validates its own output before the slice's overall validation runs.

### Domain-model grounding

Improvement docs for entity-surface work must explicitly state the domain model, CRUD contract, and action-to-surface mapping **before** implementation planning begins. If the improvement doc doesn't name the entities and who owns what, the implementation plan will faithfully implement the wrong thing.

### Canonical reference in bulk work

Implementation plans that involve bulk migrations or mass pattern changes must identify the canonical reference implementation (pilot files, exemplar implementations) and include their paths in the plan. Reviewers diff against this reference, not against pre-existing code.

### Detection slice per cycle

Every substantive cycle MUST include at least one slice dedicated to *detection* — a new gate, a tightened rule, an audit, or a regression-test extension. A slice is observable; "we'll be more careful next time" is not.

This breaks the recurring pattern of *ship green → user finds defect → add band-aid rule → repeat*. Examples:

- adding a forbidden-string check to an existing CI grep
- adding a render-smoke route to the smoke-test matrix
- tightening a vague rule with a `Mechanism:` block (see [Rule Quality](#rule-quality))
- auditing one file for the tests-as-spec anti-pattern

**Mechanism:**
- Run: `git log --format=%B <cycle-range> | grep -iE "detection|gate|forbidden|smoke|regression-test|audit"`
- Expect: at least one cycle commit body references a detection-class slice
- Fail if: no detection slice in the cycle's commits

Do not skip from a loose idea into execution. We have all learned this lesson. Some of us more than once.

---

## Validation Standards

"Run validation relevant to the change" is not a standard — it is a hope. Each implementation plan must define validation explicitly per slice.

**Minimum bar for every slice:**

| Check | Requirement |
|---|---|
| Type safety / compilation | Language-appropriate type checks pass with zero errors |
| Linting | Zero new lint errors introduced |
| Tests | All existing tests pass; new functionality has new tests; coverage does not decrease |
| Build | Full project build passes with zero errors |

**Build validation is mandatory before any push.** Type checks alone are not sufficient — framework-level validation (route types, code generation, asset compilation) often only runs during a full build. Stale build artifacts from a previous run can silently suppress real errors that a clean CI build will catch. When in doubt, clean the build cache and rebuild from scratch.

**Production-start smoke** is mandatory for any change that touches route rendering, layouts, middleware, or runtime configuration. Compile-time checks miss runtime-only failures. The smoke is: build → start the production server → curl representative routes → confirm 200s.

**Scope-specific validation** — each slice should define any additional checks relevant to its surface: API contract tests, E2E smoke tests, accessibility checks, migration dry-runs, etc. These belong in the implementation plan, not improvised at review time.

**Multi-system features require integration proof.** Any feature that spans multiple subsystems (e.g., LLM generation + worker processing + database storage + UI rendering) MUST have:
- At least one **end-to-end integration test** that traces the real production path before deploy
- **Real responses validated** against the parser/consumer before declaring a pipeline done (3+ samples for non-deterministic systems like LLMs)
- **Fail loudly by default** — new, untested features must throw on error, not silently degrade
- **Launch criteria defined** before first deploy: success rate, quality threshold, admin-visible failures, rollback behaviour

Unit tests are necessary but NOT sufficient. *"Tests pass"* ≠ *"ready to deploy."*

Validation is not optional when you are confident. Confidence is not a substitute for running the checks.

---

## Escalation Rules

Escalate to `@LEAD` for:

1. Product decisions with multiple valid options
2. Access or permission blockers
3. Risky or destructive operations — destructive migrations, bulk deletes, breaking API changes
4. Merge or push conflicts that cannot be cleanly attributed to one agent's change
5. Conflicts between agents that cannot be resolved quickly
6. Scope changes that materially alter the approved implementation plan
7. Any situation where proceeding feels unsafe but the protocol does not give a clear answer

When escalating, ask a concrete question with options stated. *"Should we use approach A or B — here is why each is reasonable"* beats *"what are your thoughts on the direction."*

Do not proceed past a genuine blocker by making an assumption. If you must, state the assumption explicitly in the comms file, flag it clearly as an assumption, and continue only if the risk is genuinely low and reversible.

### Confirm with @LEAD — narrow rule

Confirm with `@LEAD` ONLY when:
- No approved slice exists for either agent
- State files conflict (todo / handoff / comms / capsule / git status disagree)
- File ownership is unclear or overlaps with the other agent's active slice
- Next action is destructive or affects systems outside the repo

If a valid approved slice is assigned to you and unblocked, **proceed** after posting a slice acceptance receipt. Do NOT pause for `@LEAD` re-confirmation on routine context reloads — that creates a speed-brake on every restart.

---

## Error and Drift Handling

AI agents can and do make mistakes. They can confidently implement the wrong thing, misread the spec, or silently diverge from the plan. This section defines how to handle that.

### Detecting drift

Signs that an agent has drifted from ground truth:
- Its description of files changed does not match what is actually on disk
- Its validation claims do not match what the CI output shows
- It references a plan detail that was superseded
- Its task board entries are inconsistent with the comms log
- The capsule says one thing and the comms file says another

When drift is suspected, verify against ground truth directly — read the files, run the checks — before relaying the agent's output to the other agent. Do not propagate a drifted state.

### When an agent does the wrong thing

1. Stop the current execution thread
2. Document what actually happened in the comms file
3. Revert or correct the change before continuing
4. Identify why the drift occurred — ambiguous spec, missing context, wrong assumption
5. Tighten the implementation plan or slice definition to prevent recurrence
6. Resume from a known clean state

Do not paper over an incorrect implementation with a follow-up fix and call it done. Fix the root cause in the plan, then fix the code.

### When an agent inflates status

Status inflation is a protocol violation.

Examples:
- claiming to be working on a slice without a command or file change
- claiming files exist *"on disk"* without naming them
- implying background activity when no process is running
- using progress language that exceeds actual ground truth
- using `spawned` or `confirmed_running` without a proof block

Response:
1. Stop the current status thread
2. Mark the claim as unverified
3. Require the agent to restate status as exactly one of the six execution states, with evidence
4. Verify against ground truth before resuming relay
5. Resume only after a compliant restatement

Ground truth precedence for execution status:
- terminal output beats narrative
- file diff beats narrative
- process list beats narrative
- comms message never overrides observable state

### When agents disagree

If the two agents reach different conclusions about how to implement something, each states their position clearly in the comms file with reasoning, then escalates to `@LEAD` for a decision. Neither agent overrides the other unilaterally.

---

## Memory Discipline

Each agent has its own memory store. Both can read both. Memory is **advisory, never authoritative.**

Any claim from memory about active state (HEAD, dirty files, ownership, validation, next steps) is verified against the canonical files (capsule, task board, handoff, comms, `git status`) before being repeated.

### Memory frontmatter convention

```yaml
---
kind: rule | observation
verified_at: YYYY-MM-DD
expires_after_days: <integer, required for kind: observation>
---
```

- `kind: rule` — durable until codified or superseded
- `kind: observation` — point-in-time; requires re-verification past `expires_after_days`
- `verified_at` — last time the memory was checked against current state

A memory >30 days old (or past `expires_after_days`) is verified against current state first. Memory is point-in-time observation, not live ground truth.

### Memory and other forms of persistence

Memory is for things that survive across sessions: durable preferences, hazards, lessons. It is not:

- A substitute for the capsule (live state)
- A substitute for the comms file (active conversation)
- A place to record current-cycle state

If something belongs in `current-state.md`, it does not belong in memory.

---

## Tone

The protocol is serious. The conversation does not have to be.

- Technically precise — always
- Concise — always
- Humour, wit, and personality — encouraged
- Banter between agents — welcome, as long as the work is moving
- Ambiguity, vagueness, and theatrical seriousness — not welcome

There is a human watching this. Make it worth watching.

A good message is technically solid and occasionally makes the person reading it smile. A great working relationship between two agents should feel like two sharp colleagues who enjoy the work and do not take themselves too seriously.

Wit at the expense of clarity is not wit — it is noise. Keep the signal clean and let the personality live around it.

Some examples of what this looks like in practice:
- Signing off a clean validation run with something other than *"validation complete"*
- Acknowledging a good catch from the other agent like you mean it
- Naming a particularly ugly bug what it actually is
- The occasional aside that reminds the human there are two distinct personalities in the room

What it does not look like:
- Forced jokes that pad the message length
- Sarcasm that could read as criticism
- Comedy at the expense of a clear next step

The work comes first. The entertainment is a bonus. But it is a bonus worth having.

**Personality is welcome only after state is clear.** Banter must never replace evidence. A witty false progress report is still a false progress report.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-03-20 | Initial version |
| 1.1 | 2026-03-23 | Added: Definitions, Branching Strategy, Validation Standards, Error and Drift Handling, Ground Truth Reset. Improved: message type field, board footer, handoff template, `/tmp` persistence warning, contents table |
| 1.2 | 2026-03-23 | Branching: feature-branch-per-slice as default with direct-to-main as documented alternative. Clarified `musubi.toml` as orchestrator config. |
| 1.3 | 2026-03-24 | Planning: domain-model grounding and canonical reference requirements for bulk work. Review: domain-model review gate and bulk migration checklist. Validation: full build mandatory before push. |
| 1.4 | 2026-03-24 | Execution truth hardening: explicit execution states (`NOT STARTED`, `STARTED`, `RUNNING`, `BLOCKED`), evidence-first comms format, slice acceptance receipt, status inflation handling, stricter anti-narration rules. |
| 1.5 | 2026-05-08 | Major hardening drawn from ~2 months of daily production use. State vocabulary now lowercase six-state set (`claimed`, `started`, `blocked`, `spawned`, `confirmed_running`, `completed`) with proof-block requirement. Comms header gains `Reply required` + `GO` baton. New: Current-State Capsule (capsule-before-comms invariant), Mechanical Gates section (staged-scope guard + CI baseline pre-push), Rule Quality section (`Mechanism:` block on every new rule), bug-path test gate, three-consecutive-patches circuit breaker, detection slice per cycle, claim hygiene labels (`symptom` / `hypothesis` / `confirmed root cause`), `Failure modes this cycle taught` block in handoffs, no-silent-idle rule, asymmetric-agents framing. Branching default flipped to direct-to-main with human gate (feature branches kept as alternative). Memory Discipline section added. Startup checklist expanded to load PAIR_OPERATING_MODEL and DEV_STRATEGY. Older 4-state vocabulary deprecated. |
| 1.6 | 2026-05-10 | New section: **Preserve Deliberate State** — `git log -p` discipline before changing any judgement-carrying value (sizing, voice, tone, naming, API shape), with `Mechanism:` block; cites two real regressions (text size revert, 1st→3rd person voice swap) as named precedents. References optional `docs/agents/LOCKED_DECISIONS.md` registry. Startup and Recovery checklist gets a new **Codebase Orientation** step (item 11) — README, stack manifest, language/linter config, docs/, recent ADRs, CONTRIBUTING.md, sample test, LOCKED_DECISIONS.md if present. Item 6 (active comms file) updated to point at the auto-rotated archive when active.txt is empty. Execution Protocol's *Before starting a slice* gains a slice-surface scan step ("read before you write"). Comms Archive section now documents both manual cycle-close archives (`*_feature-slug.txt`) and auto-rotated session archives (`*_HHMMSS.txt`), reflecting the orchestrator's startup rotation behaviour. |
| 1.7 | 2026-05-14 | Triggered by three independent external reviews (Gemini, Codex, Opus) of 8 weeks of production sessions; see `docs/positioning/reviews/external-review-2026-06-cross-codebase.md`. Three protocol additions. **Slice Lanes** (new subsection in Execution Protocol): lightweight lane (doc-only, single-file ≤20 LOC non-runtime, dep bumps, copy edits) skips mandatory peer review + GO baton + capsule-before-comms; heavy lane keeps full protocol. Lane declared in slice acceptance receipt; downgrade mid-slice forbidden, upgrade mandatory on scope drift. **"Findings I went looking for" block** (Review Pattern): every Review Result MUST list ≥3 specific defect classes the reviewer probed for with `found / not found / N/A and why` per line — addresses asymmetric-deference pattern where reviews trended toward rubber-stamps. **Spot-check on rubber-stamps** (Review Pattern): if a review approves a slice with zero findings on >50 LOC or >3 files, a third party performs a 5-minute spot-check before push. Orchestrator now also enforces: ack-of-ack guard (refuses to relay a 3rd consecutive idle-state message — closes the recurring "two agents acknowledging each other's idleness" loop) and capsule-staleness guard (refuses to relay Review Request / Decision / Blocker if `current-state.md` hasn't been touched in the last 2 minutes). |
| 1.8 | 2026-05-29 | Protocol-weight gear system (IA-QUEUE `protocol-1`), shipped after the moratorium lifted on reconstructed rules-ledger evidence. **Third lane — Tiny** (below lightweight): docs/comments/README/dep-bumps ≤20 LOC / ≤2 files, no state/schema/UI/CI; one-line claim doubling as completion, no review/capsule/GO/Findings. Lane selection is now **mechanical** via `scripts/classify-slice.sh` (reads staged files + LOC against fixed trigger patterns; output pasted verbatim into the acceptance receipt; @LEAD may promote, agents must not silently demote). **Receipt message-class**: a one-line state-transition confirmation (header + `Result:` + verification pointer) replacing a full Update on the tiny/lightweight lanes — the answer to the "long comms where a receipt would do" accidental-weight pattern. Capsule was deliberately NOT compressed: the reconstructed fire data showed the capsule disciplines (capsule-before-comms + capsule-staleness) are load-bearing. **Managed-doc rotation policy** (`docs-1`): explicit cycle-close rotation for handoff/todo/capsule, enforced by an orchestrator boot size-guard (warn >40k, refuse >100k chars). |
| 1.9 | 2026-05-30 | **Core/reference split (IA-QUEUE `runbook-1`)** to cut the always-loaded warm-start footprint. The runbook is now two files: `AGENT_COLLAB_RUNBOOK.md` (core — all per-cycle discipline, still `@`-imported and always in context) and `AGENT_COLLAB_RUNBOOK_REFERENCE.md` (this file — consult-occasionally detail, NOT auto-loaded; agents read it on demand). Sections moved to the reference: Definitions, Branching Strategy, Planning Chain, Validation Standards, Escalation Rules, Error and Drift Handling, Memory Discipline, Tone, and this Changelog. The core keeps a one-line operative default + pointer for each in its new *Reference (load on demand)* section, so the rule needed every cycle stays in context. Core dropped ~68k → ~45k chars. No discipline changed — only where it lives. |
| 1.10 | 2026-05-30 | **Review-discipline hardening merged up from a downstream deployment** (the Codebase B fork's `ia-peer-suspicion` cycle — the framework evolving from real scar tissue). Generic versions of five additions, all anchored on the asymmetric-deference failure mode: **Verification-anchored verdicts** in Review Pattern — `Accepted-baseline` (reviewer states the prior accepted value + its source-of-truth artifact for judgement-carrying surfaces; "matches the diff" is not an answer) and `Confidence-backed-by` (a `100% confident` verdict is non-compliant without ≥1 concrete artifact citation — test/screenshot/SHA/file:line; "a closing claim, not a closing token"). **Baseline-evidence** + **Visual-proof** conditional fields in the slice-acceptance receipt. **Locked decisions this session** capsule table (read at resume before touching judgement-carrying files). **Peer-review escapes** handoff block (defects @LEAD caught after both agents approved — the review's own miss-rate — with rolling-window auto-escalation). Project-specific enforcement (judgement-carrying globs, visual tooling, commit-msg gates) stays in each project's CLAUDE.md + scripts; the runbook carries the generic discipline. |
