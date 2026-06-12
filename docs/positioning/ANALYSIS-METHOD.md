# Analysis method — how to re-run the musubi collaboration analysis

*A complete, reproducible procedure for the multi-codebase collaboration analysis.
Re-run this end-to-end on a later corpus to get a fresh, comparable read. Everything
below is deterministic except Track 2 (one LLM rater) and Track 3 (not yet run).*

Outputs of one full pass (all in `docs/positioning/`):
- `external-review-2026-06-cross-codebase.md` — re-test of the original findings
- `collaboration-sophistication-and-benchmarks-2026-06.md` — framework lenses + plan
- `benchmark-results-2026-06.md` — Track 1 + Track 2 scored results
- `collaboration-improvements-forced-debate.md` — design proposal from the weaknesses
- `heterogeneous-vs-homogeneous.md` — the vendor-diversity question + experiment
- (date the filenames to the run so old passes stay comparable)

---

## 0. Inputs

Three test-bed repos, each with a `docs/agents/` comms tree:

| Test bed | Path | Domain |
|---|---|---|
| cc-aic / Slí | `~/Dev/aic/cc-aic/docs/agents` | production SaaS |
| 1-in-a-billion-paradise | `~/Dev/1-in-a-billion-paradise/docs/agents` | mobile + marketplace |
| portfolio-experiment | `~/Dev/portfolio-experiment/docs/agents` | equity research (non-software) |

"Comms" = `archive/*.txt`, `archive/*.md`, and `comms/active.txt` under each
`docs/agents`. Message format: a turn starts with `[@SPEAKER] [YYYY-MM-DD] [HH:MM TZ]`,
carries a `Type:` line, body sections (`Action/Evidence/Result/Next`), and ends with
`<OVER>`. The parser keys on that header; older archives vary but mostly conform.

To discover any new/renamed corpora before a run:
```sh
for r in ~/Dev/aic/cc-aic ~/Dev/1-in-a-billion-paradise ~/Dev/portfolio-experiment; do
  find "$r/docs/agents" -type f \( -name '*comms*' -o -name 'active.txt' \) -not -name '*.lock'
done
```

---

## 1. Phase A — mechanical baseline (grep, sanity check)

Quick counts to confirm the corpus grew and the protocol spine held. Use Python
(zsh does NOT word-split unquoted vars — a `cat $files` loop silently reads nothing):

```python
python3 - <<'PY'
import os, re, glob
repos = {
 'cc-aic': os.path.expanduser('~/Dev/aic/cc-aic/docs/agents'),
 '1-in-a-billion': os.path.expanduser('~/Dev/1-in-a-billion-paradise/docs/agents'),
 'portfolio': os.path.expanduser('~/Dev/portfolio-experiment/docs/agents'),
}
def files(d):
    out=[]
    for root,_,fs in os.walk(d):
        if '/.git/' in root: continue
        for f in fs:
            if f.endswith('.lock'): continue
            if ('comms' in f.lower() or f=='active.txt') and f.endswith(('.txt','.md')):
                out.append(os.path.join(root,f))
    return out
for name,d in repos.items():
    txt=''.join(open(f,errors='ignore').read()+'\n' for f in files(d))
    print(name, 'lines=', txt.count(chr(10)),
          'Type=', len(re.findall(r'(?mi)^Type:',txt)),
          'OVER=', txt.count('<OVER>'),
          '@OYA=', txt.count('@OYA'))
PY
```
Expected spine signals: `<OVER>` ≈ `Type:` count (turn discipline ~1.0/msg);
`@OYA` > 0 (supervisor present — was 0 before 2026-05).

---

## 2. Phase B — Track 1: deterministic metrics (`scripts/comms-metrics.py`)

The reproducible core. One command, JSON out:

```sh
python3 scripts/comms-metrics.py \
  ~/Dev/aic/cc-aic/docs/agents \
  ~/Dev/1-in-a-billion-paradise/docs/agents \
  ~/Dev/portfolio-experiment/docs/agents \
  --json /tmp/comms-metrics.json
```

