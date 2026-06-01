# Asymmetry Report — schema v1

Per-cycle artefact authored by Oya at cycle close. Captures the points where the two different-vendor agents (Opus + Coda) made or would have made different calls — the framework's most distinctive empirical signal, surfaced explicitly rather than left buried in comms threads.

Reports accumulate at `docs/agents/asymmetry/<cycle-name>.md` inside the target project. Over time the corpus becomes the evidence base for the framework's load-bearing claim — *"two different-vendor LLMs catch more than two same-vendor LLMs."* On any given Tuesday you can grep N cycles of asymmetry reports and answer the sales question *"why pay for two vendors?"* with concrete catches.

## Why this exists

Vendor disagreement is the most distinctive signal the pair produces. Every other framework claim (structured peer review, mechanical guards, supervisor pattern) is now also being made elsewhere. Asymmetric-vendor catches are not. But in normal cycle operation the signal is thrown away — Opus writes "I'd take approach A," Coda's review says "I'd actually do B," they reconcile, and the disagreement vanishes into a merged consensus. The asymmetry report extracts the disagreement *before* it vanishes, classifies it, names the pattern it reveals.

## File location + lifecycle

- **Path:** `docs/agents/asymmetry/<cycle-slug>.md` inside the target project (e.g. `docs/agents/asymmetry/platform-ds-audit-2026-05-19.md`).
- **Author:** Oya, at cycle close. The pair does not write asymmetry reports — only Oya, who reads the full comms thread and can extract disagreements neutrally.
- **Trigger:** Oya's cycle-close exec brief is the *operator-facing* summary; the asymmetry report is the *corpus-facing* summary. Both produced in the same close-out pass.
- **Empty cycles:** if a cycle had zero substantive disagreements, the report still gets written with `## Disagreements\n\n_None this cycle._` plus a one-line note in **Patterns observed** explaining why (e.g. "lightweight-lane single-author cycle; no peer-review surface"). Empty reports are corpus signal too.
- **Commit:** the `asymmetry/` directory IS committed (unlike `comms/` which is gitignored) — the corpus is durable evidence and survives session boundaries.

## What counts as a "disagreement"

Threshold (any one is sufficient):

1. A `Review Result` with `Result: changes_requested` that names a BLOCKER class.
2. A `Decision` or `Blocker` message containing explicit push-back ("I disagree," "wrong approach," "I'd take X instead").
3. A `Deviation` Opus or Coda explicitly flagged in a Review Request that the peer accepted or rejected.
4. An `@OYA` Decision message that adjudicated between two stated agent positions.
5. A capsule footnote / Open follow-up that records a per-agent split position.

Routine ack chains, GO baton handoffs, mechanical-guard refusals, and same-direction Findings DO NOT count as disagreements. The bar is *explicit, named, vendor-specific position divergence*.

## Schema (v1)

```markdown
# Asymmetry Report — <cycle-slug>

**Cycle:** <name> (<start-date> → <end-date>)
**Slices:** <count + identifier list>
**Authored by:** @OYA at <timestamp UTC>
**Pair:** @OPUS (<vendor>) ↔ @CODA (<vendor>)

---

## Summary

<2–4 sentences naming the cycle's vendor-asymmetry texture: were disagreements clustered around one class? did one agent consistently catch / get caught? was the resolution rate skewed?>

**Disagreements surfaced:** N
**Resolutions:** P opus-right · Q coda-right · R partial · S reconciled · T unresolved

---

## Disagreements

### D1 — <short-name> (<class>)

**Slice:** <slice ID>
**Surfaced:** <YYYY-MM-DD HH:MM UTC> via <comms reference — message subject + sender>

**@OPUS position:**
<one paragraph quoting or summarising Opus's stance, with file:line evidence if applicable>

**@CODA position:**
<one paragraph quoting or summarising Coda's stance, with file:line evidence if applicable>

**Resolution:** <opus-right | coda-right | partial | reconciled | unresolved>
<one paragraph: how the disagreement resolved, who/what produced the resolution (the pair themselves, @LEAD, @OYA), and what landed in the slice>

**Vendor-asymmetry signal:**
<one or two sentences naming the pattern this disagreement reveals about the two vendors' default tendencies. This is the corpus row. Examples:
- "Opus defaults to removing scaffolding when the static path covers the case; Coda preserves scaffolding by default and requires explicit justification to remove it."
- "Coda holds plan-as-written; Opus exercises architectural judgement to defer when implementation reveals a misfit. Resolution required explicit scope update.">

---

### D2 — ...

<repeat per disagreement>

---

## Patterns observed across this cycle

- <bullets — recurring asymmetry classes; calibration drift; surprising consensus on something contested elsewhere>
- <each bullet ≤2 sentences; cite a disagreement ID and a corpus signal>

---

## Corpus contribution

This cycle adds the following rows to the asymmetry corpus:

| Class | Vendor-asymmetry signal | Instance count this cycle |
|---|---|---|
| <class> | <signal — copy from a Vendor-asymmetry signal field above> | <N> |

---

## Methodology notes

<optional one-paragraph: any unusual call about what was included or excluded as a disagreement; any classification ambiguity; anything the operator should know about how Oya scoped the report>
```

