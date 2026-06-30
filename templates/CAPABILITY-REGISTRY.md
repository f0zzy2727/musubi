# Capability Registry

<!-- Oya and the pair read this file on startup. It is the shared, written answer to
     "what can we actually reach, and how?" — so an agent stops *arguing* that a task
     is impossible when really it just doesn't know the path.

     This file is project-owned. The rows below are a starting reference of the
     common landscape; correct them to YOUR setup, delete what you don't use, and
     append every new connector the moment you discover one. A capability that lives
     only in the operator's head will be re-litigated every cycle. Write it down once.

     Fill in the angle-bracket prompts and delete this comment when you're done. -->

**Last updated:** <ISO-8601 date>

---

## The one rule

**Unknown ≠ impossible.** Before any agent tells the operator "I cannot do X"
(enable an API, change a RevenueCat setting, create a store product, drive a
browser), it MUST check this registry first. The honest failure modes are:

1. **It's here →** use the listed path.
2. **A sibling agent is better at it →** route the task there (say which, and why).
3. **It's genuinely not here →** say *"I don't have a known path for this; the
   options are (a) operator does it, (b) I try <method>"* — and then **append the
   answer to this file** once it's found.

A flat "I can't, you'll have to do it manually" with no check against this file is
a defect. It burns the operator's time re-explaining the same connector.

## Agent capability matrix

Which agent to hand a task to, and how each one reaches a browser. Edit to match
the agents you actually run.

| Agent | Browser path | Strong at | Route here for |
|-------|--------------|-----------|----------------|
| Opus (this orchestrator, terminal) | `claude-in-chrome` / gstack `connect-chrome` | reasoning, code, file ops, gates, planning | architecture, code, review, the cycle itself |
| Codex (CLI / Desktop) | its own Chrome driver; Desktop ↔ Chrome connector | deterministic multi-step flows; simulator runs; screenshot walkthroughs | "open the simulator, walk every screen, screenshot, build a walkthrough site" |
| anti-gravity (Google) | native Chrome (Google-owned) | smoothest in-browser navigation, store consoles | manual/half-manual store + browser flows where an API is missing |
| operator (human) | the real Chrome, with real logins | anything needing real credentials, payment, 2FA | login-gated and money-moving actions |

<!-- If you only run one or two of these, delete the rest. The point is that
     "Codex is better at the simulator walkthrough than I am" is a ROUTING fact,
     not a refusal. -->

## External service connectors

How to actually reach each service. Prefer an API/CLI/MCP over a browser login
every time — browser logins are the slow, fragile, re-auth-every-time path.

| Service | Reach via (preferred → fallback) | Notes |
|---------|----------------------------------|-------|
| RevenueCat | **official RevenueCat MCP / AI Toolkit** (Codex + Claude) → CLI → browser | Use the MCP. Do NOT default to "log in to the dashboard for me." Verify + wire the MCP once; record the server name here. |
| Google Cloud APIs | `gcloud` CLI → console | Enable APIs with `gcloud services enable <api>` — don't make the operator click the console. Record which project. |
| Google Play | Play Developer API → browser (anti-gravity / operator) | A paid app needs a **product/SKU created in Play Console** — this is the thing audits silently miss. See SHIP-DOD.md. |
| Apple App Store | App Store Connect API / Transporter → browser (operator) | A paid app needs an **in-app product created in App Store Connect**. See SHIP-DOD.md. |
| <your service> | <mcp / cli / api / browser> | <gotchas, account, project id> |

## Chrome profile gotcha (read before "log in for me")

When an LLM/automation opens Chrome it usually launches a **fresh, isolated
profile** (its own `user-data-dir`): no extensions, no saved passwords, no
existing sessions — by design, so automation can't touch your real cookies. That
is why you land on an empty browser asking you to re-authenticate everything.

To drive YOUR real session (extensions + logins present), connect to your
existing profile instead of spawning a blank one:

- Claude: the `claude-in-chrome` tools attach to your live Chrome tabs (real session).
- gstack: `connect-chrome` launches/attaches a real Chrome window you can watch.

If an agent finds itself on a blank re-auth screen, that's the wrong path —
switch to the real-profile connector above rather than asking the operator to log
in to a throwaway window.

## How to keep this file alive

- Discover a connector mid-cycle → add the row before moving on.
- Find a sibling does a task better → record the routing fact, don't just do it worse.
- A row goes stale (API replaced a browser flow) → update it; this file is the
  source of truth the next session trusts.
