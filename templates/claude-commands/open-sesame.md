---
description: Warm-start checklist — load all musubi context for this session
---

You are resuming a musubi-managed multi-agent session. Walk this checklist in order, reading each file fully before moving on. Report only at the end with a one-line confirmation.

## Step 1 — Protocol authority

Read these in order:
1. `docs/agents/AGENT_COLLAB_RUNBOOK.md` — protocol (state vocabulary, comms format, slice lifecycle)
2. `docs/agents/PAIR_OPERATING_MODEL.md` — patterns + the *why* behind the runbook

(The operator-facing daily/weekly cadence at `docs/operator/DEV_STRATEGY.md` is not part of the warm-start checklist — read it only if a cadence question comes up.)

## Step 2 — Live state

4. `docs/agents/current-state.md` — capsule (active cycle, owners, blocked items, last verified HEAD)
5. `docs/agents/agent-todo.md` — task board (current-state block first, then active cycle)
6. `docs/agents/agent-handoff.md` — most recent entry only
7. The active comms file (path defined in the project's `musubi.toml`; default `docs/agents/comms/active.txt`). If empty because the orchestrator just rotated it on startup, also read the most recent `docs/agents/archive/agent_comms_*.txt` for the prior session's transcript — the structured handoff and capsule capture intent, the archive captures texture.

## Step 3 — Ground truth

8. `git status --short --branch` — verify worktree state matches what comms / todo / capsule claim

## Step 4 — Codebase orientation

The `docs/agents/` files cover collaboration protocol; the rest of the repo carries the actual conventions you must respect. Scan, don't deep-read:

9. Repo `README.md` (project intent, entry points)
10. Stack manifest: `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Gemfile` (whichever exists) — what stack and what scripts
11. Language and linter/formatter config (`tsconfig.json`, `.eslintrc*`, `ruff.toml`, `.prettierrc`, etc.) — strictness and style rules already in force
12. `docs/` directory listing — note any `architecture/`, `adr/`, or `decisions/` subdir; read its index plus the most recent 2–3 ADRs to learn active constraints
13. `CONTRIBUTING.md` if present (workflow expectations)
14. One sample file from the project's test directory (testing convention)
15. `docs/agents/LOCKED_DECISIONS.md` if the project maintains one — deliberate choices that look unusual and must not be silently reverted (see the runbook's "Preserve Deliberate State" section)

The point is to understand: what stack applies, what architectural decisions are locked, what the testing pattern is, and what already exists so you don't duplicate or contradict it. You are not writing code yet — you are learning what the codebase has already decided.

## Step 5 — Active slice docs

16. The implementation/improvement doc for the active slice ONLY (skip historical docs)

## Step 6 — Memory

17. Agent-specific memory as advisory context — never authority. Verify any memory claim about active state against the canonical files above before repeating it.

## Step 7 — Restate

After reading, restate in one short message:

- What was the last thing completed
- What is currently in progress (named slice + execution state from {`claimed`, `started`, `blocked`, `spawned`, `confirmed_running`, `completed`})
- What is next

If state files conflict, no approved slice exists for you, file ownership is unclear, or the next action is destructive/external — pause and ask the human lead. Otherwise: post a slice acceptance receipt and proceed.

End with the literal line: **"Startup complete. Ready."**
