# Sample cycle — what the message protocol looks like in practice

This file shows a representative slice cycle running through the musubi protocol — slice claim, peer review, GO baton, slice acceptance. It is **illustrative, not historical**: the project, file paths, and findings are invented to demonstrate the message format. A real archive looks like this in shape; the substance varies with the work.

For the actual runbook authority on the protocol, see [`../agents/AGENT_COLLAB_RUNBOOK.md`](../agents/AGENT_COLLAB_RUNBOOK.md). For the rationale behind the format, see [`../agents/PAIR_OPERATING_MODEL.md`](../agents/PAIR_OPERATING_MODEL.md).

---

## Scenario

A two-agent pair is adding a webhook-signature validation step to an HTTP intake endpoint. Opus is the implementer; Coda is the reviewer. `@MICHI` (the human lead) made the scope call at the start of the cycle.

The slice is "heavy" lane (multi-file, runtime-affecting), so full review + GO baton + capsule discipline apply.

---

## The cycle

### 1. Slice claim

```text
---------------------------------------------------
[@OPUS] [2026-XX-XX] [09:14 UTC]
Type: Update
Subject: Slice WEBHOOK-1 claimed — HMAC signature verification on /intake
Reply required: only-if-blocker
GO: no
GO owner: none
GO action: none

@CODA

Action:
Claiming slice WEBHOOK-1 from the cycle board. Scope: add HMAC-SHA256
signature verification on POST /api/intake. Reject on missing header,
bad signature, or replay (>5min skew).

Evidence:
- Slice acceptance receipt (heavy lane):
  - Files: src/api/intake.ts, src/lib/webhook-sig.ts (new), tests/intake.test.ts
  - Risk class: auth-adjacent (trust boundary)
  - Disciplines expected to fire: threat-model-auth-changes, abuse-case-named-on-new-input
  - Estimated diff: ~120 LOC + tests

Result:
claimed

Next:
Implement signature verification in src/lib/webhook-sig.ts; wire into
intake handler; add tests covering missing-header / bad-sig / valid-sig /
replay-window cases.

<OVER>
```

### 2. Update mid-slice (capsule touched first)

```text
---------------------------------------------------
[@OPUS] [2026-XX-XX] [10:02 UTC]
Type: Update
Subject: WEBHOOK-1 — sig verification implemented, tests passing locally
Reply required: only-if-blocker
GO: no
GO owner: none
GO action: none

@CODA

Action:
Implemented src/lib/webhook-sig.ts with verify(rawBody, header, secret).
Wired into intake handler. Added 4 tests; all pass locally.

Evidence:
- Files changed:
  - src/lib/webhook-sig.ts (new, 52 LOC)
  - src/api/intake.ts (+18 LOC, -3 LOC)
  - tests/intake.test.ts (+74 LOC)
- Test run:
  - `pnpm test tests/intake.test.ts` -> 4 passed (missing-header / bad-sig
    / valid-sig / replay-window)
- Capsule updated: docs/agents/current-state.md @ 10:01 UTC
  ("WEBHOOK-1 implementation complete, ready for review")

Result:
in_review

Next:
Awaiting review. No further code changes planned until @CODA's findings.

<OVER>
```

### 3. Review request

```text
---------------------------------------------------
[@OPUS] [2026-XX-XX] [10:04 UTC]
Type: Review Request
Subject: WEBHOOK-1 review request — HMAC sig verification
Reply required: yes
GO: no
GO owner: none
GO action: none

@CODA

Please review WEBHOOK-1.

Diff: git diff origin/main..HEAD -- src/lib/webhook-sig.ts \
  src/api/intake.ts tests/intake.test.ts

Findings I am asking you to probe for (at minimum):
1. Constant-time comparison correctness (HMAC compare must not leak via
   string compare timing).
2. Replay-window correctness (5-min skew; signed timestamp parsed from
   header; clock-skew direction handled both ways).
3. Failure-mode telling: does the handler distinguish "header missing"
   from "header present but bad signature" in a way that helps an attacker
   enumerate? (It should NOT.)

Other areas welcome: error response shape, log content (don't log secrets),
testability of the verify function in isolation.

<OVER>
```

### 4. Review result with `Findings I went looking for`

```text
---------------------------------------------------
[@CODA] [2026-XX-XX] [10:21 UTC]
Type: Review Result
Subject: WEBHOOK-1 review — changes requested (2 findings)
Reply required: yes
GO: no
GO owner: none
GO action: none

@OPUS

Reviewed src/lib/webhook-sig.ts (52 LOC), src/api/intake.ts (+18/-3),
tests/intake.test.ts (+74 LOC).

Findings I went looking for:
1. Constant-time comparison correctness — FOUND. webhook-sig.ts:34 uses
   `===` to compare the computed HMAC to the header value. This leaks
   compare time. Use `crypto.timingSafeEqual(Buffer, Buffer)`.
2. Replay-window correctness — NOT FOUND. Window is 5min absolute,
   parsed correctly, handles both clock-skew directions.
3. Failure-mode telling — FOUND. intake.ts:91 returns 401 with body
   "missing signature header"; intake.ts:96 returns 401 with body
   "invalid signature". Different bodies let an attacker distinguish.
   Both paths should return the same opaque response body.

Other notes:
- Tests are tight. Good coverage of the four cases. Consider adding a
  fifth case for "header malformed but present" (e.g. `Signature: not a
  hex string at all`) — currently this falls through bad-sig path but
  it's worth a dedicated test so a future refactor doesn't lose it.
- Logging: clean. No secret material in any log statement I could find.

Result:
changes_requested

Next:
Fix Findings 1 and 3, then re-request review with the diff scoped to
those two changes only.

<OVER>
```

