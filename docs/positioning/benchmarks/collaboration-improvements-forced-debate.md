# Forcing genuine debate — design proposal to fix premature convergence

*The cross-codebase analysis found the system's one real collaboration weakness:
disagreements resolve almost instantly and never deadlock. This doc proposes
concrete, implementable mechanisms to convert fast consensus into genuine debate
and negotiation — and ties each to existing musubi machinery and to established
team-science / multi-agent-debate constructs.*

Companion to
[collaboration-sophistication-and-benchmarks](collaboration-sophistication-and-benchmarks-2026-06.md)
and the [cross-codebase review](../reviews/external-review-2026-06-cross-codebase.md).

> **Premise update (after [benchmark-results](benchmark-results-2026-06.md)).** A
> strict per-cycle rating *partially refuted* the "never debates" claim: the newest
> cycles sustain genuine multi-round negotiation **56%** of the time with **zero
> rubber-stamps**; only **44%** of contested items converge in a single exchange,
> and nothing reaches a true impasse (counter-positions get *corrected*, not
> defended to deadlock). So these mechanisms should target *that 44%* — right-sized,
> not an overhaul of a system that never argues. The larger *measured* defect is
> communication hygiene (the SaaS bed ~30% duplicate messages), addressed separately. Keep
> that proportion in mind while reading the seven mechanisms below.

---

## The problem, stated precisely

Three independent signals say the same thing:

1. **Qualitative (corpus):** no case in ~249k lines of an agent *holding a contrary
   position after the other presented counter-evidence*. Disagreements resolve in
   ≤1 exchange via independent re-verification. Convergence is fast and consensual.
