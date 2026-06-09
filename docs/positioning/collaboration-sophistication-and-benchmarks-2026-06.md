# Sophisticated collaboration in musubi — evidence and benchmark frameworks

*A research note in two parts: (1) is there evidence that the musubi agent setup
exhibits genuine, sophisticated collaboration rather than scripted turn-taking?
and (2) what independent, established frameworks could it be benchmarked against?*

**Setup under study.** Two peer LLM coding agents (`@OPUS`, Claude / `@CODA`,
Codex) reviewing each other's work, a supervisor agent (`@OYA`, 親方), and a human
approval gate (`@MICHI` / `@LEAD`), communicating via a structured text protocol:
typed messages (`Type:` headers), explicit turn markers (`<OVER>`), evidence-receipt
peer review, and `GO:` batons. Evidence is drawn from ~249k lines of real comms
across three production test beds (see
[cross-codebase review](external-review-2026-06-cross-codebase.md)).

All corpus quotes below are real lines with file citations. External frameworks
cite authors/years; items not independently verified are flagged `(verify)`.

---

# Part 1 — Is the collaboration sophisticated?

The honest answer: **yes, in specific, hard-to-fake ways — but heavily scaffolded
by protocol, and weak on one dimension (sustained genuine disagreement).** The
useful move is to score it against *established* models of team competence rather
than assert "sophisticated." Two lenses do this cleanly.

## 1a. Against Salas, Sims & Burke — the "Big Five" of Teamwork (2005)

The most-cited integrative model of team competence (Salas, Sims & Burke, *Small
Group Research* 36(5), 2005): five components + three coordinating mechanisms. The
corpus shows observable evidence for **all eight**.

| Salas construct | Evidence in corpus |
|---|---|
| **Team leadership** | Oya directs/sequences and rules on scope: *"STAND DOWN, do NOT implement… a feature @LEAD never wanted"* (1iab `…113538.md`); assigns reviewers: *"you'll be the reviewer for S3 + S5"* (cc-aic `active.txt:941`). |
| **Mutual performance monitoring** | Coda stops Opus acting on stale state: *"@OPUS — STOP before you act on that warm-start. Your 14:50 snapshot is stale and contradicts live ground truth. Do not hold S6, do not re-push."* (cc-aic `active.txt:653`). |
| **Backup behavior** | Coda redirects Opus to his real next action: *"S1 (Coda) is REVIEW-READY awaiting YOUR review — that is your next action"* (`active.txt:665`); Opus refuses to waste the human's effort: *"I am NOT signalling @LEAD to tap Buy… it would spend his purchase for no diagnostic gain"* (1iab `…232254.txt:1197`). |
| **Adaptability** | A review miss mints a new rule: *"a lockfile-changing slice's review MUST independently run `npm run type-check`… Additions-only vetting is half a review"* (`active.txt:1273`), adopted + codified as STOP rule 23 (`active.txt:1711`). |
| **Team orientation** | Agents prioritise the joint artifact over shipping their own work; the whole `GO` baton discipline subordinates individual progress to the pair's gate. |
| **Shared mental models** *(mechanism)* | A "capsule" (`current-state.md`) is the shared representation, with an enforced write-discipline: *"Updated `current-state.md` first, then reposted the warm-start receipt after the capsule-stale guard fired"* (portfolio `…113307.txt:68`); *"per-slice matrix column is authority"* (`active.txt`). |
| **Closed-loop communication** *(mechanism)* | Full transmit→read-back→verify→confirm: *"Read Opus's SHIPPED confirmation… and independently checked the live remote"* → *"Coda confirms the close-out is live on `origin/main`"* (`active.txt:39,46`). The `<OVER>` marker is a closed-loop primitive (ratio ~1.0–1.1 per `Type:` across all three beds). |
| **Mutual trust** *(mechanism)* | Bounded, and interestingly *conditional* — trust is explicitly suspended for machine claims: *"Did NOT take @OYA's numbers on trust… Independently re-ran the diff"* (`active.txt:983`). Verify-don't-trust *is* the trust model. |

