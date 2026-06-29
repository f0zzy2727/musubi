# Loops at the edge, peers at the centre

*What "loop engineering" gets right, and the one thing it can't structurally prevent.*

---

There's a piece going around called [*Loop Engineering*](https://www.linkedin.com/pulse/loop-engineering-ahmet-acar-fnqge/). It names a real shift, and it names it well. The argument: prompt engineering was the first craft, context engineering the second, and the third is writing the *loops* that prompt the model for you. Your job stops being "talk to the agent" and becomes "design the system that runs the agent." The human steps out of execution and becomes a gardener.

I read it twice. Most of it I agree with — enough that the overlap with what I've been building is almost uncomfortable. But there's one place where we point in opposite directions, and that place is the whole reason Musubi exists. This is an attempt to be fair about the overlap and honest about the split.

---

## The overlap is real

Strip both down to primitives and you find nearly the same parts bin:

- **Skills** — externalised conventions in a file the agent reads, so you stop re-explaining your standards.
- **Worktrees** — isolated git checkouts so parallel agents don't collide.
- **Connectors** — MCP tools so the agent can actually *do* things, not just talk.
- **Memory** — a state file the work persists into between runs.
- **A heartbeat** — something that wakes the system on a schedule. Musubi has a `/loop` too.
- **A checker** — a separate agent that verifies work against a spec.

If you only looked at the components, you'd call them the same system. The author's "five-beat control cycle" — discover, assign, verify, persist, decide — would not look out of place described as a Musubi cycle.

So the disagreement isn't about plumbing. It's about two things the plumbing doesn't settle: **what makes the output trustworthy**, and **where the human sits**.

---

## Loop engineering's risk list is Musubi's risk list

The most striking thing in the piece is its catalogue of debts. It warns about:

- **Verification debt** — loops make mistakes unattended; a checker only raises your confidence, it doesn't guarantee correctness.
- **Comprehension debt** — the system grows past what any human still understands.
- **Intent debt** — agents fill the gaps in an ambiguous instruction with their own unstated assumptions.
- **Cognitive surrender** — you start accepting outputs you no longer evaluate, and your own judgment quietly atrophies.

I could have written that list. I more or less did, under different names, over eight weeks of watching two agents work. *Cognitive surrender* is what I ended up calling **asymmetric deference** — one agent rubber-stamping another's work, the failure being invisible from inside the system. *Intent debt* is exactly what the third agent in Musubi exists to guard against; I call it being the guardian of intention. *Verification debt* is why I never trusted a single gate to mean "done."

So we agree on the diseases. The interesting part is the cure.

---

## Two cures

Loop engineering's cure for a wrong-but-confident output is **a checker agent**. A maker does the work; a checker reads it against the spec and raises or lowers your confidence. It's a pipeline: plan, build, verify, with the human standing at the edge reviewing what comes out.

It's a good pattern. It's also the pattern that produces the very debt the same essay warns about. A checker that shares the maker's blind spots will pass the maker's mistakes — confidently. "Verification only raises confidence" is true precisely *because* a single checker can't escape the maker's frame. The author knows this; it's why verification debt is on the list. But the architecture has no answer to it beyond "review the outputs more carefully," which is the exact discipline that cognitive surrender erodes.

Musubi's cure is different in kind, not degree. It doesn't bolt a checker onto a maker. It puts **two peers who must disagree** at the centre, and treats their disagreement as the mechanism rather than a nuisance to be resolved. The peers are deliberately *unlike* — different training lineages — because two models with the same blind spots will agree for the same wrong reasons, and agreement is the thing I learned to distrust. In Musubi, consensus is the alarm, not the goal. When the pair drifts toward frictionless agreement, that drift is *measured* — it has a name and a number — because a pair that stops disagreeing has stopped working.

The human doesn't stand at the edge. They stay at the centre, as the one who holds intent and signs off. Not because automation can't run without them, but because the most expensive failure in this kind of work is a confident wrong answer nobody challenged — and removing the human is how you manufacture exactly that.

---

## Edge versus centre

That's the cleanest way I can put the split.

**Loop engineering optimises for getting the human out of the loop.** Success is the gardener who tends the system and rarely touches the work. Verification is a stage in a pipeline. The win is throughput and reach: well-specified, repeatable work, run cheaply at scale, with cost discipline as a first-class concern (cheap triage, expensive checkers only when there's something to check). For that kind of work, it's the right design, and I'd use it.

**Musubi optimises for catching the error the autonomy creates.** Success is the wrong answer that got challenged before it shipped, and the judgment that transferred from human to system without being abandoned. Disagreement isn't a stage; it's the architecture. The win is in the work where the spec is ambiguous, the stakes are real, and the failure you actually fear is the plausible-looking output that no single reviewer — human or agent — would have caught alone.

This is also why Musubi is **not for small projects**. A third agent is overhead; structured disagreement is friction; staying in the loop is work. If the task is well-specified and cheap to verify, that ceremony is a tax, and a loop is the better tool. Musubi earns its weight only when being confidently wrong is more expensive than being slow.

---

## Where this leaves both

I don't think these compete so much as they sit at two ends of one spectrum. At one end: specified work, run at scale, human at the edge, autonomy maximised — loops. At the other: ambiguous work, high cost of error, human at the centre, disagreement as the safeguard — pairs.

The honest thing to notice is that loop engineering's own risk list is an argument *for* the other end of the spectrum. Verification debt, intent debt, cognitive surrender — these aren't bugs you patch inside an autonomy loop. They're the predictable cost of removing the human, and they get worse the better the loop gets. The author is right to name them. I just think the answer to "how do I stop trusting a confident wrong output" isn't a more careful gardener. It's a second pair of eyes that was built to disagree.

Loops at the edge. Peers at the centre. Pick by how much it costs to be wrong.
