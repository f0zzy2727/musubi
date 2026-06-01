"""Oyakata (Oya) — optional third-agent supervisor layer.

When `[agents.oyakata].enabled = true`, the watcher relays each parsed comms
message + capsule edits to a third tmux pane running an observer claude
session. The Oya pane is discovered by `pane_current_path` (cwd-based) at
runtime — it doesn't have to exist at orchestrator startup; the attach
helper (scripts/attach-oya.sh, invoked via the orchestrator's
spawn_oya_if_enabled) adds it post-launch.

Imports `_log` and `send_message` from orchestrator lazily to avoid a
module-level circular import. The lazy-import trick is well-supported in
CPython; the cost is one extra dict lookup per call, which is irrelevant
on the 3-second watcher tick.
"""

import json
import os
import re
import subprocess
import sys
import time


def oyakata_enabled(cfg):
    return bool(cfg.get("agents", {}).get("oyakata", {}).get("enabled", False))


def oyakata_permissions_enabled(cfg):
    """True when the operator opted into the oyakata-2 PreToolUse hook layer.

    Reads `[agents.oyakata.permissions].enabled`. Default is False — operators
    must explicitly opt into the permission-modifying hook because it changes
    the agent's authority surface (auto-approves a tier-1 read-only allowlist
    without prompting). Backwards compatible with configs that pre-date the
    block.
    """
    return bool(
        cfg.get("agents", {})
           .get("oyakata", {})
           .get("permissions", {})
           .get("enabled", False)
    )


# Path-substring marker used to identify musubi-managed PreToolUse entries
# in the project's `.claude/settings.local.json`. The auto-wirer locates
# entries to update vs append by looking for this token in the nested
# hook command path. Stable across musubi clone locations — only the
# script basename matters, not the absolute path the operator's setup
# happens to land it at.
PRETOOLUSE_HOOK_MARKER = "oya-pretooluse.py"

# Matcher value for the auto-wired hook entry. Mirrors the tool set the
# hook script actually classifies — keep these in sync if the allowlist
# grows. The matcher being a superset of what the script handles is fine
# (the script defers on unhandled tools); a subset would silently miss
# tools the script could allow.
PRETOOLUSE_HOOK_MATCHER = "Read|Grep|Glob|NotebookRead|Bash"

# Per-call hook timeout (seconds). Generous enough for the hook to read
# stdin + classify + write a one-line log entry; tight enough that a
# misbehaving hook can't stall the tool flow indefinitely. The hook's
# own error paths exit fast (0 with no output) so reaching this timeout
# means something is genuinely wrong.
#
# NOTE: this is the *Claude Code-side* timeout — the wall-clock budget CC
# gives the hook process to return. It must be larger than the tier-2
# verdict poll budget (TIER2_VERDICT_TIMEOUT_S) so the hook can do its
# full round-trip with Oya without CC killing it mid-poll.
PRETOOLUSE_HOOK_TIMEOUT = 30


# --- oyakata-2 slice 3: tier-2 (Oya-as-decider) -----------------------------
# Tier-2 is the rung above the static read-only allowlist: tool calls that
# COULD be safe in context (e.g. an Edit to a file already in `git status`),
# but require judgement the hook can't apply mechanically. The hook routes
# these to Oya via the filesystem: writes a request, polls for a verdict,
# returns the verdict to Claude Code. Graceful degrade — if no orchestrator
# or no Oya, the poll times out and the hook defers to the operator prompt.

# Directory (relative to the project root, i.e. the hook's cwd at runtime)
# where the hook writes request JSON and Oya writes verdict JSON. Sibling
# of the audit log. Both files for a single decision live here until the
# hook consumes the verdict, then both are deleted (the audit log keeps
# the durable record).
TIER2_PENDING_DIR = os.path.join("docs", "agents", "oyakata-pending")

# Wall-clock budget for the hook to wait for Oya's verdict. Oya is a
# Claude Code instance with multi-second reasoning latency; the
# orchestrator watcher's relay loop is on a 3s tick; allow Oya at least
# one full think cycle. Operator sees this as latency on tier-2 tool
# calls, so don't bloat — defer-on-timeout is a safe fallback.
TIER2_VERDICT_TIMEOUT_S = 20

