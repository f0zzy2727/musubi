# Benchmark results rerun — Fable check (2026-06-10)

Third pass of `docs/positioning/ANALYSIS-METHOD.md`, this time with Claude
Fable 5 as the analysis driver and an independent Fable-powered Track-2 rater.
It does not replace `benchmark-results-2026-06.md`; with the Codex rerun
(`benchmark-results-2026-06-09-codex-rerun.md`) it gives a **three-rater**
record over a near-identical corpus, which finally lets rater variance be
separated from sample variance.

## Inputs

Track 1 used the full `docs/agents` comms trees (same three beds as before).
The corpus is **byte-identical to the 2026-06-09 runs** at the spine level
(same line counts), so any Track-2 movement is rater, not corpus.

Track 2 deliberately used the **exact same sample files as the Codex rerun**
— this directly answers the Codex handoff's open question #4 ("run a second
independent rater on the same sample to measure whether the Track 2
disagreement is sample variance or rater variance"):

| Bed | Files |
|---|---|
| cc-aic | `comms/active.txt`; `archive/agent_comms_2026-06-09_hardening-sprint.txt` |
| 1-in-a-billion-paradise | `comms/active.txt` (rotation stub); `archive/comms-active-archive-20260606-113538.md` |
| portfolio-experiment | `comms/active.txt`; `archive/agent_comms_2026-06-09_125311.txt` |

## Phase A — corpus spine

*ELI5: a quick headcount before grading — how many lines of conversation exist,
did every message follow the required format, and is the supervisor (@OYA)
actually present in all three projects. If these counts look wrong, the rest of
the analysis is reading a broken corpus.*

```text
cc-aic lines=157524 Type=4710 OVER=5120 @OYA=1945
1-in-a-billion lines=79886 Type=1942 OVER=1981 @OYA=586
portfolio lines=11551 Type=336 OVER=338 @OYA=798
```

Identical to both 2026-06-09 runs. Spine holds.

## Track 1 — deterministic metrics

Command:

```sh
python3 scripts/comms-metrics.py \
  ~/Dev/aic/cc-aic/docs/agents \
  ~/Dev/1-in-a-billion-paradise/docs/agents \
  ~/Dev/portfolio-experiment/docs/agents \
  --json /tmp/comms-metrics-fable-20260610.json
```

**Reproduced exactly — third consecutive identical pass** (Claude 06-09,
Codex 06-09, Fable 06-10):

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
| single-exchange contested rate | 1.0 (n=1) | null | null |

The Phase-1 review-verdict metrics and the Phase-2 `Slice:`-keyed contested
rates are live in the script; contested rates stay inert until the
contested-debate spike runs on a bed (as designed — `contested_slices` ≈ 0/1).

### ELI5 — what each Track-1 metric measures

- **messages** — how many notes the team passed to each other in total.
- **`<OVER>` per message** — the agents talk like walkie-talkie users: every
  turn must end with "over". 1.0 means nobody ever forgot to end their turn.
- **closed-loop ack rate** — how often a listener repeats back what they heard
  ("so you're saying X") so the speaker knows the message landed.
- **evidence-block rate** — how often a message shows its homework (an
  `Evidence:` section) instead of just claiming something is true.
- **receipt rate** — how often a message points at exact proof: a commit hash
  or a `file:line` you could go and check yourself.
- **role-divergence SEI** — do the two coders sound like two different people,
  or like one person talking to a mirror? Low score = mirror. (Mirror = risk
  they share the same blind spots.)
- **duplicate-msg rate** — how often the exact same note got posted more than
  once. Pure noise; tells you how messy the channel is.
- **zero-finding approve rate** — what share of reviews said "looks good"
  without naming one thing they actually checked and found. A high number
  *could* mean lazy approvals — or could be the clean last turn of a real
  argument; this metric alone can't tell which.
- **substantive review rate** — share of reviews that came back with at least
  one concrete finding ("this line is wrong because…").
- **formal dissent rate** — share of reviews that flat-out said "no, not
  approved". The hardest form of pushback.