2. **Quantitative (comms-metrics.py):** **role-divergence SEI is 0.05–0.14** (Jensen-
   Shannon divergence of the two coders' vocabularies; 0 = identical). The peers
   talk almost alike — low behavioural specialization. The pair is closer to "two
   careful reviewers who agree" than "two minds in productive tension."
3. **Structural:** the protocol *rewards* convergence. The `GO` baton fires on
   agreement; nothing fires on, or even records, *sustained disagreement*. There is
   no cost to premature agreement and no credit for a defended dissent.

The reviewer's instinct — named in the corpus itself — is to *confirm-the-
implementer* (the mobile/marketplace bed `agent_comms_2026-05-10_ia-peer-suspicion.txt:347`). The
existing countermeasures (rotating default-skeptic, mandatory spot-check on
zero-finding reviews, ≥3 mutual falsification) raise the *floor* of scrutiny but
do not manufacture *debate* — they make rubber-stamping harder, not disagreement
richer. "Agreement is the failure mode, not the goal" is asserted as a slogan
(the mobile/marketplace bed `…113538.md:19`) but not yet enforced as a gate.

## Design principles

1. **Dissent must be cheap and mandatory, agreement must be earned.** Flip the
   incentive: the default is "object or steelman-the-alternative," not "approve."
2. **High-confidence agreement on high-blast-radius is suspicious, not done.**
   Operationalize the slogan: convergence should *trigger* scrutiny exactly where
   it currently ends it.
3. **Understand before you critique.** Quick rejection and quick approval are the
   same failure — neither demonstrates the reviewer modelled the author's design.
4. **Commit a position before seeing the other's.** Anchoring is what makes the
   reviewer confirm the implementer. Break it structurally.
5. **Cost-gate everything.** These mechanisms fire only on contested / high-blast-
   radius slices (via `classify-slice.sh`). The Tiny lane stays frictionless —
   debate ceremony on a typo fix is the over-encoding failure musubi already warns
   about.

## Seven mechanisms (ordered by value-to-cost)

### 1. Blind position-commitment on contested slices *(highest value, lowest cost)*
Before either coder reads the other, **both post a Position + Confidence under an
Oya-held barrier**; Oya releases both simultaneously, then a reconciliation turn.
- *Implementation:* `classify-slice.sh` already exists — add a `contested` /
  `high-blast-radius` flag; for flagged slices Oya runs the equity-research bed's
  **blind-protocol Phase 1/2** (already proven there:
  `2026-06-01_105001.txt:413` *"I will not react to @OPUS until both outputs are
  posted and @OYA opens Phase 2"*) — generalize it from the equity-research bed to all beds.
- *Lineage:* breaks Clark-style anchoring; directly attacks "confirm-the-
  implementer." This is the single change most likely to move the SEI/convergence
  numbers.

### 2. Mandatory steelman before any review verdict
A `Type: Review` message must contain a `Steelman:` section — the reviewer restates
the author's design *in its strongest form* — **before** APPROVE or
CHANGES_REQUESTED. Oya rejects verdicts lacking a genuine steelman.
- *Implementation:* new required section in the Review message template; Oya's
  scope sensor gains a "steelman present + non-trivial" check.
- *Lineage:* **Rapoport's rules of engagement** + Clark's grounding (acceptance
  phase = proof of understanding). Kills both strawman-reject and lazy-approve.

### 3. No zero-objection GO on contested slices (dissent quota)
On a flagged slice, the reviewer must file **≥1 substantive objection** OR an
explicit *"alternative X considered and rejected because Y (with evidence)."* A
bare APPROVE is not a valid baton.
- *Implementation:* extends the existing *mandatory-spot-check-on-zero-finding*
  rule into a *mandatory-dissent-or-documented-alternative* rule; codified per-agent
  like STOP rule 23/14 already is (the SaaS bed `active.txt:1711`).
- *Lineage:* CRM **two-challenge rule** — a team member is *obligated* to voice a
  concern, not merely permitted.

### 4. Confidence-divergence trigger ("agreement is the failure mode" gate)
When both coders post **high confidence + agreement** on a **high-blast-radius**
change, Oya does **not** clear it — she forces a falsification round (each agent
must produce one concrete way the change breaks).
- *Implementation:* Oya already issues `GO: no` and forces falsification ad hoc
  (the mobile/marketplace bed `…162642.md:444`). Make it a deterministic rule keyed on
  (blast_radius × confidence_agreement), not Oya's discretion.
- *Lineage:* the corpus's own *"agreement is the failure mode"* finally enforced.

### 5. Structured argumentation rounds (minimum-deliberation budget)
For an Oya-flagged **contested decision**, require a minimum of **2 argument rounds**
(claim → rebuttal → counter-rebuttal) before a `GO` is permitted — *a contested
item cannot converge in the same turn it was raised.*
- *Implementation:* the runbook **gear system** (Tiny / standard) gains a
  "Contested" gear with a turn-budget floor; Oya tracks rounds in a **disagreement
  ledger** (new close artefact alongside asymmetry/shadow-review).
- *Lineage:* **Multi-Agent Debate** (Du et al. 2023) + Toulmin argument model
  (claim/grounds/warrant/rebuttal).

### 6. Rotating adversary mandate (mandated devil's advocate)
Beyond default-skeptic: per contested slice, **one agent is explicitly tasked
"make the strongest case AGAINST shipping this"** — rotating, so dissent is
role-mandated, not personality-dependent. The adversary's objections must be
evidence-backed (receipts), never performative.
- *Implementation:* Oya assigns the adversary role in the slice brief; rotates it
  off the existing default-skeptic rotation.
- *Lineage:* CRM challenge role + red-team practice; addresses the low-SEI finding
  by *manufacturing* role divergence the vocabulary data says is missing.

### 7. Adjudication by argument quality, recorded (MAD judge)
For contested calls, Oya (or the human) adjudicates on **argument merit, not
authority**, and records *which side won and why* — feeding the existing
**shadow-review** so the framework keeps falsifying its own "unlike-pair is load-
bearing" claim with real disagreement data, not just agreement data.
- *Lineage:* MAD judge / debate adjudication; closes the loop with the
  null-result discipline already in the equity-research bed
  (`shadow-review/2026-06-08-cycle8.md:38`).

## Closing the loop: make the benchmark a live guardrail

`comms-metrics.py` already computes role-divergence (SEI) and an ack rate. Add a
**convergence-quality metric** — % of contested-flagged items that converge in ≤1
exchange (the premature-consensus proxy the Track-2 rater computes by hand) — and
report it per cycle. Then these mechanisms have a number to move: **SEI up,
premature-consensus rate down.** Spike mechanism #1 (blind position) on one bed,
measure before/after, and only roll out what actually moves the metric.

## Risks and the honest counter-argument

- **Theatre.** Mandated dissent can become performative ("I object: nit on naming").
  *Mitigation:* objections must carry receipts (the evidence-discipline norm already
  filters empty claims); Oya scores objection substance, low-substance dissent is
  flagged like a rubber-stamp.
- **Speed.** Real debate is slower. *Mitigation:* cost-gate to contested /
  high-blast-radius only; the Tiny lane stays zero-ceremony. The pair already moves
  in many small gated steps — debate is added only where blast radius justifies it.
- **The deeper question:** maybe fast convergence is *correct* when both models are
  genuinely right, and forcing debate manufactures noise. This is testable —
  mechanism #7's adjudication record will show whether forced debate *changes
  outcomes* or just adds rounds. If it never changes an outcome, that is itself a
  publishable finding (the unlike pair converges because it should), and the
  mechanisms should be dialed back. **Don't assume more friction is better — measure
  whether it changes decisions.**

## Phase 0+1 — SHIPPED (foundation + baseline metric, 2026-06-09)

The first two phases are implemented and measured. No agent behaviour changed —
this is instrumentation only, the measure-first step the proposal demands.

**What shipped:**
- `scripts/classify-slice.sh` gains a `blast_radius: high|low` field (JSON + text).
  This is a *separate axis from the lane*: high = touches a destructive/irreversible
  surface (state / schema / CI / UI) or >300 LOC. A modest multi-file code edit is
  `heavy` lane but `low` blast radius — so the later debate gates fire on blast
  radius, not on the lane, and don't ceremony-tax plain code. ("contested" stays a
  runtime/social property, not classifiable from a diff.)
- `scripts/comms-metrics.py` gains three Review-Result verdict metrics:
  `zero_finding_approve_rate`, `substantive_review_rate`, `formal_dissent_rate`.
- Tests: `tests/test_comms_metrics_convergence.py`, additions to
  `tests/test_classify_slice.py` (suite 528).

**Measured baseline** (review-result verdicts per bed):

| bed | N | zero_finding_approve | substantive | formal_dissent | SEI |
|-----|---|----|----|----|----|
| SaaS | 849 | 0.674 | 0.082 | 0.244 | 0.053 |
| mobile/marketplace | 223 | 0.780 | 0.117 | 0.103 | 0.072 |
| equity | 18 | 0.278 | 0.667 | 0.056 | 0.142 |

**Two findings from the baseline run itself:**
1. **Formal dissent is nearly unrecorded as a token.** The literal
   `changes_requested` verdict appears ~2× against ~900 approves across beds — so
   the metric had to key on Findings-block *substance* (`found` vs `not-found`),
   not the verdict word. This corroborates the proposal's premise: the protocol
   has no first-class place for "I disagree."
2. **The clean exchange-level number needs a `Slice:` key we don't have yet.**
   `zero_finding_approve_rate` is a *per-message* signal — it flags every
   zero-finding approve, including the *final* approve of a genuine multi-round
   debate. It is therefore a **ceiling** on premature consensus, not the rate
   itself. The true "converged in ≤1 exchange" number requires grouping turns by
   slice identity — a comms-protocol `Slice:` field, which is a behaviour change
   deferred to Phase 2. Until then, read these numbers as "fraction of verdicts
   that are rubber-stamp-*shaped*", and watch the *direction* they move when a
   mechanism is spiked, not their absolute level.

The high equity-research-bed `substantive` (0.667) vs low SaaS/mobile-marketplace
(0.08–0.12) is the SEI story again: the equity-research bed (blind-protocol bed)
records real findings far more often. That is the signal Phase 2 (#1 blind
position-commitment) aims to spread.

## Recommended sequence

1. Add the **convergence-quality metric** to `comms-metrics.py` (measure the
   baseline first — you can't claim improvement without it).
2. Spike **#1 blind position-commitment** on contested slices in one bed.
3. Add **#2 steelman** + **#3 dissent quota** (cheap, codify like STOP rule 23).
4. Re-measure. Only if premature-consensus drops *and* adjudication (#7) shows
   outcomes changed, roll out #4–#6.

The whole proposal is falsifiable by its own metric — which is the musubi-
consistent way to ship it.
