# Mixed models vs same models in agentic development

*Is musubi's two-different-vendor pairing (Claude + Codex) actually better than the
same protocol run with two agents of the same model? What the evidence supports,
what it doesn't, and the clean experiment that would settle it.*

Companion to [benchmark-results](../benchmarks/benchmark-results-2026-06.md) and
[collaboration-sophistication-and-benchmarks](../benchmarks/collaboration-sophistication-and-benchmarks-2026-06.md).

---

## The honest framing first

**No same-model arm has ever been run.** Every corpus we have is
mixed-model (Claude `@OPUS` + Codex `@CODA`). So this is **not** a measured
A/B result. It is: (1) what the mixed-model data already implies, (2) a theory of
where the difference should live, and (3) a concrete experiment — with the
mixed-model baseline now measured, so the experiment has a number to beat.

Anyone who tells you "different models are obviously better" is asserting, not
showing. The interesting question is *where* and *how much*.

## The load-bearing distinction: protocol value vs model-mixing value

musubi bundles two different things, and they are usually conflated:

1. **The protocol** — typed messages, turn discipline, evidence receipts, peer
   review, a supervisor, a human gate. **Vendor-agnostic.** Nothing here requires
   two *different* models.
2. **The model-mixing** — the two reviewers come from different training runs.

Almost everything the [benchmark results](../benchmarks/benchmark-results-2026-06.md) credit —
planning-time bug catches, "looks good" reviews not surviving, the supervisor
catching stale-state replays — is **protocol value.** A *same-model* pair running
the same protocol would inherit most of it. The protocol is the engine; model-mixing
is, at most, a tuning option.

So the real question narrows to: **what does model-mixing add on top of the
protocol, and is it worth the cost of running two vendors?**

## What the mixed-model data already hints (the framework half-tests itself)

Three signals from the existing corpus — all pointing the *same, deflationary* way:

1. **Which vendor is "the rigorous one" is configuration, not vendor.** Three test
   beds → three different deference directions
   ([cross-codebase review](../reviews/external-review-2026-06-cross-codebase.md)). If the
   benefit came from an inherent vendor difference, the direction would be stable.
   It isn't. → the diversity is real but not a fixed vendor property.

2. **Unlike vendors already talk alike.** Measured role-divergence (Jensen-Shannon
   of the two coders' vocabularies, `comms-metrics.py`):

   | bed | SEI (0 = identical) |
   |---|---|
   | SaaS | 0.053 |
   | mobile/marketplace | 0.072 |
   | equity | 0.142 |

   Even *different-vendor* models diverge only slightly. A same-model pair would
   diverge *less* → the headroom model-mixing buys is small to begin with.

3. **The framework recorded its own NULL.** The equity-research bed's per-cycle shadow-review,
   Cycle 8: *"same-vendor-would-have-done-as-well (on the decision); asymmetric pair
   added one non-decisive catch."* Their own instrument says the model-mixing
   premium is sometimes ≈ zero.

4. **Both-agents-missed events still happen — even mixed-model.** Proxy count of
   "review escape / both approved / neither caught / CI caught" admissions
   (`escape_admissions`): **the SaaS bed 55, the mobile/marketplace bed 18, the
   equity-research bed 7.** Model-mixing did *not* eliminate correlated misses.
   (Proxy, keyword-based — directional, not exact.) Meanwhile the reviewer *does*
   surface issues at a healthy rate (`reviewer_finding_rate`: the SaaS bed 0.57,
   the mobile/marketplace bed 0.30, the equity-research bed 0.83) — but that is
   review *discipline* (protocol), which same-model would share.

## The one genuine edge for model-mixing: uncorrelated blind spots

Here is the real, defensible case — and it is narrow:

> Two models from different training have **less-correlated failure modes.** A
> same-model pair shares blind spots: when it is wrong, it tends to be *confidently
> wrong in the same direction*, and the reviewer nods because the author's mistake
> looks correct to an identical mind. A different-model reviewer is more likely to
> *not share* that specific blind spot — so it catches the bug both same-model
> agents would have waved through together.

Model-mixing is **blind-spot insurance**, not a raw-capability boost. Its payoff is
concentrated entirely in the **correlated-miss** column — the bug *both* agents
miss. The `escape_admissions` count (55/18/7) is exactly the column where a
same-model arm should do *worse*, and is the metric the experiment must isolate.

This also predicts the deflationary signals above: most of the time the author is
*not* in a blind spot, so the different-vendor reviewer adds nothing the protocol
didn't already get (→ shadow-review NULLs, low SEI). The value is rare-but-real:
cheap insurance against the expensive, confident, shared mistake.

## The clean experiment to settle it

Run the **same protocol**, same task set, three arms:

| Arm | Pair | Tests |
|---|---|---|
| **A** | Claude + Codex | mixed-model (current) |
| **B** | Claude + Claude | same-model |
| **C** | Codex + Codex | same-model |

Score every arm with instruments that already exist (`comms-metrics.py` + the
Track-2 rater):

- **Correlated-miss rate** — bugs *both* agents approved that CI/human/restart later
  caught. *The key metric.* Hypothesis: **B/C worse than A here, and only here.*
- **Independent-catch rate** — reviewer finds a bug the author missed
  (`reviewer_finding_rate`, plus the rater's hand-count). Diversity payoff, directly.
- **Role-divergence SEI** — does mixed-model actually diverge more than same-model?
  (Quantifies whether the "different minds" premise even holds in the language.)
- **Convergence quality / premature-consensus rate** — does same-model converge
  faster *and wronger*? (same-model predicted to have *more* premature consensus.)
- **Throughput + SWE-bench Verified resolve rate** per arm (Track 3) — the
  comparable headline number; tests whether A pays a *speed* cost for the insurance.

**Predicted result (what the existing data forecasts):** B and C nearly match A on
throughput and total bug-catch, but A wins specifically on **correlated-miss rate**
and shows higher SEI. If that holds, the pitch sharpens from the unfalsifiable
*"different models are better"* to the precise, defensible:

> **Model-mixing isn't for speed or IQ — it's insurance against the bug both
> same-model agents confidently miss together. Buy it when a shared blind spot is
> expensive; skip it when throughput matters more than tail-risk.**

**What would falsify the premium:** if A's correlated-miss rate ≈ B/C's, the
model-mixing adds nothing the protocol didn't, and musubi should be sold as a
*protocol* (run it same-model, cheaper). The shadow-review NULLs mean this is a live
possibility, not a strawman — which is exactly why the experiment is worth running.

## Conclusion

- **Is musubi useful for agentic development?** Yes — but the evidenced value is
  overwhelmingly the **protocol** (turn discipline, evidence receipts, supervisor,
  human gate), which is vendor-agnostic and would benefit a same-model team too.
- **Is mixed-model better than same-model?** *Unproven, narrowly likely.* The
  honest position from the data: model-mixing buys **uncorrelated-blind-spot
  insurance** — a small, rare, real edge in the correlated-miss column — at the cost
  of running two vendors. It is not a throughput or capability multiplier, and the
  framework's own NULLs warn against overclaiming it.
- **The defensible sell** is the protocol first, model-mixing as a tail-risk hedge —
  and the three-arm experiment is what turns "we think different models help" into a
  number you can stand behind.

---

*Mixed-model baseline metrics: `scripts/comms-metrics.py` (2026-06-09).
`escape_admissions` and `reviewer_finding_rate` are keyword proxies — directional,
not ground-truth; the true correlated-miss / independent-catch numbers require the
controlled three-arm run with labelled bug outcomes. No same-model arm has been run;
arms B and C above do not yet exist.*
