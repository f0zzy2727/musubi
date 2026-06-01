<!-- musubi:start -->
<!-- This block is managed by `musubi/bootstrap.sh`. Do not hand-edit between the markers — your edits will be overwritten on the next bootstrap run. To opt out of musubi management, delete the markers and the bootstrap will leave this section alone. -->

## Multi-Agent Collaboration (musubi)

This project uses [musubi](https://github.com/f0zzy2727/musubi) — a two-agent collaboration pattern. Read these in order on every fresh session:

- @docs/agents/AGENT_COLLAB_RUNBOOK.md — protocol authority (state vocabulary, comms format, slice lifecycle)
- @docs/agents/PAIR_OPERATING_MODEL.md — patterns + adoption guide (the *why* behind the runbook)

The operator-facing daily/weekly cadence lives at `docs/operator/DEV_STRATEGY.md` — not auto-loaded into agent context. Read it on request if a cadence question arises.

Then run the runbook's [Startup and Recovery](docs/agents/AGENT_COLLAB_RUNBOOK.md#startup-and-recovery) checklist to load:

- @docs/agents/current-state.md — live capsule (active slices, owners, blockers, last verified HEAD)
- @docs/agents/agent-todo.md — task board
- @docs/agents/agent-handoff.md — most recent slice handoff
- comms file (default: `docs/agents/comms/active.txt`)
- `git status --short --branch`

If a `/open-sesame` slash command is defined for this project, you can run it as a shortcut for the full startup checklist.

**Execution states** (from the runbook): `claimed` · `started` · `blocked` · `spawned` · `confirmed_running` · `completed`. Use only these. Conservative reporting: when uncertain, report the lower state.

**Comms message format** uses `Action / Evidence / Result / Next` with explicit `Reply required` and `GO` baton fields. End every message with `<OVER>` on its own line so the orchestrator can relay it.

**Mechanical gates** (see [Mechanical Gates](docs/agents/AGENT_COLLAB_RUNBOOK.md#mechanical-gates)):
- Pre-commit: `scripts/guard-staged-scope.sh <allowed-paths>`
- Pre-push: `scripts/ci-baseline.sh` — surface CI baseline status verbatim in the push-approval message

**Capsule-before-comms invariant:** update `docs/agents/current-state.md` *before* the comms message that describes the change. The comms message reports reality; the capsule is reality.

**Skill / tooling discipline:** Skills (slash commands, plugin commands, named skill triggers) are not invoked proactively. Default to plain file reads, edits, and shell commands. Use a skill only when the task explicitly calls for it AND the skill is genuinely the right fit — never as a reflex or because it sounds related. A skill invoked on a task that didn't need it adds noise, latency, and context bloat without producing value.

**Preserve deliberate state:** Before changing any value that carries judgement (text size, copy register, voice, tone, colour, layout, API shape, naming convention), run `git log -p -- <path>` and check `docs/agents/LOCKED_DECISIONS.md` if the project maintains one. Silent normalisation reverses other people's decisions and reintroduces fixed bugs. See [Preserve Deliberate State](docs/agents/AGENT_COLLAB_RUNBOOK.md#preserve-deliberate-state) in the runbook for the full rule and Mechanism block.

<!-- musubi:end -->
