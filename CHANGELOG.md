# Changelog

All notable changes to musubi-the-orchestrator are documented here. The runbook (`docs/agents/AGENT_COLLAB_RUNBOOK.md`) maintains its own version + changelog for protocol-level changes.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Calendar-shaped versioning — `v0.1.0` is the first tagged release; semver discipline firms up from `v1.0.0` onward.

## [Unreleased]

### Added

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
- `docs/positioning/external-review.md`: synthesis of three independent LLM reviews (Gemini, Codex, Opus) of an 8-week production corpus. Captures convergent findings, divergent findings (the asymmetric-deference pattern only the third-party read surfaced), quantitative baseline.
- `docs/positioning/asymmetric-deference.md`: follow-up essay drilling into the divergent finding — what only one of three reviewers caught, the structural explanation, the protocol change it triggered.
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
