# Rules Ledger — schema v1

Per-project artefact at `docs/agents/rules-ledger.yml`. Tracks every named rule the project's runbook + project-rules files (`CLAUDE.md` / `CODEX.md`) define, plus the empirical data on each rule's activity: how often it fires, what it catches, how often it gets bypassed, what its provenance is.

The framework that requires machine-verified evidence for code claims now applies the same standard to its own rules. The ledger is the framework's most self-reflexive artefact — every rule earns its keep with data, or surfaces as a candidate for pruning, promotion, or refinement.

## Why this exists

Most protocols accrete rules. Few prune them. The runbook reached v1.7 through retrospective hand-audits — every rule has a story in someone's head about why it exists, but no rule has *empirical data* about whether it's still earning its keep. After 8 weeks of production use on a single codebase, the runbook is already heavy. After 8 months across multiple projects, it'll be unmaintainable unless rules retire on their own evidence.

The ledger is the framework eating its own dogfood. Just as the asymmetry corpus turns vendor-disagreement anecdote into queryable evidence, the rules ledger turns rule provenance + activity into queryable evidence. After 3–6 months of accumulating data, the ledger answers questions like:

- *"Has the bug-path test gate ever caught a real bug, or is it discipline theatre?"*
- *"How often does the capsule-staleness guard fire vs how often does it actually catch a stale-claim drift?"*
- *"Which STOP rules have zero fires across 12 cycles? Why are they still in CLAUDE.md?"*
- *"What's the ack-rate on the three-consecutive-patches circuit breaker? Are we breaking it too often, suggesting the rule's threshold is wrong?"*

Each of those is a runbook-improvement signal that's currently invisible.

## File location + lifecycle

- **Path:** `docs/agents/rules-ledger.yml` inside the target project.
- **Format:** YAML (chosen for machine-edit friendliness + human readability).
- **Author:** the `fires` counters + header metadata are written mechanically by `scripts/ledger-from-comms.py --apply` at cycle close (protocol-1 Tier 1); Oya authors the judgment counters (catches, bypasses, silent_misses, skips) and the `cycle_summary` notable_signals in the same pass. Operator may also hand-edit to add rules, fix provenance, or refine `notes` fields.
- **Initial backfill:** when the ledger is first created (or when a new rule lands in the runbook), the rule's entry is created with zero counters. Subsequent cycles populate the empirical data.
- **Committed:** yes. Like the asymmetry corpus, the ledger is durable evidence and survives session boundaries.

## What counts as a "fire"

A rule **fires** when:

1. The rule's canonical name appears in a comms message in a load-bearing position (cited as authority, blocker, requirement, or specification). Example: *"per STOP rule 18, surfacing CI baseline …"* — the citation IS the fire.
2. A mechanical guard refuses a relay due to the rule (Ack-of-ack guard, Capsule-staleness guard). The orchestrator's stdout log is authoritative for these.
3. A reviewer's `Findings I went looking for` block names the rule as a probed class — counts as a fire even if not found.
4. An Oya log entry observes the rule fired (or should have fired but didn't — see *silent_misses* below).

Routine mentions in passing ("the runbook says X, FYI") DO NOT count. The bar is *the rule shaped the outcome of this comms event*.

## What counts as a "catch"

A fire is **also a catch** when:

- The cited rule prevented a defect that would otherwise have shipped (a reviewer found the issue *because they were following the discipline the rule prescribes*).
- A mechanical guard refusal led to a corrected action that wouldn't have been corrected without the refusal.
- A `Findings I went looking for` entry returned `found` AND the finding was substantive (changes-requested / blocker), not cosmetic.

Catches are classified by the same taxonomy as the asymmetry corpus (`architectural`, `scope`, `spec-doc-accuracy`, `test-design`, `risk-tolerance`, `style`, `tooling`, `other`) plus `protocol-discipline` for rules that catch process violations rather than code defects.

## What counts as a "bypass"

A **bypass** happens when:

- The rule fires but the operator (or agent with cited authority) waives it for the specific event. Example: `@LEAD` pre-acknowledges a stale CI baseline, bypassing STOP rule 18 for this push.
- An agent acks the rule but explicitly states "not applicable this time" with a stated reason. The reason is logged in the bypass entry.

Bypasses are not failures — they're *information about whether the rule fires in cases where the operator doesn't actually want it to*. High bypass rate is a refinement signal (the rule is over-broad).

## What counts as a "skip"

> **Added in v0.3-strategic (2026-05-20).** Specific to strategic-Oya discipline rules. Earlier rule types (`invariant`, `guard`, `discipline`, `mechanism`, `stop-rule` from runbook v1.7) do not use this counter — their non-application is captured as `silent_misses` instead.

A **skip** happens when Oya's slice-claim challenge fires the discipline (triggered by the scope sensor), the pair is informed via an `@OYA` Recommendation, and the pair acknowledges but does not produce the required artefact before push. Skips are the *forgiving authority* path made visible.

A skip is NOT a defect:
- The pair (or operator) has authority to skip any discipline; the runbook does not block on this.
- Skipping is rational when the slice's context makes the discipline costly relative to its expected value.
- High skip rates per discipline are a sensor-refinement signal (the discipline may be over-triggering), not a discipline failure.

A skip IS structural evidence:
- The cumulative skip count per discipline tells the operator which strategic concerns the cycle keeps deferring.
- Patterns over time (e.g. *"3 cycles in a row shipped auth changes with no threat model"*) become operator-facing signals at cycle close.
- Compares cleanly against later catches/incidents to falsify discipline value (high skip + zero downstream defect = discipline is theatre; high skip + recurrent defect = the skip pattern was costly).

Skips are distinct from bypasses:

| | Bypass | Skip |
|---|---|---|
| Trigger | Mechanical guard / numbered STOP rule fires | Strategic-Oya discipline triggered by scope sensor |
| Authority | Operator's explicit waiver with reason | Pair acknowledgement; no formal waiver required |
| Severity | Tracked but not surfaced (legitimate operator override) | Tracked AND surfaced at cycle close (pattern matters) |

## What counts as a "silent miss"

A **silent miss** is the inverse of a fire: an event happened where the rule's preconditions were met and it *should have fired*, but it didn't. Almost always logged by Oya retrospectively at cycle close (the pair wouldn't catch their own miss).

High silent-miss rate is a discipline-drift signal (the rule exists but is being forgotten in practice).

## Schema (v1)

```yaml
schema_version: 1
project: <project-slug>             # your project's slug — rename when copying
runbook_version: "<vX.Y>"            # e.g. "1.7"
generated_at: <ISO-8601 UTC>         # first-creation timestamp
last_updated_at: <ISO-8601 UTC>      # most recent Oya update
last_updated_cycle: <cycle-slug>     # which cycle's close-out wrote the last update

rules:
  - id: <kebab-case-identifier>         # canonical id used everywhere; matches citation_pattern
    type: <invariant | guard | discipline | mechanism | stop-rule>
    scope: <framework | project>        # framework = from the runbook; project = from CLAUDE.md/CODEX.md
    runbook_section: "<file § section heading path>"
    citation_pattern: "<substring agents type when invoking the rule>"

    provenance:
      added_in_runbook_version: "<vX.Y>"
      added_on: <YYYY-MM-DD>
      added_reason: |
        <1–4 sentences naming the incident or rationale that produced the rule.>
      revisions:                        # optional list; one entry per material revision
        - version: "<vX.Y>"
          date: <YYYY-MM-DD>
          note: "<what changed and why>"

    fires:
      total: <int>
      by_cycle: {}                      # {cycle-slug: count}
    catches:
      total: <int>
      by_class: {}                      # {architectural: N, scope: N, …, protocol-discipline: N}
      examples: []                      # optional: brief refs to standout catches with cycle-slug + 1-line description
    bypasses:
      total: <int>
      examples: []                      # optional: bypass instances + stated reason
    skipped:                            # v0.3+ — strategic-Oya disciplines only; omit for older rule types
      total: <int>
      examples: []                      # optional: cycle-slug + 1-line context
    silent_misses:
      total: <int>
      examples: []                      # optional

    notes: |
      <free text Oya or operator can add: known sensitivities, recent threshold
      changes, cross-references to other rules.>

# Rules-ledger metadata Oya writes at cycle close
cycle_summary:
  - cycle: <cycle-slug>
    closed_at: <ISO-8601 UTC>
    rules_that_fired: <int>             # distinct rules that had at least one fire
    total_fires: <int>
    total_catches: <int>
    total_bypasses: <int>
    notable_signals: |
      <2–4 sentences: which rules earned heavily, which were silent, which bypassed unexpectedly.>
```

## Locked taxonomies

### Rule `type`

| Type | What it is |
|---|---|
| `invariant` | A stated property that must always hold. Violations are caught after the fact and require correction. Example: capsule-before-comms invariant. |
| `guard` | An orchestrator-enforced refusal (mechanical, automatic, blocks the action). Example: capsule-staleness guard. |
| `discipline` | A required practice the agents apply during work. Example: Findings I went looking for block; bug-path test gate. |
| `mechanism` | A specific procedural construct (named, reusable). Example: GO baton, proof block, lane choice. |
| `stop-rule` | A numbered project-specific rule from CLAUDE.md / CODEX.md (e.g. STOP rule 18, STOP rule 19, STOP rule 20). |
| `strategic-discipline` | A v0.3+ engineering-discipline rule (threat-model-auth-changes, abuse-case-named-on-new-input, etc.) Triggered by the scope sensor on slice-claim. Forgiving authority — uses the `skipped` counter alongside fires/catches. |

### Catch `by_class`

Same taxonomy as the asymmetry corpus (`architectural` / `scope` / `spec-doc-accuracy` / `test-design` / `risk-tolerance` / `style` / `tooling` / `other`) plus one extra class specific to the ledger:

- `protocol-discipline` — the catch is a process violation (not a code defect), e.g. a reviewer caught an agent skipping the Findings block.

## Health signals — how to read the ledger

The schema doesn't include a `health` field for v1 because thresholds depend on cycle volume + project context. After 5+ cycle updates, Oya can begin computing health signals manually in the cycle-summary `notable_signals` field. Suggested heuristics:

| Pattern | Interpretation |
|---|---|
| `fires.total == 0` across ≥ 5 cycles | **Candidate for pruning.** The rule has had zero opportunities to apply. Either the use case it addresses has disappeared, or its citation pattern is wrong and we're missing fires. Investigate before removing. |
| `fires.total > 0`, `catches.total == 0` across ≥ 5 cycles | **Candidate for refinement.** The rule fires but never catches. It's discipline theatre — agents cite it but it doesn't shape outcomes. Either the threshold is wrong or the rule's logic doesn't match the actual failure mode. |
| `catches.total / fires.total > 0.5` | **Earning its keep.** The rule fires for genuine reasons and catches a substantial fraction of those fires. Consider promoting (e.g. discipline → guard, where mechanical enforcement is possible). |
| `bypasses.total / fires.total > 0.3` | **Over-broad.** The rule fires in cases where the operator doesn't actually want enforcement. Refine the trigger condition. |
| `silent_misses.total > catches.total` | **Discipline drift.** The rule exists but is being forgotten. Either tighten the prompt/runbook, or accept that the rule is too easy to skip and rebuild it as a mechanical guard. |
| `skipped.total / fires.total > 0.7` (strategic-Oya disciplines only) | **Sensor over-firing OR discipline genuinely costly.** Either the scope sensor's triggers are too broad (false positives), or the discipline is firing on genuine cases but its cost-to-value ratio doesn't justify operator effort. Investigate via the skip examples + downstream defect rate. |

These are heuristics, not laws. Operator judgement always trumps the numbers — the ledger surfaces *signals*, not verdicts.

## Worked example

The framework ships an initial ledger template at `templates/rules-ledger.yml.template` with 13 high-prominence framework rules from runbook v1.7. The template is copied into new bootstraps as `docs/agents/rules-ledger.yml`; counters start at zero and Oya's cycle-close updates fill them in over time. Add project-specific STOP rules to your install's ledger under the same shape (commented template included).

## See also

- `oyakata-prompt-v0.1.md` § Cycle-close rules-ledger update — Oya's authorship instructions.
- `asymmetry-schema.md` — sibling artefact, applies the same data-not-doctrine principle to vendor-disagreement.
- `docs/agents/AGENT_COLLAB_RUNBOOK.md` (in your project) — the rules being tracked.

## Open design questions (v2+)

- **Confidence-scored catches.** Brier-style: each catch carries a confidence level; cycle-close compares against post-merge bug discovery. The natural successor once the ledger has 3+ months of data.
- **Cross-project meta-ledger.** Once musubi has multiple deployments, aggregate ledgers to find rules that earn their keep across contexts vs ones that are project-specific.
- **Automated pruning proposals.** Oya generates PR-style runbook patches based on ledger signals ("propose removing X; here's the data"). Currently the patches are produced by human reading the ledger — that's fine for v1.