## Classes — locked v1 taxonomy

Disagreement classes are a fixed set so the corpus is queryable. Use exactly one per disagreement.

| Class | What belongs here |
|---|---|
| `architectural` | structure / shape / placement / abstraction-level choices — "should this be one component or two?", "does this go in the shell or the page?" |
| `scope` | what's in / out of this slice — "should X be deferred?", "this is a separate cycle's work" |
| `spec-doc-accuracy` | docs, plans, or capsules diverging from reality — wrong file paths, wrong counts, wrong scope statements |
| `test-design` | what should be tested, how, at what layer — "this needs an integration test not a unit test," "the bug-path test doesn't probe the actual bug" |
| `risk-tolerance` | how aggressive vs cautious to be on a specific change — push-now vs push-after, allowlist vs broad, hotfix vs full-fix |
| `style` | code style, naming, comments, formatting — narrow, low-stakes |
| `tooling` | which command / script / library / config to use for a given purpose |
| `other` | use sparingly; if `other` appears more than ~10% of the corpus, the taxonomy needs another class added |

## Resolution types — locked v1 taxonomy

| Type | Meaning |
|---|---|
| `opus-right` | Coda's blocker withdrawn or judged incorrect; the change lands as Opus proposed |
| `coda-right` | Opus's deviation reversed; the change lands as Coda required |
| `partial` | Mixed outcome — some of each agent's position lands; common when the disagreement bundles multiple sub-issues |
| `reconciled` | Synthesis neither agent originally proposed; usually @OYA- or @LEAD-mediated |
| `unresolved` | Cycle closed with the disagreement still open (filed to BACKLOG / I&A / next cycle) |

## Vendor-asymmetry signal — the corpus value

The signal field is the report's *load-bearing* sentence. A good signal:

- Names a *tendency*, not the specific instance ("Opus defaults to X; Coda defaults to Y").
- Is falsifiable — a future disagreement of the same class will either confirm or contradict it.
- Is short — one or two sentences. The corpus accumulates many rows; brevity matters.

Examples of good signals (from the framework's reference corpus):

- "Opus prefers light-touch migration paths and exercises architectural judgement to defer surfaces that don't fit a constrained pattern; Coda holds plan-as-written until the plan is explicitly amended." *(class: scope)*
- "Coda treats spec-doc accuracy as a peer-review surface; Opus prioritises code-truth over doc-text and accepts post-hoc spec updates." *(class: spec-doc-accuracy)*
- "Opus removes optional scaffolding aggressively when the static path covers the case; Coda preserves scaffolding by default unless the cost is named." *(class: architectural)*

Examples of bad signals (do not produce these):

- "Opus and Coda disagreed about ThemeProvider." *(instance-specific, not a tendency)*
- "Opus was too optimistic." *(judgement without specifics; not falsifiable)*
- "Different vendors have different preferences." *(content-free)*

## What this is not

- **Not** a per-slice diff log. The cycle-close exec brief in `oyakata-log.md` covers operator-facing cycle outcomes; this report covers vendor-asymmetry only.
- **Not** an arbiter / scoreboard. The corpus is descriptive, not normative. "Opus was right N times" is a less interesting fact than "Opus tends to make this class of call this way."
- **Not** a complete record of the cycle. A disagreement that didn't meet the threshold above is intentionally excluded — the report's value is the high-quality signal, not the full transcript.

## See also

- `oyakata-prompt-v0.1.md` — Oya's prompt, which includes the cycle-close authorship instruction.
- Your own asymmetry corpus at `docs/agents/asymmetry/` once the framework runs cycles in your project. The author's reference corpus (stored separately from this repo) is the canonical worked-example collection.