- **single-exchange contested rate** — when there *was* an argument, did it end
  after just one back-and-forth? (Needs the `Slice:` tag to count properly —
  mostly inert until the debate spike runs.)

## Track 2 — fresh independent rater (Fable, no prior context)

### ELI5 — what each Track-2 instrument measures

- **NOTECHS** — a scorecard borrowed from how airline crews and surgical teams
  are graded on teamwork (not technical skill): do they help each other
  (*Cooperation*), does someone keep the work organised (*Leadership*), do they
  notice what's actually going on around them (*Situation awareness*), and do
  they make sound calls (*Decision-making*). 0–10 each, and every score must
  quote a real line from the transcript as proof.
- **MARBLE communication score** — is the talk clear, on-topic, and not
  repeating itself? One number, 0–10, per project.
- **Convergence quality** — the big one: find every real disagreement between
  the agents, then ask — was it a genuine argument (positions held, evidence
  demanded, someone changing their mind *for a reason*) or did one side just
  instantly cave / wave it through? "Converged in ≤1 exchange" = the argument
  was over after a single back-and-forth; "rubber-stamp" = approval with no
  real check behind it.

### NOTECHS

| Bed | Cooperation | Leadership | Situation awareness | Decision-making | Mean |
|---|---:|---:|---:|---:|---:|
| cc-aic | 9 | 9 | 8 | 9 | 8.75 |
| 1-in-a-billion-paradise | 8 | 9 | 7 | 8 | 8.00 |
| portfolio-experiment | 6 | 7 | 7 | 6 | 6.50 |
| overall | 7.7 | 8.3 | 7.3 | 7.7 | **7.75** |

