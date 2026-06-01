# Shadow Review — schema v1

Per-cycle artefact authored by Oya. Picks one slice from the cycle and produces a **same-vendor counterfactual review**: if the same vendor had been on both sides of the slice (Opus implementing + Opus reviewing, or Coda implementing + Coda reviewing), what would the review have caught? What would it have missed?

Lives at `docs/agents/shadow-review/<cycle-slug>.md` inside the target project. Committed. The framework's falsifiability instrument.

## Why this exists

The asymmetry corpus accumulates **evidence for** the asymmetric-vendor claim. After N cycles of catches classified by class, the corpus shows what asymmetric-vendor pairs catch. But the corpus alone can't falsify the claim — it can only corroborate. The framework's load-bearing empirical claim deserves an experimental design that could prove it wrong.

The full version of falsifiability is "shadow mode" — run a parallel same-vendor pair on the real slice and compare outcomes. That doubles compute. The lean version is what this schema captures: at cycle close, Oya picks 1 slice and *reasons through* the counterfactual. *"Here is the diff and the actual asymmetric Review Result. If Opus had been the reviewer in Coda's role on this slice, what would Opus probably have caught? What would Opus probably have missed?"* The counterfactual is Oya's best honest read, not an actual execution — but it's still empirical signal accumulating in a structured corpus.

Over time, the shadow-review corpus tests the framework's claim. If same-vendor counterfactuals reliably catch fewer / less-substantive issues than the actual asymmetric reviews, the claim is supported. If they're roughly equivalent, the claim is weaker than thought.

## File location + lifecycle

- **Path:** `docs/agents/shadow-review/<cycle-slug>.md`.
- **Author:** Oya at cycle close.
- **Cadence:** 1 per cycle. If the cycle had no review-bearing slices, skip with a one-line note in the cycle summary.
- **Slice selection:** Oya picks the slice with the **most interesting actual review** — preferentially one with surfaced disagreements (already in the asymmetry corpus), or the largest / highest-stakes slice of the cycle. Document the selection rationale in the artefact.

## Schema

```markdown
# Shadow Review — <cycle-slug>

**Cycle:** <name + dates>
**Slice selected:** <slice ID + 1-line description>
**Selection rationale:** <why this slice — most disagreements, largest, highest stakes, etc.>
**Authored by:** @OYA at <timestamp UTC>
**Actual review by:** <agent name + vendor>
**Counterfactual review modeled as:** <other agent name + same-vendor role: e.g. "Opus2 in Coda's role">

---

## Actual review (summary)

<3–5 bullets summarising the actual review's Findings I went looking for block: what classes were probed, what was found, what landed as blockers / changes-requested / approval.>

## Counterfactual review — what the same-vendor pair likely catches

<For each defect class the actual reviewer probed, Oya's honest read of whether the same-vendor counterfactual would likely have caught it. Be specific about reasoning.>

- **<class>** — likely caught / likely missed / equivalent. Rationale: <one or two sentences.>

## Counterfactual review — what the same-vendor pair likely misses

<For each issue the actual asymmetric review caught that the counterfactual would likely miss, name it specifically. This is the load-bearing section — where the asymmetric-vendor pair earned its keep.>

- <named issue + file:line if relevant>. Counterfactual likely misses because: <one or two sentences about why same-vendor priors would let this slide.>

## Counterfactual review — what the same-vendor pair might catch the asymmetric pair missed

<If applicable. Be honest. Sometimes a same-vendor pair would catch something the asymmetric pair missed because of shared training context. Empty if none observed.>

## Net read

<One paragraph: did the asymmetric pair add value on this slice, was it equivalent, or did the same-vendor counterfactual look likely to do as well? Be honest. The corpus's value depends on Oya's honesty here, not on rooting for the framework.>

**Verdict:** asymmetric-pair-added-value | equivalent | same-vendor-would-have-done-as-well | counterfactual-actually-stronger

## Caveats

- Counterfactual is reasoning, not execution. The "what Opus would have caught" line is Oya's read of Opus's training-conditioned priors on this kind of code, not a real Opus session's output.
- Single slice per cycle is sparse data. The signal is in the corpus aggregated over many cycles, not in any one report.
- Counterfactual is not blind to the actual review. Oya read the actual review before writing the counterfactual, which biases toward agreeing with what the actual review caught. v2 should explore blind authorship.
```

## Locked verdict types

| Verdict | Meaning |
|---|---|
| `asymmetric-pair-added-value` | The actual asymmetric review caught something material that the same-vendor counterfactual likely misses. The framework's claim is supported for this slice. |
| `equivalent` | The asymmetric and counterfactual reviews would likely have reached similar outcomes. The framework's claim is neither corroborated nor falsified for this slice. |
| `same-vendor-would-have-done-as-well` | The actual review's catches don't appear to require asymmetric vendor priors — same-vendor counterfactual likely catches them too. Mild evidence against the framework's claim for this slice. |
| `counterfactual-actually-stronger` | The same-vendor counterfactual would likely have caught something the actual asymmetric review missed. Strongest evidence against the framework's claim for this slice. |

## Discipline

- **Honesty trumps framework loyalty.** If the counterfactual would have done as well, say so. The corpus's value as evidence depends on its honesty.
- **Reason from priors.** What is each vendor's training-conditioned default approach to *this kind of code*? That's the load-bearing reasoning.
- **Be specific about what same-vendor would miss.** "Shared priors" is not specific enough. "Both same-vendor agents would likely accept the optimistic state-management pattern because Anthropic's training emphasises clean React patterns; an asymmetric reviewer brought in by training that emphasises operational caution catches the race condition" is.
- **Brief is better than thorough.** Each report is ~500–800 words. Long reports either over-explain or speculate too freely. The corpus's value is in the verdict + the named miss, not in the depth.

## What this is not

- Not a real shadow mode. Real shadow mode runs a parallel same-vendor pair on the same slice and compares actual outputs. This schema is the lean approximation.
- Not a definitive verdict per slice. Counterfactuals are inferences. The corpus aggregates the inferences.
- Not a claim that Oya knows what Opus or Coda would have done. It's Oya's read of training-conditioned priors based on observation over time.

## See also

- `oyakata-prompt-v0.1.md` § Cycle-close shadow review — Oya's authorship instructions.
- `asymmetry-schema.md` — sibling artefact, captures the actual asymmetric review's outcomes.

## v2+ open questions

- **Real shadow mode** — run a parallel same-vendor pair on selected slices in actual worktrees. Compare actual outputs, not counterfactuals. Cost: doubles compute on sampled slices. The lean version is a precursor that builds the corpus and the comparison muscle without the compute cost.
- **Blind counterfactual** — Oya writes the counterfactual *before* reading the actual review, then compares. Removes the anchoring bias from the lean version.
- **Cross-project counterfactual aggregation** — once musubi has multiple deployments, aggregate shadow-review verdicts across projects. The framework's claim is falsifiable at scale.
