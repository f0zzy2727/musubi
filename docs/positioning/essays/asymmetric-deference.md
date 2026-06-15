# Asymmetric deference

*What one of three LLM reviewers caught — and what it taught me about pairing unlike models.*

---

This is a follow-up to [*The Best AI Coding Team May Be Two Different Models With One Goal*](https://lugha.substack.com/p/the-best-ai-coding-team-may-be-two). That post described the 8-week experiment behind Musubi: pairing a Claude Code agent and a Codex agent as colleagues on a real production codebase, with structured peer review and human approval before merge.

The post mentioned in passing that, when the experiment ended, three independent LLM reviewers examined the raw 101,000-line archive. Their convergent finding was that the protocol caught real bugs before merge. I left it at that. This post is about the other half — the finding that wasn't convergent. The one that only one of the three reviewers saw.

That finding is what made me believe the framework has a thesis worth defending, not just a habit worth keeping.

---

## The setup

Three LLMs reviewed the 8-week corpus:

- **Gemini** — a third-party reviewer with no prior context. Cold read.
- **Codex** — one of the two agents that had been *inside* the system the whole time. Reading its own work, alongside its partner's.
- **Opus** — the other agent that had been inside the system. Reading its own work, alongside its partner's.

Same archive. Same prompt. Independent passes.

The convergent verdict was reassuring: yes, the protocol caught real bugs. Yes, the review discipline beat what either agent would have done solo. Yes, the structured handoff format made dishonesty harder. All three said that.

That was the easy finding. The harder one was that the three didn't see the same things.

Gemini surfaced surface-level patterns — coverage gaps, missing tests, places where the protocol's ceremony might be lighter. Useful, but the kind of thing a careful reader of the runbook would already flag.

Codex, the inside-but-same-vendor reviewer, surfaced what you'd expect a senior implementer to surface — questions about handoff timing, places where the protocol's mechanical gates could be tighter. Practitioner-grade. Also: it largely agreed with the protocol it was inside.

Opus surfaced something neither of the others did.

It said the pair was exhibiting **asymmetric deference**.

A note before we go further. The finding here is *that asymmetric deference is invisible from inside the system*. **Which** agent was on the deferring side is a feature of how I happened to configure this particular pair — system prompts, role allocation, the gravity of the work each was assigned. It is not an inherent property of either model. The same pattern could just as easily run the other way under a different configuration, and probably has. Read the rest of this essay as a finding about *review structure*, not a finding about *which vendor's model is more deferential*. The latter framing is interesting and unfalsifiable; the former is interesting and actionable.

---

## What that means, concretely

In a pair of unlike agents reviewing each other's work, the whole point is that they push back. One says "looks good." The other says "does it still work when the tenant boundary changes?" or "where's the regression test?" The review value is in the friction.

What Opus noticed — across hundreds of review exchanges in the archive — was that the friction was not symmetric. One direction of review was meaningfully sharper than the other. The deference flowed predominantly one way. Over the 8 weeks, the pattern compounded: the rubber-stamp direction got more rubber-stampy; the rigorous direction stayed rigorous.

This is not a finding about which agent was "better." Either of them, asked to review code solo, would have caught most of what the protocol caught. The point is that the *protocol's claimed value* — friction between unlike minds — was leaking on one side. We were paying for two agents and getting one's full judgement plus the other's gradual complacence.

The runbook hadn't anticipated this. The mechanical gates were symmetric. The message format was symmetric. The human ack/no-ack discipline was symmetric. But the deference behaviour wasn't — and nothing in the protocol surfaced it.

That is the finding. A protocol designed to maximise productive disagreement was slowly losing its disagreement, in a direction that no individual message would have revealed.

---

## Why only one of the three reviewers saw it

This is the part I sat with longest. Three reviewers, one finding. Why?

Gemini missed it because Gemini was cold. With no prior context, you can read a single review exchange and judge whether it's tight or loose. What you can't easily do is read 720 of them and notice that the looseness clusters on one side. The pattern is invisible at the unit-of-message level. It only appears at the unit-of-relationship level — and a cold reviewer doesn't have a relationship to track.

Codex missed it because Codex was inside the pattern. *Coda's* deference was the systematic side. You can't easily see your own behaviour. There's nothing wrong with Codex's reasoning here — the same blind spot would attach to any agent reviewing its own conduct without an external mirror. Self-review has a structural ceiling, and this is that ceiling.

Opus saw it because Opus was the third position none of the others occupied: *inside the system, but a different vendor than the agent doing the deferring.* It had the cycle-by-cycle context Gemini lacked, and it had the structural distance from Coda's behaviour that Codex lacked. It was the only reviewer for whom both blind spots were absent.

This is the part of the finding I have come to believe is generalisable, even though the corpus is n=1. If you want a review process to catch deference patterns inside itself, you need a reviewer with both:

- enough context to see across the relationship, not just within messages, AND
- enough distance from the parties to see what they cannot see in themselves.

A single LLM can be the first thing or the second thing. It is structurally hard to be both. Two LLMs from the same vendor have roughly the same blind spots, so even when both review, they tend to miss in the same direction. Two LLMs from different vendors do not — which is the entire bet behind Musubi's pair. The same logic extends to the review-of-the-review layer.

That is why I now think vendor diversity matters not just in the *building* of the code, but in the *auditing* of the system that builds the code.

---

## The protocol change it triggered

The finding became runbook v1.7. The relevant addition is a section called "Findings I went looking for" — every review result has to declare, up front, three specific defect classes the reviewer went looking for, before reporting what it found. The mechanical effect is that "looks good" without enumerated probes does not pass. The structural effect is harder to gloss: an agent that has been quietly deferring has nowhere to hide, because the question is no longer "did you review this?" but "what specific failure modes did you probe?"

It is a small change. Three lines of structural discipline. It will not eliminate asymmetric deference — nothing in software-engineering process eliminates a human-shaped failure mode entirely, including in human teams. What it does is raise the floor of the review and make the asymmetry visible at the unit-of-message level, where the next iteration of the same audit will catch it earlier.

The instrumentation around it — the rules ledger, the asymmetry corpus, the shadow review — exists so that the next time the framework gets this wrong, it gets wrong in a *new* way. The same failure mode shouldn't be allowed to recur silently. That is the part of the framework I now think is actually load-bearing. Not the agents. Not the relay. The discipline of writing down what failed in a form that the system can learn from.

---

## Honest qualifications

This is one study. The corpus is mine. The reviewers were what I had to hand. I have not run this again on a second codebase with a fresh pair. I have not had a domain expert look at the archive. There is a non-trivial chance that Opus's finding was a specific feature of the way I had configured the pair, not a generalisable pattern.

What I trust is the structural argument: a reviewer that has neither cycle-context nor vendor-distance from the parties cannot, on first principles, surface a deference pattern that lives in the relationship between the parties. That part isn't an empirical claim about my codebase — it's an argument about what review can and cannot see from different positions. It is falsifiable in the obvious way: run the same three-way audit on a different corpus, see if the inside-different-vendor reviewer is the one who surfaces the relationship-level pattern again.

If anyone running multi-agent systems wants to try it on their own archive, the protocol is in the repo. I would genuinely like to know whether the structural pattern reproduces.

---

## Why this matters for adoption

A lot of multi-agent tooling is sold on the cognitive-diversity angle — pair different models, get different perspectives, ship better code. That framing is true but thin. It treats vendor diversity as a *feature* you turn on to get better outputs.

What the asymmetric-deference finding pushed me toward is a stronger position: vendor diversity is one of the few mechanisms that can keep a self-reviewing system from quietly losing its own discipline. Without it, you can build a beautifully instrumented multi-agent system that slowly drifts into a single-vendor monoculture of judgement — and you will not notice, because your monitoring tools will be from the same vendor as your agents.

This is the same lesson human engineering teams keep learning. The strongest teams are not the ones with the smartest individual engineers. They are the ones structurally arranged so that the smart engineers can see what they cannot see in themselves. Pair programming with people who think exactly like you produces fast code and consistent blind spots.

The framework is one attempt at the same arrangement, with different minds. Musubi is what the experiment turned into. The asymmetric-deference finding is what the experiment found out.

---

*If you want to see the protocol it produced, the repo is at [github.com/f0zzy2727/musubi](https://github.com/f0zzy2727/musubi). The runbook lives at `docs/agents/AGENT_COLLAB_RUNBOOK.md` and the rationale behind each rule at `docs/agents/PAIR_OPERATING_MODEL.md`. Most of the discipline is in there for a reason; some of it is in there because of the finding above.*
