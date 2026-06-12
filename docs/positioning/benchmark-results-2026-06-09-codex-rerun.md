# Benchmark results rerun — Codex check (2026-06-09)

This is a direct rerun of `docs/positioning/ANALYSIS-METHOD.md` by Codex. It
does not replace `benchmark-results-2026-06.md`; it records a second pass so the
non-deterministic Track 2 rating can be compared against Claude's earlier pass.

## Inputs

Track 1 used the full `docs/agents` comms trees:

| Bed | Path |
|---|---|
| cc-aic / Sli | `~/Dev/aic/cc-aic/docs/agents` |
| 1-in-a-billion-paradise | `~/Dev/1-in-a-billion-paradise/docs/agents` |
| portfolio-experiment | `~/Dev/portfolio-experiment/docs/agents` |

Track 2 used the current active file plus newest substantial archive per bed:

| Bed | Files |
|---|---|
| cc-aic | `comms/active.txt`; `archive/agent_comms_2026-06-09_hardening-sprint.txt` |
| 1-in-a-billion-paradise | `comms/active.txt`; `archive/comms-active-archive-20260606-113538.md` |
| portfolio-experiment | `comms/active.txt`; `archive/agent_comms_2026-06-09_125311.txt` |

## Phase A — Corpus Spine

```text
cc-aic lines=157524 Type=4710 OVER=5120 @OYA=1945
1-in-a-billion lines=79886 Type=1942 OVER=1981 @OYA=586
portfolio lines=11551 Type=336 OVER=338 @OYA=798
```

The turn-signalling spine still holds: `<OVER>` is close to or above `Type:` in
all three beds, and Oya is present everywhere.

## Track 1 — Deterministic Metrics

Command:

```sh
python3 scripts/comms-metrics.py \
  ~/Dev/aic/cc-aic/docs/agents \
  ~/Dev/1-in-a-billion-paradise/docs/agents \
  ~/Dev/portfolio-experiment/docs/agents \
  --json /tmp/comms-metrics.json
```

Key reproduced numbers:

| Metric | cc-aic | 1iab | portfolio |
|---|---:|---:|---:|
| messages | 5065 | 1691 | 336 |
| `<OVER>` per message | 1.011 | 1.171 | 1.006 |
| closed-loop ack rate | 0.449 | 0.555 | 0.708 |
| evidence-block rate | 0.512 | 0.345 | 0.411 |
| receipt rate | 0.385 | 0.517 | 0.107 |
| role-divergence SEI | 0.0529 | 0.0721 | 0.1420 |
| duplicate-msg rate | 0.296 | 0.050 | 0.095 |
| zero-finding approve rate | 0.674 | 0.780 | 0.278 |
| substantive review rate | 0.082 | 0.117 | 0.667 |
| formal dissent rate | 0.244 | 0.103 | 0.056 |

Track 1 matches the existing benchmark document. The deterministic part of
Claude's analysis is reproducible.

## Track 2 — Fresh Independent Rater

A fresh sub-agent was spawned with the NOTECHS / MARBLE / convergence rubric from
`ANALYSIS-METHOD.md`.

### NOTECHS

| Bed | Cooperation | Leadership | Situation awareness | Decision-making | Mean |
|---|---:|---:|---:|---:|---:|
| cc-aic | 8 | 8 | 7 | 8 | 7.75 |
| 1-in-a-billion-paradise | 8 | 9 | 8 | 8 | 8.25 |
| portfolio-experiment | 6 | 7 | 7 | 6 | 6.50 |
| overall | 7.3 | 8.0 | 7.3 | 7.3 | 7.48 |

The rater's strongest cc-aic marker was Oya stopping a stale warm-start:
`@OPUS -- STOP before you act on that warm-start. Your 14:50 snapshot is stale`.
The main weakness was the later S3 escape: both peer review and pre-push
validation approved it before CI caught it.

The strongest 1iab marker was an adversarial end-artifact review for missing
cached hook-audio regeneration rather than accepting dead signed URLs. The main
weakness was unresolved provider/sandbox proof, not lack of review structure.

The portfolio score is lower than the previous benchmark because the newest
supplied files contain closure summaries and repeated receipts, not much of the
underlying analyst disagreement trail.

### MARBLE-style communication score

| Bed | Score | Read |
|---|---:|---|
| cc-aic | 8 | Strong concrete before/after evidence, dragged by stale SHA evidence. |
| 1-in-a-billion-paradise | 8 | Strong falsification messages, with some contradictory done-call accounting. |
| portfolio-experiment | 5 | Orderly closure, but repeated bootstrap receipts and little debate substance. |

### Convergence quality

| Bed | Disagreements / reviews with findings | Median exchanges | Converged <=1 exchange | Multi-round | Rubber-stamp / procedural approvals |
|---|---:|---:|---:|---:|---:|
| cc-aic | 7 | 1 | 71% | 2 | 4 |
| 1-in-a-billion-paradise | 7 | 1 | 71% | 2 | 1 |
| portfolio-experiment | 0 found in supplied files | N/A | N/A | 0 | 2 |
| overall | 14 | 1 | 71% | 4 | 7 |

Best negotiation identified by the rater: the cc-aic S3 lockfile correction,
where Oya challenged a `0/0/0` audit story against a real lockfile diff, Opus
independently confirmed the problem, and Coda amended the audit record.

Most premature convergence identified by the rater: cc-aic S3 original approval,
where Opus approved at 95% confidence and the system later recorded that both the
review and pre-push validation missed a defect CI caught.

The rater found no sustained counter-position after hard counter-evidence. Agents
generally corrected quickly rather than holding an opposing position to impasse.

## Reconciliation With Claude's Benchmark

The deterministic Track 1 result is stable. The Track 2 result moved because the
rater sampled the newest available portfolio files and applied a stricter standard
to convergence.

The earlier benchmark said convergence was partially refuted as a weakness: 44%
of contested items converged in one exchange, 56% were multi-round, and zero
rubber-stamps were found. This rerun is less charitable: 71% of contested items
in the supplied cc-aic and 1iab cycles converged in one exchange, and portfolio
was not deeply rateable from the newest supplied files.

The combined read is:

1. The protocol's turn discipline and evidence scaffolding are reproducible.
2. Communication hygiene and low SEI remain measured defects.
3. The convergence weakness is not settled by one LLM rater. The direction is
   consistent: there is real adversarial review, but sustained disagreement after
   counter-evidence is rare.
4. A second independent rater, or a labelled `Slice:` grouping key, is needed
   before treating any exact premature-consensus percentage as publishable.

