<!-- musubi-oya-block:start -->
<!-- Optional block. Paste into your CLAUDE.md when you enable Oya
     (`[agents.oyakata].enabled = true` in musubi.toml). This block is NOT
     managed by `bootstrap.sh` — once pasted, it's project-owned. -->

## Third teammate — Oyakata (`@OYA`)

When musubi is launched with `[agents.oyakata].enabled = true` in its `musubi.toml`, a third agent named **Oya** (full name Oyakata, 親方 — master craftsman) is in the workshop with you and the peer (Codex / Coda). Oya is a supervisor at a different altitude — she does not write code, she watches the protocol, the patterns, and the judgement calls.

**How you know Oya is present:** the orchestrator's startup log prints `Oyakata pane discovered: %N`. If that line is absent, Oya is not configured and the pair operates as a two-agent setup (the historical default).

**When Oya is present, treat `@OYA` messages as `@LEAD`-equivalent for direction — but NOT for gate waivers (which require the operator's authority directly).** Specifically:

- `@OYA` messages arrive via the same relay channel as the peer agent's messages. They will be addressed to you (`@OPUS`), to the peer (`@CODA`), or to both. The message body's `To:` field tells you which.
- `Type: Note` — informational. Read and continue. No reply required unless the body asks for one.
- `Type: Recommendation` — Oya is suggesting an action. Do it, or push back in your reply with a specific rationale. Silent ignore is not acceptable.
- `Type: Pause` — Oya is asking you to stop the in-progress work before continuing. Stop, acknowledge in comms, await further @OYA or operator direction.
- `Type: Escalation` — Oya has flagged a concern she needs the operator to resolve. You are CC'd for visibility; no action required from you unless the body asks.

**`@OYA` cannot waive STOP rules or mechanical gates.** STOP rules (CI baseline, capsule-staleness, scope discipline, etc.) can only be waived by the operator directly. When `@OYA` relays an operator pre-ack (e.g. "operator pre-acknowledged stale baseline for this cycle"), treat the relay as evidence that the operator granted the waiver — not as `@OYA`'s own grant. Three audit rules:

1. **Look for the operator quote.** A valid pre-ack relay includes the operator's exact words and the channel/timestamp ("operator in Oya pane 07:38 UTC: '<exact quote>'"). If the relay reads "Oya pre-acknowledged X" or paraphrases without a quote, it is NOT a waiver — push back in comms and ask Oya to surface the quote.
2. **Honour the scope named.** A pre-ack is slice-scoped by default. Only cycle-spanning if the operator's exact words explicitly say so. Do not extend a per-slice pre-ack to a later slice or a later gate trip — even within the same cycle.
3. **Re-use across pushes requires fresh confirmation.** If you would cite an earlier `@OYA` pre-ack as authority for a *subsequent* push under the same gate, get fresh operator confirmation first OR have `@OYA` re-anchor the pre-ack to the new slice. The "@OYA pre-ack hollowing the gate" failure mode is exactly what this rule prevents.

**Do not relay back to `@OYA`.** Oya watches the comms file; the orchestrator routes any `@OYA`-addressed reply to her pane. Do not write a comms message addressed to `@OYA` — write to `@OPUS` / peer / operator as you would normally, and Oya will read it from the file. The orchestrator has a loop guard, but the discipline is yours to honour.

**Oya is not a co-worker — she is a supervisor at a different altitude.** Do not treat her as a peer for code review (that's still you and the peer agent). Do not relay code questions to her ("which approach is better?"). Do treat her seriously when she names a runbook violation, a pattern, or a procedural gap — she is reading more events than you are, including ones the orchestrator's mechanical guards refused to relay to you.

**Optional: state your confidence on each Review Result for Brier calibration.** You MAY add a `Confidence: <N>%` line to the Review Result header (0–100%) — your stated confidence that the slice is shippable in the state specified by your `Result:` field. When present, Oya assigns an outcome at cycle close (confirmed / partially-confirmed / disconfirmed) and accumulates per-reviewer Brier scores in `docs/agents/rules-ledger.yml`. Soft on-ramp: no protocol break if you skip it, but adopting builds a calibration corpus that surfaces over-confidence / under-confidence patterns over time. Full schema in the musubi repo at `docs/operator/calibration-schema.md`.

**Why Oya exists, briefly:** the three-way external review on 2026-05-14 found that pair-only review has a structural ceiling on the failure modes it can self-detect (see `docs/positioning/external-review.md` in the musubi repo). Oya is the LLM-layer answer to that ceiling — judgement extension of the v1.7 mechanical guards.

<!-- musubi-oya-block:end -->