# How often the hook re-checks for the verdict file. Tight enough to feel
# responsive (verdict files are short JSON; existence checks are cheap),
# loose enough not to spin the CPU during the wait.
TIER2_VERDICT_POLL_INTERVAL_S = 0.5


def tier2_pending_dir(project_path):
    """Absolute path to the tier-2 pending-decisions directory for the
    project. Created lazily (by the hook on first write, or by the watcher
    on first scan) — not at orchestrator boot, because the directory only
    matters when the permissions layer is enabled."""
    return os.path.join(project_path, TIER2_PENDING_DIR)


def tier2_request_filename(request_id):
    """Just the basename — caller joins it with the pending dir. Suffixed
    `.request.json` so glob patterns can distinguish requests from
    verdicts written by Oya into the same directory."""
    return f"{request_id}.request.json"


def tier2_verdict_filename(request_id):
    """Verdict file basename for a given request_id."""
    return f"{request_id}.verdict.json"


def discover_oyakata_pane(session, cfg):
    """Find the Oya pane in this session. Returns the libtmux pane object or None.

    Identification is by pane_current_path FIRST (Oya's cwd is set to
    <musubi-root>/docs/operator by attach-oya.sh, while the pair panes
    live in the target project's path — so the path is a reliable
    discriminator). Pane title is a fallback only — Claude Code's TUI
    aggressively overwrites pane_title with response headlines, which made
    the old title-only check miss live Oya panes and caused the orchestrator
    to double-spawn."""
    if not oyakata_enabled(cfg):
        return None

    musubi_root = os.path.dirname(os.path.abspath(__file__))

    # Primary: match by pane_current_path. attach-oya.sh launches claude with
    # cwd = $MUSUBI_ROOT/docs/operator (deliberately not the project dir so
    # claude doesn't auto-load the project CLAUDE.md and adopt Opus identity).
    try:
        for pane in session.active_window.panes:
            out = pane.cmd("display-message", "-p", "#{pane_current_path}").stdout
            path = (out[0] if out else "") or ""
            if path.startswith(musubi_root):
                return pane
    except Exception:
        pass

    # Fallback: title-substring match. Works briefly after attach-oya.sh sets
    # the title and before the Claude TUI overwrites it. Kept for back-compat
    # with operators who pinned a non-default cwd or pane_title in musubi.toml.
    target = cfg["agents"]["oyakata"].get("pane_title", "OYAKATA")
    try:
        for pane in session.active_window.panes:
            out = pane.cmd("display-message", "-p", "#{pane_title}").stdout
            title = (out[0] if out else "") or ""
            if target in title:
                return pane
    except Exception:
        pass

    return None


def relay_to_oyakata(message_block, sender, p_oyakata, cfg):
    """Forward a parsed comms message to Oya's pane as an event notification.
    Oya keeps its own running context across these messages; whether to write
    an observation is its own judgement call.

    Loop guard: when sender is OYAKATA itself, do NOT relay — that would
    feed Oya's own messages back to her and create an infinite loop.
    """
    from orchestrator import send_message  # lazy import to avoid cycle
    if p_oyakata is None:
        return
    if sender.upper() == "OYAKATA":
        return  # loop guard — Oya's own messages must not be relayed back
    sender_key = sender.lower()
    from_handle = cfg["agents"].get(sender_key, {}).get("handle", f"@{sender.upper()}")
    notification = (
        f"@OYA event — comms relay from {from_handle}:\n\n"
        f"{message_block}\n\n"
        f"Build context across events; write an observation to your log only "
        f"if the runbook is being violated, drift is accumulating, or a "
        f"pattern across recent messages warrants it. Otherwise stay silent "
        f"and continue collecting. Heartbeat per the prompt."
    )
    send_message(p_oyakata, notification, cfg)


# Lines in a slice-claim/acceptance receipt that name the slice's file surface.
_FILE_TARGET_LINE_RE = re.compile(
    r"(?:first file target|second owned file(?: confirmed)?|owned file|files?)\s*[:=]\s*(?P<rest>.+)",
    re.IGNORECASE,
)
# A path-ish token: has a slash or a dotted extension.
_PATHISH_RE = re.compile(r"[\w./-]*\.[A-Za-z0-9]+|[\w-]+/[\w./-]+")