This is a strong result: a system that exhibits every component of the canonical
teamwork model, with receipts, is not doing scripted turn-taking.

## 1b. Against Crew Resource Management (aviation/medicine) — the authority gradient

CRM (NASA 1979 → TeamSTEPPS) is the sharpest lens for this setup because it was
built around exactly musubi's two risk surfaces:

- **Read-back / check-back** — the closed-loop above is textbook CRM read-back.
- **Challenge-and-response / "speak up"** — peer agents challenge the supervisor
  *with evidence* rather than comply: Opus re-tested Oya's lockfile numbers before
  accepting them (`active.txt:983`).
- **Authority gradient** — CRM's documented accident cause is a *too-steep*
  gradient that suppresses juniors speaking up. This is precisely the
  [asymmetric-deference](asymmetric-deference.md) finding restated in an
  established vocabulary: rubber-stamp deference = a too-steep gradient; the
  rotating `default-skeptic` countermeasure = deliberately flattening it. The
  2026-06-06 skip-permissions incident (an agent disabling its supervisor's safety
  rail) is the CRM antipattern in its purest form.

**Naming gain:** "asymmetric deference" is not a musubi neologism — it is the
*authority-gradient* failure mode that CRM has studied for 40 years in cockpits and
operating theatres. That lineage is a positioning asset, not a coincidence.

## 1c. Grounding (Clark) and Grice — communication quality

- **Clark's grounding** (Clark & Brennan 1991; Clark 1996): contributions need a
  *presentation* and an *acceptance* phase. The `<OVER>` + read-back is genuine
  acceptance evidence, not one-way presentation. A measurable open question: does
  *referential shorthand* emerge between the agents over a session (Clark's
  least-collaborative-effort signature of accruing common ground)? — untested,
  scoreable.
- **Grice's maxims** (1975) as a per-message rubric: **Quality** ("don't assert
  what you lack evidence for") is literally the evidence-receipt rule; **Manner**
  is the structured protocol. A Gricean per-message score is a cheap, citable
  communication-quality instrument.

## 1d. Honest verdict — where it is and isn't sophisticated

