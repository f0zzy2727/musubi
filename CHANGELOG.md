# Changelog

All notable changes to musubi-the-orchestrator are documented here. The runbook (`docs/agents/AGENT_COLLAB_RUNBOOK.md`) maintains its own version + changelog for protocol-level changes.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Calendar-shaped versioning — `v0.1.0` is the first tagged release; semver discipline firms up from `v1.0.0` onward.

## [Unreleased]

### Added

- **Cross-app setup repair tooling.** New `scripts/setup-fix.sh` (mechanical
  engine: scaffolds a real north-star, creates a durable `docs/i-and-a/` home,
  repairs binary/corrupt comms files, lays a shared cross-app rules skeleton;
  report by default, `--fix` with backups, idempotent, `-c` scopes to one app —
  never mutates tomls), `scripts/launch_setup_fix.sh` (one-command interactive
  launcher), and the `/musubi-setup-fix` command
  (`templates/claude-commands/musubi-setup-fix.md`, installed by `bootstrap.sh`)
  that drives an agent through audit → mechanical fix → interview/draft/approve
  real content → wire `context_docs`. Closes the loop where a lesson learned in
  one app never reaches its siblings, so the same bug stops being re-derived.
  Field origin: an operator's five apps, three booting Oya on the managed
  `IaA.md` with the reclone lesson absent from every rules-ledger.
- **`collect-debug-bundle.sh` is text-only and size-capped** — binary/media/model
  files (e.g. TTS audio) and oversize files are skipped (logged in the MANIFEST),
  so a binary-heavy project no longer balloons the bundle to gigabytes.

### Changed

- **`scripts/doctor.sh` gains a comms-file health check and `-c` config
  targeting.** It now FAILs on a binary/corrupt `active.txt` (the pair and Oya
  read it as their shared record), and `-c musubi-<app>.toml` checks any sibling
  config instead of only the default `musubi.toml`.

- **Repo-scoped orientation reads auto-approve under the disclosure opt-in
  (`perm-1`).** The agents' per-session boot orientation (`sed -n`/`tail`/`head`/
  `cat`/`nl`/`rg`/`grep` over project files) was the single biggest source of
  permission-prompt friction — deferred every session because content-reads can
  leak secrets (sec-1). The PreToolUse hook now auto-approves these under the
  existing `[security].repo_has_no_secrets` opt-in, but ONLY when every path
  argument is repo-relative AND not a secret-bearing filename — an out-of-repo
  read (`cat ~/.ssh/id_rsa`), a `..` traversal, or a secret basename (`.env`,
  `*.key`, `*.pem`, `id_rsa`, …) still defers even with the opt-in. A strictly
  tighter guarantee than the old blanket exclusion, with the daily friction
  removed for opted-in beds. `sed` is gated to the read-print form (`-n`, never
  `-i`).

## [0.3.0] - 2026-06-24

Operational-reliability + safety release. The headline is the **stall watchdog**:
the three silent-stall classes that recurred across cycles (an agent blocked on a
permission modal, a single pane parked after its own turn, and a verdict that
landed in the capsule but never relayed) are now detected mechanically and
surfaced to the operator instead of waiting for a human to notice. Alongside it,
a **blast-radius gate** stops a vague "apply to the others" from fanning a costly
or destructive action across an account before anyone declares what it touches.

### Added

- **Stall watchdog — three silent-stall classes detected mechanically
  (`started-idle-watchdog-gap`, `blast`-adjacent reliability).** Each recurred
  across cycles and was only ever caught by a human. (1) *Permission-modal halt:*
  any pane (workers + Oya) blocked on a permission/approval prompt is surfaced to
  the operator with the specific question — never keystroke a modal. Always on.
  (2) *Per-pane park:* a single coder pane that goes idle after its own turn
  (`buffer_is_working` distinguishes a live spinner from a finished turn) is
  nudged, then escalated — catches a park the channel-level silence watchdog
  misses because the channel isn't quiet. `[comms].pane_idle_seconds` (240).
  (3) *Comms-drop:* a capsule/verdict update that lands over a quiet, fully-relayed
  channel with no comms append following is flagged as a dropped relay baton —
  the S3/S4 field bug, now detected in ~90s instead of waiting on the 300s silence
  net. `[comms].baton_grace_seconds` (90). Pure detectors, fixture-tested.
- **Silence watchdog (`idle-1`).** When the channel is fully relayed and quiet
  past `[comms].idle_wake_seconds` (300) with nothing pinned for the operator,
  the orchestration layer is woken (Oya, or both coders on a pair-only bed),
  escalating to the operator on a persistent stall — the built-in equivalent of
  the operator's `/loop 5m` Oya cadence. Skips any pane holding an unsent typed
  line (would garble it) and routes the operator to submit it instead.
