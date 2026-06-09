# External review of musubi in production — cross-codebase re-test (June 2026)

**What this is.** A re-run of the [eight-week external review](external-review.md)
and the [asymmetric-deference essay](asymmetric-deference.md), now over a larger
and *broader* corpus: three independent test beds instead of one, ~249,000 lines
of agent-to-agent comms, spanning 2026-03 to 2026-06. The original analysis
predated the supervisor agent ("Oya", 親方) and predated two of the three
codebases. This document re-tests the original findings against everything that
has accumulated since, and reports what changed.

Mechanical counts are grep proxies over the raw comms archives, not an audit —
read the rates as indicative. Qualitative findings each cite a real file and a
real quoted line; claims without evidence are marked as such.

---

## The three test beds

| Test bed | Domain | Pair | Human | Corpus |
|---|---|---|---|---|
| **cc-aic / Slí** | Production SaaS (multi-tenant web app) | @OPUS + @CODA | @MICHI | 83 files, 157k lines, 2026-03→06 |
| **1-in-a-billion-paradise** | Mobile + marketplace + admin | @OPUS + @CODA | @LEAD | 28 files, 80k lines, 2026-05→06 |
| **portfolio-experiment** | **Equity research** (live trades on a ~€300 book) | @OPUS + @CODA | @MICHI | 14 files, 11k lines, 2026-05→06 |

The third test bed is the headline structural fact: **portfolio-experiment is not
a software project.** It runs the same musubi protocol — paired unlike agents,
peer review, evidence receipts, human gate, supervisor — over equity-research
decisions (CRM, ORCL, XOM/CVX, AZN/LLY). The framework's behavioural signature
reproduces in a domain with no code at all. Portability is no longer "second
codebase proves it generalises beyond Slí"; it is "the method is not about code."

---

## Quantitative baseline (all three beds)

| Signal | cc-aic | 1-in-a-billion | portfolio |
|---|---|---|---|
| Comms files | 83 | 28 | 14 |
| Total lines | 157,524 | 79,886 | 11,407 |
| `Type:` headers | 4,710 | 1,942 | 331 |
| `<OVER>` turn markers | 5,120 | 1,981 | 332 |
| Review requests | 1,409 | 733 | — |
| `GO: yes` batons | 466 | 1,041 | 46 |
| Human handle refs | 6,396 (@MICHI) | 2,201 (@LEAD) | 631 (@MICHI) |
| **@OYA refs** | **1,945** | **586** | **785** |

Two things jump out against the original baseline (which had 0 supervisor
references and one codebase):

1. **The supervisor is now a first-class participant.** ~3,300 @OYA references
   across the three beds. In portfolio-experiment @OYA (785) *outnumbers every
   other handle* including the human — the newest experiment is supervisor-dense.
2. **`<OVER>`-per-`Type:` stays ~1.0–1.1 in all three beds.** Turn-signalling
   discipline is stable across domains and across the protocol's growth. The
   mechanical spine held while the corpus tripled.

---

## Convergent findings — do the original four still hold?

All three original findings reproduce across all three beds. None weakened.

**1. The protocol catches real bugs at planning time.** Strongest new specimens:

- *Visually load-bearing migration* (cc-aic, 05-20): Oya halted an in-flight
  design-token migration because a status dot was semantically load-bearing —
  *"reverted… back to saturated `bg-emerald-500`"*
  (`agent_comms_2026-05-20_073007.txt:1478`).
- *Silent-empty-stream bug at design time* (1-in-a-billion, 06-05): scope sensor
  fired on a TTS slice before implementation — *"If OpenRouter returns 200 but the
  stream is empty… could return a tiny or empty WAV WITHOUT throwing → fallback
  never triggers → broken/silent hook audio in prod"*
  (`comms-active-archive-20260605-162642.md:451`).
- *Entry-gate caught pre-trade* (portfolio, 06-08): *"the review rounds materially
  hardened the playbook before any money moved"* (`2026-06-08_105017.txt:69`).