def extract_file_targets(message_block):
    """Pull declared file paths from a slice-claim / acceptance-receipt message
    ('First file target:', 'Second owned file:', 'Files:'). Returns a de-duped
    ordered list. Best-effort text scrape — the runbook's acceptance receipt
    format reliably carries 'First file target:' (used by the A1 discipline
    auto-fire wiring)."""
    paths = []
    for line in message_block.splitlines():
        m = _FILE_TARGET_LINE_RE.search(line)
        if not m:
            continue
        for tok in _PATHISH_RE.findall(m.group("rest")):
            tok = tok.strip().rstrip(".,;)")
            if tok and ("/" in tok or "." in tok) and tok not in paths:
                paths.append(tok)
    return paths


def run_discipline_sensor(file_paths, orchestrator_dir):
    """Run scripts/classify-slice-disciplines.py against file_paths and return
    its parsed JSON (or None on any failure — best-effort, never breaks relay).
    This is the A1 wiring: the scope sensor fires automatically on slice-claim
    instead of waiting for manual Oya invocation."""
    if not file_paths:
        return None
    script = os.path.join(orchestrator_dir, "scripts", "classify-slice-disciplines.py")
    if not os.path.isfile(script):
        return None
    try:
        out = subprocess.run(
            [sys.executable, script, "--format", "json", "--files", *file_paths],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def flag_disciplines_to_oyakata(message_block, p_oyakata, cfg, orchestrator_dir):
    """On a slice-claim, auto-run the discipline scope sensor over the claim's
    declared file targets and relay any triggered disciplines to Oya as an
    @OYA Recommendation. No-op when Oya is absent, no files are declared, or no
    disciplines fire. Forgiving authority — this informs Oya, never blocks the
    slice (A1 / oyakata-3 wiring)."""
    from orchestrator import send_message, _log  # lazy import to avoid cycle
    if p_oyakata is None:
        return
    files = extract_file_targets(message_block)
    result = run_discipline_sensor(files, orchestrator_dir)
    if not result:
        return
    triggers = result.get("triggers", [])
    if not triggers:
        return
    lines = "\n".join(
        f"  - {t['discipline']}: {t['summary']}" for t in triggers
    )
    _log("WATCHER", f"scope sensor fired {len(triggers)} discipline(s) on slice claim "
                    f"({', '.join(files)})")
    notification = (
        f"@OYA event — scope sensor fired on a slice claim.\n\n"
        f"Declared files: {', '.join(files)}\n"
        f"Triggered engineering disciplines:\n{lines}\n\n"
        f"Consider an @OYA Recommendation naming the discipline(s) the pair "
        f"should address before code begins. Forgiving authority — the pair "
        f"may acknowledge and skip; record the skip per the ledger."
    )
    send_message(p_oyakata, notification, cfg)


def notify_oyakata_capsule_edit(p_oyakata, cfg):
    """Tell Oya the current-state.md capsule mtime changed."""
    from orchestrator import send_message  # lazy import to avoid cycle
    if p_oyakata is None:
        return
    cap = cfg["comms"].get("capsule", "docs/agents/current-state.md")
    if not os.path.isabs(cap):
        cap = os.path.join(cfg["project"]["path"], cap)
    notification = (
        f"@OYA event — capsule edit at {cap}. Re-read it to update your "
        f"model of cycle state. No observation needed unless the new content "
        f"reveals drift or contradiction with recent comms."
    )
    send_message(p_oyakata, notification, cfg)


def scan_pending_tier2_requests(project_path, seen_ids):
    """Scan the pending-decisions directory for tier-2 request files Oya
    hasn't been notified about yet. Returns a list of (request_id,
    request_path, verdict_path) tuples for new requests. Updates
    `seen_ids` in place so the caller's set tracks what's already been
    relayed (avoiding duplicate notifications when the watcher loop
    revisits the directory before Oya consumes the request).

    Returns an empty list when:
      - The pending directory doesn't exist (first call before any tier-2
        candidate has fired).
      - The directory exists but contains no .request.json files.
      - The pending directory can't be read.

    Idempotent w.r.t. duplicate relays: the hook deletes both files after
    consuming the verdict, so a fresh request with the same UUID prefix
    cannot collide (uuid4).
    """
    pending_dir = os.path.join(project_path, TIER2_PENDING_DIR)
    if not os.path.isdir(pending_dir):
        return []
    try:
        entries = os.listdir(pending_dir)
    except OSError:
        return []
    new_requests = []
    for entry in entries:
        if not entry.endswith(".request.json"):
            continue
        request_id = entry[: -len(".request.json")]
        if request_id in seen_ids:
            continue
        request_path = os.path.join(pending_dir, entry)
        verdict_path = os.path.join(
            pending_dir, tier2_verdict_filename(request_id)
        )
        new_requests.append((request_id, request_path, verdict_path))
        seen_ids.add(request_id)
    return new_requests


def notify_oyakata_tier2_pending(p_oyakata, request_id, request_path, verdict_path, cfg):
    """Send Oya a notification about a pending tier-2 decision.

    Includes the request_id, both file paths, and the verdict schema Oya
    must write. The instruction is explicit and self-contained — Oya
    doesn't need to look up the protocol from her startup prompt every
    time. Fast cadence matters: Opus is blocked on the hook poll for up
    to TIER2_VERDICT_TIMEOUT_S; every second of Oya hesitation pushes
    operator-facing latency.
    """
    from orchestrator import send_message  # lazy import to avoid cycle
    if p_oyakata is None:
        return
    notification = (
        f"@OYA event — TIER-2 PENDING DECISION {request_id}\n\n"
        f"Opus is blocked on a permission prompt for a tool call that's "
        f"in-scope (target file is in `git status`). The hook is waiting "
        f"for your verdict.\n\n"
        f"Read the request:\n  {request_path}\n\n"
        f"Decide based on:\n"
        f"  - Current slice scope (capsule + comms)\n"
        f"  - Whether the tool_input.file_path is in the slice's declared "
        f"surface or a reasonable adjacent edit\n"
        f"  - Recent drift signals (does this look like Opus expanding "
        f"scope mid-slice, or working within plan?)\n\n"
        f"Write verdict to:\n  {verdict_path}\n\n"
        f"Verdict file schema:\n"
        f'  {{"verdict": "allow" | "defer", "reason": "<short justification>"}}\n\n'
        f"Conservative default: defer. Operator gets a normal prompt and "
        f"decides. You only choose `allow` when the call clearly fits "
        f"the active slice. If you cannot decide quickly, write "
        f"`defer` with the reason — silence costs operator latency.\n\n"
        f"Timeout: the hook gives up after a fixed budget and defers "
        f"automatically. Don't try to think it through past ~10 seconds — "
        f"better to write `defer` and let the operator see the prompt."
    )
    send_message(p_oyakata, notification, cfg)


def spawn_oya_if_enabled(cfg, config_path, session):
    """If [agents.oyakata].enabled = true, spawn scripts/attach-oya.sh and
    wait for its pane to appear in the tmux session.

    Returns the discovered Oya pane (libtmux Pane) or None. attach-oya.sh
    handles the pane split + claude launch + .claude/settings.local.json
    write + prompt auto-paste. We just kick it off and wait for the pane
    to show up, then return so the orchestrator can proceed to brief the
    pair.

    OYA_QUIET_BANNER=1 tells the script to suppress its trailing 'Next:'
    cheat-sheet — the orchestrator owns the boot narrative."""
    from orchestrator import _log  # lazy import to avoid cycle
    if not oyakata_enabled(cfg):
        return None

    # Idempotency layer 1: if a pane is already running in the musubi-root cwd
    # (Oya's signature), don't spawn another. Common when launch_musubi.sh
    # --with-oya ran and the orchestrator's auto-spawn is the second caller.
    existing = discover_oyakata_pane(session, cfg)
    if existing is not None:
        _log("OYA", f"Oya pane already exists at {existing.id} — skipping spawn (idempotent)")
        return existing

    # Idempotency layer 2: pane-count check. If the session has 3+ panes but
    # discover_oyakata_pane didn't match, a parallel attach-oya.sh is likely
    # mid-spawn (split done, cwd not yet visible). Wait briefly and re-check
    # before adding a duplicate.
    try:
        if len(session.active_window.panes) >= 3:
            _log("OYA", f"session has {len(session.active_window.panes)} panes already — assuming parallel attach is in flight, waiting 5s")
            time.sleep(5)
            existing = discover_oyakata_pane(session, cfg)
            if existing is not None:
                _log("OYA", f"parallel attach completed; using existing pane {existing.id}")
                return existing
            _log("OYA", "no Oya pane found despite 3+ pane count — proceeding with spawn")
    except Exception:
        pass

    orchestrator_dir = os.path.dirname(os.path.abspath(__file__))
    attach_script = os.path.join(orchestrator_dir, "scripts", "attach-oya.sh")
    if not os.path.exists(attach_script):
        _log("OYA", f"attach-oya.sh not found at {attach_script} — Oya will not auto-spawn")
        return None

    _log("OYA", f"agents.oyakata.enabled = true — spawning Oya via {os.path.relpath(attach_script, orchestrator_dir)}")
    env = os.environ.copy()
    env["MUSUBI_SESSION"] = session.name
    env["OYA_QUIET_BANNER"] = "1"
    # Tell attach-oya.sh where this install lives. Its default is
    # ~/Dev/musubi.repo but the README documents ~/Dev/musubi; pinning the
    # actual install dir here makes auto-spawn portable to any clone path.
    env["MUSUBI_ROOT"] = orchestrator_dir
    try:
        # Let attach-oya.sh's stdout flow to the orchestrator's stdout — its
        # [HH:MM:SS] [ATTACH] lines interleave consistently with our [BOOT]
        # / [OYA] lines. No redirect, no PIPE.
        subprocess.Popen(
            [attach_script, config_path],
            env=env,
        )
    except Exception as e:
        _log("OYA", f"failed to spawn attach-oya.sh: {e!r} — pair continues without Oya")
        return None

    # Wait for the Oya pane to appear in the session. attach-oya.sh handles
    # the tmux split, claude launch, settings write, and prompt paste; this
    # poll just confirms the pane exists before we hand off to the pair brief.
    deadline = time.time() + 30
    p_oya = None
    while time.time() < deadline:
        p_oya = discover_oyakata_pane(session, cfg)
        if p_oya is not None:
            _log("OYA", f"pane discovered: {p_oya.id}")
            return p_oya
        time.sleep(1)

    _log("OYA", "pane did not appear within 30s — pair will continue; check attach-oya output for errors")
    return None


# --- oyakata-2 slice 2: auto-wiring -------------------------------------------
# Reads/writes the operator's project `.claude/settings.local.json` to register
# the PreToolUse hook on each launch. Idempotent (no duplication across runs),
# update-aware (musubi-clone moves are followed), and defensive against
# pre-existing operator config (never clobbers unrelated entries).
#
# Why settings.local.json (not settings.json): the file contains absolute
# paths to this musubi clone, which are machine-specific. Claude Code
# convention gitignores settings.local.json by default; the operator's
# project should too. settings.json (committed) would propagate the path
# across teammates' machines incorrectly.

def _resolve_hook_command(orchestrator_dir=None):
    """Return the absolute path Claude Code should invoke as the hook.

    Computed from this module's location, not the caller's cwd, so the path
    survives the orchestrator being launched from anywhere. `orchestrator_dir`
    is exposed only so tests can inject a path; production callers leave it
    None.
    """
    if orchestrator_dir is None:
        orchestrator_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(orchestrator_dir, "scripts", "oya-pretooluse.py")


def _build_hook_entry(command_path):
    """Shape the JSON object Claude Code expects in the PreToolUse array."""
    return {
        "matcher": PRETOOLUSE_HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": command_path,
                "timeout": PRETOOLUSE_HOOK_TIMEOUT,
            }
        ],
    }


