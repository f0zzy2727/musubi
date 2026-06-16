# oyakata-2 — Opus permission auto-approval (tiers 1 + 2)

The `oyakata-2` work addresses the canonical Opus-halted-on-permission failure mode: Opus blocked on a Claude Code permission prompt for ~2 hours mid-cycle while the operator was reachable but not at the keyboard. Closing that gap was the highest-leverage Oya feature after the v0.1 advisory mode shipped.

Two tiers ship today:

- **Tier 1** — static read-only allowlist. Hook auto-approves Read/Grep/Glob/NotebookRead and a narrow safe-Bash set without consulting anyone. Documented in this file.
- **Tier 2** — Oya-as-decider. When the hook sees an Edit/Write/NotebookEdit on a file already in `git status`, it routes the call to Oya via the filesystem and honours her verdict (allow/defer) within a hard timeout. Documented in the "Tier 2" section below.

## What this slice ships

A Claude Code `PreToolUse` hook (`scripts/oya-pretooluse.py`) that auto-approves a narrow, fixed set of read-only operations on Opus's pane. Everything else falls through to Claude Code's normal permission flow — the operator still decides on any state-changing action.

**Tier-1 allowlist (disclosure-aware since sec-1, 2026-06-16):**
- Tools that are read-only by construction: `Read`, `Grep`, `Glob`, `NotebookRead`.
- **Metadata-only Bash** (auto-approved): `git status`/`branch`/`rev-parse`/`ls-files`/`ls-tree`, `git log --oneline` (summary form only), plus `pwd`/`whoami`/`date`/`ls`/`wc`/`file`/`stat`/`which`/`command -v`/`type`. These reveal status/refs/names/stats — never file content.
- **Content/config-disclosing Bash** (defer by default; opt-in via `[security].repo_has_no_secrets`): `git show`/`diff`/`log` (general)/`blame`, `git config --get`/`--list`, `git remote -v`. Rationale: "non-mutating" is not "safe to disclose" — `git show HEAD:.env` prints a tracked secret exactly as `cat .env` would.
- **Never auto-approved at all:** `cat`/`head`/`tail` (arbitrary file contents), `printenv`/`env` (environment incl. API keys), `echo` (removed — cleanest env-expansion vector).
- Bash commands containing **any** shell metacharacter **or `$` expansion** (`|`, `>`, `<`, `;`, `&`, `$`, `$(`, backtick, newline) defer regardless of the command head. `$` is fenced so `echo $TOKEN` / `ls $HOME` never auto-approve. Conservative: `git log --grep="foo|bar"` will not auto-approve. The cost is one extra permission prompt; the safety margin is large.

**Out of scope (deferred to v0.2.x+):**
- Oya-as-decider (hook consults Oya's pane for judgement using slice context).
- The full 4-tier ladder (in-context writes, escalation, blocklist).
- Codex/Coda parity (the Codex hook protocol is different — separate slice).
- The hardcoded allowlist (script-internal) stays the source of truth. The toml toggles auto-wiring on/off and (since sec-1) the disclose-tier opt-in `[security].repo_has_no_secrets`; there's still no per-command `allow_extra` / `deny_extra`. Note: the disclose opt-in currently reads the `MUSUBI_REPO_HAS_NO_SECRETS` env var — the orchestrator auto-export from the toml block is the remaining sec-1 slice (until then, export it in your shell before launch).

The deferred-work backlog is tracked in the author's working notes (not in this repo).

## How to wire it (recommended: auto-wiring via the orchestrator)

Add this to your `musubi.toml`:

```toml
[agents.oyakata.permissions]
enabled = true
```

On every launch, the orchestrator idempotently registers the PreToolUse hook in `<project_path>/.claude/settings.local.json`:
- First run: creates the file (and the `.claude/` dir if missing) with a single PreToolUse entry pointing at this musubi clone's `scripts/oya-pretooluse.py`.
- Subsequent runs with the same musubi clone path: no-op.
- Subsequent runs after you moved your musubi checkout: updates the command path in place — your existing settings.local.json contents are preserved.
- Existing `settings.local.json` with unrelated entries: the musubi entry is appended; nothing else is touched.
- Malformed JSON in the existing file: orchestrator logs a warning and skips — never overwrites a file it can't safely parse.

The orchestrator only touches `.claude/settings.local.json` (gitignored convention). It never writes to `.claude/settings.json` (committed config).

You'll see one of these lines in the orchestrator boot stream:
- `[PERMS] created <path> with musubi PreToolUse hook entry`
- `[PERMS] added musubi PreToolUse hook entry to existing <path>`
- `[PERMS] updated musubi PreToolUse hook in <path> (command path changed)`
- (no PERMS line) — entry already correct, no-op.

## How to wire it (manual fallback)

The hook script lives in this repo at `scripts/oya-pretooluse.py`. Claude Code reads its hook config from the project's `.claude/settings.local.json` (which is per-user / per-machine — it shouldn't be committed). Add this entry:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Glob|NotebookRead|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/musubi.repo/scripts/oya-pretooluse.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Substitute the absolute path to your musubi checkout. The hook does not honour `$PWD`-relative paths — Claude Code spawns it from your project root, not from musubi.

