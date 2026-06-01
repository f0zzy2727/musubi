<!-- musubi-managed: this file is updated by `bootstrap.sh` from the musubi repo. To fork it, delete this marker; the bootstrap will then warn and diff instead of overwriting. -->

# Dev Strategy

A daily cadence for AI-assisted development.

> **Optional companion to the runbook.** The runbook is per-cycle protocol (every commit). This document is week-over-week rhythm (every cycle). Adopt it if you want a structured rhythm; ignore it if you have your own.

---

## What this is

A working rhythm for an operator running an AI-assisted codebase day to day. Five sprint types, each a day in length, sequenced in a repeating pattern with two event-triggered extensions for compliance and load.

In AI-assisted development, a *sprint* is a day. That is the unit the rest of this document is built on. A sprint is not a fortnight of meetings followed by a demo — it is a single focused day of work with a defined shape, a clear deliverable, and a stop time at the end.

This cadence is the *operating mode* of a healthy app — it keeps the codebase tested, the AI agents calibrated, and the operator sane over months of sustained work. Before a project is healthy, a recovery plan applies; this cadence is what comes after.

---

## Why this shape

AI-assisted development has specific failure modes that calendar agile and ship-fast both miss:

- **Tests lag features.** AI ships features faster than it ships tests. Without a dedicated catch-up day, test debt compounds invisibly.
- **AI extends rather than challenges.** Given an existing pattern, AI elaborates on it. Whether that pattern is right or wrong rarely gets questioned. Independent audit days break that loop.
- **The AI agents themselves drift.** Yesterday's CLAUDE.md rule is today's blind spot. Without a structured way to update the rules, the same mistakes recur on item 47 that were caught on item 3.
- **Compliance and capacity are silent until they aren't.** An app can run for months without a regulatory issue or a capacity ceiling, and then both arrive at once. Triggered sprints catch them at the right moment — when something material has changed.

The cadence below addresses each of these directly. It is not the only valid rhythm, but it is one that holds up under sustained AI-assisted work without producing burnout or drift.

---

## The five sprint types

| # | Type | Purpose | Length |
|---|---|---|---|
| 1 | **Dev Sprint** | Build a feature or fix a defect | One day per logical unit of change |
| 2 | **Independent Architecture Audit Sprint** | Read what the dev sprints produced with fresh eyes | One day |
| 3 | **Hardening Sprint** | Patch the gaps the audit found and the tests the dev sprints skipped | One day |
| 4 | **Inspect / Adapt Sprint** | Update CLAUDE.md, AGENTS.md, and the cadence itself | Half a day |

Plus two event-triggered extensions:

| # | Type | Trigger | Length |
|---|---|---|---|
| 5 | **Compliance Sprint** | A new piece of major functionality has shipped that touches data, auth, payments, AI handling, or platform terms | One to two days |
| 6 | **Load Testing Sprint** | A new piece of major functionality has shipped that adds compute load, AI calls, database load, or user concurrency | One day |

The first four run as a continuous cycle. The last two slot in when their triggers fire, replacing or extending the Hardening Sprint that follows the relevant feature.

---

## The core cycle

```
Dev → Dev → ... → Dev → Audit → Harden → Adapt → repeat
```

The number of consecutive dev sprints is not fixed. It is whatever the change in flight requires. A small bug fix is one day. A new feature might be three or four. A larger one, a week. The audit follows the change, not a calendar.

The discipline is that *no audit is ever skipped*. Whatever the dev work was — small or large — it earns an audit before the next change starts. The audit is the gate, not the calendar.

This produces a rhythm that, in practice, looks like:

| Day | Sprint type | Notes |
|---|---|---|
| Mon | Dev | Building feature X |
| Tue | Dev | Continuing feature X |
| Wed | Audit | Independent review of X |
| Thu | Harden | Tests, docs, gaps from Wed |
| Fri (am) | Adapt | Update rules, plan next |
| Fri (pm) | — | Real recovery time |
| Mon | Dev | Building feature Y |
| Tue | Audit | Y was small |
| Wed | Harden | |
| Thu (am) | Adapt | |
| Thu (pm) | Dev | Starting feature Z |

