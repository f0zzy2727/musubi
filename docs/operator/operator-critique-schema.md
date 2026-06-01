# Operator Critique — schema v1

Per-cycle artefact authored by Oya. Reviews the **operator's** (@LEAD's) cycle decisions for the same failure modes Oya watches for in the pair: confirmation bias, scope drift, asymmetric deference (this time, deference *to* the pair instead of *between* them), unstated assumptions, premature closure.

Lives at `docs/agents/operator-critique/<cycle-slug>.md` inside the target project. Committed. Sibling to the asymmetry corpus and rules ledger.

## Why this exists

The framework's load-bearing claim is *"no actor + reviewer combo can self-detect their own deference."* That claim is symmetric. It applies to operator + pair just as much as to Opus + Coda. The operator sees the pair's work and forms judgements (gate waivers, scope decisions, slice acceptance, push approvals) but has no one watching whether *their own* judgements drift, over-defer, or smuggle in confirmation bias.

The asymmetry corpus closes the loop at the pair altitude. The operator critique closes it at the operator altitude. Without this, the framework has a structural blind spot — the operator gets to mark their own work.

## File location + lifecycle

- **Path:** `docs/agents/operator-critique/<cycle-slug>.md`.
- **Author:** Oya at cycle close, in the same pass as exec brief / asymmetry report / rules ledger.
- **Cadence:** NOT every cycle. Author when **at least one** of these signals fires:
  - Operator gate-waiver invoked this cycle (stale CI baseline, scope expansion, mid-cycle re-prioritisation, etc.)
  - Operator decision overrode a pair-stated position (resolved a dispute with operator authority rather than letting the pair reconcile)
  - Operator approved a slice with zero spot-checks despite the slice meeting spot-check criteria (>50 LOC or >3 files, zero findings)
  - Oya observed three consecutive operator approvals with no question / pushback / refinement (the operator-side equivalent of the ack-of-ack guard)
  - Operator requested a critique explicitly
- If none of those fire, skip. Empty critique reports are not useful signal at the operator altitude.

## Schema

```markdown
# Operator Critique — <cycle-slug>

**Cycle:** <name + dates>
**Operator:** @LEAD
**Authored by:** @OYA at <timestamp UTC>
**Trigger:** <which signal fired — gate-waiver / override / silent-spot-check / 3-approval-streak / explicit-request>

---

## Decisions reviewed this cycle

<List the operator's load-bearing decisions for the cycle — gate waivers, dispute adjudications, slice acceptances, push approvals, scope changes. One bullet each with timestamp + comms ref.>

## Observed patterns

For each pattern observed, name the class (`confirmation-bias` / `scope-drift` / `pair-deference` / `unstated-assumption` / `premature-closure` / `other`) and the evidence.

### <pattern-name> — <class>

**Evidence:**
- <timestamp + comms ref>
- <timestamp + comms ref>

**What this looks like:**
<one paragraph: what specifically happened, why it matches the named class>

**Suggested counter-discipline:**
<one paragraph: what the operator could do differently if this pattern recurs. Concrete: "before approving a stale-baseline push, require @CODA to also confirm the bypass scope is what they understand" or similar.>

---

(repeat per pattern)

## Patterns NOT observed (what went well)

<Optional 2–3 bullets naming places where the operator's discipline held — gate waivers backed by quoted @LEAD rationale; decisions where the operator pushed back on the pair rather than accepting; etc. Important to log because it prevents the critique becoming a relentless-fault-finding artefact.>

## Open question for the operator

<One specific question Oya wants @LEAD to consider before next cycle. Optional.>
```

## Locked taxonomy — operator-side classes

| Class | What belongs here |
|---|---|
| `confirmation-bias` | Operator accepted a position they were already inclined toward without testing it against contrary evidence the pair had surfaced. |
| `scope-drift` | Operator approved a scope expansion mid-cycle without an explicit "is this still one slice?" check. |
| `pair-deference` | Operator deferred a decision to the pair where the operator's own judgement would have been load-bearing — usually because deferring is faster. Mirror of asymmetric deference but at operator altitude. |
| `unstated-assumption` | Operator's decision rests on an assumption that the pair hasn't confirmed and that turns out to be wrong or fragile. |
| `premature-closure` | Operator closed a discussion / approved a slice / waived a gate before all surfaced concerns had a stated resolution. |
| `other` | Use sparingly. If `other` exceeds ~15% over time, the taxonomy needs another class. |

## Discipline

- **Quote, don't paraphrase.** Where the operator's words matter (gate waivers, override decisions), quote them with comms ref or pane timestamp.
- **Be specific.** "Operator drifted on scope" is not useful. "Operator approved adding S5 mid-cycle at 09:47 UTC without flagging that the original 4-slice plan had three remaining" is.
- **Counter-discipline must be actionable.** Avoid "the operator should be more careful." Suggest a concrete check, citation, or prompt the operator can use next time.
- **Tone is collegial, not adversarial.** This is a critique, not a charge sheet. The framework treats the operator as a peer who benefits from a third-party read on their own decisions — same way the pair benefits from Oya's read on theirs.

## What this is not

- Not a scoreboard. The artefact is descriptive, not normative. "Operator was wrong N times" is not the point.
- Not a record of every operator decision. Only the load-bearing ones + the ones where a pattern surfaced.
- Not a mid-cycle intervention. The critique is written at cycle close; in-flight operator concerns go via the normal `@OYA → @LEAD in pane` channel.
- Not a substitute for retro. Cycle retros (when held) are bigger; the critique is the per-cycle operator-altitude read.

## See also

- `oyakata-prompt-v0.1.md` § Cycle-close operator critique — Oya's authorship instructions.
- `asymmetry-schema.md` — sibling artefact at the pair altitude.
- `rules-ledger-schema.md` — sibling artefact at the protocol altitude.
