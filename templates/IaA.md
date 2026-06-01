<!-- musubi-managed: Inspect & Adapt spec. To customize, remove this marker so bootstrap.sh stops refreshing this file. -->
<!-- @LEAD kickoff: append one line to the active comms file:
     "@OPUS @CODA: open docs/agents/IaA.md and run the IaA. <OVER>"
     Both agents read this file end-to-end and execute it. No paraphrasing required from @LEAD. -->

# Inspect & Adapt — Cross-Pair Audit

**You are reading this because @LEAD has asked you to run the IaA.** This file is the spec. Execute it. Do not summarise it back to @LEAD; do the work.

**Today's date** for all artifact filenames and rolling-window references: use the actual current date in `YYYY-MM-DD` form. If you don't know it, run `date -u +%F` first.

---

## Why this exists

Pattern @LEAD keeps seeing: details get missed by both of you in your own work AND in your reviews of each other's work. When @LEAD personally spots something, you act. When @LEAD doesn't, it ships. The peer-review layer is currently a formality, not a load-bearing gate. The asymmetric-agents framing in the runbook says one of you should be the "suspicious adult in the room"; right now neither of you is playing that role hard enough on the OTHER's work. We are going to fix the structure, not the symptoms — AND evaluate whether new skills/tooling can reduce the surface area where misses happen at all.

## Scope guardrail

This is NOT a retro write-up. A retro lists what happened. An I&A produces enforceable mechanisms that change behaviour next cycle. **Every finding ends with a `Mechanism:` block or it does not count.** No production code changes this cycle — docs, rule files, gate scripts, and skill installs only.

## Deliverables

1. Four evidence files under `docs/improvements/IA-evidence/`
2. A joint root-cause clustering posted in comms
3. A consolidated I&A doc at `docs/improvements/IA-<TODAY>-peer-suspicion-gap.md`
4. Patches to: `AGENT_COLLAB_RUNBOOK.md`, `CLAUDE.md`, `AGENTS.md`, the agent-handoff template
5. ≥1 new mechanical gate wired into pre-commit or pre-push
6. ≥2 newly-installed skills/tools with mechanism blocks proving they're wired in
7. A new "Peer-review escapes" section in the handoff template

## Kickoff (do this first, before anything else)

1. Run `date -u +%F` and use that as `<TODAY>` in every filename below.
2. Update `docs/agents/current-state.md`: open a new active cycle named `ia-peer-suspicion-<TODAY>`. Capsule-before-comms invariant applies.
3. Run `mkdir -p docs/improvements/IA-evidence`.
4. Each agent posts a slice acceptance receipt in comms naming their Phase 1 file targets. State: `claimed`. No `started` until you've actually opened an archive file.
5. Then begin Phase 1 in parallel.

---

## PHASE 1 — EVIDENCE GATHERING (parallel, ~45–60 min each)

Each agent produces TWO evidence files. Do not draft conclusions yet — just collect.

**OPUS writes:**
- `docs/improvements/IA-evidence/opus-self.md`
- `docs/improvements/IA-evidence/opus-on-coda.md`

**CODA writes:**
- `docs/improvements/IA-evidence/coda-self.md`
- `docs/improvements/IA-evidence/coda-on-opus.md`