def _entry_marks_oya_hook(entry):
    """True if a settings entry looks like a musubi-managed oya-pretooluse
    hook — keyed on the script basename substring so the match is stable
    across operator clone-path moves. False on shape mismatches; the auto-
    wirer treats those as someone else's entries and leaves them alone.
    """
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    for h in hooks:
        if not isinstance(h, dict):
            continue
        cmd = h.get("command")
        if isinstance(cmd, str) and PRETOOLUSE_HOOK_MARKER in cmd:
            return True
    return False


def _merge_hook_into_settings(settings, command_path):
    """Mutate `settings` (a parsed JSON dict) to include the oya-pretooluse
    hook entry. Returns one of:
      - 'created' — fresh entry appended (no prior musubi entry detected)
      - 'updated' — existing musubi entry had a different path; updated in place
      - 'unchanged' — existing musubi entry already matches; no-op

    The caller decides whether to actually write the file based on this
    verdict (skips disk I/O on 'unchanged').
    """
    hooks_block = settings.setdefault("hooks", {})
    if not isinstance(hooks_block, dict):
        # Operator has a non-dict 'hooks' value (malformed manual edit?). Don't
        # clobber. Leave settings untouched and report unchanged.
        return "malformed"
    pre_list = hooks_block.setdefault("PreToolUse", [])
    if not isinstance(pre_list, list):
        return "malformed"

    new_entry = _build_hook_entry(command_path)

    for i, entry in enumerate(pre_list):
        if _entry_marks_oya_hook(entry):
            # Existing musubi entry — see if it needs an update (e.g. musubi
            # was moved to a new clone path).
            if entry == new_entry:
                return "unchanged"
            pre_list[i] = new_entry
            return "updated"

    pre_list.append(new_entry)
    return "created"