The cadence flexes to match the work. The *sequence* never breaks.

---

## Sprint 1 — Dev Sprint

**Purpose.** Build something. A feature, a fix, a refactor with a stated reason.

**What it contains.**
- A discussion phase to capture decisions before code is written.
- A planning phase to produce the change spec, including the test list.
- An execution phase to produce the code.
- Tests that pass before the day ends — not perfect coverage, but the safety net for what was built.
- A clean commit on a short-lived branch with a one-sentence PR description (or directly to main with human approval, per your branching default).

**What it does not contain.**
- No *"while I'm in here"* refactors. The change in flight is the only change.
- No undocumented decisions. Anything material captured in your planning directory.
- No skipped CI. Green before merge, no exceptions.

**Exit criteria.** The change is merged or, if a multi-surface change, ready for verification steps. The test list from the plan phase has been executed.

**Stop time.** End of day. If the work is unfinished, it continues into another Dev Sprint. The day still ends.

---

## Sprint 2 — Independent Architecture Audit Sprint

**Purpose.** Read the codebase with fresh eyes — specifically *not* the eyes that built it.

**Why it works.** AI agents working sequentially elaborate on what came before. The third feature in a row inherits the assumptions of the first. Independent audit breaks the loop because it reads the architecture as a whole, not as a sequence of additions.

**What it contains.**
- Run a code-review pass against the codebase at its current state, with a fresh context window.
- Run a design-review pass against the architecture and data-model docs to check they still match the code.
- Specifically ask: where has duplication accumulated? Where do three features now share a fragile pattern that wants to become a shared abstraction? Where does the architecture diverge from your `ARCHITECTURE.md`? Where has a recent change introduced a class of bug that did not exist before?
- Produce `docs/audits/<date>-architecture.md` with findings, severity-ordered.

**What it does not contain.**
- No code changes. The audit is read-only.
- No tests. Tests come tomorrow.
- No defence of decisions. The audit asks questions; the operator answers them in writing or in the next sprint, not by arguing back at the AI.

**Exit criteria.** A dated audit document exists. Findings have severity tags. Anything `critical` or `high` is queued for tomorrow's Hardening Sprint.

**A note on freshness.** This sprint is more useful when run in a fresh AI session — new context window, no carry-over from the dev sprints. The point is independent reading, not an extension of yesterday.

---

## Sprint 3 — Hardening Sprint

**Purpose.** Catch up on everything the dev sprints produced but did not finish: tests, docs, audit findings.

**What it contains.**
- Address every `critical` and `high` finding from the audit.
- Add the tests that the dev sprints skipped (characterisation tests, regression tests for any bug fixed, contract tests if a backend change shipped).
- Update `ARCHITECTURE.md`, `DATAMODEL.md`, and any other living docs to match the code as it now is.
- Run mutation testing on the code added or changed in the last cycle. Confirm tests catch deliberate breaks.
- Confirm CI is green and the dashboard shows no new errors from the recent dev work.

**What it does not contain.**
- No new features. Hardening only.
- No medium or low audit findings. Those go in the backlog and get addressed when the right Dev Sprint takes them.

**Exit criteria.** Every `critical` and `high` finding has either been resolved or moved to the backlog with a documented reason. Tests pass. Docs match code.

**A useful test.** At the end of this sprint, the question *"if I disappeared tomorrow, could a competent stranger pick up the codebase?"* should be more truthfully answerable than it was at the start of the cycle. If not, hardening did not happen.

---

## Sprint 4 — Inspect / Adapt Sprint

**Purpose.** Improve the way the next cycle runs. The cadence itself is a deliverable.

**What it contains.**
This is the half-day sprint. Three structured questions, each answered in writing:

1. **What did the AI agents get wrong this cycle?** Not bugs in code — bugs in *behaviour*. Where did either agent produce confidently-wrong output? Where did the cross-review miss something the human caught? Where did an agent claim done when it wasn't?
2. **What pattern, if added to CLAUDE.md or AGENTS.md, would prevent that next time?** Specific, concrete, enforceable. Vague rules don't get followed. Every new rule gets a `Mechanism:` block (see the runbook's [Rule Quality](AGENT_COLLAB_RUNBOOK.md#rule-quality) section).
3. **What is the cadence itself missing?** Should there be a sprint type that doesn't exist yet? Is one of the existing sprints producing diminishing returns?

The answers go into:
- `CLAUDE.md` — new rules added; ineffective rules removed.
- `AGENTS.md` — same treatment.
- `docs/cadence-log/<date>.md` — a one-page record of what changed and why.

**What it does not contain.**
- No code changes.
- No defensive justifications. If a rule isn't being followed, the question is whether it should exist, not who failed to follow it.

**Exit criteria.** CLAUDE.md is more accurate at the end of the day than at the start. The next Dev Sprint will benefit from at least one improvement made today.

**A discipline that pays off.** Once a quarter, read the last twelve `cadence-log/` entries in a single sitting. Patterns emerge that are invisible at the daily level. Some rules added six months ago are no longer needed; others should never have been added; one or two were the most valuable changes ever made.

---

## Sprint 5 — Compliance Sprint (event-triggered)

**Trigger.** A piece of major functionality has shipped that touches:

- Personal data collection, processing, or transfer.
- Authentication, authorisation, or session management.
- Payment flows or subscription handling.
- AI handling that materially changes what the model does or which data it sees.
- Platform terms (App Store, Play Store, EU AI Act, GDPR, regional consumer law).
- A new market or jurisdiction.

The trigger is *material change*, not calendar time. A small text fix to a privacy policy doesn't trigger this sprint. Adding a second AI provider does. Adding a new sign-in method does. Launching in a new market does.

**What it contains.**
- Re-run the compliance audit checks for the area that changed.
- Update the privacy policy, the data-processing record, and any user-facing disclosures to match the new behaviour.
- If iOS: re-check the App Store privacy nutrition labels and the Reviewer Notes.
- If EU users: re-check GDPR data export, deletion, and the legal basis for any new processing.
- If new AI behaviour: re-check disclosure obligations under the EU AI Act.
- Document the change in `docs/compliance-log/<date>-<feature>.md` so the next compliance review starts from a known point.

**What it does not contain.**
- No code changes that aren't directly required by compliance findings.
- No optimistic interpretation of grey areas. If something is unclear, it goes to your engineer or compliance contact, not to AI.

**Exit criteria.** A dated compliance log entry exists. Any privacy or terms documents are updated. Any necessary platform metadata is updated. Any genuinely unclear item is escalated, not deferred.

**Length.** One day for narrow changes (single-area). Two days when multiple compliance surfaces are touched at once.

---

## Sprint 6 — Load Testing Sprint (event-triggered)

**Trigger.** A piece of major functionality has shipped that adds:

- New compute load (a heavier endpoint, a new background job).
- New AI API calls, especially expensive ones.
- New database load (a new query pattern, a new index requirement).
- New user concurrency (a feature that increases simultaneous active users).

Same principle as compliance: material change, not calendar time. Adding an AI-powered feature triggers this sprint. Renaming a button does not.

**What it contains.**
- Re-run the load testing scenarios for the path that changed.
- Capture: median and p95 latency, error rate, AI provider rate-limit hits, cost per session at expected and at 3× expected load.
- Compare against the previous capacity baseline. Note any regression.
- If a regression exists, decide: accept it (with documentation), fix it (queue a Dev Sprint), or roll back the feature (rare but valid).
- Update `CAPACITY.md` with the new numbers and the date.

**What it does not contain.**
- No general optimisation work. The sprint is specifically about establishing whether the recent change broke capacity assumptions, not about making the app faster overall.
- No comparison to industry benchmarks. The relevant comparison is yesterday's app vs today's app.

**Exit criteria.** Capacity numbers exist for the changed path. Any regression has a documented decision attached. CAPACITY.md reflects current reality.

**Length.** One day for most changes. Longer if the load testing reveals a deep capacity issue that needs investigation in the same sprint.

---

## How the sprints interact

The five sprint types form a small but interlocked system. Each one consumes outputs from the previous and produces inputs for the next.

| Sprint | Consumes | Produces |
|---|---|---|
| Dev | The plan, the spec, the user need | Code, tests for the change, an updated PR |
| Audit | The codebase as it now is | Severity-ordered findings document |
| Harden | The audit findings, the dev sprints' test gaps | Closed audit items, fuller test coverage, current docs |
| Adapt | The cycle's behavioural data | Updated CLAUDE.md, cadence-log entry |
| Compliance | A material change | Updated compliance docs, platform metadata, log entry |
| Load | A material change | Updated CAPACITY.md, regression decisions |

The interlock matters. Skipping the audit means the harden sprint has nothing structured to work on. Skipping the harden sprint means the adapt sprint has no recent quality data to learn from. Skipping the adapt sprint means the next cycle inherits yesterday's mistakes.

The cadence works because each sprint is necessary for the next.

---

## What stays out

Some things deliberately do not fit this rhythm:

- **Multi-day deep refactors.** If a refactor needs more than a single Dev Sprint, it gets its own milestone with its own discuss/plan/execute/verify cycle. The cadence above resumes when the milestone is closed.
- **Real production incidents.** A live outage breaks the cadence — that is correct. Use your break-glass hotfix path. The cadence resumes when the incident is closed and the postmortem is written.
- **Strategic decisions.** *"Should we keep this product line?"* is not a sprint question. It is a founder question that happens in conversation, with reflection time, not on a daily cadence.
- **Long-form writing and design work.** A new product strategy or a deep technical doc lives outside this cadence. Some work is not sprint-shaped.

The cadence is a *day-to-day operating rhythm*, not a universal system. Most work fits inside it. Some doesn't. Knowing which is which is its own discipline.

---

## How this connects to the other documents

| Document | Role | Time horizon |
|---|---|---|
| `AGENT_COLLAB_RUNBOOK.md` | Per-cycle protocol authority | Always loaded, every action |
| `PAIR_OPERATING_MODEL.md` | Pattern + adoption guide | Read once at adoption, occasionally re-read |
| `CLAUDE.md` / `AGENTS.md` | Per-action rules for AI agents | Always loaded, every action |
| `DEV_STRATEGY.md` *(this document)* | Day-to-day cadence | Daily and weekly, ongoing |

The runbook handles individual cycles. The cadence is the connective tissue — the rhythm that ties cycles together day by day.

---

## A worked cycle

A representative two-week period:

| Day | Sprint | What happened |
|---|---|---|
| Mon | Dev | Built the new "shared library" feature. AI generated the API endpoints, the iOS view, the database migration. Tests for the happy path. Merged. |
| Tue | Dev | Polished the feature based on overnight thoughts. Added two error-path tests. Merged. |
| Wed | Audit | Ran the architecture audit with a fresh context. Found two duplications across the new code and the existing user-library code. Found one missing input validation. Added all three to the harden queue. |
| Thu | Harden | Refactored the duplications into a shared service. Added the input validation. Added contract tests for the new endpoint. Updated `ARCHITECTURE.md` to describe the shared service. Ran mutation testing — three weak tests surfaced and were rewritten. |
| Fri (am) | Adapt | Reflected: the audit caught a duplication that should have been caught earlier. Added a rule to CLAUDE.md: *"When extending a feature that resembles an existing one, propose the shared abstraction in the plan phase."* Updated cadence-log. |
| Fri (pm) | — | Walked the dog. |
| Mon | Dev | Started a small bug fix. |
| Tue | Audit | The fix was small enough that audit took half a morning. Then started the next Dev Sprint in the afternoon: adding a third AI provider as fallback. |
| Tue (pm) | Dev | First half of the new-provider integration. |
| Wed | Dev | Finished the new-provider integration. Merged. |
| Thu | Audit | Two findings. One about error handling on provider failover, one about cost tracking. |
| Fri | Harden + Compliance + Load | The new provider triggered both compliance (new data processor in the chain — privacy policy update needed) and load testing (new AI API to baseline). Spent the morning on harden + compliance, the afternoon on load. |
| Following Mon (am) | Adapt | Reflected: triggered sprints landing on the same day worked but felt rushed. Added to cadence-log: consider splitting compliance and load across two days when both are triggered by the same feature. |

That's the rhythm. It produces shipped features, a tested codebase, current docs, an updated rule set, and an operator who finishes the week with the system in writing rather than in their nervous system.

---

## Signs the cadence is working

- Each cycle's audit finds *fewer* `critical` and `high` items than the previous one.
- The Adapt sprint's CLAUDE.md changes are smaller over time, not larger. The early changes were structural; later ones are nuance.
- The same audit finding does not appear in two consecutive cycles. If it does, the harden sprint isn't actually addressing root causes.
- The cadence-log reads as a meaningful history, not a series of nearly-identical entries.
- Triggered sprints (compliance, load) become routine rather than alarming.
- The operator can describe last week's work in five sentences without consulting notes.

---

## Signs the cadence is drifting

- Audits are getting longer because nothing was hardened in the previous cycle.
- Adapt sprints are becoming defensive — explaining why a rule wasn't followed rather than improving the rules.
- Dev sprints are stretching to two and three days routinely. Either the work is genuinely larger and needs to be a milestone, or scope is creeping inside individual sprints.
- Compliance and load sprints are being deferred because *"things are stable."* That is precisely when something is changing in a way nobody noticed.
- The cadence-log goes silent for weeks at a time. Adapt sprints are being skipped.
- The operator can't remember when the last triggered sprint ran.

When drift appears, the response is not heroic catch-up. It is a single Inspect / Adapt sprint dedicated to figuring out what changed, with the question: *"What is this rhythm telling me about what needs to change?"*

---

## Failure modes and recoveries

A short register of the most common ways this cadence breaks down, and how to recover.

| Failure mode | Recovery |
|---|---|
| Dev sprints stretch to a week each | Convert to a multi-cycle milestone; resume cadence when the milestone closes. |
| Audits stop finding things | Almost certainly the audit context isn't fresh enough. Run the next audit in a brand-new AI session with no prior context. |
| Harden sprints become a dumping ground for medium and low audit findings | Tighten the rule: only `critical` and `high` from the audit get hardened in-cycle. Everything else is backlog. |
| Adapt sprints get skipped on busy weeks | The cadence-log going dark is the first signal. Recovery: schedule the next Adapt as the highest-priority sprint, even ahead of dev work. |
| Compliance gets deferred because *"no triggers"* | Run a manual review every six months regardless of triggers. Triggers can be missed; calendars catch what triggers miss. |
| Load testing gets deferred because *"nothing has changed"* | Same. Quarterly capacity check regardless. |
| The operator burns out | Reduce dev sprint count between audits. The cadence is supposed to sustain, not extract. If it isn't sustaining, it has been over-scaled. |

---

## A final note

This cadence is one rhythm among several that could work. Its specific shape — daily sprints, audit gates, structured reflection, event-triggered compliance and load — is suited to AI-assisted solo development on apps that touch payments, AI APIs, and platform compliance. Different work shapes will want different rhythms.

What it offers, more than the specific structure, is *the principle that the meta-process is itself a deliverable*. The Adapt sprint is the unusual move. Most development methodologies ask *"what should we build?"* This one also asks, every cycle, *"how should we build it differently?"* That second question is what keeps an AI-assisted codebase from drifting toward the AI's defaults — and the AI's defaults, for all their helpfulness, are not where a serious product wants to live.

The cadence is the small daily move. The compounding is what comes from never skipping the cycle.
