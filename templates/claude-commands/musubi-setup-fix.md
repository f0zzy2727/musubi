---
description: Audit and repair musubi setup across all apps — north-star docs, shared cross-app rules, durable I&A, comms health, and context_docs wiring
---

You are repairing the structural setup of one operator's musubi apps. The goal:
stop the same bugs being re-derived across apps because lessons never become
durable, shared, reloaded rules. You will run mechanical helpers for the safe
parts and do the judgement parts (writing real product/architecture content,
rewiring configs) yourself — **always with the operator's approval before any
write.**

Run from the operator's musubi folder (where the `musubi*.toml` files live).

## Iron rules

- **Never invent-and-commit intent.** You may DRAFT a vision/architecture, but a
  draft is wired in only after the operator reads and approves it. An unreviewed,
  agent-invented north-star is worse than none — the agents will then trust it.
- **Back up before every overwrite.** The helper does this; you do it too for any
  file you edit directly (copy to `<file>.bak.<timestamp>`).
- **Show, then write.** For every content draft and every toml edit, show the
  exact diff/content and get a yes before writing.
- One change at a time. Report what you did after each.

## Step 1 — Audit

1. Discover every `musubi*.toml` (exclude `*.example`).
2. For each, run `bash scripts/doctor.sh -c <that-toml>` (the per-config
   preflight; it flags managed-template north-stars, missing docs, and binary
   comms). Always pass `-c` — without it, doctor checks only the default
   `musubi.toml`, which is the WRONG app for every sibling config.
3. Run `bash scripts/setup-fix.sh` (report mode) for the cross-app view.
4. Summarise per app: real north-star? durable I&A home? comms healthy? what does
   `context_docs` load today? Present this table to the operator before changing
   anything.

## Step 2 — Mechanical fixes

Run `bash scripts/setup-fix.sh --fix` (it asks per step; or `-y` if the operator
wants it unattended). This will, with backups:
- create the shared cross-app intent doc skeleton (`shared-intent/CROSS-APP-RULES.md`)
- scaffold missing `docs/PRODUCT-VISION.md` / `docs/ARCHITECTURE.md` from templates
  (marked DRAFT) for any app booting blind
- create a durable `docs/i-and-a/` home per app
- back up and recreate any binary/corrupt comms file

It does NOT write real content or touch tomls — that's the next steps.

## Step 3 — Fill the shared cross-app rules (do this first; it's the keystone)

Open `shared-intent/CROSS-APP-RULES.md`. Interview the operator for the truths
that apply to ALL apps — the things that, if known, would have prevented the
cross-app bugs. Ask concrete, informed questions, e.g.:
- "Are there resources shared across all apps (accounts, voice/clone IDs, API
  keys, billing)? Which are account-level and must never be rebuilt per app?"
- "What invariants hold everywhere — naming, deploy targets, data ownership?"
Draft the rules from the answers, show them, write on approval.

## Step 4 — Fill each app's vision + architecture (the DRAFT scaffolds)

For every app you scaffolded:
1. Read that app's code, README, and existing docs first — so your questions are
   informed, not blank.
2. Interview the operator on what's missing: what the app is for, who uses it,
   the core flows, the architecture and key decisions.
3. Draft `PRODUCT-VISION.md` and `ARCHITECTURE.md` from their code + answers.
4. Show each, revise to their corrections, write on approval. Remove the DRAFT
   banner once real.

## Step 5 — Wire context_docs

For each app's toml, set (back up the toml first, show the diff, get a yes):
```
[agents.oyakata]
context_docs = ["docs/PRODUCT-VISION.md", "docs/ARCHITECTURE.md", "<abs path to shared-intent/CROSS-APP-RULES.md>"]
```
Decide with the operator how the shared doc is referenced so all apps load the
SAME file (absolute path, or a symlink into each repo's `docs/`) — not per-app
copies that drift. Confirm the loader accepts the chosen form.

## Step 6 — Move live I&A off the trap

If the operator has lessons living only in `IaA.md` (which is managed and
clobbers appends), help them move durable rules into `docs/i-and-a/` files and/or
`rules-ledger.yml` so they actually reload next cycle. Cross-app lessons go in the
shared doc.

## Step 7 — Verify

Re-run `bash scripts/doctor.sh` per config and `bash scripts/setup-fix.sh`
(report). Confirm: every app now has a real north-star, loads the shared doc,
has a durable I&A home, and a healthy comms file. Report the before/after table.

## Done when

Every app boots Oya with real vision + architecture + the shared cross-app rules;
lessons have a durable home that reloads; no binary comms files. The
reintroduction loop is closed: a rule learned once is now loaded everywhere.