Strongest cc-aic markers: honest dual ownership of the S3 escape (*"BOTH my S3
review AND Coda's pre-push validation approved it; CI type-check caught it.
Owning my half honestly"*) and Oya's stale-warm-start falsification
(*"`git ls-remote` hits the live remote — it cannot return `38418855` now"*).
SA docked 2 points in cc-aic because the stale-evidence replay was caught by
the supervisor, not self-caught.

Portfolio 6.5 matches Codex's read for the same reason: the newest window is
cycle-close + warm-start housekeeping; the analytic disagreement trail is
asserted (*"pair CONVERGED independently (solo-shadows match)"*) but not shown
in the supplied files.

### MARBLE-style communication score

| Bed | Score | Read |
|---|---:|---|
| cc-aic | 7 | Clarity/relevance near-ceiling; five consecutive zero-information Coda "observed/holding" echoes are the defect |
| 1-in-a-billion-paradise | 8 | Long but information-dense; one near-verbatim claim-receipt echo |
| portfolio-experiment | 5 | Quadruple bootstrap receipt (4 msgs, 1 minute, 3 with zero new info) in a 143-line file |

Identical bed ordering to both prior raters (cc-aic/1iab high, portfolio 5),
and the portfolio defect is the same specimen class all three raters found
(repeat-posted receipts).

### Convergence quality (Instrument C)

| Measure | Fable (06-10) |
|---|---:|
| genuine disagreements / reviews-with-findings | **11** (cc-aic 5, 1iab 6, portfolio 0) |
| median exchanges to converge | **1** |
| converged ≤1 exchange (premature-consensus proxy) | **82%** (9/11) |
| genuine multi-round | **2** |
| rubber-stamps | **0** |

Best negotiation: the cc-aic S3 **mechanism sub-dispute** — Coda corrected both
supervisor and reviewer with command-sequence evidence (*"my live command
sequence evidence shows the broad package-lock diff was already produced by the
real `npm audit fix --package-lock-only`"*) and won the point; Opus amended
(*"Mechanism corrected"*). An implementer holding and **winning** a
counter-position against two seniors.

Most premature convergence: the 1iab **Google Geocoding/TimeZone false
positive** — both peers converged in one round on a shared unverified premise
(REQUEST_DENIED from an expired *local* key, never probed against prod); Oya
refuted it post-convergence (*"Geocoding + Time Zone ALREADY WORK in prod…
The diagnosis was made off the expired local key, never prod"*).

Two findings unique to this pass:

1. **Challenge is directional.** Oya→pair and Opus→Coda probes are routine;
   **Coda almost never probes Opus**. Invited dissent (*"If you think
   strict-abort… is better, argue it in comms before coding"*) drew zero
   argument. This is the asymmetric-deference pattern showing up *inside* the
   peer pair, not just agent→supervisor.
2. **The real premature-consensus failure class is shared-unverified-premise,
   not deference.** The Google false positive is a correlated miss: two
   different vendors' models, same wrong premise, single-round convergence.
   Heterogeneity did not save it; the supervisor's independent probe did.
   This is precisely the failure mode the hetero-vs-homo experiment
   (`heterogeneous-vs-homogeneous.md`) is designed to price.

## Three-rater reconciliation

Same Track 1, three Track-2 raters. Claude's pass used a slightly older
portfolio archive; Codex and Fable used identical samples.

| Measure | Claude (06-09) | Codex (06-09) | Fable (06-10, same sample as Codex) |
|---|---:|---:|---:|
| NOTECHS overall | 7.9 | 7.48 | 7.75 |
| MARBLE (cc-aic / 1iab / portfolio) | 7 / 8 / 5 | 8 / 8 / 5 | 7 / 8 / 5 |
| disagreements found | 9 | 14 | 11 |
| median exchanges | 2 | 1 | 1 |
| ≤1 exchange | 44% | 71% | 82% |
| genuine multi-round | 5 | 4 | 2 |
| rubber-stamps | 0 | 7 | 0 |

**What the comparison establishes:**

1. **Rater variance is real and large on the categorical judgments.** Codex
   and Fable read the *same files* and still disagree: 14 vs 11 disagreements,
   71% vs 82% single-exchange, and most starkly **7 vs 0 rubber-stamps** —
   Codex counted procedural approvals as rubber-stamps; Fable inspected each
   fast convergence and attributed it to decisive machine-verified
   counter-evidence, not deference. The Codex handoff's question is answered:
   the Track-2 spread is substantially **rater** variance, not sample variance.
   No exact premature-consensus percentage is publishable from single-rater
   passes. (The `Slice:` grouping key + two-rater protocol — already built as
   forced-debate Phases 1–2 — is the fix.)
2. **The qualitative direction is unanimous and therefore robust.** All three
   raters, independently: convergence is fast (median 1–2 exchanges); genuine
   multi-round negotiation exists but is the minority; no disagreement is ever
   held to impasse — counter-positions get corrected by evidence, not defended
   to deadlock; the newest portfolio window is not deeply rateable; cc-aic
   has a measured hygiene defect; per-message rigor is high. Publish the
   direction, not the digits.
3. **Track 1 is the bedrock.** Three passes, three drivers (Claude, Codex,
   Fable), bit-identical numbers. The deterministic story — turn discipline
   ~1.0, low SEI, the duplicate-rate defect, the zero-finding-approve ceiling —
   carries the quantitative weight of the positioning.

**Combined positioning (refines the Codex formulation, evidence-cited):**

> Musubi is defensibly "evidence-governed multi-agent judgment with human
> sovereignty," and the evidence-forcing is demonstrably real (zero
> rubber-stamps on close inspection; concessions are machine-verified, and an
> implementer can hold and win a counter-position against two seniors). It is
> not yet proven as "robust adversarial deliberation": challenge flows one way
> (Coda rarely probes Opus), and the worst observed failure — the Google false
> positive — was a shared-unverified-premise correlated miss that heterogeneity
> alone did not prevent. The debate claim still needs the `Slice:`-keyed
> measurement and a two-rater protocol before any percentage ships.

## Next steps (unchanged from the queue, now better motivated)

1. Live-run the Phase-2 contested-debate spike on one bed (portfolio
   recommended) — the Fable pass adds the strongest reason yet: the
   premature-consensus specimens are shared-premise events, exactly what blind
   position-commitment targets.
2. Phase 3 (steelman + dissent quota) should specifically address the
   **directional** challenge gap (Coda→Opus probes ≈ 0), not just volume.
3. Two-rater protocol with inter-rater agreement is now mandatory for any
   published convergence number — this doc is the demonstration of why.