- **Context-budget watchdog (`P1b`).** Warns the operator before a coder pane
  dies of context exhaustion (a nudge can't recover a context-dead pane), reading
  the CLI's own "`/clear to save Nk tokens`" pressure hint.
  `[comms].context_warn_k` (400).
- **Quarantine consolidation (`P3`).** Unparseable comms regions now append to a
  single `_unparseable.log` beside the comms file instead of proliferating
  per-incident sidecars (the okami bed reached 47), and orphan-tail debris is
  distinguished from a real unknown-handle drop (only the latter alarms the
  operator).
- **Env preflight (`keys-1`).** `scripts/env-preflight.sh` sources a project
  `.env` and gives operator-readable guidance when an agent CLI launches without
  the API keys it needs (the "Codex is sandboxed / has no keys" field report),
  wired into both launchers.
- **Agreement Auditor v0 scorer (`consensus-1`).** `scripts/comms-metrics.py`
  emits a `correlated_blindspot_risk` composite — treating dissent-free agreement
  as a risk signal, not a success state — from ledger silent-miss / blast-radius /
  zero-finding-approve inputs.
- **Rule-fire counter widening (`P2b`).** `scripts/ledger-from-comms.py` gains
  `citation_aliases` + `citation_regex` so rule-fire reconstruction stops
  under-counting cited rules; schema documented in `rules-ledger-schema.md`.

### Security

- **Blast-radius gate on operational / cost / destructive actions (`blast-1`).**
  Field report: "apply this to the other apps" became "re-clone every voice for
  the other apps" — an API spend that overwrote resources that already existed,
  hand-stopped by the operator; neither peer flagged it. Every gate to date
  watched *code* (diffs, files, tests); none watched what runs. Part A: the
  PreToolUse hook (`scripts/oya-pretooluse.py` `classify_blast_radius`) now
  hard-`deny`s high-blast Bash (`rm -rf`, force-push, `reset --hard`,
  `DROP`/`TRUNCATE`, `DELETE`-without-`WHERE`, `terraform destroy`,
  `kubectl delete`, prune, `s3 rb`, voice/model clone, `--all` fan-out,
  destructive loops) with a reason that tells the agent to declare the blast
  radius (count, cost, reversibility, overwrite) and get an operator confirm
  before retrying — checked before the allowlist, so it overrides any match.
  Part B: an Oya pre-push red-team gate (3.6) carries the same discipline to
  Codex, in-app/API, and opaque-script actions the Opus-Bash hook can't see.
  Honest limit: Part A is Opus-Bash-only by construction (documented + tested).

- **PreToolUse allowlist no longer auto-approves secret-disclosing reads
  (`sec-1`).** An external audit found the oyakata-2 hook equated "non-mutating"
  with "safe to auto-approve": it still auto-approved `echo $TOKEN` (bare `$`
  was never fenced, so the shell expanded it), `git show HEAD:.env` (prints a
  tracked secret — the exact thing removing `cat` was meant to prevent),
  `git diff`, `git config --list`, and `git remote -v`. The allowlist is now
  split by disclosure risk: metadata-only commands (`git status`/`branch`/
  `rev-parse`/`ls-files`, `git log --oneline`, `pwd`/`ls`/`stat`/…) auto-approve;
  content/config-disclosing reads defer by default and re-enable only under a
  new `[security].repo_has_no_secrets` opt-in. Bare `$` expansion is fenced and
  `echo` is removed. Wiring quotes the hook path so a checkout location with a
  space stays one argument. The disclose opt-in logs a loud warning each launch.

- **`pyproject.toml` + a `musubi` console script (`pkg-1`).**
  `pip install -e '.[dev]'` builds the package and installs a `musubi` command;
  `orchestrator.py`'s entry point is now a `main()` returning an exit code.
- **A reproducible metric artifact (`pkg-1`).** `scripts/comms-metrics.py` JSON
  output is now demonstrated by a committed fixture comms thread
  (`tests/fixtures/comms-sample/`) and its deterministic artifact
  (`docs/positioning/benchmarks/artifacts/sample-metrics.json`), pinned by a
  test so the numbers stay reproducible from committed data. A README documents
  the reproduce command, the schema, and the honest scope (private-corpus
  headline numbers are not reproducible from the repo).

### Changed

- **README: "Why peers, not a pipeline" section.** States the load-bearing
  differentiator up front — equal peers of different lineage that both build and
  check each other (disagreement is the mechanism), versus the delegated
  plan→build→judge pipelines that fix each agent to a station on a line.
- **Oya prompt hardening (`oya-1confab`, `consensus-1`, `blast-1`).** A
  no-invent-system-internals rule (say known-vs-inferred; never name a flag/mode
  you can't read in a file — verify and read it instead); a mandatory mechanical
  secret/PII data-leak scan on data-touching slices (the gate's measured weak
  spot — no longer eyeballed); the convergence→falsification rule sharpened
  (agreement on a high-blast slice triggers injected dissent); and the
  operational blast-radius red-team gate (3.6).
- **New `[comms]` watchdog knobs (defaults safe, documented in
  `musubi.toml.example`).** `idle_wake_seconds` (300), `context_warn_k` (400),
  `pane_idle_seconds` (240), `baton_grace_seconds` (90). Existing beds inherit
  the defaults — no config edit needed; the permission-modal class is always on
  with no knob.
- **Positioning: README now states up front when musubi fits — and when it's
  overkill (`scope-1`).** A new section makes the boundary explicit: musubi is
  for work where a missed defect costs more than the tokens; small/low-risk
  work is solo or pair-only (no third agent). Light by default, ceremony scales
  with risk.
- **Native Windows fails fast with a "use WSL2" message (`scope-1`).** The
  runtime is tmux + libtmux; `orchestrator.py` and `launch_musubi_tmux.sh` now
  exit cleanly on native Windows instead of breaking deep in the relay. Windows
  is documented as out of scope (use WSL2).
- **Debug bundles are private by default (`priv-1`).**
  `scripts/collect-debug-bundle.sh` no longer collects Claude/Codex transcripts
  unless `-T` is passed; when it is, a best-effort secret-redaction pass
  (`scripts/redact-bundle.py`) runs before zipping, and the MANIFEST declares
  which sensitive classes the bundle contains. **Behaviour change:** callers
  relying on default-in transcripts must now pass `-T`.
- **Operator console input prompt is now visible (`ux-1`).** The `YOU →` prompt
  is rendered bold/cyan so the operator can tell where they type.

### Fixed

- **Operator console no longer eats pasted/typed text (`console-1`).** The raw
  `os.read`+`select` paste fix had bypassed the tty driver's echo, so input was
  invisible until Enter. `scripts/operator-console.py` now re-asserts a known-good
  tty state at startup (ICANON|ECHO|ISIG, bracketed-paste off, restored on exit);
  no-ops cleanly on a non-tty.
- **Idle watchdog won't garble a parked pane (`P2a`).** When a coder pane parks
  with its next action typed-but-unsent (`❯ continue S2`), the silence watchdog
  skips keying it (which would append to and corrupt the pending line) and routes
  the operator to submit it instead.
- **Oya's scoped `settings.local.json` is written via a JSON helper, not a
  heredoc (`robust-1`).** `scripts/write-oya-settings.py` renders the file with
  `json.dump`, so a project path containing a quote, backslash, or `$` can no
  longer corrupt it (and it stops violating the repo's own no-heredoc rule).
- **Oya pane discovery uses a separator-aware path match** so a sibling clone
  (`<root>.bak/…`) can't be mistaken for the active checkout's Oya pane.


- **The relay no longer floods Oya with a whole cycle's old messages after a
  comms-file shrink.** Field report from a second operator (Oya herself
  flagged it): something external truncated+rewrote the active comms file
  mid-cycle, so `current_size < last_offset` fired, the watcher reset the read
  offset to 0 and re-drained the entire file — and the recently-relayed dedup
  window was `maxlen=8`, far too small to recognise a full re-read as already
  delivered. Every message older than the last 8 re-relayed to Oya, repeating
  and growing on each shrink, burning her context and risking a real new
  message getting buried. The dedup window is now `RECENTLY_RELAYED_WINDOW =
  1000` (a named constant with the rationale), deep enough to cover a whole
  cycle, so a shrink-triggered re-read recognises and skips everything already
  delivered — no flood, and still no drops (refused blocks remain excluded per
  the 2026-06-06 fix). Restarting the orchestrator was the only prior
  mitigation. 2 regression tests guard the window size + re-read behaviour
  (`tests/test_relay.py`); suite at 494. (The deeper question — what truncates
  the file mid-cycle — is logged via `[WATCHER] Comms file shrank`; this fix
  makes the re-read safe regardless of the trigger.)

- **CI has been red since the repo went public — one info-level shellcheck
  finding (SC2015, `A && B || C` in `attach-oya.sh`'s pane-tint block)
  failed the lint step on every run, and because lint precedes pytest, the
  hosted suite never actually executed. Rewritten as a plain if/else; the
  full CI shellcheck invocation now passes locally.**

- **The relay no longer silently drops messages — four defects fixed in one
  redesign of the watcher's read path.** Field-diagnosed on a second
  operator's deployment (and independently root-caused by that deployment's
  own Oya, who patched her local copy, validated it against this repo's full
  test suite, and left it uncommitted for maintainer review — this is the
  canonical version of that fix, plus two defects she didn't hit):
  (1) **batch-drop** — the watcher extracted only the LAST message in a read
  span, so any fast exchange landing 2+ posts in one ~3s window silently
  discarded all but the newest; the watcher now drains every complete block
  in write order (`comms.extract_messages()`); (2) **advance-before-deliver**
  — the read offset advanced before relay delivery, so one transient tmux
  failure lost that message permanently; the offset now advances only after
  the whole span is processed, and a mid-drain failure retries the span
  (already-relayed blocks are skipped by a new multi-deep recently-relayed
  memory — worst case a duplicate nudge, never a silent drop);
  (3) **refusal-poisoned re-post** — a guard-refused message (e.g.
  capsule-stale) was remembered as "already relayed", so an agent that fixed
  the cause and re-posted the same text VERBATIM had it silently dropped;
  refusals no longer feed the dedup memory; (4) **partial-tail jump** — the
  offset advanced to end-of-file even when the span ended with a
  still-composing message, losing it when its over-signal arrived; the
  advance now stops at the last COMPLETE block. Duplicate skips and
  multi-message drains are logged. 8 regression tests; suite at 470.

### Added

- **One orchestrator per comms file — a second one on the same file now refuses
  to boot instead of corrupting the relay.** Root cause behind the Oya-flood
  bug: every orchestrator truncates its active comms file to zero bytes at boot
  (`archive_and_reset_comms`), so a second orchestrator pointed at a comms file
  a live peer is mid-cycle on would zero it underneath them — the other process
  saw the shrink, reset its read offset, and replayed the whole cycle (and both
  send-keys into the same panes). This happens with a leaked/duplicate
  orchestrator on one instance, or two tomls pointing at one project; it does
  NOT happen for two genuinely distinct projects (distinct comms files). The
  orchestrator now claims a lockfile beside its comms file at boot; if a live
  peer already holds it, it refuses with an actionable error naming the peer's
  PID/session. A stale lock (owning PID dead — e.g. `kill -9` or a `SIGTERM`
  restart) is taken over, so a crash never wedges future launches. Applies to
  both fresh launches and `--attach` resumes. The lock is released on clean
  exit. 9 tests (`tests/test_comms_lock.py`); suite at 503.

- **The channel pane now renders Oya's markdown instead of showing it raw.**
  The `OYA → OPERATOR` pane ran a plain `tail -F`, so the operator saw the
  file's markup verbatim — literal `**` around every header, `---`
  separators, and `tail`'s hard mid-word wraps at the pane edge (field note:
  "not really human language"; the words were fine, the rendering wasn't).
  It now runs `scripts/channel-view.py`: a zero-dependency follower that
  strips inline `**bold**`/`*italic*`/`` `code` ``, turns `**… — Oya:**`
  headers into bold coloured lines, renders `---` as a horizontal rule, and
  word-wraps to the pane width without breaking words or hyphenated tokens.
  It re-opens on truncation/recreation like `tail -F`, **re-renders the
  visible tail on terminal resize (SIGWINCH)** so lines reflow to the new
  pane width instead of staying wrapped at the old one, and `attach-oya.sh`
  falls back to plain `tail` when python3 isn't on PATH — a progressive
  enhancement, not a new dependency. 10 tests (`tests/test_channel_view.py`).

- **Operator console — the operator now types to Oya in a pane of their own,
  not in her relay-fed pane.** Follow-up to the channel pane from the same
  second operator: the channel fixed Oya's answers scrolling away (output),
  but the *input* was still clobbered — he typed into Oya's pane while the
  orchestrator `send-keys`-relayed pair traffic into that same pane, and his
  keystrokes got overwritten mid-line. His own fix instinct ("put the input
  on the fourth screen") was right. Now `attach-oya.sh` adds a fifth pane —
  a console (`scripts/operator-console.sh`) under the channel pane — with
  exactly one writer: him. Each line he submits is appended to
  `docs/agents/operator-input.md`; the orchestrator watches that file and
  relays each entry into Oya's pane (the same path comms relays take), and
  she answers + mirrors to the channel he reads above. The whole
  operator↔Oya loop (type below → Oya → read above) never touches the
  relay-fed pane, which also fixes the side effect that scrolled-up copy in
  Oya's pane kept snapping back to the bottom (that was the relay redraw).
  Opt out with `OYA_INPUT_PANE=0` (pane) or
  `[agents.oyakata].operator_input = false` (relay); height via
  `OYA_INPUT_PANE_HEIGHT`. 12 tests (`tests/test_operator_input.py`); suite
  at 482.

- **Operator-channel viewer pane — Oya's answers to you no longer drown in
  the relay scroll.** Field report from a second operator: Oya answered his
  questions correctly, but constant relay traffic from Opus/Coda
  (`send-keys` into her pane) scrolled every answer away before he could
  read it. The operator-actions capsule pins *blocking asks* but
  deliberately excludes conversational answers — those had no durable
  surface at all. Now they do: Oya mirrors every message she addresses to
  the operator (answers, questions, requested status snapshots) verbatim
  into an append-only `docs/agents/operator-channel.md`, and
  `attach-oya.sh` adds a fourth pane — a passive `tail -F` viewer, no
  agent — right of Oya that shows only that file. Nothing else writes
  there, so it only moves when Oya speaks to *you*. Same hard turn-end
  gate as the pin rule: addressed the operator → channel entry that same
  turn, "they're watching live" is not an exemption. Opt out with
  `OYA_CHANNEL_PANE=0`; width via `OYA_CHANNEL_PANE_WIDTH` (default 35%).
  Also fixes a latent `set -u` crash on idempotent re-runs of
  `attach-oya.sh` when the existing Oya pane was matched by cwd rather
  than title.

- **Relay refusals now interrupt the operator instead of scrolling away.**
  The watcher's guards (ack-of-ack idle streaks, capsule-stale holds, and
  unparseable-content drops) were printed to the watcher log and nowhere
  else — from the operator seat, a *refusing* relay was indistinguishable
  from a *broken* one. Field report from a second operator: an entire
  session spent hand-carrying every handoff between panes because nothing
  said why nothing moved. Refusals now ride the same interrupt surface as
  operator actions: a `⛔ RELAY HELD` segment pinned to the tmux status bar
  (composing with, not clobbering, the `⚑ AWAITING YOU` pin), a desktop
  notification plus terminal-bell banner on the first refusal of each
  episode, and an automatic all-clear the moment a message relays normally.

- **Protocol-health boot banner: detect the workshop running without the
  protocol.** Musubi guarded oversized docs (orch-2) and capsules going
  stale *within* a session, but the outer failure was silent: days of code
  commits landing from bare agent sessions while capsules/comms never move,
  so the next supervised session warm-starts from a contradiction soup and
  the operator blames the agents. Two warn-only pre-flight checks now run at
  launch: (1) **detachment** — newest project commit vs the newest sign of
  life (commit or mtime) across capsule/todo/handoff/comms; a gap over
  `[orchestrator].detachment_threshold_days` (default 2) emits a loud
  `⚠ PROTOCOL HEALTH` banner with the commit count and reconciliation
  warning; (2) **runbook version drift** — the project runbook's
  `**Version:**` header vs the copy this checkout ships; an out-of-date fork
  gets one line saying exactly that ("run bootstrap.sh — your fork is backed
  up"). The combined note is also handed to Oya at spawn, since a
  days-stale picture is precisely her altitude. Honest limit: the check
  fires at the *next* launch — bare sessions are invisible while they
  happen.

- **Oya north-star docs are now a first-class, documented prerequisite.** Oya's
  first duty is custody of the vision, and she can't guard a vision she can't
  see — but the setup path never said so. Three additions close that gap:
  (1) starter stubs `templates/VISION.md`, `templates/ROADMAP.md`,
  `templates/ARCHITECTURE.md`, each shaped so Oya can read it as a north-star
  (copy into your project's `docs/` and fill in; project-owned, never
  refreshed); (2) a new README section **"Prerequisite: give Oya a north-star"**
  listing the recognised filenames, the `context_docs` knob for non-standard
  names, and the copy command; (3) `scripts/doctor.sh` now WARNs, when the Oya
  layer is enabled, if the project has no vision/architecture/roadmap docs (or a
  `context_docs` path is missing) — so you catch it before launch rather than on
  Oya's turn one. The check is silent when Oya is disabled, and never FAILs (she
  degrades gracefully by asking on turn one). Tied to Oya enablement only —
  pair-only projects are unaffected; base `bootstrap.sh` is unchanged.

### Security

- **Permission auto-approver hardened (opt-in feature; default off).** Two holes
  closed in the optional `[agents.oyakata.permissions]` PreToolUse hook
  (`scripts/oya-pretooluse.py`): (1) a newline-injection bypass — an allow-listed
  first line (`git status\n…`) could smuggle an arbitrary second command past the
  start-anchored allowlist; newlines are now treated as command separators and
  defer; (2) the tier-1 allowlist no longer auto-approves file-content or
  environment readers (`cat`/`head`/`tail`/`printenv`/`env`), which could
  silently disclose secrets (`cat ~/.ssh/id_rsa`, `printenv` → API keys). Normal
  file reads route through the path-scoped `Read` tool. `scripts/attach-oya.sh`
  no longer writes unscoped `Bash(cat|head|tail|grep|rg:*)` grants for the Oya
  pane for the same reason. The permission hook remains **opt-in** — both
  `[agents.oyakata].enabled` and `[agents.oyakata.permissions].enabled` default
  to `false`; the adopting operator must explicitly enable it. 10 new regression
  tests; suite now 400+ passing.

### Changed

- **Oya runs on Opus, not Sonnet.** The optional supervisor pane
  (`scripts/attach-oya.sh`) now launches `claude --model opus` (the alias for the
  latest Opus). The supervisor role is judgement-heavy — vision/architecture
  custody and engineering-discipline refereeing — so it runs on the strongest
  reasoning rather than the cheapest model. Note: an always-on Opus observer
  costs more per cycle than Sonnet did.

### Fixed

- **`launch_musubi.sh` arg parsing under zsh (regression).** The macOS/iTerm
  launcher has a `#!/bin/zsh` shebang but read positionals with bash-style
  0-based indexing (`${POSITIONAL[0]}` / `[1]`). zsh arrays are 1-based, so
  `[0]` was empty — `CONFIG` silently fell back to the default `musubi.toml`
  (loading the *wrong* project) and the real config path landed in `SESSION`,
  where tmux rejected it (`BadSessionName: contains periods`). Now reads via
  `set -- "${POSITIONAL[@]}"` and `$1`/`$2`, which are 1-based and identical
  across zsh and bash. The bash launcher (`launch_musubi_tmux.sh`) was already
  correct and is unchanged. Introduced when the earlier index fix (correct for
  the bash launcher) was applied to the zsh launcher too.
- **Mouse-scroll no longer traps a pane in a scroll lock.** Builds on the
  `escape-time` fix below. New `scripts/tmux-copymode.conf` (sourced by the
  orchestrator right after `set -g mouse on`) does two things: (1) routes the
  wheel to tmux's own copy-mode and never forwards it to the agent CLI, so an
  agent's full-width scrollback pager (the `(jump to forward)` bar that appears
  when an agent has mouse reporting on) can no longer be triggered by scrolling;
  (2) makes a left-click / `Enter` / `q` cancel copy-mode on the first try and
  focus the clicked pane, defeating the trackpad-momentum re-entry that made you
  mash keys to escape.
- **`launch_musubi.sh` honours its config-path + session-name arguments.** The
  positional parse read array indices `[1]`/`[2]` instead of `[0]`/`[1]`, so
  `./launch_musubi.sh /path/to/musubi.toml <session>` silently loaded the default
  `musubi.toml` and ignored the path — breaking multi-project / multi-session use.
  The no-argument default flow was unaffected (which is why it went unnoticed).
  Now matches `launch_musubi_tmux.sh`, which was already correct.
- **tmux copy-mode no longer feels frozen.** The session now sets
  `escape-time 10` (down from tmux's 500ms default). Mouse-scroll drops a pane
  into copy-mode (the yellow status bar); the long default escape delay made the
  Escape that exits it feel dead, so you'd mash it while another pane printed
  live. Copy-mode now exits on the first Escape. (Scroll-to-bottom already
  auto-exits via tmux's default `copy-mode -e` wheel binding.)
- **`bootstrap.sh --force` no longer clobbers a fork.** Re-syncing a forked
  managed doc now backs the fork up to `<name>.fork-backup-<timestamp>` *before*
  it is replaced (via `cp -L`, so the backup captures real content even when the
  doc is a symlink), and a symlinked doc is swapped for a real file rather than
  written through the link. Makes fork re-sync a safe, built-in operation — the
  old version is always recoverable on disk. The skip-message and `--force`
  banner now state the backup behaviour.

### Changed

- **Runbook v1.10 — review-discipline hardening merged up from a downstream deployment**
  (the Codebase B fork's `ia-peer-suspicion` cycle). Generic versions of five
  additions, all targeting the asymmetric-deference failure mode: **Verification-anchored
  verdicts** (`Accepted-baseline` + `Confidence-backed-by` — a confidence verdict needs a
  concrete artifact citation, not just the word), **Baseline-evidence** + **Visual-proof**
  slice-acceptance fields, a **Locked decisions this session** capsule table, and a
  **Peer-review escapes** handoff block (the review's own miss-rate, with rolling-window
  escalation). Project-specific enforcement stays in each project's CLAUDE.md + scripts.
  A nice validation of the framework's evolution model: a deployment's scar tissue
  sharpened the parent.

## [0.2.0] – 2026-05-30

The stabilisation line. Lifts the protocol-lightening moratorium on
reconstructed empirical evidence, ships the adaptive-ceremony gear system,
hardens the orchestrator, and closes the test-coverage gaps. Validated by a
live Codebase A road-test (GATE-TEST-PARITY-001) — the mechanical lane classifier
overrode an under-classification (89-LOC change planned lightweight → forced
heavy/full-review), the Receipt class was adopted, and Oya closed the cycle
and caught a real capsule-before-comms silent miss.

### Added

- **`scripts/ledger-from-comms.py`** — mechanical rules-ledger fire counting.
  Reconstructs each rule's `fires` counters by scanning comms archives for its
  `citation_pattern`, attributed by cycle. Audit-first (default report; `--apply`
  writes back preserving every non-fires byte; `--check` is a CI currency gate).
  Removes the human dependency (manual Oya cycle-close) that left the ledger
  at backfill-zero.
- **Protocol-1 gear system (runbook v1.8):**
  - **Tiny lane** — a third lane below lightweight for docs/comments/dep-bumps
    (≤20 LOC, ≤2 files, no state/schema/UI/CI): one-line claim, no review/capsule.
  - **`scripts/classify-slice.sh`** — mechanical tiny/lightweight/heavy lane
    classifier reading staged files + LOC against fixed trigger patterns. Output
    pasted verbatim into the acceptance receipt; @LEAD promotes, agents never
    silently demote.
  - **Receipt message-class** — a one-line state-transition confirmation
    replacing a full Update on the tiny/lightweight lanes.
  - **Managed-doc rotation policy** (`docs-1`), paired with the orch-2 boot guard.
- **Discipline auto-fire (A1)** — the orchestrator runs the discipline scope
  sensor on a slice claim over the receipt's declared file targets and relays
  triggered disciplines to Oya. Forgiving authority; informs, never blocks.
- **Cycle-close ledger wiring** — `ledger-from-comms.py` is now the cycle-close
  fire counter: `--apply` MERGES a cycle's fires into existing history (prior
  cycles preserved, idempotent) and stamps `last_updated_at`/`last_updated_cycle`.
  The Oya prompt runs it for fires + metadata and authors only the judgment
  counters (catches / bypasses / silent_misses / skips) + `notable_signals`.
- **`bootstrap.sh --check`** — verify install currency without writing; exits
  non-zero on any missing/stale file, dir, managed doc, injected block, or
  `.gitignore` entry. Usable as a CI gate.
- **Real-tmux integration test** — exercises the actual send-keys/capture-pane
  path against a live tmux server (CI installs tmux). Plus full `bootstrap.sh`
  coverage via pytest-subprocess.

### Changed

- **Orchestrator startup banner** prints git HEAD, `musubi.toml` mtime, agents,
  and recognised handles; a mid-session staleness check warns once if the
  running code drifts from disk (orch-3).
- **Managed-doc size guard on boot** — warns >40k chars; above the 100k ceiling
  it **offers to rotate the doc in place** (`Rotate now? [y/N]` → archives the
  full doc and trims to the two most-recent cycle sections, then continues),
  falling back to a hard refuse only when declined or non-interactive (orch-2).
- **`bootstrap.sh` installs `scripts/classify-slice.sh`** into target projects —
  the runbook's lane-choice step depends on it.
- Capsule template deliberately **not** compressed: the reconstructed fire data
  showed the capsule disciplines are load-bearing.

### Fixed

- **orch-1** — `resolve_archive_dir` no longer resolves to the read-only `/archive`
  root for legacy `/tmp` comms paths; falls back to a project-local archive dir,
  with a writability pre-check that fails fast with an actionable error.
- **orch-3** — unrecognised-handle comms discards now name the specific bracketed
  handle (e.g. `@OYA`) and say "restart to load it" instead of a generic
  unparseable-bytes message.
- **`inject_block` marker matching** — anchored the musubi markers to their own
  line. The previous `str.find()` matched the markers mentioned in prose in the
  CLAUDE.md/AGENTS.md header templates, so `--update` refreshed the wrong region
  and double-bootstrap mangled the header.
- Added a `# shellcheck shell=bash` directive to `cwd-preflight.sh` for newer
  shellcheck (SC2148).

## [0.1.0] – 2026-05-28

First tagged release. Covers the project from initial public-shape through the oyakata-2 PreToolUse hook system and Linux Oya support. Suitable for early adopters comfortable with reading the code; still pre-`v1.0` so the protocol may shift between minor versions if road-tests surface needed changes.

### Added

- **Orchestrator launcher hardening (`orch-6`):**
  - Cross-platform `scripts/cwd-preflight.sh` (sourced by both launchers) — verifies `pwd` is readable before any agent spawn; re-anchors cwd to the orchestrator dir; warns when the project path is under `~/Desktop` / `~/Documents` / `~/Downloads` (iCloud-synced macOS folders). Catches the EPERM uv_cwd crash class before it reaches the operator as a Node stack trace.
  - `validate_project_path()` Python preflight in `orchestrator.start_musubi` — raises `ConfigError` on missing / non-enterable `project.path`.
  - `detect_eperm_uvcwd()` + `emit_eperm_recovery()` translate the Node crash signature into operator-readable recovery instructions inside the boot-polling loop.
- **Smart existing-session handling (`orch-5`):** three-state classifier (`live` / `orphan` / `ambiguous`) decides whether to attach, recreate, or prompt when a tmux session with the target name already exists. `pane_in_shell()`, `classify_existing_session()`, `describe_session_panes()`.
- **PreToolUse hook system for Opus (`oyakata-2`, three slices):**
  - **Tier 1 — static allowlist** (`scripts/oya-pretooluse.py`): auto-approves `Read` / `Grep` / `Glob` / `NotebookRead` unconditionally and a narrow read-only Bash subset (`git status|log|diff|show|branch|rev-parse|config --get|...`, plus `pwd|ls|cat|head|tail|wc|file|stat|which|...`). Any shell metachar in the Bash command defers regardless of head-match. Closes the canonical Opus-halted-on-permission case (~80% of blocking prompts are reads).
  - **Tier 2 — Oya-as-decider:** routes `Edit` / `Write` / `NotebookEdit` calls on files-in-git-status to Oya via a filesystem round-trip (hook writes request JSON, Oya writes verdict JSON, hook honours with 20s timeout). Graceful degrade on no-orchestrator / no-Oya / hung / malformed → defer.
  - **Auto-wiring:** orchestrator idempotently registers the hook in `<project>/.claude/settings.local.json` when `[agents.oyakata.permissions].enabled = true` in `musubi.toml`. Updates path on musubi-clone moves; preserves unrelated entries; refuses to overwrite malformed JSON.
  - Decision audit trail at `docs/agents/oyakata-decisions.md` (per-cycle, gitignored).
- **Optional third agent — Oyakata (`@OYA`)** (`scripts/attach-oya.sh`, `orchestrator.py`):
  - Active-mode supervisor (v0.1) — relays every comms message + capsule edit to a third tmux pane, builds context across events, intervenes via `@OYA` comms posts when judgement-shaped patterns warrant it (rubber-stamp reviews, lane drift, planning-doc claim drift, capsule timestamp drift). Pair treats `@OYA` messages as `@LEAD`-equivalent for direction; does NOT waive STOP rules (only `@LEAD` does — see `@OYA` pre-ack discipline in the prompt).
  - **Auto-spawn from orchestrator** when `[agents.oyakata].enabled = true` in `musubi.toml`. No flags or extra launchers needed. `scripts/attach-oya.sh` splits the third pane, pre-approves Oya's startup tools via a scoped `.claude/settings.local.json`, auto-pastes the v0.1 prompt with `<PROJECT_PATH>` / `<MUSUBI_ROOT>` placeholders substituted, and submits.
  - Idempotent pane discovery via `pane_current_path` (not `pane_title` — Claude Code's TUI overwrites titles); duplicate spawns are prevented.
  - **Cross-platform clipboard fallback** — probes `pbcopy` / `wl-copy` / `xclip` / `xsel` / `clip.exe` in preference order; soft-fails when none present. Unblocks Linux / WSL Oya.
  - Per-agent capabilities documented in `docs/operator/oyakata-prompt-v0.1.md`. Pair-side rules (`@OYA` weight, no relay-back, gate-waiver discipline) live in the project's `CLAUDE.md` / `CODEX.md` Oyakata block.
- **Structured `[HH:MM:SS] [COMPONENT]` log format** across orchestrator boot + watcher. Components: `BOOT`, `RELAY`, `BRIEF`, `OYA`, `ATTACH`, `WATCHER`, `PERMS`, `TIER2`.
- **Auto-advance boot gates** (`wait_for_or_skip`): the five `Press Enter` prompts in `start_musubi` and `relay_test` now poll for the actual condition (tmux client attached, both CLIs ready, `RELAY TEST SUCCESSFUL` × 2, `Startup complete. Ready.` × 2) with a hard timeout per gate. Enter still works as an override.
- **Orchestrator anti-pattern guards** (`watch_and_relay`):
  - **Ack-of-ack guard**: refuses to relay a third consecutive idle-state message and nudges the writer to claim a slice or name a real blocker. Closes the recurring "two agents acknowledging each other's idleness" loop pattern surfaced by the 8-week production review.
  - **Capsule-staleness guard**: refuses to relay `Review Request` / `Decision` / `Blocker` messages when `docs/agents/current-state.md` hasn't been touched in `CAPSULE_FRESHNESS_WINDOW_SECONDS` (default 120s). Enforces the capsule-before-comms invariant mechanically.
  - Both guards expose new helper functions: `parse_result_field`, `is_idle_result`, `message_type`, `is_state_affecting`, `capsule_path`, `capsule_is_stale`. New optional `comms.capsule` config key.
- **Runbook v1.7** (`docs/agents/AGENT_COLLAB_RUNBOOK.md`):
  - **Slice Lanes** subsection: lightweight lane skips mandatory review + GO baton + capsule discipline for doc-only / single-file ≤20 LOC non-runtime / dep-bump / copy-edit work. Heavy lane keeps full protocol.
  - **"Findings I went looking for" block** (Review Pattern): every Review Result MUST list ≥3 specific defect classes the reviewer probed for with `found / not found / N/A and why` per line. Addresses the asymmetric-deference pattern.
  - **Spot-check on rubber-stamps**: third-party 5-minute spot-check when a review approves a slice with zero findings on >50 LOC or >3 files.
- `docs/positioning/reviews/external-review-2026-06-cross-codebase.md`: synthesis of three independent LLM reviews (Gemini, Codex, Opus) of an 8-week production corpus. Captures convergent findings, divergent findings (the asymmetric-deference pattern only the third-party read surfaced), quantitative baseline.
- `docs/positioning/essays/asymmetric-deference.md`: follow-up essay drilling into the divergent finding — what only one of three reviewers caught, the structural explanation, the protocol change it triggered.
- `docs/examples/sample-cycle.md`: illustrative redacted slice-cycle showing the actual message protocol in action.
- Cross-platform `launch_musubi_tmux.sh` for Linux / WSL / macOS without iTerm2.
- `validate_config(cfg)` — walks `musubi.toml` against a required-shape map; raises `ConfigError` with the dotted path of the first missing key, wrong type, or empty string.
- `validate_cli_available(cli)` — fails fast if the agent CLI isn't on PATH.
- Session-collision prompt: `start_musubi` requires explicit y/yes before wiping an existing tmux session with the same name.
- Main-loop crash guard: transient errors in the watcher are logged and the loop continues after a 10s pause; `KeyboardInterrupt` propagates cleanly to `__main__`.
- Optional `comms.send_pause_seconds` knob for high-latency tmux setups.
- `resolve_archive_dir(cfg)` helper — single source of truth for the archived-comms path.
- **320 passing tests** across `test_parsing` (48), `test_relay` (27), `test_classify_session` (23), `test_classify_slice_disciplines` (23), `test_upgrade_project` (14), `test_oya_pretooluse` (20 functions / 94 parameterised cases), `test_auto_wire_pretooluse` (18), `test_tier2_pretooluse` (16), `test_cwd_preflight` (16).
- GitHub Actions CI matrix on Python 3.11 / 3.12 / 3.13 (py_compile, bash syntax, shellcheck, pytest).
- `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`.
- `.editorconfig`, PR template, bug + proposal issue templates.

### Changed

- **`launch_musubi.sh` process model:** orchestrator now runs in the **current terminal**. Only ONE iTerm window is spawned — for `tmux attach`. Replaces the old `osascript`-launched orchestrator window which sometimes auto-closed and hid the log stream.
- **`--with-oya` flag is deprecated** on both launchers. Oya is now controlled by `[agents.oyakata].enabled` in `musubi.toml` (single source of truth).
- Repo layout: managed protocol docs moved to `docs/agents/`; positioning PDFs under `docs/positioning/`. Bootstrap source and target paths are now symmetric.
- `DEV_STRATEGY.md` moved from `docs/agents/` to `docs/operator/`. Stopped auto-importing it into agent context — it's operator-facing.
- `CLAUDE.md.template` and `AGENTS.md.template` collapsed to header-only; `bootstrap.sh::inject_block` concatenates the canonical `musubi-block-*.md` content at install time. Fresh-install and upgrade-install now produce the same block.
- README + comparison framing: dropped "only published instance" / "~2 months on a multi-tenant production codebase" claims; softened to "extended daily use on a real production codebase".
- `PRETOOLUSE_HOOK_TIMEOUT` raised 5s → 30s so the tier-2 poll budget (20s) fits inside CC's per-hook deadline.
- `requirements.txt` pins `libtmux>=0.55,<0.56`.
- `read_new_content` opens with `encoding='utf-8'`, `errors='replace'` — non-UTF-8 bytes no longer crash the watcher.
- `__main__` catches `ConfigError`, `FileNotFoundError`, and `KeyboardInterrupt` with clean messages and conventional exit codes (2, 130).

### Removed

- Unimplemented `state_file` references from `musubi.toml.example`, README, and `.gitignore`.
- Dead `run()` helper in `bootstrap.sh`.
- All `CODEX.md` references in `templates/IaA.md` — `AGENTS.md` is canonical for Codex.
- Redundant `chmod +x launch_musubi.sh` step in README.

### Internal

- `.claude/`, `.codex/`, `.agents/`, `.planning/`, `docs/operator/internal/` added to `.gitignore`. Author working notes / per-machine state stays local.

[Unreleased]: https://github.com/f0zzy2727/musubi/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/f0zzy2727/musubi/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/f0zzy2727/musubi/releases/tag/v0.1.0