**Note:** if you already have `PreToolUse` hooks in your `settings.local.json`, append a new entry to the existing `PreToolUse` array; don't replace it.

Manual wiring is useful when:
- You haven't (or can't) opt into the auto-wirer.
- You want to use a different matcher (e.g. exclude `Bash` if you'd rather always be prompted).
- You're debugging the hook in isolation and want to control exactly which entry CC sees.

If auto-wiring is enabled AND you've manually wired the hook, the orchestrator detects your existing entry (by `oya-pretooluse.py` substring match) and updates the path in place rather than appending a duplicate.

## What it does at runtime

When Claude Code is about to run an in-scope tool call (matched by the `matcher` regex above), it pipes a JSON description of the call to the hook on stdin. The hook:

1. Classifies the call against the tier-1 allowlist.
2. If matched → returns `{"hookSpecificOutput":{"permissionDecision":"allow","permissionDecisionReason":"oyakata-2 tier-1 allowlist: ..."}}` on stdout. Claude Code skips the permission prompt and runs the tool.
3. If not matched → exits 0 with no stdout. Claude Code applies its normal permission flow (settings-level allowlist or operator prompt).

Either way, the hook appends a one-line audit entry to `docs/agents/oyakata-decisions.md` (relative to the project root, where the hook's cwd is set by Claude Code). Decisions are formatted as `<ISO timestamp> <ALLOW|DEFER> <tool> :: <reason> :: <command-or-input>`.

**The log is per-cycle audit data — not source. Add it to your project's `.gitignore`:**

```
# oyakata-2 PreToolUse decision audit trail
docs/agents/oyakata-decisions.md
```

Musubi's own `.gitignore` already has this entry — adopt the same pattern in your project.

## Failure modes the hook protects against

- **Hook crashes or times out** → Claude Code falls back to the normal permission prompt. The operator is never worse off than they would be without the hook.
- **Malformed stdin JSON** → hook exits 0 with no decision; normal prompt applies.
- **Log file write fails** (read-only volume, permissions, etc.) → exception is swallowed; the decision still flows through.
- **Hook script missing or non-executable** → Claude Code surfaces a hook-config error; the normal permission flow applies until you fix it.

## Verifying it works

After wiring, on your next Opus session, ask Opus to run something read-only like `git status`. You should NOT see a permission prompt. Then check `docs/agents/oyakata-decisions.md` — you should see an `ALLOW Bash` line for that call.

If you don't see a log entry, the hook didn't fire. Common causes:
1. `command` path in `settings.local.json` is wrong (must be absolute).
2. Script isn't executable (`chmod +x scripts/oya-pretooluse.py`).
3. `PreToolUse` matcher doesn't include the tool you're testing (e.g. you wired `Bash` only and tried `Read`).
4. Claude Code is running with hooks disabled (`--no-hooks` flag, or operator-disabled).

## Tier 2 — Oya-as-decider

Tier 2 routes calls the hook can't decide mechanically through Oya for a judgement verdict. Currently scoped to `Edit`, `Write`, and `NotebookEdit` calls where `tool_input.file_path` is already in `git status` (modified or untracked) — "the file is in motion this cycle." That covers the common in-slice editing case without granting Oya open-ended approval authority.

### When it triggers

The hook reaches the tier-2 path only when:

1. Tool name is `Edit` / `Write` / `NotebookEdit`.
2. `tool_input.file_path` resolves to a real path.
3. That path appears in `git status --porcelain` output (M or ?? line).

Otherwise the call falls through to defer (operator prompt) without involving Oya. Bash writes, network calls, and edits to files outside `git status` all stay in the defer path.

### The protocol

When tier-2 triggers, the hook:

1. Writes a request JSON to `docs/agents/oyakata-pending/<uuid>.request.json` (atomic tmp+rename).
2. Polls `docs/agents/oyakata-pending/<uuid>.verdict.json` every 0.5s.
3. Waits up to **20 seconds** for the verdict file to appear.
4. On `{"verdict": "allow", ...}` → auto-approves with the operator-facing reason set to Oya's explanation.
5. On `{"verdict": "defer", ...}` OR on timeout → falls through to operator prompt.
6. Deletes both files (request + verdict).

The orchestrator's main watcher loop scans `docs/agents/oyakata-pending/` every 3 seconds. New requests get relayed to the Oya pane via `tmux send-keys`. Oya reads the request JSON, decides, writes the verdict.

### Request schema (the hook writes this, Oya reads it)

```json
{
  "request_id": "uuid-hex",
  "timestamp": "ISO-UTC",
  "tool_name": "Edit",
  "tool_input": { "file_path": "...", "old_string": "...", "new_string": "..." },
  "tier_2_signal": "file in `git status` (in-scope for current cycle)",
  "cwd": "/absolute/path/to/project"
}
```

### Verdict schema (Oya writes this, the hook reads it)

```json
{ "verdict": "allow", "reason": "Edit on test file for the declared slice" }
```

or

```json
{ "verdict": "defer", "reason": "file_path is outside the slice surface in current-state.md" }
```

`reason` is required. It surfaces in the operator-facing `permissionDecisionReason` on auto-approve, and in the audit log on either path.

### Timeout and graceful degrade

The hook caps every tier-2 call at `TIER2_VERDICT_TIMEOUT_S = 20s`. If no verdict file appears, the hook defers (operator gets the normal prompt). This means the layer fails-safe in three scenarios:

- **No orchestrator running** — watcher isn't relaying to Oya; verdict never appears; hook defers.
- **Oya pane absent or hung** — same outcome; hook defers.
- **Oya writes after the deadline** — late verdicts are ignored. The operator has already seen the prompt and decided.

Operator-facing latency: tier-2 candidates take up to 20s. In practice Oya should respond within ~5–10s (her prompt explicitly instructs fast cadence + conservative defer-by-default). If she's slow, tighten the timeout in `oyakata.py:TIER2_VERDICT_TIMEOUT_S`.

### Audit trail

Every tier-2 outcome is logged to `docs/agents/oyakata-decisions.md` with Oya's verdict reason verbatim:

```
2026-05-28T11:42:13Z ALLOW Edit :: tier-2 Oya verdict — file is in declared slice surface :: /path/to/file.py
2026-05-28T11:42:55Z DEFER Edit :: tier-2 Oya verdict — out of slice scope :: /path/to/other.py
2026-05-28T11:43:21Z DEFER Edit :: tier-2 Oya did not respond within 20s :: /path/to/third.py
```

Request and verdict JSON files are deleted after consumption — they're transient. The audit log is the durable record.

### What it doesn't do (yet)

- **Comms escalation** when Oya defers — the operator just sees a normal prompt, not a `@MICHI: Oya deferred on X` message. Queued as a follow-up sub-slice in IA-QUEUE.
- **Tier-3 or higher** rungs (writes outside `git status`, Bash writes, new dependencies). Out of scope for this slice.
- **Codex parity** — only Opus's Claude Code instance has this hook. Codex's hook protocol is different; separate slice.

## Codex / Coda parity

Codex CLI's hook system is different from Claude Code's. The Codex pane on `@CODA` doesn't run this hook. For now, that asymmetry is accepted — the 2-hour spike halt was on the Opus pane, and Opus's blockage rate is materially higher than Codex's in the codebase as currently exercised. Codex parity is queued under `oyakata-2` deferred-work in `IA-QUEUE.md`.