### Metric dictionary (what each means, how to read it)

| Metric | Definition | Read |
|---|---|---|
| `over_per_msg` | `<OVER>` markers ÷ messages | ≈1.0 = clean closed-loop turn discipline |
| `closed_loop_ack_rate` | frac msgs with explicit read-back/confirm | higher = more grounding (Clark/CRM) |
| `evidence_block_rate` | frac msgs with `Evidence:` section | evidence discipline |
| `receipt_rate` | frac msgs with a SHA or `file:line` | hard-receipt discipline |
| `role_divergence_SEI` | Jensen-Shannon div of the two coders' vocab (0=identical) | **low (0.05–0.14) = peers talk alike → groupthink risk** |
| `overhead_TEI` | boilerplate-token fraction | protocol overhead |
| `duplicate_msg_rate` | exact-dup message bodies ÷ msgs | **hygiene; cc-aic ~0.30 (incl. relay re-posts)** |
| `consec_neardup_rate` | same-speaker >0.8-overlap consecutive | ack spam |
| `reviewer_finding_rate` | frac Review msgs raising a finding | **PROXY: independent-catch** |
| `escape_admissions` | count of "both missed / CI caught / review escape" | **PROXY: correlated-miss** |
| `zero_finding_approve_rate` | frac Review *results* that approve with no positive finding | **CEILING on premature-consensus (not the rate)** |
| `substantive_review_rate` | frac review results with ≥1 positive finding | genuine-round signal |
| `formal_dissent_rate` | frac review results with explicit non-approve verdict | hardest contested signal |
| `single_exchange_contested_rate` / `multi_round_contested_rate` | exchange-level convergence | **only meaningful once `Slice:` grouping exists (see limits)** |

### Known limits of Track 1 (do not over-read)
- `duplicate_msg_rate` includes orchestrator **relay re-posts** across archive files,
  not only agent redundancy → treat as an *upper bound* on ack spam.
- `escape_admissions` / `reviewer_finding_rate` are **keyword proxies** — directional,
  not ground-truth. True numbers need labelled bug outcomes (Track 3 / a human pass).
- **Exchange-level convergence** (`*_contested_rate`) needs a `Slice:` identity echoed
  on review turns so they can be grouped into exchanges. Until the comms protocol adds
  that key, `contested_slices` ≈ 1 and these fields are inert. The per-message
  `zero_finding_approve_rate` is the usable proxy meanwhile — read it as a *ceiling*
  on premature consensus, since a clean approve can be the final turn of a real
  multi-round debate.

---

## 3. Phase C — Track 2: independent LLM rating