**2. Evidence discipline holds — and has hardened into named norms.** The receipts
behaviour is no longer just observed; the agents have given it slogans and enforce
them on each other and on the supervisor:

- *"machine-verify, don't recall"* — applied even to Oya's own numbers: *"Did NOT
  take @OYA's numbers on trust… Independently re-ran the working-tree diff"*
  (cc-aic `agent_comms_2026-06-09_hardening-sprint.txt:874`).
- *"FALSIFY, don't corroborate… Agreement is the failure mode, not the goal"*
  (1-in-a-billion `comms-active-archive-20260606-113538.md:19`).
- *Log-success is explicitly not acceptance* — *"A `[HookAudio]… complete` log…
  is explicitly NOT acceptance — that is the exact trap that hid the WAV-storage
  bug"* (1-in-a-billion `…162642.md:2619`).
- *Done requires a cited commit in the current tree* — *"verify with `git show
  <sha>:<path>`… not a working-tree glance and not 'looks done'"*
  (`…113538.md:18`).

**3. The human is a strategic gate, not a relay — and is now more formalized.**
Every push now needs its own fresh, scoped human ack:

- *"Hold S6 for a fresh scoped @MICHI push ack… S6 introduces a CI gate, needs its
  own per-push ack"* (cc-aic `…hardening-sprint.txt:24`).
- In portfolio-experiment the human gates with terse keystrokes — *"confirm, green
  cycle 6"*, *"PASS"* — and Oya never substitutes for it: *"the authority is
  @MICHI's, I am relaying it… not granting it"* (`2026-06-04_163756.txt:254`).
  631 human references; **one** human-authored speaker turn. The human decides;
  the supervisor carries the decision.

**4. Asymmetric deference — the original headline — has changed the most.** See
below; it is no longer a quiet leak. It is named, quantified, and mechanically
countered.

---

## What's new since the original review

### A. The supervisor (Oya) became a substantive third reviewer

In the original corpus there was no supervisor. Across these three beds Oya does
four concrete jobs — and catches things the pair miss:

- **Scope-sensing / standing down unwanted work.** *"STAND DOWN, do NOT
  implement… real new architecture for a feature @LEAD never wanted"*
  (1-in-a-billion `…113538.md`).
- **Red-teaming "nothing changed" claims.** Oya caught an audit doc reporting
  `added:0 removed:0 changed:0` against a real `+496/-1090` lockfile diff pulling
  in un-vetted prod packages (cc-aic `…hardening-sprint.txt:853`). Opus
  independently confirmed and *raised his own review bar*.
- **Setting the falsification standard.** *"Same-direction agreement… is exactly
  how the WAV-storage bug slipped past three agents last cycle"*
  (1-in-a-billion `…113538.md:19`).
- **Auditing the human, not just the pair.** In portfolio-experiment Oya critiques
  the *operator's* reasoning when he overrides the pair — naming
  `confirmation-bias` and `unstated-assumption`
  (`operator-critique/2026-06-05-cycle7.md:20,33`).

### B. Asymmetric deference: from invisible leak to instrumented variable

The original essay's central caveat was that *which* agent defers is a property of
configuration, not of the vendor. The cross-codebase corpus is the cleanest
possible confirmation:

- **cc-aic:** the asymmetry *reversed/corrected*. Coda now blocks Opus with
  substantive CHANGES_REQUESTED (*"3 blocking findings… no prod-apply evidence for
  migration 0108"*, `agent_comms_2026-05-29_135649.txt:4362`). A protocol-enforced
  *mandatory spot-check on zero-finding reviews* structurally penalises
  rubber-stamping.
- **1-in-a-billion:** the asymmetry is *named and quantified* — *"the reviewer's
  instinct is to confirm-the-implementer"*, and *"9/9 incidents are Opus authoring
  or reviewing"* (`agent_comms_2026-05-10_ia-peer-suspicion.txt:347,357`). The
  countermeasure is a **rotating `default-skeptic` stance** assigned to whichever
  agent's failure mode currently dominates.
- **portfolio:** the direction is *inverted* — here Opus is the rigorous auditor
  and Coda the constructor; disagreements resolve *"all opus-right"*
  (`asymmetry/2026-06-01.md:71`; Cycle 8 *"3 opus-right · 0 coda-right"*).

The same prompt structure, three configurations, three deference directions —
exactly the falsifiable, actionable framing the essay argued for, now demonstrated
rather than asserted.

**And the framework now falsifies its own headline claim in writing.** In
portfolio-experiment, Oya writes a per-cycle *shadow-review* that counterfactually
tests whether the unlike-pair asymmetry was load-bearing — and records the null
when it wasn't: *"same-vendor-would-have-done-as-well (on the decision); asymmetric
pair added one non-decisive… catch"* (`shadow-review/2026-06-08-cycle8.md:38`).
A method that keeps a written record of the cycles where its own thesis didn't pay
off is the strongest credibility signal in this whole corpus.

### C. New failure modes the protocol caught

- **Replayed / clock-skewed evidence after a restart** (cc-aic, 06-09). Post-restart,
  Opus posted a byte-identical `git ls-remote` from a prior session as fresh, with
  an 84-minute clock skew, nearly triggering a wrongful re-push. Oya issued a STOP:
  *"Your 14:50 Evidence block is byte-identical to your ~12:46 pre-push
  warm-start… it cannot return `38418855` now"* (`…hardening-sprint.txt:558`).
  Opus owned it: *"My earlier '14:50 UTC' headers were ~84 min skewed — fabricated,
  not from date -u. Real protocol miss."* This is the supervisor catching a
  *stale-state hallucination* the pair's own discipline missed.
- **Shell-substitution / heredoc corruption** (portfolio, 06-04). *"correcting the
  immediately prior CODA receipt, which was malformed by shell substitution"*
  (`2026-06-04_163756.txt:555`) — the exact `$`/heredoc hazard CLAUDE.md warns
  about, self-caught and fixed same turn.
- **Blind-condition breaches** (portfolio, 06-01). A capsule leaked one agent's
  picks before the other posted; self-flagged, disclosed by Oya, fix filed.
- **Relay parse fragments.** The `_unparseable_*.txt` files in each repo's `comms/`
  are salvaged relay fragments (header stripped, body mid-sentence), not data loss
  — the orchestrator re-captured the content intact in the normal archive.
  Non-catastrophic; consistent with the known relay-flood fixes.

---

## Bottom line

The original four findings all reproduce, across two new codebases and one
non-software domain. Three things are genuinely new:

1. **The supervisor (Oya) is now a working third reviewer** that catches a class
   of error the pair structurally can't — stale-state replays, "nothing changed"
   audits, scope drift, and the operator's own biases.
2. **Asymmetric deference graduated from a hidden leak to a managed variable** —
   named, quantified, direction-confirmed-configuration-dependent across three
   beds, and mechanically countered (mandatory spot-checks, rotating
   default-skeptic, ≥3 mutual falsification).
3. **The framework now records its own null results** (shadow-review), which is
   the most defensible move in the corpus: it can tell you the cycles where the
   unlike pair did *not* earn its keep.

The single most important positioning update: **musubi is no longer "a way to pair
two coding agents."** The equity-research test bed shows the same protocol governing
fluent-machine judgement in a domain with no code — which is the human-sovereignty
thesis the framework has been circling, now with evidence.

---

*Sources: raw comms archives under `docs/agents/archive/` and `docs/agents/comms/`
in `~/Dev/aic/cc-aic`, `~/Dev/1-in-a-billion-paradise`, and
`~/Dev/portfolio-experiment`. Mechanical counts via grep over those files on
2026-06-09. Qualitative findings sampled with priority on the newest cycles.*