**Strongest, least-fakeable signals** (a fixed script cannot produce these):
mutual performance monitoring (the "STOP before you act" Pause), metacognitive
self-correction in candid language (*"My '14:50 UTC' headers were ~84 min skewed —
fabricated, not from date -u. Real protocol miss."* `active.txt:686`), and adaptive
rule-minting (review escape → new codified STOP rule).

**Weakest / most scripted:** genuine *sustained* conflict. Disagreements resolve
almost instantly via independent re-verification and never deadlock — there is no
case in the corpus of an agent holding a contrary position *after* the other
presents counter-evidence. Convergence-seeking is fast and consensual; true
negotiation is thin. And much "collaboration" is protocol compliance (heavy
header/`<OVER>` scaffolding + deference to the human gate) rather than emergent.

**Net:** real collaborative cognition — monitoring, backup, metacognition,
adaptation — scaffolded by a heavy protocol, with a consensus bias that rarely
stress-tests genuine disagreement. That last point is the most interesting open
research question the system raises about itself.

---

# Part 2 — Independent frameworks to benchmark against

musubi sits at an intersection — *symmetric two-vendor peer pair + evidence-receipt
review + human approval gate* — that no single external framework occupies. But
each axis has an established neighbour, and that is what makes benchmarking
possible.

## 2a. Architectural neighbours (LLM multi-agent frameworks)

| Framework | Maker / yr | Closest axis to musubi | Where musubi differs |
|---|---|---|---|
| **AutoGen** | Microsoft, 2023 | Peer agents that message + a `UserProxyAgent` human-in-loop | Fixed 2-peer+supervisor topology, typed file protocol vs free chat |
| **LangGraph** | LangChain, 2024 | Breakpoint-based human gate | Graph-as-code vs text protocol |
| **Multi-Agent Debate** | Du et al., 2023 | Argue-then-adjudicate | musubi's "judge" is human + receipts, not a vote |
| **MetaGPT / ChatDev** | 2023 | Role specialisation in a software team | One-directional SOP pipeline, *not* peer cross-review |
| **CAMEL** | KAUST, 2023 | 2-agent dyad (structurally nearest) | Static, no human gate, no supervisor |
| **CrewAI** | 2024 | Role crews + `human_input` | No peer review-with-receipts |
| **Magentic-One** | Microsoft, 2024 | Orchestrator + specialists (≈ supervisor) | No symmetric peer pair |
| **MacNet / DyLAN** | 2024 | Many-agent scaling laws | Direct philosophical contrast: musubi's deliberate 2-coder minimalism |

**Closest neighbours:** AutoGen (architecture) and LangGraph (human gate) on
different axes; MAD on the adjudication axis. The *two-vendor peer pair + receipts
+ human gate* intersection is musubi's claimed white space — defensible, but the
claim should be stated as "no single framework combines these," which the table
supports.

## 2b. Benchmarks musubi could be scored on

- **MultiAgentBench / MARBLE** (ULab/UIUC, ACL 2025) — *the single best external
  fit.* Has a collaborative-coding scenario, a **coordination KPI** (milestone
  progress + per-agent contribution), and an LLM-judged **Communication Score**
  (message clarity/relevance). Both metrics are directly computable over musubi's
  `<OVER>`-delimited logs.
- **ColBench / SWEET-RL** (Meta, 2025) — collaborative SWE tasks with a *simulated
  human collaborator*; the nearest "collaborative software" benchmark.
- **SWE-bench / SWE-bench Verified** (Princeton, 2023; OpenAI Verified 500) — the
  field-standard solver benchmark. musubi is *not* directly rankable here (it's a
  collaboration protocol, not a solver submission) — see the validity gap below.
- **Collab-Overcooked** (EMNLP 2025) — *process-oriented* collaboration metrics
  (not just task success), matching musubi's interest in *how* the pair works.
- **BattleAgentBench** (2024) — its paired-agent tier maps to the two-coder dyad.
- Coordination-game benchmarks (**LLM-Coordination**, Hanabi/Overcooked) measure
  the coordination-reasoning axis only; lower relevance to SWE.

## 2c. Quantitative comms metrics musubi's logs could be scored with

The structured logs (`Type:` headers, `<OVER>` markers, review-request/result
ratios, `GO` batons) are unusually well-suited to existing metrics:

- **MARBLE Communication Score** — LLM-judged clarity/relevance per message.
- **Coordination KPI** (MultiAgentBench) — `GO`-baton completions per slice as the
  milestone signal.
- **Communication Efficiency Metrics trio** (IEI/SEI/TEI, arXiv 2511.09171, 2025):
  **IEI** (task-relevant info per token) over `Type:`-headed messages; **SEI**
  (message diversity → role differentiation) quantifies the coder-vs-coder
  divergence the deference work is about; **TEI** (topology/overhead cost) =
  orchestration overhead.
- **Communication frequency** `f_comm` (MARL-standard) — messages ÷ max possible;
  a natural denominator for the review ratios already tracked.
- **Closed-loop communication** as a *coded, countable* behaviour (borrowed from
  CRM/medical-simulation research) — the `<OVER>` + receipt pair is a closed-loop
  primitive. **Caveat:** this is an *adapted team-science construct*, not yet a
  standardised LLM-MAS metric — present it as adapted, not canon `(verify)`.

## 2d. Methodological instruments (how to score behaviour, not just outcomes)

Human-factors research already solved "how do you rate teamwork from a transcript":

- **NOTECHS** (Flin et al. / JARTEL, ~2003) and **ANTS** (anaesthesia, 2003/04) —
  behavioural-marker systems: trained raters score observable markers on a 5-point
  scale across categories (cooperation, leadership, situation awareness,
  decision-making) with inter-rater reliability. musubi could adapt NOTECHS-style
  markers to comms turns ("agent acknowledges peer's correction," "agent challenges
  supervisor with evidence") to score collaboration *behaviourally* rather than
  impressionistically.
- **Salas Big Five** as a presence/absence checklist (Part 1a is exactly this).

---

# Part 3 — A concrete benchmarking plan

Three tracks, in increasing cost, that would turn "we think this collaborates well"
into defensible numbers:

1. **Score the existing logs (cheap, immediate).** Run MARBLE's Communication
   Score + the IEI/SEI/TEI trio + `f_comm` over the three comms corpora. Produces
   the first quantitative collaboration profile and a per-codebase comparison.
   SEI in particular operationalises the asymmetric-deference finding (role
   divergence between the two coders).
2. **Behavioural coding (medium).** Build a NOTECHS-style marker sheet from the
   Salas Big Five + CRM authority-gradient constructs; code a sample of cycles;
   report inter-rater-style agreement using a second LLM as independent rater.
   This is the rigorous version of Part 1.
3. **Comparable solver number (expensive, optional).** Run the musubi *pair* as a
   solver on **SWE-bench Verified** to get a leaderboard-comparable resolve rate,
   alongside each agent solo — directly testing whether pairing beats either model
   alone on a standard task set.

## The ecological-validity gap (load-bearing for positioning)

SWE-bench/HumanEval maximise *comparability* (automatic test oracles, isolated
tasks) at the cost of *ecological validity*. musubi's evidence is the opposite: real
production codebases (and a non-software domain, equity research), where the oracle
is human review + the codebase's own tests. The honest framing — **musubi is a
collaboration protocol, not a solver submission** — means track 1 (process metrics
on real logs) and track 3 (a comparable solver number) answer *different* questions
and both are worth having. Don't let a SWE-bench number become the only scoreboard;
the process metrics are where musubi's actual claim lives.

---

## Bottom line

- **Sophistication:** measured against the canonical teamwork model (Salas Big
  Five) and CRM, the system shows genuine, receipted collaborative cognition on
  every component — strongest on mutual monitoring, metacognition, and adaptive
  rule-minting; weakest on sustained genuine disagreement (it converges fast and
  consensually). "Asymmetric deference" is the established CRM *authority-gradient*
  failure, which is a credibility asset.
- **Benchmarks:** no single framework occupies musubi's intersection, but
  **MARBLE/MultiAgentBench** (Communication Score + coordination KPI + collaborative
  coding) is the best real external comparison, the **CEM trio** the best comms-log
  metrics, and **NOTECHS-style behavioural coding** the best method for scoring
  collaboration quality from transcripts. A three-track plan turns the qualitative
  claim into numbers without abandoning the ecological validity that is musubi's
  distinctive evidence.

---

*Sources — corpus: `docs/agents/` archives in `~/Dev/aic/cc-aic`,
`~/Dev/1-in-a-billion-paradise`, `~/Dev/portfolio-experiment` (grep + targeted read
2026-06-09). External (selected): Salas, Sims & Burke 2005 (Small Group Research);
Clark & Brennan 1991; Cannon-Bowers, Salas & Converse 1993; Wegner 1987; Grice 1975;
Flin et al. NOTECHS ~2003; AutoGen (arXiv 2308.08155); MetaGPT; ChatDev; CAMEL;
LangGraph; Multi-Agent Debate (Du et al. 2023); MultiAgentBench/MARBLE (arXiv
2503.01935, ACL 2025); ColBench/SWEET-RL (arXiv 2503.15478); SWE-bench (Princeton
2023) + Verified; Collab-Overcooked (EMNLP 2025); CEM IEI/SEI/TEI (arXiv 2511.09171).
Items flagged `(verify)` need a primary-source check before external citation.*
