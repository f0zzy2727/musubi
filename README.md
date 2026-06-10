# musubi — paired-LLM software engineering

> **Musubi: vibe coding, with receipts.**

Most multi-agent tools treat agents as interchangeable workers — same task pool, sequential stages, or cost-routed. Musubi does the opposite. It pairs two different LLMs from two different vendors — one Claude, one Codex — and runs them as colleagues: one optimist, one sceptic, different training, different blind spots. The disagreements between them surface bugs that two instances of the same model would both miss, because the blind spots don't overlap.

**Who it's for:** a single operator directing a paired build who wants the speed of vibe coding without giving up review discipline — and who wants a record of where the second vendor actually earned its keep.

The orchestration tools manage capacity. Musubi manages quality.

**Short visual primer (PDF):** [the musubi operating model](docs/positioning/musubi-operating-model.pdf) — the two configurations, Oya as guardian of intention, and where musubi sits in the landscape.
**Full written rationale:** `docs/agents/PAIR_OPERATING_MODEL.md`.
**The story behind it:** [*The Best AI Coding Team May Be Two Different Models With One Goal*](https://lugha.substack.com/p/the-best-ai-coding-team-may-be-two) — an 8-week experiment that became Musubi.
**The specific finding that holds it up:** [*Asymmetric deference*](docs/positioning/asymmetric-deference.md) — what a three-way LLM review surfaced, and why two unlike models matter more than one strong one.

> *About the name.* *Musubi* (結び) is the Shinto idea of binding distinct things into a whole — two minds, one comms thread, one protocol. Pronounced *moo-soo-bee*. (Yes, also the Hawaiian rice-and-spam dish, which borrows the same word for the same reason.)

---

## How it works

Claude Code (Opus) and Codex (Coda) run in adjacent terminal panes. A relay watches a shared append-only comms file. When either agent finishes a message with `<OVER>`, the relay forwards it to the other pane — exactly as if a human had typed it. The human stays in the loop: monitoring, intervening, approving merges.

```
┌─────────────────────┬─────────────────────┐
│       Opus          │       Coda          │
│   (Claude Code)     │     (Codex)         │
│                     │                     │
│  Working on Slice 1 │  Working on Slice 2 │
└─────────────────────┴─────────────────────┘
           ↕ orchestrator relays ↕
      docs/agents/comms/active.txt
```

The protocol the agents follow — message format, state vocabulary, slice lifecycle, review pattern, mechanical gates — has been refined through extended daily use on a real production codebase. It is opinionated. The rules encode specific lessons from real incidents.

That's the pair — musubi's default and most battle-tested shape. It can also run a third agent *above* the pair, described next.

---

## The third agent — Oya (optional)

Musubi runs in two shapes, and the difference is **who plays the senior engineer**.

**The pair (Opus + Coda).** Two builders who write code and review each other. Here, *you* are the senior engineer in the room — you hold the vision, you catch the discipline they skip, you judge which vendor is right when they disagree. Maximum control; the engineering conscience is yours to carry.

**The pair + Oya.** Add a third agent — **Oyakata** (*Oya*, 親方, "master craftsman") — and you *get* that senior engineer as the third seat. She sits above the bench the way a master watches two apprentices: she writes no code, but she holds the whole picture and speaks only when speaking matters.

**Her first duty is custody of the vision.** Oya holds two pictures at once — one of the **end state** (the vision, architecture, and strategy you set out to build) and one of the **two agents** at the bench right now. She reads your vision and architecture docs on startup and keeps them in view through every cycle. The pair, heads-down in the diff, will cheerfully build a flawless version of the *wrong* thing; Oya is the one still holding what "right" was meant to be — and she steers them back before the wrong thing ships, not after. Guardian of intention as much as referee of craft.

```
┌─────────────────────────────────────────┐
│   OYA · 親方 — master craftsman          │
│   holds the vision · watches both        │
├─────────────────────┬───────────────────┤
│       Opus          │       Coda        │
│   (Claude Code)     │     (Codex)       │
│  Working on Slice 1 │  Reviewing Slice 1│
└─────────────────────┴───────────────────┘
           ↕ orchestrator relays ↕
      docs/agents/comms/active.txt
```

What the master craftsman watches for:

- **Is this still serving the goal?** Past "does the code work," she asks the question the pair rarely stop to ask mid-task: *does this slice move us toward the end state, or has the work quietly drifted?* The strategic check, every cycle.
- **Are they cutting corners?** She nudges when the pair skips the discipline a senior would insist on — a threat model on an auth change, a rollback plan on a migration, the error states on a new screen.
- **Who was right, and why?** Opus and Coda come from different makers and catch each other's blind spots; Oya watches *which* of them was right and *why* — the whole reason you're paying for two.
- **What just happened?** At the end of each work session she writes a short plain-English recap: what shipped, where they disagreed and how it resolved, what was learned — so you get a clean read instead of scrolling the transcript.
- **Are you drifting too?** If you wave something through or overrule the pair, she notes it — a sanity-check on the human, not just the robots.

She *watches and speaks*; she doesn't take the wheel. The pair still self-coordinate, and you're still the gate. That's deliberate: a third agent that *directs* the other two is just the supervisor pattern every other framework already ships. Oya is the overview, not the conductor.

**Honest caveat.** The pair is the battle-tested core; Oya is the newer layer. Most routine cycles don't need her — the pair plus the mechanical guards is enough. Turn her on when the work is complex enough that a *missing* senior engineer would cost you: long cycles, security- or money-touching code, or a non-technical operator who can't supply that engineering judgement themselves. She earns her place by what she catches — and the framework tracks exactly that (see [the rules ledger](#rules-ledger--the-protocol-auditing-itself)). Setup is one config block: [Optional: Oyakata third-agent layer](#optional-oyakata-third-agent-layer).

---

## What it costs

The honest frame: the second agent is nearly free if you already pay a flat subscription.

Musubi runs two CLIs — Claude Code and Codex — each on its own vendor's plan. If you're already on a Pro/Max-style flat subscription for both (not metered API), the marginal cost of running them as a pair instead of one alone is roughly zero. You're paying for the seats either way.

The receipt: Codebase A, a real production platform, was built this way — ~289K lines of TypeScript/TSX/SQL, 3,984 passing tests, 313 API routes, one person directing the Claude + Codex pair over ~15 weeks. Actual AI-tooling spend for the whole build was EUR 1,500–3,500 on flat-rate subscriptions; that figure is verifiable. All-in, costing the operator's own time at a market rate, the mid-range build came to ~EUR 41,000, against a rough traditional-team estimate of EUR 1.1–1.4M for the same scope. Treat the resulting ~35x as an order-of-magnitude signal from a single project, not a benchmark — the comparison estimate is the operator's own and the codebase is private. This is an experiment; the honest claim is narrow — it worked, at this scale, for this operator.

Two caveats, both real:

1. That EUR 1,500–3,500 is the build cost *under flat-rate subscriptions*. On metered API the second agent genuinely runs ~2–3x the token spend in real money. If you're billed per token, the pair is not free — price it accordingly.
2. This is build cost only. Running the inference of the *product* you ship is a separate meter entirely — don't conflate the two.

Want your own numbers, not ours? `scripts/cost-report.py` reads Claude Code's local session logs and prints the actual token counts for your run (Claude side only — Codex doesn't log per-turn usage). It deliberately prints no dollar figure, because the honest cost depends entirely on whether you're on a flat subscription or metered API.

Who it's for: the pair pays off when the cost of a shipped defect beats the cost of the tokens. That means production code, not prototypes.

---

## What's in the box

```
musubi/
├── orchestrator.py                 # Main orchestrator — tmux + comms relay
├── launch_musubi.sh                # One-shot launcher (macOS + iTerm2)
├── launch_musubi_tmux.sh           # Cross-platform launcher (Linux / WSL / macOS without iTerm2)
├── bootstrap.sh                    # Installer — places musubi files into your project
├── musubi.toml                     # Configuration (gitignored)
├── musubi.toml.example             # Shareable config template
├── requirements.txt                # Python dependencies
│
├── docs/
│   ├── agents/                     # Protocol docs — auto-imported by both agents on every fresh session
│   │   ├── AGENT_COLLAB_RUNBOOK.md     # Protocol authority — core, per-cycle rules (auto-loaded)
│   │   ├── AGENT_COLLAB_RUNBOOK_REFERENCE.md  # On-demand detail (NOT auto-loaded)
│   │   └── PAIR_OPERATING_MODEL.md     # Rationale + adoption guide (the "why")
│   ├── operator/                   # Operator-facing docs — not auto-imported
│   │   └── DEV_STRATEGY.md             # Optional daily/weekly cadence
│   └── positioning/                # Comparison + operating-model PDFs
│
├── scripts/
│   ├── classify-slice.sh           # Mechanical slice-lane classifier (tiny/lightweight/heavy)
│   ├── guard-staged-scope.sh       # Pre-commit guard — slice-scope discipline
│   ├── ci-baseline.sh              # Pre-push CI baseline check
│   ├── ledger-from-comms.py        # Mechanical rules-ledger fire counter (cycle close)
│   ├── cost-report.py              # Honest Claude-side token accounting from local logs
│   ├── doctor.sh                   # Preflight: checks tmux, CLIs, clipboard, paths
│   └── attach-oya.sh               # Adds the optional third (Oya supervisor) pane; invoked by the orchestrator
│
├── tests/                          # 400+ tests — parsing, relay, lane classifier,
│                                   # ledger, bootstrap, real-tmux integration, …
│
└── templates/
    ├── CLAUDE.md.template          # Used when target has no CLAUDE.md
    ├── AGENTS.md.template          # Used when target has no AGENTS.md
    ├── musubi-block-claude.md      # Block injected into existing CLAUDE.md
    ├── musubi-block-agents.md      # Block injected into existing AGENTS.md
    ├── agent-todo.md               # Task board template
    ├── agent-handoff.md            # Handoff log template
    ├── current-state.md            # Live capsule template
    └── claude-commands/
        └── open-sesame.md          # /open-sesame slash command (warm-start)
```

---

## Prerequisites

| Requirement | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| tmux | 2.4+ | macOS `brew install tmux` · Debian/Ubuntu/WSL `sudo apt-get install tmux` |
| iTerm2 (macOS launcher only) | Any recent | [iterm2.com](https://iterm2.com) |
| Claude Code | Latest | `npm install -g @anthropic-ai/claude-code` |
| Codex | Latest | `npm install -g @openai/codex` |
| A clipboard tool (only if enabling Oya) | any | `pbcopy` (macOS, bundled) · `xclip`/`wl-copy` (Linux) · `clip.exe` (WSL) — soft-fails if absent |
| GitHub CLI (optional, for `ci-baseline.sh`) | Latest | `brew install gh` |

Both Claude Code and Codex must be authenticated and working in your terminal before running musubi. Test them independently first.

---

## Setup

### 1. Clone musubi

```bash
git clone https://github.com/f0zzy2727/musubi.git ~/Dev/musubi
cd ~/Dev/musubi
cp musubi.toml.example musubi.toml
```

### 2. Bootstrap your project

The bootstrap installs all the docs, templates, scripts, and slash command into the target project, and wires the agent project-rules files (`CLAUDE.md` / `AGENTS.md`) so both agents auto-load the protocol on every fresh session.

```bash
./bootstrap.sh /path/to/your/project
```

What it places (and what gets refreshed vs. created):

| Path in target project | Lifecycle |
|---|---|
| `docs/agents/AGENT_COLLAB_RUNBOOK.md` | **musubi-managed** — refreshed every bootstrap (core, auto-loaded) |
| `docs/agents/AGENT_COLLAB_RUNBOOK_REFERENCE.md` | **musubi-managed** — on-demand detail, not auto-loaded |
| `docs/agents/PAIR_OPERATING_MODEL.md` | **musubi-managed** — refreshed every bootstrap |
| `docs/operator/DEV_STRATEGY.md` | **musubi-managed** — refreshed every bootstrap; operator-facing, not auto-imported |
| `docs/agents/current-state.md` | created if absent, then **project-owned** |
| `docs/agents/agent-todo.md` | created if absent, then **project-owned** |
| `docs/agents/agent-handoff.md` | created if absent, then **project-owned** |
| `docs/agents/comms/` | gitignored directory for the active comms transcript |
| `docs/agents/archive/` | committed directory for closed-cycle comms logs |
| `scripts/classify-slice.sh` | created if absent, executable (the runbook's lane classifier) |
| `scripts/guard-staged-scope.sh` | created if absent, executable |
| `scripts/ci-baseline.sh` | created if absent, executable |
| `.claude/commands/open-sesame.md` | created if absent (warm-start slash command) |
| `CLAUDE.md` | block injected (idempotent) — see merge strategy below |
| `AGENTS.md` | block injected (idempotent) |
| `.gitignore` | `docs/agents/comms/` added if missing |

The bootstrap is idempotent — re-run it after every musubi update to pull the latest runbook / operating model / dev strategy.

```bash
./bootstrap.sh --dry-run /path/to/project   # preview without writing
./bootstrap.sh --check   /path/to/project   # verify the install is current; non-zero exit on drift (CI-friendly)
./bootstrap.sh --force   /path/to/project   # overwrite forks of managed docs
```

### 3. CLAUDE.md / AGENTS.md merge strategy

This is the part that matters if your project already has these files.

The bootstrap injects a clearly-marked block:

```markdown
<!-- musubi:start -->
... managed content ...
<!-- musubi:end -->
```

Three cases:

| Target file state | What bootstrap does |
|---|---|
| Doesn't exist | Creates from `templates/CLAUDE.md.template` (or `AGENTS.md.template`). Block is at the bottom; your project rules can be added above it. |
| Exists, has the markers | Replaces only the content between `<!-- musubi:start -->` and `<!-- musubi:end -->`. Everything else in your file is preserved verbatim. |
| Exists, no markers | Appends the block at the end with a separator. Your existing content stays exactly as it was. |

You will never lose existing content. The block is small (~30 lines) and uses Claude Code's `@docs/agents/AGENT_COLLAB_RUNBOOK.md` import syntax so the actual content lives in `docs/agents/` and the block stays stable across musubi updates.

To opt a file out of management entirely, delete the markers — bootstrap will warn and skip on the next run.

### 4. Configure musubi

Edit `musubi.toml`:

```toml
[project]
path = "/path/to/your/project"     # absolute path

[agents]
[agents.opus]
name = "Opus"                      # rename freely
handle = "@OPUS"
cli = "claude"

[agents.coda]
name = "Coda"
handle = "@CODA"
cli = "codex"

[comms]
file = "docs/agents/comms/active.txt"
over_signal = "<OVER>"
runbook = "docs/agents/AGENT_COLLAB_RUNBOOK.md"
operating_model = "docs/agents/PAIR_OPERATING_MODEL.md"

[tmux]
session_name = "musubi"
```

The only required change is `project.path`. Everything else has working defaults.

---

## Running

**Preflight (optional but recommended for a first run):**

```bash
scripts/doctor.sh
```

Launches nothing — it just checks tmux, both agent CLIs, a clipboard tool, Python, and that your `project.path` is enterable, and tells you what to fix. Non-zero exit if anything's broken.

There are two launchers — pick the one for your platform; both are first-class and run the same orchestrator:

**Linux / WSL / macOS (any terminal) — `launch_musubi_tmux.sh`:**

```bash
./launch_musubi_tmux.sh
```

The portable path, no terminal-emulator assumptions. It checks Python + tmux, creates a venv if needed, installs deps, creates the tmux session, and runs the orchestrator in your current terminal. When it prints `[BOOT] attach in another terminal with: tmux attach -t musubi`, open a second terminal (or a tmux split) and run that command to watch the panes. `Ctrl+C` in the orchestrator terminal stops the watcher. On a fresh Linux box you'll want `sudo apt-get install -y tmux` and a clipboard tool (`xclip` or `wl-clipboard`) if you're enabling Oya.

**macOS + iTerm2 — `launch_musubi.sh`:**

```bash
./launch_musubi.sh
```

The macOS convenience path: same flow, but it also opens **one** iTerm window that auto-`tmux attach`es to the session, so you don't open the second terminal yourself. The orchestrator still runs in the terminal you launched from. Use the tmux launcher above instead if you're not on iTerm2.

### First run: what to expect

The orchestrator emits a `[HH:MM:SS] [COMPONENT]` log stream — one line per boot phase. A successful first run takes ~30–90 seconds and looks roughly like this:

```
[10:00:00] [BOOT] session 'musubi' created
[10:00:00] [BOOT] attach in another terminal with: tmux attach -t musubi
[10:00:00] [BOOT] waiting for a tmux client to attach to this session — waiting up to 60s (Enter to skip)
[10:00:04] [BOOT] condition met after 4s — advancing
[10:00:04] [BOOT] starting Opus CLI in left pane
[10:00:06] [BOOT] starting Coda CLI in right pane
[10:00:06] [BOOT] waiting for both CLIs to finish booting — waiting up to 90s (Enter to skip)
[10:00:23] [BOOT] condition met after 17s — advancing
[10:00:23] [RELAY] running relay test (pinging pair)
[10:00:35] [RELAY] condition met after 12s — advancing
[10:00:35] [BRIEF] sending warm-start briefings to pair
[10:00:38] [BRIEF] waiting for both agents to print 'Startup complete. Ready.' — waiting up to 180s (Enter to skip)
[10:01:42] [BRIEF] condition met after 64s — advancing
[10:01:42] [WATCHER] all gates cleared — starting relay watcher
```

You'll know it worked when you see `[WATCHER] all gates cleared — starting relay watcher`. The watcher then idles until the agents post comms messages.

In your iTerm window (the one running `tmux attach`), the panes look like this when both agents are loaded:

```
┌────────────────────┬────────────────────┐
│  OPUS · Anthropic  │  CODA · OpenAI     │
│  (Claude Code)     │  (Codex CLI)       │
│                    │                    │
│  > Startup         │  > Startup         │
│    complete.       │    complete.       │
│    Ready.          │    Ready.          │
│  ❯                 │  ›                 │
└────────────────────┴────────────────────┘
```

With Oya enabled (`[agents.oyakata].enabled = true`), a third pane stacks on top:

```
┌──────────────────────────────────────────┐
│  OYAKATA · 親方 · master craftsman       │
│  (Claude Code, supervisor)               │
│  > Startup complete. Ready.              │
│  > [HH:MM:SS] [OYA] verdict: READY       │
├────────────────────┬─────────────────────┤
│  OPUS · Anthropic  │  CODA · OpenAI      │
│  > Ready.          │  > Ready.           │
│  ❯                 │  ›                  │
└────────────────────┴─────────────────────┘
```

**Gates auto-advance** — the orchestrator polls for each condition (tmux client attached, CLIs booted, relay test responded to, agents briefed) and moves forward when it's met, with a timeout fallback per gate. You can press **Enter at any prompt** to skip the wait immediately. You will *not* be asked to press Enter to start each phase — the old multi-Enter ritual is gone.

The brief walks each agent through the warm-start checklist:

1. Read the runbook (`docs/agents/AGENT_COLLAB_RUNBOOK.md`)
2. Read the operating model (`docs/agents/PAIR_OPERATING_MODEL.md`)
3. Read the dev strategy (optional)
4. Run the runbook's *Startup and Recovery* checklist to load capsule, todo, handoff, comms, `git status`
5. (Optional) `/open-sesame` slash command as a shortcut for steps 1–4
6. Confirm with `"Startup complete. Ready."`

This works whether or not `/open-sesame` is defined — the brief is self-contained.

### Launcher arguments

Both launchers accept two positional arguments, both optional:

```bash
./launch_musubi.sh [config-toml] [session-name]
```

- `config-toml` — path to a musubi.toml. Defaults to `musubi.toml` in the current directory.
- `session-name` — tmux session name. Defaults to `musubi`.

Useful invocations:

```bash
./launch_musubi.sh                              # musubi.toml + session 'musubi'
./launch_musubi.sh my_other_project.toml        # custom config, default session
./launch_musubi.sh musubi.toml project_alpha    # default config, custom session (for running multiple at once — see Using multiple sessions)
```

---

## How auto-loading works

Each agent's harness auto-loads its project-rules file on session start:

- **Claude Code** auto-loads `CLAUDE.md` and recursively follows `@path/to/file` imports. The musubi block uses `@docs/agents/AGENT_COLLAB_RUNBOOK.md`, etc., so the runbook + operating model + dev strategy are pulled in automatically with no extra steps.
- **Codex** auto-loads `AGENTS.md`. The musubi block is a *Required reading* list — Codex reads the listed files before starting.

The orchestrator's brief is the belt-and-braces layer: even if a harness misses an import, the brief explicitly tells each agent to read all three docs and walk the startup checklist.

This means three independent paths feed context into a fresh session:

1. Harness auto-load of `CLAUDE.md` / `AGENTS.md` (with imports)
2. Orchestrator brief walks the warm-start checklist explicitly
3. `/open-sesame` slash command runs the same checklist on demand (e.g., after a `/clear`)

---

## Using multiple sessions

Each session needs a unique name. Pass it as a second argument:

```bash
./launch_musubi.sh musubi.toml project_alpha
./launch_musubi.sh musubi.toml project_beta
```

Or use the default — `musubi` — and only run one session at a time. The launcher tears down any existing session with the same name before creating a new one.

---

## Switching panes

Mouse support is enabled automatically when the session starts. Click any pane to switch focus and type into it directly.

Keyboard shortcut: `Ctrl+b` then an arrow key.

---

## How the agents communicate

The agents write to a shared append-only file:

```
docs/agents/comms/active.txt
```

Every message ends with `<OVER>`. When the orchestrator detects that signal, it reads the new message block and sends it to the other agent's pane via `send_keys` — exactly as if a human had typed it.

A message looks like this:

```text
---------------------------------------------------
[@OPUS] [2026-01-01] [10:00 UTC]
Type: Review Request
Subject: Slice 1 complete — ready for review
Reply required: yes
GO: no
GO owner: none
GO action: none

@CODA

Action:
Implementation done.

Evidence:
- src/components/Widget.tsx
- src/api/widget.ts
- tsc passes; jest 12/12.

Result:
completed

Next:
Awaiting your review.

<OVER>
```

The full protocol — message types, planning chain, review pattern, branching strategy, escalation rules, mechanical gates — is defined in `docs/agents/AGENT_COLLAB_RUNBOOK.md`. Read it before your first session.

---

## Stopping

`Ctrl+C` in the terminal where the orchestrator is running stops the relay watcher. The tmux session and both agent panes stay alive — you can keep working in them manually.

To kill the tmux session entirely:

```bash
tmux kill-session -t musubi
```

To re-attach the watcher after a code change to `orchestrator.py` without re-briefing the agents:

```bash
python3 orchestrator.py --attach
```

Run this from inside the musubi repo (with the venv activated). It picks up the existing tmux session, skips briefing, and resumes the relay watcher only.

---

## Comms file persistence

By default the active comms file lives at `docs/agents/comms/active.txt` inside your project repo, so it survives reboots. The directory is gitignored — only the archived copy at `docs/agents/archive/` (written at cycle close) is committed. The bootstrap adds `docs/agents/comms/` to your project's `.gitignore` automatically.

If you'd rather keep the active file ephemeral, set `comms.file` to an absolute path like `/tmp/agent_comms.txt` in `musubi.toml`.

---

## Renaming the agents

Edit `musubi.toml`:

```toml
[agents.opus]
name = "Atlas"
handle = "@ATLAS"
cli = "claude"

[agents.coda]
name = "Forge"
handle = "@FORGE"
cli = "codex"
```

The orchestrator reads names and handles from the config. The runbook uses `Opus` and `Coda` as defaults — the brief substitutes whatever you set.

---

## Project structure for the agents

After bootstrap, your project will have:

```
your-project/
├── CLAUDE.md                            # auto-loaded by Claude Code (with musubi block)
├── AGENTS.md                            # auto-loaded by Codex (with musubi block)
├── docs/
│   ├── agents/
│   │   ├── AGENT_COLLAB_RUNBOOK.md      # protocol authority — core (auto-imported)
│   │   ├── AGENT_COLLAB_RUNBOOK_REFERENCE.md  # on-demand detail (not auto-imported)
│   │   ├── PAIR_OPERATING_MODEL.md      # rationale + adoption guide (auto-imported)
│   │   ├── current-state.md             # live capsule (project-owned)
│   │   ├── agent-todo.md                # task board (project-owned)
│   │   ├── agent-handoff.md             # handoff log (project-owned)
│   │   ├── comms/                       # active comms cycle (gitignored)
│   │   └── archive/                     # closed cycle logs (committed)
│   └── operator/
│       └── DEV_STRATEGY.md              # optional daily cadence (operator-facing, not auto-imported)
├── scripts/
│   ├── classify-slice.sh                # slice-lane classifier (run at slice acceptance)
│   ├── guard-staged-scope.sh            # pre-commit guard
│   └── ci-baseline.sh                   # pre-push CI baseline check
└── .claude/
    └── commands/
        └── open-sesame.md               # warm-start slash command
```

---

## Optional: Oyakata third-agent layer

Default musubi is a two-agent pair (Opus + Coda). Some projects benefit from a **third agent** — a supervisor who watches the pair work, doesn't write any code, and speaks up when the judgement of a cycle starts drifting. Musubi calls this third agent **Oyakata** (Oya, 親方 — master craftsman).

**Most projects do not need this layer.** The pair plus the runbook's mechanical guards is enough for most cycles. Enable Oya when you've outgrown that — typically: long cycles, complex domain decisions, or remote-operator setups where you want better in-flight visibility without sitting at the screen.

**What Oya does:** the orchestrator relays every comms message and every capsule edit to her pane. She builds context across events and, when a judgement-shaped pattern warrants it (a review that didn't probe specific defect classes, a planning doc whose factual claims don't match the repo, a stale capsule, a drift across multiple messages the pair can't see from inside), she posts an `@OYA` message to the comms file. The pair treats `@OYA` messages with `@LEAD`-equivalent weight for direction. Oya does not waive STOP rules — only `@LEAD` (the operator) can.

### Prerequisite: give Oya a north-star

**Oya's first duty is custody of the vision — and she cannot guard a vision she cannot see.** Before she watches a single cycle, she reads your project's vision / architecture / roadmap docs to build a picture of where the project is *trying to go*, not just how it's currently coded. Without them she falls back to watching only the code, and on turn one she'll stop and ask you to point her at the north-star. So have these in place before you enable her.

On startup she auto-discovers the recognised filenames (read every one that's present, all relative to your project root):

| Kind | Recognised paths |
|---|---|
| Vision / brief | `docs/PRODUCT-VISION.md`, `docs/VISION.md`, `docs/PRD.md`, `PRD.md`, `README.md` |
| Architecture / decisions | `docs/ARCHITECTURE.md`, ADRs under `docs/adr/` or `docs/architecture/` |
| Roadmap / backlog | `docs/ROADMAP.md`, `docs/BACKLOG.md` |

**If you already have these docs** (under any of the names above), you're done — Oya finds them. **If they live under non-standard names**, list them explicitly via `context_docs` in the `[agents.oyakata]` block so she reads *your* docs rather than guessing:

```toml
context_docs = ["docs/product-brief.md", "docs/tech-design.md", "docs/plan.md"]
```

> **Don't point `context_docs` at a musubi-managed file** (anything whose first
> line carries the `<!-- musubi-managed: -->` marker, e.g. `docs/agents/IaA.md`).
> Those are process machinery that `bootstrap.sh` refreshes — they contain no
> product knowledge, so Oya boots "successfully" knowing nothing about your app.
> This has happened in the field: one operator's apps all listed `IaA.md` as
> "the live spec", and every copy was the identical blank template. `doctor.sh`
> now warns on it, and Oya treats a managed file as a missing north-star.
>
> **And keep the docs honest once they exist.** A north-star that's loaded but
> stale is worse than none: the field incident that taught us this happened in
> a project whose vision and architecture docs were real and read at every
> boot — but an abandoned product rule survived in the docs, got copied forward
> by an agent as if current, and the pair faithfully built to a design the
> operator had dropped months earlier. When you change your mind about how the
> product behaves, mark the old rule superseded *in the doc* — agents can't
> hear what you only decided in your head.

**If you're starting from nothing**, copy the starter stubs and fill them in (a short, honest page Oya can hold in view beats a spec nobody reads):

```bash
cp templates/VISION.md templates/ROADMAP.md templates/ARCHITECTURE.md /path/to/your/project/docs/
```

These stubs are project-owned — copy once and edit freely; musubi never refreshes or overwrites them.

`scripts/doctor.sh` checks this for you: when Oya is enabled, it WARNs if no vision/architecture/roadmap docs are found (or if a `context_docs` path is missing), so you catch it before launch rather than on Oya's turn one.

### To enable

1. **Uncomment the `[agents.oyakata]` block in `musubi.toml`.** Set `enabled = true`. See `musubi.toml.example` for the template — including the optional `context_docs` knob described in the prerequisite above.
2. **Paste the optional Oya block into your project's `CLAUDE.md` and `AGENTS.md`.** Sources at [`templates/musubi-oya-block-claude.md`](templates/musubi-oya-block-claude.md) and [`templates/musubi-oya-block-agents.md`](templates/musubi-oya-block-agents.md). Tells the pair (Opus + Coda) what `@OYA` messages mean, how to handle `@OYA`-relayed gate waivers, and the optional `Confidence: <N>%` opt-in for Brier-scored review calibration. Both blocks are project-owned (not bootstrap-managed) — paste once and edit freely.
3. **Run musubi as normal:**
   ```bash
   ./launch_musubi.sh
   ```
   The orchestrator notices `[agents.oyakata].enabled = true` and auto-spawns the Oya pane (via `scripts/attach-oya.sh`) once the pair CLIs are up. You'll see a `[OYA] pane discovered: %N` line in the orchestrator's log stream.
4. **Watch for Oya's `Startup complete. Ready.`** in her pane. She writes a structured READY block to `docs/agents/oyakata-log.md` immediately after — you can `less` that log at cycle close for her cycle-close exec brief.

### What `attach-oya.sh` does on your behalf

- Splits a third tmux pane (top, ~30% height, full width) running `claude --model opus`.
- Writes a scoped `docs/operator/.claude/settings.local.json` into the musubi repo so Oya's startup tools (Read on project + musubi files, Edit on her log + comms, Bash on read-only commands like `tmux capture-pane` / `date` / `cat` / `grep`) are pre-approved. The file is gitignored — it doesn't ship with the repo.
- Auto-pastes the Oya v0.1 prompt (with `<PROJECT_PATH>` and `<MUSUBI_ROOT>` placeholders substituted to absolute paths) into the new pane and submits it. Also copies the prompt to your clipboard as a Cmd+V fallback.

### Read more

- The prompt + behavioural contract Oya runs under: [`docs/operator/oyakata-prompt-v0.1.md`](docs/operator/oyakata-prompt-v0.1.md).
- The structural rationale (three-way LLM audit that surfaced asymmetric-deference): [`docs/positioning/external-review.md`](docs/positioning/external-review.md).

---

## The instrumentation stack

A solo agent fails opaquely: it merges a plausible-looking result and you find out later, if at all. The pair fails out loud — the two vendors disagree, the disagreement gets recorded, and the failure has a name, so it can be engineered out rather than rediscovered. The instrumentation stack is what makes that legibility durable: per-cycle artefacts that name where the second vendor earned its keep, which rules earned theirs, and where the operator's own judgement drifted. None of it is in the marketing copy — it's in the artefacts, committed and greppable. To keep itself honest, the stack ships an instrument built to be able to conclude it was pointless: shadow review reasons through a same-vendor counterfactual each cycle and is free to return *"a same-vendor pair would have done as well"* — a claim that, if it kept coming back, would undercut the framework's central bet.

Five per-cycle artefacts, each addressing a different axis:

| Artefact | Path | What it instruments | When written |
|---|---|---|---|
| **Exec brief** | `oyakata-log.md` (appended) | operator-facing cycle summary | every cycle close |
| **Asymmetry corpus** | `docs/agents/asymmetry/<cycle>.md` | where the two vendors made different calls | every cycle close |
| **Rules ledger** | `docs/agents/rules-ledger.yml` (incremental) | which runbook rules earn their keep | every cycle close |
| **Shadow review** | `docs/agents/shadow-review/<cycle>.md` | what a same-vendor pair would have caught vs missed | every cycle close (1 sampled slice) |
| **Operator critique** | `docs/agents/operator-critique/<cycle>.md` | operator's own decisions for bias / drift / deference | when triggered (gate-waiver, override, etc.) |

Plus one optional protocol extension:

- **Brier-scored review calibration** — reviewers MAY include `Confidence: <N>%` on a Review Result. Oya scores outcomes at cycle close; per-reviewer calibration accumulates in the rules ledger. No protocol break for non-adopters.

Each artefact is committed (durable). Each is queryable. I'm not aware of another multi-agent framework that ships all of these as durable per-cycle artefacts — if one does, I'd genuinely like to know.

### Asymmetry corpus — *the framework's empirical edge*

Most other claims of the framework (structured review, mechanical guards, supervisor pattern) are now also being made elsewhere. The asymmetric-vendor angle is the part I haven't seen elsewhere. The asymmetry corpus surfaces vendor-disagreement *before* it vanishes into the merged result. Each disagreement is classified (`architectural` / `scope` / `spec-doc-accuracy` / `test-design` / `risk-tolerance` / `style` / `tooling`), both agents' positions quoted from comms, resolution recorded, and a one-sentence *vendor-asymmetry signal* naming the tendency the disagreement reveals. After N cycles you can grep the corpus and answer *"why pay for two vendors?"* with concrete catches.

Schema: [`docs/operator/asymmetry-schema.md`](docs/operator/asymmetry-schema.md). Worked example referenced therein.

### Rules ledger — *the protocol auditing itself*

Most multi-agent protocols accrete rules; they rarely retire on evidence. The ledger gives every named rule (runbook rules + project STOP rules) provenance plus empirical counters: `fires` (cited in the comms), `catches` (fires that shaped a real outcome, classified by class), `bypasses` (waivers with stated reasons), `silent_misses` (rule should have fired but didn't). The `fires` counts are mechanical — `scripts/ledger-from-comms.py` reads them straight from the comms at cycle close, so a forgotten update can't quietly leave the ledger empty; the judgement counters (catches, silent misses) stay Oya's. After 5+ cycles it surfaces health candidates: **prune** (zero fires), **promote** (high catch rate), **refine** (high bypass rate), **discipline drift** (silent misses exceed catches). I haven't seen another protocol that makes its own rules earn their place on evidence — if you have, point me to it.

Schema: [`docs/operator/rules-ledger-schema.md`](docs/operator/rules-ledger-schema.md).

### Shadow review — *the framework's falsifiability instrument*

The asymmetry corpus accumulates evidence **for** the asymmetric-vendor claim but can't falsify it. Shadow review can. At every cycle close, Oya picks one slice and reasons through a same-vendor counterfactual: *"if Opus had been the reviewer in Coda's role, what would they likely have caught? What would they likely have missed?"* Verdict per slice: `asymmetric-pair-added-value` / `equivalent` / `same-vendor-would-have-done-as-well` / `counterfactual-actually-stronger`. Honesty trumps framework loyalty — the corpus's value as evidence depends on it. Lean version of true shadow mode (which would run a parallel same-vendor pair in worktrees, doubling compute); this one is a counterfactual exercise, not a parallel execution.

Schema: [`docs/operator/shadow-review-schema.md`](docs/operator/shadow-review-schema.md).

### Operator critique — *closing the asymmetric-deference loop at the operator altitude*

The framework's claim is *"no actor + reviewer combo can self-detect their own deference."* That applies to operator + pair as much as it does pair-internally. The operator forms judgements (gate waivers, dispute adjudications, slice acceptances, push approvals) but has no one watching whether their own judgements drift, over-defer, or smuggle in confirmation bias. The operator critique closes this loop: when the cycle's events trigger any of a defined set of signals, Oya authors a critique reviewing the operator's decisions for `confirmation-bias` / `scope-drift` / `pair-deference` / `unstated-assumption` / `premature-closure`. Tone is collegial — same way the pair benefits from Oya's read on their work, the operator benefits from a third-party read on theirs.

Schema: [`docs/operator/operator-critique-schema.md`](docs/operator/operator-critique-schema.md).

### Calibration — *per-reviewer competence over time*

Reviewers state confidence (0–100%) on each Review Result. Oya scores outcomes at cycle close (`confirmed` / `partially-confirmed` / `disconfirmed`). Per-reviewer Brier scores accumulate per class. After 10+ reviews per cell, the framework can answer *"how much should I trust Coda on architectural slices vs Opus on test-design?"* with calibration data, not anecdote. Soft on-ramp: confidence is optional per review; non-adopters aren't penalised.

Schema: [`docs/operator/calibration-schema.md`](docs/operator/calibration-schema.md). Lives as a section of the rules ledger, not a separate file.

### Why this matters for adoption

A new adopter reading the README and asking *"is the protocol overhead worth it?"* now gets answered with a corpus they can grep. The framework's distinguishing claims are self-instrumenting. Three months in, the corpus tells you which rules earned their keep, where vendor asymmetry actually paid off, how often the framework would have been outperformed by a same-vendor pair, where the operator's own discipline held vs drifted, and which reviewer is best calibrated on which class of work. None of that is in the marketing copy — it's in the artefacts.

---

## Slice lanes — ceremony that scales with risk

A typo fix and an auth-schema migration are different animals, and the protocol treats them that way. Before a slice is accepted, `scripts/classify-slice.sh` reads the staged files and the diff size and picks a lane:

| Lane | For | Ceremony |
|---|---|---|
| **tiny** | docs / comments / README / dependency bumps (≤20 LOC, ≤2 files) | one-line claim that doubles as the completion; no review, no capsule |
| **lightweight** | a single small code change, or bigger doc edits | optional review; no GO baton |
| **heavy** | anything touching state, schema, UI, or CI — or a multi-file / larger code change | the full protocol: mandatory review, the "Findings I went looking for" block, GO baton |

```bash
scripts/classify-slice.sh            # reads the staged set; prints the lane + why
```

The classifier is **mechanical on purpose** — an agent can't talk its way into a lighter lane to skip review, and the operator can always bump a slice heavier. On the road-test, it caught an 89-line change the pair had planned to run lightweight and forced it down the full-review path. The light lanes also unlock a one-line **Receipt** message in place of a full status report, so trivial work doesn't carry heavy work's paperwork. Full rules: the *Lane choice* section of the runbook.

---

## Mechanical gates

Two scripts ship as starter implementations of the runbook's mechanical-gate requirements:

### `scripts/guard-staged-scope.sh` — pre-commit

Run before every `git commit` to enforce slice-scope discipline:

```bash
scripts/guard-staged-scope.sh src/components/Widget.tsx src/api/widget.ts
```

Fails if files outside the declared allowlist are staged, or if any allowlisted path has nothing staged. The allowlist must match the file list that was peer-reviewed.

### `scripts/ci-baseline.sh` — pre-push

Run before requesting `@LEAD`'s push approval. Surfaces the CI status of the last 5 main runs in a format meant to be pasted verbatim into the push-approval comms message:

```bash
scripts/ci-baseline.sh ci.yml
```

If 0/5 are green, the script also prints the detail block and a one-line warning that explicit `@LEAD` ack is required before push. Requires GitHub CLI (`gh`).

Both scripts are designed to be wrapped in your own pre-commit / pre-push hooks if you want, but the runbook treats them as scripts run by the agent before the corresponding comms message — that way the output gets surfaced rather than swallowed by the hook.

---

## Status & honest limitations

Musubi is **pre-1.0**. It works, it's in daily use, but the API, the protocol vocabulary, and the file layout can still change between versions without a migration path. Treat it as something you adopt and adapt, not something you depend on unattended.

**Single maintainer.** One person builds and maintains this. The mitigation is in the design, not in a community — there isn't one yet, and this README won't pretend otherwise. The load-bearing part of musubi is markdown (the runbook, the operating model, the protocol) plus a few hundred lines of Python and shell. It's portable and re-hostable. If this repo went quiet, the protocol docs are the asset, and they're readable and forkable by anyone.

**The tmux transport is finicky.** Musubi drives two CLIs by sending keystrokes into a terminal multiplexer. That's how it works with *any* CLI that has no API, and how it keeps both agents in full, human-visible panes you can read and type into. The cost is setup friction: pane discovery, paste timing, and boot races are real (see the Oya troubleshooting entries). We think it's the right trade — visible panes and CLI-agnosticism are worth more than a cleaner transport — but the friction is real and we're not hiding it. (`scripts/doctor.sh` checks the common failure points before you launch.)

**Pairing creates failure modes a solo agent never hits.** Two agents sharing state can desync — a botched multi-line write that leaves the comms file or a capsule inconsistent, a relay that fires on a half-written message. A solo agent doesn't have these. The argument for pairing isn't that it's failure-free; it's that the failures are *legible*. The system surfaces and names them, so they get engineered out one at a time, instead of a solo agent failing opaquely with no second party to notice.

**The rules-ledger fire-counts are a trend proxy, not an audit.** `ledger-from-comms.py` greps the comms for rule citations. A grep can't tell a load-bearing citation from a passing mention, so absolute counts run hot. What's reliable is the *signal*: a rule that fires zero times across many cycles is a sound prune candidate. Read the counts as a trend, not a measurement.

**The evidence base is two codebases, one operator.** Musubi has run on two real projects of different shapes (Codebase A — ~289K lines, 3,984 tests, 313 routes; and Codebase B, a mobile + marketplace app). That tests portability across domains. It does *not* test portability across operators — both were driven by the same person. The across-operators gap is open, and closing it is the single thing that would most harden the framework's central claim. We'd rather say that than imply more.

> **Roadmap: sturdier transport.** The file-based comms protocol is already transport-agnostic — tmux send-keys is one implementation, not a dependency. An MCP comms channel is **designed but not built**; it does not exist yet. When it lands it'll be an alternative to the keystroke transport, not a replacement for the panes.

---

## Updating musubi in a project

To pull the latest runbook / operating model / dev strategy / scripts into a project that's already bootstrapped:

```bash
cd /path/to/musubi
git pull
./bootstrap.sh /path/to/your/project
```

The bootstrap is idempotent. Managed docs get refreshed; project-owned files (capsule, todo, handoff) are left alone; the CLAUDE.md / AGENTS.md block is updated in place.

If you've forked a managed doc (deleted the `<!-- musubi-managed -->` marker), bootstrap shows a diff and skips. Pass `--force` to overwrite anyway.

---

## Troubleshooting

**The venv fails to create**
Delete it and let the script recreate it: `rm -rf .venv && ./launch_musubi.sh`

**Messages are sent but the agent doesn't respond**
The CLI may not have finished loading. Either wait — the orchestrator polls for `Startup complete. Ready.` in both panes before starting the watcher — or `Ctrl+C` the watcher and re-run with `python3 orchestrator.py --attach` once both prompts are visible.

**`<OVER>` is not being detected**
Check that the agent is actually writing to the comms file path defined in `musubi.toml`. The orchestrator watches that exact path.

**Pane is visible but not interactive**
Mouse support is enabled automatically by the launcher. If it didn't take, run `tmux set -g mouse on` manually.

**Merge conflicts between agents**
Neither agent resolves conflicts unilaterally. Raise a Blocker in the comms file and resolve it yourself. See the Branching Strategy section of the runbook.

**Launch warns (or stops) on an oversized managed doc**
The handoff / todo / capsule accrete across cycles. Above ~40k chars the orchestrator warns; above 100k it offers to rotate the doc in place — `Rotate now? [y/N]` archives the full file to `docs/agents/archive/` and trims the active copy to the two most-recent cycles. Say yes and it continues. CLAUDE.md and the runbook are large by nature (no cycle sections to trim) — they only ever warn.

**Bootstrap says my CLAUDE.md is a fork**
You stripped the `<!-- musubi-managed -->` marker from one of the managed docs. Either re-add the marker (then bootstrap will refresh it) or pass `--force` to overwrite. The fork detection is just a safety net.

### Oya-specific

**Oya pane never appears (only two panes after launch)**
Check the orchestrator's log stream for `[OYA] agents.oyakata.enabled = true — spawning Oya …`. If absent, your musubi.toml doesn't have the `[agents.oyakata]` block uncommented + `enabled = true`. If present but no `[OYA] pane discovered: %N` follows within ~30s, check the `[ATTACH] ...` lines for the actual failure (most often `claude --model opus` not on PATH, or `pbcopy` missing on Linux).

**`claude: command not found` from Oya pane**
The Oya pane runs `claude --model opus`. The `claude` CLI must be on PATH for the shell tmux launches with. `npm install -g @anthropic-ai/claude-code` if needed, then restart musubi.

**No clipboard tool found (Oya auto-paste falls back to tmux only)**
`scripts/attach-oya.sh` probes for a clipboard tool in order — `pbcopy` (macOS), `wl-copy` (Wayland), `xclip` / `xsel` (X11), `clip.exe` (WSL) — and soft-fails if none is present (Oya still attaches; only the Cmd+V clipboard fallback is unavailable, the tmux paste path still works). On a headless Linux box with none installed, `sudo apt-get install xclip` (or `wl-clipboard`) restores it.

**Oya pane opens but never runs startup**
The auto-paste raced the Claude Code TUI boot — the prompt was sent before the input box was ready. Focus the Oya pane and Cmd+V to paste the prompt manually (`attach-oya.sh` always copies it to your clipboard as a fallback), then Enter. If this happens regularly, bump the `sleep 5` in `scripts/attach-oya.sh:Step 6` to 7–10 seconds.

**Two Oya panes appeared**
Was the case on 2026-05-18 before the orchestrator's idempotency check landed. If you see it now: `tmux kill-pane -t %N` on the halted one (check `tmux list-panes -t musubi` to find which pane id is in `docs/operator` cwd but inactive). Report it as a bug — `discover_oyakata_pane` should prevent double spawns.

**What's `docs/operator/.claude/settings.local.json` and why did it appear?**
`scripts/attach-oya.sh` writes this file at attach time. It pre-approves Oya's startup tools (Read on your project + musubi tree, Edit on her log + comms, Bash on a small set of read-only commands) so you don't have to ack "Do you want to proceed?" for every read during her boot. It's `.gitignore`d — it never ships with the repo. Inspect it freely.

**`--with-oya` says "deprecated" — what do I do?**
Oya is now controlled by `musubi.toml` (single source of truth for the run config). Open the toml, uncomment `[agents.oyakata]`, set `enabled = true`, and run `./launch_musubi.sh` with no flags. The orchestrator auto-spawns Oya on its own.

---

## Acknowledgements

Built with [libtmux](https://github.com/tmux-python/libtmux). Agents are [Claude Code](https://claude.ai/code) and [Codex](https://github.com/openai/codex). The working protocol in `docs/agents/AGENT_COLLAB_RUNBOOK.md` and `docs/agents/PAIR_OPERATING_MODEL.md` was developed through actual use across multiple development cycles — it reflects what works in practice, not just what sounds reasonable in theory.
