# Current State

> **Capsule-before-comms invariant:** this file is updated *before* the comms message that describes the change. The comms message reports reality; this file is reality.

**Last verified HEAD:** <commit-sha-and-message>
**Last updated:** <ISO-8601 UTC>
**Active cycle:** <cycle name or "none">

---

## Active slices

| Agent | Slice | State | Branch | Started | Notes |
|---|---|---|---|---|---|
| | | | | | |

State values: `claimed` · `started` · `blocked` · `spawned` · `confirmed_running` · `completed`

---

## Review queue

| Slice | Reviewer | Requested | Notes |
|---|---|---|---|
| | | | |

---

## Blocked items

| Slice | Owner | Blocker | Needs |
|---|---|---|---|
| | | | |

---

## Locked decisions this session

| Decision | Date set | Source-of-truth | Why locked |
|---|---|---|---|
| | | | |

<!-- Decisions whose value must NOT be re-derived from the diff. Read this at resume
     BEFORE touching any judgement-carrying file. Migrate durable locks to
     docs/agents/LOCKED_DECISIONS.md at cycle close. -->

---

## Dirty worktree exceptions

<!-- Files known to be dirty for a legitimate reason (long-running migration, WIP doc, etc.).
     Anything not listed here is expected to be clean or staged. -->

---

## Merge / push order

<!-- If multiple slices are queued for push, the order they should land in. -->
