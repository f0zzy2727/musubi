<!-- musubi:start -->
<!-- This block is managed by `musubi/bootstrap.sh`. Do not hand-edit between the markers — your edits will be overwritten on the next bootstrap run. To opt out of musubi management, delete the markers and the bootstrap will leave this section alone. -->

## Multi-Agent Collaboration (musubi)

This project uses [musubi](https://github.com/f0zzy2727/musubi) — a two-agent collaboration pattern. **On every fresh session, read these files before any work:**

1. `docs/agents/AGENT_COLLAB_RUNBOOK.md` — protocol authority (state vocabulary, comms format, slice lifecycle)
2. `docs/agents/PAIR_OPERATING_MODEL.md` — patterns + adoption guide (the *why* behind the runbook)

The operator-facing daily/weekly cadence lives at `docs/operator/DEV_STRATEGY.md` — not on this required-reading list. Read it on request if a cadence question arises.

Then run the runbook's *Startup and Recovery* checklist to load:

- `docs/agents/current-state.md` — live capsule (active slices, owners, blockers, last verified HEAD)
- `docs/agents/agent-todo.md` — task board
- `docs/agents/agent-handoff.md` — most recent slice handoff
- comms file (default: `docs/agents/comms/active.txt`)
- `git status --short --branch`

If a `/open-sesame` slash command (or equivalent prompt) is defined for this project, run it as a shortcut for the full startup checklist.

**Execution states** (from the runbook): `claimed` · `started` · `blocked` · `spawned` · `confirmed_running` · `completed`. Use only these. Conservative reporting: when uncertain, report the lower state.

**Comms message format** uses `Action / Evidence / Result / Next` with explicit `Reply required` and `GO` baton fields. End every message with `<OVER>` on its own line so the orchestrator can relay it. Any `spawned` or `confirmed_running` claim requires a proof block (PID / terminal / subagent / worktree / command + `checked_at`).

**Mechanical gates**:
- Pre-commit: `scripts/guard-staged-scope.sh <allowed-paths>` — fails if files outside the declared allowlist are staged.
- Pre-push: `scripts/ci-baseline.sh` — surface CI baseline status verbatim in the push-approval comms message.

**Capsule-before-comms invariant:** update `docs/agents/current-state.md` *before* the comms message that describes the change. The comms message reports reality; the capsule is reality.

**Tooling discipline:** Slash commands, named prompt shortcuts, and harness skills are not invoked proactively. Default to plain file reads, edits, and shell commands. Use a slash command or shortcut only when the task explicitly calls for it AND it is genuinely the right fit — never as a reflex or because it sounds related. Invoking one on a task that didn't need it adds noise, latency, and context bloat without producing value.

**Preserve deliberate state:** Before changing any value that carries judgement (text size, copy register, voice, tone, colour, layout, API shape, naming convention), run `git log -p -- <path>` and check `docs/agents/LOCKED_DECISIONS.md` if the project maintains one. Silent normalisation reverses other people's decisions and reintroduces fixed bugs. See the runbook's *Preserve Deliberate State* section for the full rule and Mechanism block.

<!-- musubi:end -->