def auto_wire_pretooluse_hook(cfg, project_path, orchestrator_dir=None):
    """Idempotently register the oya-pretooluse hook in the project's
    `.claude/settings.local.json`. No-op when permissions aren't enabled.

    Failure modes are all non-fatal: a missing project `.claude/` dir is
    created; a missing settings file is created; a malformed existing file
    is warned about and skipped without overwrite; any I/O error is logged
    but does not raise. The orchestrator must keep booting even if hook
    auto-wiring breaks — the hook layer is opt-in convenience, not a
    correctness dependency.
    """
    from orchestrator import _log  # lazy import — same pattern as the rest of this module

    if not oyakata_permissions_enabled(cfg):
        return

    if not os.path.isdir(project_path):
        _log(
            "PERMS",
            f"auto-wire skipped: project_path {project_path!r} is not a directory",
        )
        return

    command_path = _resolve_hook_command(orchestrator_dir)
    if not os.path.exists(command_path):
        _log(
            "PERMS",
            f"auto-wire skipped: hook script not found at {command_path}",
        )
        return

    claude_dir = os.path.join(project_path, ".claude")
    settings_path = os.path.join(claude_dir, "settings.local.json")

    try:
        os.makedirs(claude_dir, exist_ok=True)
    except OSError as e:
        _log("PERMS", f"auto-wire failed to mkdir {claude_dir}: {e!r}")
        return

    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _log(
                "PERMS",
                f"auto-wire skipped: existing {settings_path} is unreadable "
                f"or malformed ({e!r}). Will NOT overwrite — fix the file by "
                f"hand or delete it to let auto-wiring recreate it.",
            )
            return
        if not isinstance(settings, dict):
            _log(
                "PERMS",
                f"auto-wire skipped: {settings_path} top-level JSON is not "
                f"an object. Will NOT overwrite.",
            )
            return
        existed = True
    else:
        settings = {}
        existed = False

    verdict = _merge_hook_into_settings(settings, command_path)

    if verdict == "unchanged":
        # File already contains the exact entry we'd write. Skip disk I/O.
        return
    if verdict == "malformed":
        _log(
            "PERMS",
            f"auto-wire skipped: {settings_path} has 'hooks' or 'hooks.PreToolUse' "
            f"in an unexpected shape. Will NOT overwrite — fix or delete the file.",
        )
        return

    try:
        # Atomic write: tmp + rename so a half-written file never replaces a
        # working settings.local.json on disk-full / kill-9 / etc.
        tmp_path = settings_path + ".musubi.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, settings_path)
    except OSError as e:
        _log("PERMS", f"auto-wire failed to write {settings_path}: {e!r}")
        return

    if existed:
        if verdict == "updated":
            _log(
                "PERMS",
                f"updated musubi PreToolUse hook in {settings_path} "
                f"(command path changed)",
            )
        else:
            _log(
                "PERMS",
                f"added musubi PreToolUse hook entry to existing {settings_path}",
            )
    else:
        _log(
            "PERMS",
            f"created {settings_path} with musubi PreToolUse hook entry",
        )