Deterministic metrics can't judge argument quality. One independent LLM rater reads
the **newest cycle in each bed in full** and applies three instruments. Sampling rule:
the most recent `comms/active.txt` + the newest dated archive per bed (newest cycles
post-date the prior analysis; they're where change shows).

Spawn a fresh agent (no prior context) with this exact brief:

> You are a strict, skeptical independent rater scoring multi-agent collaboration from
> real comms transcripts. System: peer LLM coders @OPUS (Claude) + @CODA (Codex),
> supervisor @OYA, human gate @MICHI/@LEAD. Read these files [list newest per bed].
> Cite a real quoted line for every score. Do not fabricate.
>
> **Instrument A — NOTECHS markers (0–10 each, per bed):** Cooperation; Leadership &
> coordination; Situation awareness; Decision-making. Score + 1–2 quoted markers +
> what would make it a 10.
>
> **Instrument B — MARBLE Communication Score (0–10 per bed):** clarity, relevance,
> non-redundancy. Quote a high- and a low-quality message.
>
> **Instrument C — convergence quality (the key measure):** find every genuine
> inter-agent disagreement / review-with-findings. For each: (a) # back-and-forth
> exchanges to converge, (b) substantive objection vs rubber-stamp, (c) was a counter-
> position held after counter-evidence. Report: # disagreements, median exchanges,
> % converged in ≤1 exchange (premature-consensus proxy), # genuine multi-round, #
> rubber-stamps. Quote the best real negotiation and the most premature convergence.
>
> Return markdown: NOTECHS table (per bed + overall), Communication Score, Convergence
> analysis (numbers + quotes), 3-line verdict.

Hardening (deferred, for a rigorous pass): run **two raters** and report inter-rater
agreement; the single-rater convergence numbers are indicative, not final.

---

## 4. Phase D — Track 3: comparable solver number (NOT run)

To get a leaderboard-comparable figure, run the musubi pair as a solver on
**SWE-bench Verified** (500 tasks) and report resolve rate vs each agent solo.
Requires wiring the pair-orchestration harness to the SWE-bench task runner +
container infra. Out of scope for a comms-only pass; the right next build if a
headline number is wanted. It answers a *different* question (capability on a
standard task set) than Tracks 1–2 (collaboration quality on real work).

---

## 5. Phase E — heterogeneous vs homogeneous experiment (design, not yet run)

Same protocol, same task set, three arms: **A** Claude+Codex, **B** Claude+Claude,
**C** Codex+Codex. Score each with `comms-metrics.py` + the Track-2 rater. Key metric
= **correlated-miss rate** (bugs *both* agents approved that CI/human later caught) —
the column where heterogeneity should win if it wins anywhere. Predicted: B/C ≈ A on
throughput, A wins only on correlated-miss + SEI. Falsifier: if A's correlated-miss
≈ B/C's, the value is the protocol, not the heterogeneity. See
`heterogeneous-vs-homogeneous.md`.

---

## 6. Synthesis — turning numbers into the docs

1. **Cross-codebase re-test** — take the prior analysis's findings and re-test each
   against the new corpus + Track 1 deltas. Spawn one reader-agent per bed (parallel)
   with a "re-test these N claims, cite real lines, say 'no evidence' if absent" brief.
2. **Benchmark results** — drop Track 1 table + Track 2 scores into
   `benchmark-results-<date>.md`; reconcile any qualitative-vs-quantitative conflict
   honestly (e.g. the convergence weakness was *partially refuted* by Track 2C).
3. **Improvements** — derive mechanisms from the *measured* weaknesses (low SEI,
   premature-consensus ceiling, hygiene), each tied to musubi machinery + a framework
   lineage; right-size urgency to the numbers.
4. **Update the memory file** `cross-codebase-analysis-*.md` + `MEMORY.md` index.

### Interpretation guide (rough thresholds)
- `over_per_msg` < 0.9 → turn discipline slipping (investigate parser or protocol).
- `role_divergence_SEI` < 0.10 → peers converging in language; groupthink watch.
- `duplicate_msg_rate` > 0.15 → hygiene/relay problem; check the relay + comms-LOCK.
- `zero_finding_approve_rate` > 0.7 → many rubber-stamp-shaped approves; needs the
  Track-2 read to tell genuine-final-turn from on-sight approval.

---

## 7. Reproducibility notes

- **Deterministic:** Phases A, B (and E's Track-1 scoring) — same corpus → same
  numbers. Re-run anytime; diff against the prior dated JSON to see movement.
- **Not deterministic:** Track 2 (one LLM rater; varies run to run — quote-cited so
  spot-checkable). Track 3, E arms B/C: not yet run.
- **Honest caveats to carry into every write-up:** proxy metrics are keyword-based;
  duplicate rate includes relay artifacts; single-rater convergence is indicative;
  exchange-level convergence needs the `Slice:` protocol key; no homogeneous baseline
  exists yet.
- **To make Track-1's convergence metrics live:** add a `Slice: <id>` line to review
  turns in the comms protocol so `comms-metrics.py` can group turns into exchanges.

---

*One full pass = Phases A→B→C→(synthesis). Phases D, E and the second rater are the
rigour upgrades when a publishable number is needed. Keep filenames dated so each
pass stays comparable to the last.*