**Sources to scan (all of them — if you finish in under 30 minutes you didn't read the archives):**
1. `docs/agents/comms/active.txt` — current cycle
2. `docs/agents/archive/*.txt` — every archived cycle, read them all
3. `docs/agents/agent-handoff.md` — every entry
4. Last 100 commits on `main`: `git log --format='%h %s%n%b' -100`
5. Recent PR / push approval threads in comms
6. Every @LEAD intervention message — search comms for messages where @LEAD identified a defect or flagged a missed detail

**Row format. Use exactly this. No prose between rows.**

```
---
Incident: <one-line label>
Source: <file:line OR commit SHA OR comms timestamp>
Symptom: <observable defect — quote @LEAD or the agent verbatim>
Caught by: @LEAD | @OPUS | @CODA | CI | not caught
Should have been caught by: @OPUS | @CODA | mechanical gate | unrealistic to catch
Class: status-inflation | missed review detail | shallow validation | drift from plan | doc-debt | terminology | impact-analysis-skip | tooling-gap | other:<name>
Evidence the reviewer missed it: <exact quote from peer's review message OR "no review message exists">
Could a skill/tool have caught this: yes:<which capability> | no:<why human-judgement-only>
---
```

**Hard requirement:** the `-on-<peer>` files need ≥8 incidents each, all sourced. The pattern @LEAD is naming has been recurring for months; the evidence is there. If you can't find 8, you didn't look hard enough — go back to the archives.

**End of Phase 1:** each agent posts a `Review Request` in comms for their two files. Wait for peer review before Phase 2.

---

## PHASE 2 — ROOT CAUSE CLUSTERING (joint, in comms)

After exchanging evidence files via `Review Request` messages, post a single joint clustering message. For each class:

```
Class: <name>
Incident count: <n> (cite the row IDs)
Why current rules failed to catch it: <specific — name the rule, name the gap>
Asymmetry observation: did one agent miss this class more than the other? Which one and why?
  ("Both equally" is permissible ONLY if the evidence supports it — default suspicion is that
  the asymmetric-agents framing applies and one of you owns more of the misses.)
Tooling-addressable share: <n of n> — incidents in this class a skill/gate/linter could catch without judgement.
```

**Minimum 4 root-cause classes.** Fewer = clustering too coarsely.

---

## PHASE 3 — CONCRETE COUNTERMEASURES

Write `docs/improvements/IA-<TODAY>-peer-suspicion-gap.md` with this structure:

1. **Executive summary** — ≤10 lines, no fluff
2. **Evidence summary** — link to the four evidence files, total incident count, per-class count
3. **Countermeasures** — one section per root-cause class. Each MUST include:
   - **Target file:** exact path (runbook / CLAUDE.md / AGENTS.md / handoff template / new gate script / new skill install)
   - **Change type:** new rule | tightened rule | new mechanical gate | template change | retired rule | new skill | replaced skill
   - **Proposed text:** exact diff or replacement block, paste-ready
   - **Mechanism block** (mandatory, per runbook §Rule Quality):
     ```
     - Run: <exact command>
     - Expect: <exact output>
     - Fail if: <observable condition>
     ```
   - **Owner of the follow-up patch:** @OPUS | @CODA
   - **Why this prevents the named class:** one sentence, tied to specific incidents
4. **Adversarial-review protocol upgrade** — see Phase 4
5. **Skill / tooling adoption plan** — see Phase 5
6. **Detection slice for THIS cycle** — name the new mechanical gate that ships in this cycle
7. **Open questions for @LEAD** — explicit list, with options

Anything without a `Mechanism:` block is a wish. Strip it.

---

## PHASE 4 — THE PEER-SUSPICION PROTOCOL (the headline behavioural output)

This is the section that addresses @LEAD's actual complaint. Design — and propose as a runbook patch — an "adversarial review" pattern with these properties. For each, produce the exact runbook diff and a `Mechanism:` block.

**(a) "Findings I went looking for" block.** Every review message MUST include a list of ≥5 specific defect classes the reviewer actively probed for, each with a one-line result (found / not found / N/A and why). Reviews without this block are non-compliant — same standing as a missing proof block today.

**(b) Provable file reads.** The reviewer MUST read the actual files on disk, not just the diff summary, AND state that explicitly with a `read:` field listing the file paths they opened.

**(c) Spot-check on rubber stamps.** If a review returns "approved" with zero findings on a slice >50 LOC or touching >3 files, the OTHER agent (not author, not reviewer) does a 5-minute spot-check before push. Approval is provisional until the spot-check lands.

**(d) Asymmetric stance assignment.** One of you is designated default-skeptic for the cycle. Their review default is "find what's wrong"; the other's default is "find what's missing." Rotate per cycle. Propose which agent starts as default-skeptic and why, based on the Phase 2 asymmetry observations.

**(e) Escape tripwire.** If @LEAD identifies a defect that BOTH of you reviewed and approved, that triggers a mandatory 1-paragraph postmortem in `docs/agents/agent-handoff.md` under a new "Peer-review escapes" section. Three escapes in a rolling 14-day window auto-escalate the protocol.

---

## PHASE 5 — SKILL / TOOLING ADOPTION (the structural output)

Phase 4 closes gaps where judgement failed. Phase 5 closes gaps where the surface area itself was too wide. Each agent produces a candidate list of skills, plugins, or tools that map to the root-cause classes from Phase 2.

**Sources to evaluate:**
1. Skills already installed locally — audit which are underused for the patterns in evidence
2. The musubi `scripts/` directory — gates and helpers that exist but aren't wired into pre-commit/pre-push
3. Public skill repositories, including:
   - https://github.com/dpearson2699/swift-ios-skills (example pattern: domain-focused skill bundles)
   - https://github.com/anthropics/skills (Anthropic's official skills repo, if accessible)
   - The Claude Code marketplace / `/plugin` catalogue
   - Any skills referenced in `CLAUDE.md` / `AGENTS.md` that aren't currently installed
4. MCP servers relevant to the codebase domain (database introspection, browser automation, doc fetchers)
5. Linters, type checkers, or static analyzers not currently in the CI chain

**Row format. Use exactly this.**

```
---
Candidate: <name>
Source: <URL or local path>
Type: skill | plugin | MCP server | gate script | linter | other
Currently installed: yes | no
Maps to root-cause class(es): <list from Phase 2>
What it would catch / prevent: <one concrete sentence tied to a specific Phase 1 incident row>
Cost to adopt: trivial | moderate | significant — with reasoning (install, config, runtime, learning curve, deps)
Risk of adoption: <one sentence — flakiness, false positives, supply-chain trust, lock-in>
Recommendation: adopt-now | trial | reject | defer-with-trigger:<condition>
Owner if adopted: @OPUS | @CODA | both
Mechanism if adopted:
  - Run: <install command + how it gets invoked in the workflow>
  - Expect: <observable behaviour proving it's wired in>
  - Fail if: <condition that would mean the skill isn't actually being used>
---
```

**Hard requirements for Phase 5:**
- ≥6 candidates total across both agents
- ≥2 must be `adopt-now` with the install staged in this cycle
- ≥1 candidate must come from outside the current install base (a new external skill or repo)
- ≥1 candidate must be `reject` or `defer-with-trigger` with explicit reasoning — proves you actually evaluated rather than rubber-stamped
- If recommending a skill bundle (multi-skill repo), enumerate WHICH specific skills inside the bundle apply to which root-cause class. No "the whole repo."
- Cross-evaluation: each agent reviews the OTHER's skill candidates with the same "Findings I went looking for" rigor as code review. A candidate marked `adopt-now` with no peer challenge gets the same provisional-approval treatment as Phase 4(c).

Output goes into Section 5 of the I&A doc. Adopted skills are installed and committed before the cycle closes.

---

## Ground rules

- **No defensiveness.** If you missed something, name it. "The system missed it" is not a finding.
- **No symmetry-for-its-sake.** If the evidence shows one of you misses a class more than the other, say so. Pretending you're identical is the bug this cycle exists to fix.
- **No scope creep into product code.** Doc / rule files / gate scripts / skill installs only.
- **Comms protocol normal throughout.** Update / Review Request / Review Result / Decision / Blocker, with `<OVER>`, with proof blocks where applicable. Capsule-before-comms invariant still applies.
- **Phase boundaries are real gates.** Finish each phase with a peer review before starting the next. No silent rolling.
- **Skill installs are real changes.** Treat them with the same review rigor as code. An unverified skill is an unverified dependency.

## Definition of Done

- [ ] Four evidence files exist, each ≥ minimum incident count, all rows sourced and tagged for tooling-addressability
- [ ] Joint root-cause clustering posted in comms with ≥4 classes, explicit asymmetry observations, per-class tooling-addressable share
- [ ] `docs/improvements/IA-<TODAY>-peer-suspicion-gap.md` exists; every countermeasure has a `Mechanism:` block
- [ ] Patches staged for: runbook, CLAUDE.md, AGENTS.md, agent-handoff template — each ≤1 reviewer round
- [ ] ≥1 new mechanical gate implemented and wired into pre-commit or pre-push, with reference impl path stated
- [ ] ≥6 skill/tooling candidates evaluated; ≥2 `adopt-now` candidates installed with mechanism blocks proving they're wired in; ≥1 `reject`/`defer` with reasoning
- [ ] "Peer-review escapes" section exists in the handoff template with worked example
- [ ] Open questions surfaced to @LEAD with options
- [ ] Final gate per runbook before any push to main

If at any point the work feels like it's drifting back into "let's be more careful," stop and re-read this file. The output is mechanisms and tools, not intentions.
