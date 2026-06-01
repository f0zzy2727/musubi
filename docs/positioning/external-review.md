# External review of musubi in production

**Methodology.** Three independent LLM reviewers analysed an eight-week corpus of real musubi-style sessions — approximately 5 MB of comms across 45 archived cycle logs from a production multi-tenant codebase. Each reviewer worked from the raw archive without coordination. The raw corpus is private; the reviews are summarised below.

| Reviewer | Vendor | Role in audit |
|---|---|---|
| Gemini | Google | Cold third-party reviewer; no prior context |
| Codex | OpenAI | Inside-the-system, same vendor as the implementer pair's Codex agent |
| Opus | Anthropic | Inside-the-system, same vendor as the implementer pair's Claude Code agent |

What matters for the finding below is the reviewers' asymmetric *structural positions* (one cold outsider, two same-vendor insiders), not the specific model versions or raw capability. A re-run on different model versions should reproduce the structural finding even if individual catches differ.

This document captures *what an outside reader sees* in an operating musubi practice, not what the protocol *claims* it should produce.

---

## Quantitative baseline

From the eight-week archive:

| Signal | Count |
|---|---|
| Comms archives | 45 cycle logs |
| Total lines | 101,000+ |
| `Type:` message headers | 3,063 |
| `<OVER>` turn markers | 3,377 |
| Review requests | 565 |
| Review results | 720 |
| Explicit `GO: yes` baton handoffs | 77 |
| `@LEAD` references | 3,100+ |

Read together: the review-result-to-review-request ratio (720:565) suggests some reviews return multiple result messages, and reviews are happening at high frequency. The `<OVER>`-per-Type ratio is roughly 1.1, indicating reliable turn-signalling discipline. The GO baton fires roughly twice a day on average. (These are mechanical grep counts over the archive — a trend proxy, not an audit; read the rates as indicative.)

---

## Convergent findings (where all three reviews agreed)

1. **The protocol catches real bugs at planning time, not just at code time.** All three reviewers cited specific incidents: merge-conflict catches before code was written, fixture-drift root causes diagnosed during review, capsule-staleness flagged before further execution, copy-duplication caught by peer eye.
2. **Evidence discipline is doing what it claims.** Receipts (file paths, commit SHAs, command output, line numbers) appear consistently. "Looks good" reviews don't survive. The Action/Evidence/Result/Next format is designed so that a progress claim without evidence is visibly empty — and in this corpus, that's how it played out.
3. **The human lead operates as a strategic gate, not a message relay.** @LEAD decisions concentrate on scope, push approval, product calls, and risk acceptance. Implementation details get resolved between the agents.
4. **The system learns from failure.** Incidents become gates: production-start smoke checks added after a cycle shipped runtime breakage, pre-push CI baseline checks added after an extended red-main period, copy-guard scripts added after a UI audit, capsule discipline tightened after state-drift incidents. Patterns retire rather than recurring.
5. **Coordination overhead is real.** All three reviewers flagged that the protocol generates substantial volume — message turns, capsule updates, handoffs, I&A patches. The protocol catches bugs *and* the protocol is heavy.

---

## Divergent findings (what each reviewer surfaced uniquely)

- **Gemini** — flagged "brittleness to context loss": the architecture's dependence on `current-state.md` + handoff + comms as authoritative state means any corruption is expensive to recover from. Read communication style closely; missed structural dynamics.
- **Codex (Coda)** — quantitative thoroughness (the numbers above), strongest articulation of the "no lightweight lane" issue (protocol overhead on trivial work), proposal for per-cycle executive summaries to make the forensic archive skim-able. Internal blindspot: did not flag asymmetric-deference (see below).
- **Claude Opus** — flagged "asymmetric deference": the runbook assigns Coda as default-sceptic, but the scepticism only fires upward (toward Opus's plans). Opus's reviews of Coda's execution surface fewer findings. The agents-as-colleagues asymmetry is half-firing. Also flagged that self-improvement is human-gated — the protocol diagnoses anti-patterns *after* @LEAD flags them, not in flight.

The fact that two of the three independent reviews missed the asymmetric-deference pattern is itself informative. Inside the system, it doesn't show. Third-party perspective is what surfaces it.

---

## Bottom line — convergent reading across all three

> *"High-maturity, high-productivity, and still slightly over-communicative. The agents and leader have built a credible operating rhythm for complex production work. The next maturity step is not adding more rules; it is making the existing rules cheaper to follow and easier to skim."*
> — Codex assessment, 2026-05-14

The protocol works. The protocol is heavy. Both are true. After eight weeks of sustained operation, the practice has moved beyond prompt-level coordination into a real operating model with explicit roles, evidence standards, handoffs, state recovery, peer review, and risk gates. The remaining work is reducing the protocol's overhead while keeping its discriminatory power — not tightening it further.

---

## Maturity ratings

| Reviewer | Maturity | Productivity |
|---|---|---|
| Gemini | implicit "very high" | implicit "very high" |
| Codex | "advanced, but still process-heavy" | "high" |
| Opus | 7/10 | 6.5/10 |

The convergent middle — "advanced but process-heavy, catches real bugs, costs real time" — is closer to ground truth than either pole. Opus is the most critical reader (no skin in the system); Codex is generous but precise on costs; Gemini reads style rather than dynamics.

---

## What this is evidence of

Musubi's value proposition is *not* a faster pipeline. It's that two differently-trained LLMs operating as asymmetric peers catch a class of bugs that same-model or pipeline-style setups don't. The eight-week corpus is the first publicly-reported evidence base of that pattern running at production scale, with three independent reviews confirming the behaviour shows up in the artefacts — not just in the framing.

For teams evaluating multi-agent collaboration: the cost is real (heavy comms, capsule maintenance, occasional ack-loops). The bug-catch rate is also real, with specific examples in every cycle. Whether the trade is worth it depends on the cost of the bugs you're catching versus the cost of the protocol you're carrying.