### 5. Update — changes applied

```text
---------------------------------------------------
[@OPUS] [2026-XX-XX] [10:38 UTC]
Type: Update
Subject: WEBHOOK-1 — Findings 1 + 3 addressed, re-review ready
Reply required: only-if-blocker
GO: no
GO owner: none
GO action: none

@CODA

Action:
Addressed both review findings. Also added the malformed-header test
@CODA suggested.

Evidence:
- Files changed (since prior review):
  - src/lib/webhook-sig.ts:34 — now `crypto.timingSafeEqual(...)`
    (both arguments are Buffer; lengths checked first to avoid the
    library's throw-on-length-mismatch behaviour)
  - src/api/intake.ts:91, :96 — both 401 paths now return identical
    body "unauthorised" (no distinguishing detail)
  - tests/intake.test.ts — added test case
    "rejects when signature header is not valid hex"
- Test run:
  - `pnpm test tests/intake.test.ts` -> 5 passed
- Capsule updated: docs/agents/current-state.md @ 10:37 UTC

Result:
in_review

Next:
Awaiting @CODA's re-review of the two scoped fixes + the new test.

<OVER>
```

### 6. Review result — approved

```text
---------------------------------------------------
[@CODA] [2026-XX-XX] [10:46 UTC]
Type: Review Result
Subject: WEBHOOK-1 re-review — approved
Reply required: yes
GO: yes
GO owner: @OPUS
GO action: push to origin/main; mark WEBHOOK-1 closed on the cycle board

@OPUS

Re-reviewed the two scoped fixes + the new malformed-header test.

Findings I went looking for:
1. timingSafeEqual usage — NOT FOUND (correct). Lengths are checked
   first; both args are Buffer; falls through cleanly on mismatch.
2. 401 response body uniformity — NOT FOUND (correct). Both paths
   now return the identical literal "unauthorised".
3. New test covers the regression class @OPUS introduced last time
   (header present but malformed) — confirmed; test fails when I
   revert the malformed-header path to a permissive parse, passes
   with the strict parse. Receipt: ran the test against a stashed
   regression locally.

Result:
approved

Next:
Push when ready. @MICHI's approval covers this slice (cycle-open
pre-ack quoted in capsule).

<OVER>
```

### 7. GO baton + push

```text
---------------------------------------------------
[@OPUS] [2026-XX-XX] [10:52 UTC]
Type: Update
Subject: WEBHOOK-1 — pushed to origin/main, slice closed
Reply required: only-if-blocker
GO: no
GO owner: none
GO action: none

@CODA

Action:
Pushed WEBHOOK-1 to origin/main. Marked slice closed on cycle board.
Capsule rotated: WEBHOOK-1 moved from "active" to "shipped this cycle";
next slice WEBHOOK-2 (replay-cache table) is on deck.

Evidence:
- Push: commit a4f7d92 -> origin/main (4 files, +144/-3)
- CI status: green (https://github.com/.../runs/8821731)
- Capsule diff: docs/agents/current-state.md @ 10:51 UTC

Result:
completed

Next:
Standby on WEBHOOK-1. Will claim WEBHOOK-2 if @CODA hasn't claimed
within ~5 minutes.

<OVER>
```

---

## What's load-bearing in this exchange

Reading back through the seven messages:

- **The capsule was touched before every state-affecting comms post.** That's not narrative discipline — it's the orchestrator's capsule-staleness guard refusing to relay state-affecting messages otherwise. The receipts in each Update name the capsule edit explicitly.
- **The Review Result lists what was probed, not just what was found.** Two of the three probes returned "found"; one returned "not found." A reviewer who just wrote "looks good — approved" would be told by the runbook discipline (and a later spot-check) that this is not a review. The probe enumeration is what the receipt asks of every reviewer.
- **The fix-then-re-review loop happened in one cycle.** No "ship it now, I'll fix it later." The protocol's overhead is high but its merge gate is hard.
- **The GO baton is named explicitly.** When the work transfers (review → push approval → ship), the baton field names who owns the next action. Diffuse responsibility is one of the failure modes the protocol exists to prevent.

The protocol is heavy. The protocol catches things. The trade-off is in the operating-model doc; this file just shows the texture.

---

## What's *not* in this example

A real cycle archive includes:

- **Heartbeats** during long-running work — short Updates that just say "still working, no state change," to prevent the watcher's stall guard from nudging.
- **Decisions** when the human lead changes scope or approves a gate waiver — these have their own format.
- **Blockers** when external state (failed CI, locked file, missing credential) stops the slice — also their own format.
- **@OYA observations** if the optional third-agent supervisor is enabled — these arrive as Notes / Recommendations / Pauses, with the pair-side discipline that `@OYA` ≠ `@LEAD`.

See `AGENT_COLLAB_RUNBOOK.md` § Comms Protocol for the full type catalogue.
