# Heterogeneous vs homogeneous agentic development

*Is musubi's two-different-vendor pairing (Claude + Codex) actually better than the
same protocol run with two agents of the same model? What the evidence supports,
what it doesn't, and the clean experiment that would settle it.*

Companion to [benchmark-results](benchmark-results-2026-06.md) and
[collaboration-sophistication-and-benchmarks](collaboration-sophistication-and-benchmarks-2026-06.md).

---

## The honest framing first

**No homogeneous arm has ever been run.** Every corpus we have is
heterogeneous (Claude `@OPUS` + Codex `@CODA`). So this is **not** a measured
A/B result. It is: (1) what the heterogeneous data already implies, (2) a theory of
where the difference should live, and (3) a concrete experiment — with the
heterogeneous baseline now measured, so the experiment has a number to beat.

Anyone who tells you "different models are obviously better" is asserting, not
showing. The interesting question is *where* and *how much*.

## The load-bearing distinction: protocol value vs heterogeneity value

musubi bundles two different things, and they are usually conflated:

1. **The protocol** — typed messages, turn discipline, evidence receipts, peer
   review, a supervisor, a human gate. **Vendor-agnostic.** Nothing here requires
   two *different* models.
2. **The heterogeneity** — the two reviewers come from different training runs.

Almost everything the [benchmark results](benchmark-results-2026-06.md) credit —
planning-time bug catches, "looks good" reviews not surviving, the supervisor
catching stale-state replays — is **protocol value.** A *homogeneous* pair running
the same protocol would inherit most of it. The protocol is the engine; heterogeneity
is, at most, a tuning option.

So the real question narrows to: **what does heterogeneity add on top of the
protocol, and is it worth the cost of running two vendors?**

## What the heterogeneous data already hints (the framework half-tests itself)

Three signals from the existing corpus — all pointing the *same, deflationary* way:

1. **Which vendor is "the rigorous one" is configuration, not vendor.** Three test
   beds → three different deference directions
   ([cross-codebase review](external-review-2026-06-cross-codebase.md)). If the
   benefit came from an inherent vendor difference, the direction would be stable.
   It isn't. → the diversity is real but not a fixed vendor property.

2. **Unlike vendors already talk alike.** Measured role-divergence (Jensen-Shannon
   of the two coders' vocabularies, `comms-metrics.py`):

   | bed | SEI (0 = identical) |
   |---|---|
   | cc-aic | 0.053 |
   | 1-in-a-billion | 0.072 |
   | portfolio | 0.142 |

   Even *different-vendor* models diverge only slightly. A same-model pair would
   diverge *less* → the headroom heterogeneity buys is small to begin with.

3. **The framework recorded its own NULL.** Portfolio's per-cycle shadow-review,
   Cycle 8: *"same-vendor-would-have-done-as-well (on the decision); asymmetric pair
   added one non-decisive catch."* Their own instrument says the heterogeneity
   premium is sometimes ≈ zero.

4. **Both-agents-missed events still happen — even heterogeneous.** Proxy count of
   "review escape / both approved / neither caught / CI caught" admissions
   (`escape_admissions`): **cc-aic 55, 1iab 18, portfolio 7.** Heterogeneity did
   *not* eliminate correlated misses. (Proxy, keyword-based — directional, not
   exact.) Meanwhile the reviewer *does* surface issues at a healthy rate
   (`reviewer_finding_rate`: cc-aic 0.57, 1iab 0.30, portfolio 0.83) — but that is
   review *discipline* (protocol), which homogeneous would share.

## The one genuine edge for heterogeneity: uncorrelated blind spots

Here is the real, defensible case — and it is narrow:

> Two models from different training have **less-correlated failure modes.** A
> same-model pair shares blind spots: when it is wrong, it tends to be *confidently
> wrong in the same direction*, and the reviewer nods because the author's mistake
> looks correct to an identical mind. A different-model reviewer is more likely to
> *not share* that specific blind spot — so it catches the bug both same-model
> agents would have waved through together.

Heterogeneity is **blind-spot insurance**, not a raw-capability boost. Its payoff is
concentrated entirely in the **correlated-miss** column — the bug *both* agents
miss. The `escape_admissions` count (55/18/7) is exactly the column where a
homogeneous arm should do *worse*, and is the metric the experiment must isolate.

This also predicts the deflationary signals above: most of the time the author is
*not* in a blind spot, so the different-vendor reviewer adds nothing the protocol
didn't already get (→ shadow-review NULLs, low SEI). The value is rare-but-real:
cheap insurance against the expensive, confident, shared mistake.

## The clean experiment to settle it

Run the **same protocol**, same task set, three arms:

| Arm | Pair | Tests |
|---|---|---|
| **A** | Claude + Codex | heterogeneous (current) |
| **B** | Claude + Claude | homogeneous |
| **C** | Codex + Codex | homogeneous |

Score every arm with instruments that already exist (`comms-metrics.py` + the
Track-2 rater):

- **Correlated-miss rate** — bugs *both* agents approved that CI/human/restart later
  caught. *The key metric.* Hypothesis: **B/C worse than A here, and only here.*
- **Independent-catch rate** — reviewer finds a bug the author missed
  (`reviewer_finding_rate`, plus the rater's hand-count). Diversity payoff, directly.
- **Role-divergence SEI** — does heterogeneous actually diverge more than homogeneous?
  (Quantifies whether the "different minds" premise even holds in the language.)
- **Convergence quality / premature-consensus rate** — does homogeneous converge
  faster *and wronger*? (homogeneous predicted to have *more* premature consensus.)
- **Throughput + SWE-bench Verified resolve rate** per arm (Track 3) — the
  comparable headline number; tests whether A pays a *speed* cost for the insurance.

**Predicted result (what the existing data forecasts):** B and C nearly match A on
throughput and total bug-catch, but A wins specifically on **correlated-miss rate**
and shows higher SEI. If that holds, the pitch sharpens from the unfalsifiable
*"different models are better"* to the precise, defensible:

> **Heterogeneity isn't for speed or IQ — it's insurance against the bug both
> same-model agents confidently miss together. Buy it when a shared blind spot is
> expensive; skip it when throughput matters more than tail-risk.**

**What would falsify the premium:** if A's correlated-miss rate ≈ B/C's, the
heterogeneity adds nothing the protocol didn't, and musubi should be sold as a
*protocol* (run it homogeneous, cheaper). The shadow-review NULLs mean this is a live
possibility, not a strawman — which is exactly why the experiment is worth running.

## Conclusion

- **Is musubi useful for agentic development?** Yes — but the evidenced value is
  overwhelmingly the **protocol** (turn discipline, evidence receipts, supervisor,
  human gate), which is vendor-agnostic and would benefit a homogeneous team too.
- **Is heterogeneous better than homogeneous?** *Unproven, narrowly likely.* The
  honest position from the data: heterogeneity buys **uncorrelated-blind-spot
  insurance** — a small, rare, real edge in the correlated-miss column — at the cost
  of running two vendors. It is not a throughput or capability multiplier, and the
  framework's own NULLs warn against overclaiming it.
- **The defensible sell** is the protocol first, heterogeneity as a tail-risk hedge —
  and the three-arm experiment is what turns "we think different models help" into a
  number you can stand behind.

---

*Heterogeneous baseline metrics: `scripts/comms-metrics.py` (2026-06-09).
`escape_admissions` and `reviewer_finding_rate` are keyword proxies — directional,
not ground-truth; the true correlated-miss / independent-catch numbers require the
controlled three-arm run with labelled bug outcomes. No homogeneous arm has been run;
arms B and C above do not yet exist.*
