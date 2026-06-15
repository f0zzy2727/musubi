# Benchmark results — musubi collaboration, scored (June 2026)

*Execution of the [benchmarking plan](collaboration-sophistication-and-benchmarks-2026-06.md)
Part 3. Track 1 (deterministic comms metrics) and Track 2 (independent LLM-rated
NOTECHS + Communication Score + convergence quality) are run and reported below.
Track 3 (SWE-bench solver run) is scoped but not executed — see the note at the end.*

Track 1 numbers come from `scripts/comms-metrics.py` (deterministic, reproducible:
re-run the command at the foot of this doc). Track 2 numbers come from an
independent LLM rater reading the newest cycles in full, citing real lines.

---

## Track 1 — Deterministic comms metrics

Computed over the full comms corpus per codebase (the SaaS bed 5,065 messages,
the mobile/marketplace bed 1,691, the equity-research bed 336).

| Metric (what it measures) | SaaS | mobile/marketplace | equity |
|---|---|---|---|
| `<OVER>` per message — *closed-loop turn discipline* | 1.01 | 1.17 | 1.01 |
| closed-loop ack rate — *frac msgs w/ explicit read-back/confirm* | 0.45 | 0.56 | 0.71 |
| evidence-block rate — *frac msgs w/ `Evidence:` section* | 0.51 | 0.35 | 0.41 |
| receipt rate — *frac msgs w/ SHA or file:line* | 0.39 | 0.52 | 0.11 |
| **role-divergence SEI** — *JS-div of the two coders' vocab (0 = identical)* | **0.053** | **0.072** | **0.142** |
| overhead TEI — *boilerplate token fraction* | 0.058 | 0.101 | 0.068 |
| **duplicate-msg rate** — *exact-dup bodies (triple-posting / relay re-post)* | **0.296** | 0.050 | 0.095 |
| consec near-dup rate — *same-speaker >0.8 overlap (ack spam)* | 0.024 | 0.004 | 0.027 |

**Reads:**
- **Turn discipline is near-perfect and stable** (`<OVER>`≈1.0 per message across all
  three, including a non-software domain). This is the most defensible quantitative
  claim — closed-loop communication, in the CRM sense, is structurally guaranteed.
- **Role-divergence (SEI) is low everywhere** (0.05–0.14). The two coders talk
  almost alike. This is the quantitative shadow of the qualitative "they converge
  easily" concern — the peers are not strongly differentiated at the language level.
  The equity-research bed (the non-software, blind-protocol bed) is ~2–3× more
  differentiated, consistent with its explicit constructor-vs-devil's-advocate role split.
- **The SaaS bed carries ~30% exact-duplicate message bodies.** This is the hygiene
  problem Track 2 flagged, now measured. *Caveat:* an unknown share is orchestrator
  **relay re-posting** across archive files (a known relay-flood class), not pure
  agent redundancy — so read 0.296 as an upper bound on agent-side ack spam. The
  mobile/marketplace bed (0.05) shows the protocol *can* run clean; the gap is the
  actionable signal.

## Track 2 — Independent LLM rating (newest cycles, full read)

NOTECHS behavioural markers (0–10), strict rater, every score line-cited:

| Codebase | Cooperation | Leadership | Situation aware | Decision-making | Mean |
|---|---|---|---|---|---|
| SaaS | 8 | 9 | 9 | 8 | **8.5** |
| mobile/marketplace | 8 | 8 | 7 | 8 | **7.75** |
| equity | 7 | 8 | 8 | 7 | **7.5** |
| **Overall** | 7.7 | 8.3 | 8.0 | 7.7 | **7.9** |

