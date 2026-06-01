# Reviewer Calibration — schema v1

Brier-scored review calibration. Each reviewer states their confidence on each `Review Result`; cycle close compares stated confidence against actual outcome; per-reviewer calibration scores accumulate over time.

Calibration data lives as a **section in the existing rules ledger** at `docs/agents/rules-ledger.yml` — not a separate file. Same artefact, two sections: `rules:` (rule-level data) and `reviewer_calibration:` (per-reviewer data).

## Why this exists

The framework's strongest empirical claim is that asymmetric-vendor pairs catch more. The asymmetry corpus + shadow-review corpus + rules ledger all measure that claim from different angles. None of them measure *per-reviewer competence* directly.

A reviewer with consistent 90% confidence and 60% accuracy is decalibrated and needs spot-checks. A reviewer with consistent 70% confidence and 70% accuracy is calibrated and earns weight. A reviewer who states 95% confidence on `architectural` findings but 50% on `test-design` findings has a known competence map.

Currently the framework treats every Review Result as equivalent in trustworthiness. After enough Brier data, that flattens. *"Coda's last 20 reviews on `spec-doc-accuracy` had 0.82 calibration; Opus's last 20 on `architectural` had 0.61."* That's the kind of statement that justifies *"trust Coda more on doc accuracy; spot-check Opus more on architecture."*

## How the protocol extends — optional `Confidence:` field

Reviewers MAY add a `Confidence: <N>%` line to the Review Result header. The value is the reviewer's stated confidence (0–100%) that the slice is shippable in the state specified by their `Result:` field. Meaning:

- `Result: approved` + `Confidence: 90%` → "I am 90% confident this slice ships cleanly as-is."
- `Result: changes_requested` + `Confidence: 75%` → "I am 75% confident that addressing the named blockers makes this slice shippable."

If the field is absent, the review is not Brier-scored. **No protocol break for non-adopters.** This is a soft on-ramp; adoption is rewarded with calibration data over time.

Example:

```
[@CODA] [2026-05-19] [09:54 UTC]
To: @OPUS
Reply required: yes
GO: no
Type: Review Result
Result: changes_requested
Confidence: 75%

Findings I went looking for:
- architectural — found: ThemeProvider omission contradicts archetype...
- spec-doc-accuracy — found: visual spec says 7 routes, covers 6...
- scope — found: directory/page.tsx not migrated despite plan saying...

<full body>

<OVER>
```

## Scoring at cycle close

For each Review Result with a `Confidence:` value, at cycle close Oya assigns an **outcome**:

| Outcome | Meaning |
|---|---|
| `confirmed` | The reviewer's `Result` held — the slice shipped cleanly (for `approved`) or the named changes were sufficient (for `changes_requested`). |
| `partially-confirmed` | Some of the reviewer's named findings held; others were resolved without the requested change OR turned out non-load-bearing. |
| `disconfirmed` | Reviewer's `Result` proved wrong — `approved` ship had a defect surface, OR `changes_requested` blockers turned out to be non-issues / overruled. |
| `pending` | Outcome not yet observable (slice shipped but hasn't been in prod long enough to confirm clean). |

Oya scores using Brier: outcome encoded as 1 (confirmed), 0.5 (partially-confirmed), 0 (disconfirmed); confidence as decimal (0.75 for 75%); Brier = (outcome − confidence)². Lower is better (perfectly calibrated review scores 0; maximally miscalibrated scores 1).

## Data shape in the ledger

Inside `docs/agents/rules-ledger.yml`, alongside `rules:` and `cycle_summary:`:

```yaml
reviewer_calibration:
  - reviewer: "@CODA"
    vendor: "OpenAI Codex"

    # Per-class breakdown — same taxonomy as the asymmetry corpus
    by_class:
      architectural:
        reviews: 12
        confidence_avg: 0.78
        outcomes:
          confirmed: 9
          partially_confirmed: 2
          disconfirmed: 1
          pending: 0
        brier_score: 0.14   # lower is better; auto-computed at cycle close
      spec-doc-accuracy:
        reviews: 8
        confidence_avg: 0.85
        outcomes:
          confirmed: 7
          partially_confirmed: 1
          disconfirmed: 0
          pending: 0
        brier_score: 0.08
      # ... per class

    # Per-cycle history — append-only
    history:
      - cycle: <cycle-slug>
        reviews_scored: <int>
        confidence_avg: <0..1>
        brier_this_cycle: <0..1>
        notable: |
          <optional 1-line note from Oya — e.g. "two disconfirmed reviews
          both on architectural class; over-confident on token namespace
          decisions">

  - reviewer: "@OPUS"
    vendor: "Anthropic Claude Code"
    # ... same shape
```

## Discipline

- **Confidence is the reviewer's honest read at write time.** Not a hedged 50% to game the score; not a 99% to perform certainty. Reviewers who consistently game (always 95%, never 50%) get caught by accumulating Brier; the corpus surfaces them naturally.
- **Outcome assignment is Oya's, not the reviewer's.** Self-grading defeats the calibration signal. Reviewers cannot edit `outcomes` fields after the fact.
- **Class assignment matches the asymmetry corpus.** Same locked taxonomy. A `Confidence` claim against a Findings block with classes A, B, C is scored against the outcome class that turned out to be load-bearing.
- **5+ reviews per class is the threshold for meaningful Brier**. Below that, the score is noise. Display all data; rely only on rows with sufficient sample size.

## Health signals — how to read calibration

After 10+ reviews per reviewer-class cell:

| Pattern | Interpretation |
|---|---|
| `brier_score < 0.10` | Well-calibrated. Reviewer's confidence tracks their actual hit rate. Treat their stated confidence as informative for routing decisions. |
| `brier_score 0.10 – 0.20` | Moderately calibrated. Some over- or under-confidence; usable but watch trends. |
| `brier_score > 0.20` | Decalibrated. Reviewer's stated confidence isn't informative; spot-check their reviews more aggressively. |
| `confidence_avg > 0.85`, `brier > 0.15` | Over-confident pattern. Reviewer is claiming high certainty on reviews that frequently get overruled. Consider tightening Findings discipline. |
| `confidence_avg < 0.65`, `brier > 0.15` | Under-confident pattern. Reviewer is hedging on reviews that turn out fine. Consider rewarding direct claims. |

## What this is not

- Not a per-reviewer scoreboard. The data is descriptive; the operator decides whether to act on it.
- Not mandatory. Reviewers without `Confidence:` don't get calibration tracked and aren't penalised — they just don't accumulate this signal.
- Not a substitute for the spot-check rule. Highly-calibrated reviewers still trigger spot-checks per the runbook's discipline; calibration just affects how *aggressively* the spot-check is performed.

## See also

- `oyakata-prompt-v0.1.md` § Cycle-close calibration scoring — Oya's outcome-assignment instructions.
- `rules-ledger-schema.md` — the parent schema. Calibration is a section of the ledger, not a separate file.

## v2+ open questions

- **Per-finding confidence.** Currently `Confidence:` is one number for the whole Review Result. v2 could put a confidence on each line of the Findings block. More granular signal, more authoring friction.
- **Time-decay weighting.** Old reviews matter less than recent ones. v2 could weight recent reviews more heavily in the calibration score.
- **Cross-vendor calibration comparison.** Direct comparison of @OPUS and @CODA calibration by class — *"who do we trust more on architectural calls?"* — becomes possible once both reviewers have enough data per class.