Strongest marker (Leadership 9, the SaaS bed): Oya's stale-state STOP catching an
~85-min clock skew + replayed evidence before a wrongful re-push. Weakest (SA 7, the
mobile/marketplace bed): a confidently-stated wrong generalization (*"the script does
NOT exist anywhere"*), self-corrected two turns later — honest recovery, but the miss
caps the score.

**MARBLE-style Communication Score: the SaaS bed 7 · the mobile/marketplace bed 8 ·
the equity-research bed 5 · overall 6.5.**
Per-message rigor is high (surgical reviews with file:line findings); the score is
dragged down by **redundancy**, not by weak content — confirming Track 1's
duplicate-rate. The equity-research bed's 5 reflects a message posted verbatim three times
(append/EOF failure) plus shell-interpolation corruption stripping dollar values.

## Track 2C — Convergence quality (the headline re-test)

The cross-codebase qualitative pass claimed disagreements *"resolve instantly, never
deadlock."* The strict rater quantified this over the newest cycles and **partially
refutes it:**

- **9 genuine disagreements / reviews-with-findings** identified.
- **Median exchanges to converge: 2.**
- **Converged in ≤1 exchange: 4/9 = 44%** (premature-consensus proxy).
- **Genuine multi-round negotiation (≥2 rounds, counter-position held through
  counter-evidence): 5/9 = 56%.**
- **Rubber-stamps found: 0.** Every review carried a named "findings I went looking
  for" block.

The best specimen (the SaaS bed S3): Oya probes a `0/0/0` audit line against a `+496/-1090`
lockfile diff; Opus refuses to approve and sets a 3-item bar; Coda revises; Opus
approves at 95% — then **CI catches a real escape neither caught**, forcing a repair
round and a new codified STOP rule. Genuine adversarial convergence that surfaced a
real defect — not consensus theatre.

**Reconciliation.** The original "never debates" read was an impressionistic sweep of
249k lines; the strict per-cycle count shows the newest cycles *do* sustain
multi-round negotiation 56% of the time, with zero rubber-stamps. **The convergence
weakness is real but smaller than first stated** — ~44% of contested items still
converge in a single exchange, and no disagreement was ever held to a genuine
*impasse* (counter-positions get corrected, not defended to deadlock). So the
[forced-debate mechanisms](collaboration-improvements-forced-debate.md) should target
*that 44%*, right-sized — not a system that never argues.

## What the numbers say to prioritize

1. **Communication hygiene is the largest *measured* defect**, not convergence —
   the SaaS bed's ~30% duplicate rate and the triple-posting are cheap to fix (the
   comms-file LOCK + relay maxlen fixes already shipped address part of it;
   `duplicate_msg_rate` is now a regression metric to watch).
2. **Low SEI** is the quantitative case for the rotating-adversary mechanism (#6 in
   the improvements doc) — manufacture the role divergence the vocabulary lacks.
3. **Convergence** is the *smallest* of the three and should be tuned, not overhauled
   — measure the premature-consensus rate per cycle and only escalate mechanisms if
   it doesn't fall.

## Track 3 — not executed (honest scope)

Running the musubi pair as a **SWE-bench Verified** solver to get a leaderboard-
comparable resolve rate requires the full pair-orchestration harness wired to the
SWE-bench task runner and container infra — out of scope for this analysis pass. It
remains the right way to answer "does pairing beat either model solo on a standard
task set," and is the recommended next build if a comparable headline number is
wanted. The process metrics above answer a *different* question (collaboration
quality on real work) and do not depend on it.

---

## Reproduce

```sh
python3 scripts/comms-metrics.py \
  <saas-bed>/docs/agents \
  <mobile-bed>/docs/agents \
  <equity-bed>/docs/agents \
  --json /tmp/comms-metrics.json
```

Track 2 is an LLM-rated pass over the newest cycle in each bed (the SaaS bed
`comms/active.txt` + `archive/agent_comms_2026-06-09_hardening-sprint.txt`, the
mobile/marketplace bed `archive/comms-active-archive-20260606-113538.md`, the
equity-research bed `archive/agent_comms_2026-06-01_105001.txt`); re-run by handing
those files to an
independent rater with the NOTECHS + Communication-Score + convergence-quality
rubric.

*Track 1: deterministic, 2026-06-09. Track 2: single independent LLM rater, newest
cycles, strict scoring — a second rater would tighten the convergence numbers
(inter-rater reliability not yet computed; that is the Track-2 hardening step).*
