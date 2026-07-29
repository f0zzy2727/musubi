import libtmux
import atexit
import json
import select
import subprocess
import time
import re
import os
import shlex
import shutil
import sys
from collections import deque
try:
    import tomllib  # Python 3.11+ stdlib
except ModuleNotFoundError:  # pragma: no cover - 3.10 and earlier
    import tomli as tomllib  # requirements.txt installs tomli for python_version < "3.11"
from datetime import datetime
from libtmux.constants import PaneDirection

# Comms parsing + state classification + file IO live in comms.py.
# Imported here so both the watcher loop below and external tests that
# `from orchestrator import X` continue to work without changes.
from comms import (
    strip_ansi,
    get_file_size,
    archive_and_reset_comms,
    resolve_archive_dir,
    find_latest_archive,
    read_new_content,
    resume_offset,
    over_pattern,
    detect_writer_from_buffer,
    extract_last_message,
    parse_result_field,
    message_type,
    is_idle_result,
    silence_nudge_due,
    comms_drop_due,
    rotation_due,
    is_state_affecting,
    capsule_path,
    capsule_is_stale,
    CAPSULE_FRESHNESS_WINDOW_SECONDS,
    detect_sender,
    extract_messages,
    parse_operator_actions,
    format_actions_status,
    format_relay_refusal_status,
    compose_status_right,
    parse_runbook_version,
    runbook_version_tuple,
)

# Oyakata (Oya) — optional third-agent supervisor layer in oyakata.py.
# Lazy imports inside that module's functions avoid circular imports for
# _log / send_message defined in this file.
from oyakata import (
    oyakata_enabled,
    oyakata_permissions_enabled,
    discover_oyakata_pane,
    relay_to_oyakata,
    notify_oyakata_capsule_edit,
    notify_oyakata_tier2_pending,
    scan_pending_tier2_requests,
    spawn_oya_if_enabled,
    auto_wire_pretooluse_hook,
    flag_disciplines_to_oyakata,
    operator_actions_enabled,
    resolve_operator_actions_path,
    operator_input_enabled,
    resolve_operator_input_path,
    parse_operator_input,
    relay_operator_input_to_oyakata,
)


def ts():
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
# Every boot-phase + watcher message goes through _log so the operator sees
# one consistent stream: [HH:MM:SS] [COMPONENT] text. Components:
#   BOOT     — session creation, attach, CLI start
#   RELAY    — relay test (orchestrator ↔ pair)
#   BRIEF    — agent briefing
#   OYA      — Oya pane spawn / pane-discovery (handoff to attach-oya.sh)
#   WATCHER  — main relay watcher
#   ACTION   — operator-action surface (Oya needs a decision from the human)
# ---------------------------------------------------------------------------

def _log(component, message):
    print(f"[{ts()}] [{component}] {message}", flush=True)


# ---------------------------------------------------------------------------
# Pane introspection + auto-advance gate
# ---------------------------------------------------------------------------

def capture_pane(pane, lines=40):
    """Return the last N lines of a tmux pane's visible content as plain text.

    `tmux capture-pane -p -S -N` reads the last N lines into stdout. Returns
    "" on any failure (better to make condition checks return False than to
    raise mid-boot)."""
    if pane is None:
        return ""
    try:
        out = pane.cmd("capture-pane", "-p", "-S", f"-{lines}").stdout
        if isinstance(out, list):
            return "\n".join(out)
        return out or ""
    except Exception:
        return ""


# Known UI hint / placeholder fragments that follow a prompt marker but are NOT
# typed user input — must not be mistaken for an unsent command.
_PROMPT_HINT_MARKERS = (
    "for shortcuts", "esc to", "ctrl+", "? for", "/help", "/clear to",
    "press enter", "▌", "auto-accept", "shift+tab",
)


def _looks_like_ui_hint(text):
    low = text.lower()
    return any(h in low for h in _PROMPT_HINT_MARKERS)


def buffer_has_pending_input(buffer):
    """Heuristic: does a pane's visible buffer show an UNSENT typed line sitting
    at the agent's input prompt? `send_keys` into such a pane APPENDS to and
    garbles that pending line — the exact reason Oya refuses to comms-nudge a
    parked coder by hand (okami log 2338/2395/2419: `❯ continue S2`,
    `❯ keep going` left unsent).

    Conservative by design: it only returns True for the two concrete prompt
    signatures observed to hold unsent text — the Codex `❯ <text>` prompt and
    the Claude Code bordered input box `│ > <text> │` — and filters known UI
    hints/placeholders. When unsure it returns False (a skipped nudge is
    recoverable; a garbled command is not, so we only skip on a positive sight).
    Pure string predicate so it is unit-testable without a live TUI."""
    text = strip_ansi(buffer or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in lines[-8:]:
        s = ln.strip()
        # Codex CLI prompt: a chevron followed by typed-but-unsent text.
        m = re.match(r"^[❯➜>]\s+(\S.*)$", s)
        if m and not _looks_like_ui_hint(m.group(1)):
            return True
        # Claude Code bordered input box: │ > typed text │
        m = re.search(r"│\s*>\s+(\S.*?)\s*│", ln)
        if m and not _looks_like_ui_hint(m.group(1)):
            return True
    return False


def pane_has_pending_input(pane):
    """True if the pane's live buffer shows an unsent typed line at its prompt.
    Returns False on any capture failure (don't block a nudge on a read error)."""
    return buffer_has_pending_input(capture_pane(pane, lines=12))


# A blocking permission modal is the single highest-value stall to detect: a
# relay-dependent agent sitting at one is invisible (no event fires to anyone),
# a send_keys nudge is worse than useless (the keystroke lands IN the modal and
# can pick an option), and only the human can answer it. Field: Coda parked ~83
# min on a permission prompt mid-cycle (okami 2026-06-23 cycle-close I&A,
# headline #1); Oya parked on an `oyakata-log.md` edit prompt 8 min into the
# 2026-06-24 launch. The defining signature is the interactive numbered option
# list with the selection chevron resting on a Yes/No/Allow choice — both the
# Claude Code box and the Codex CLI render this shape.
_MODAL_OPTION_RE = re.compile(
    r"^[❯➜▶>]\s*\d+\.\s+(yes|no|allow|approve|deny|don'?t|reject)\b",
    re.IGNORECASE)


def buffer_has_permission_modal(buffer):
    """Return a short question-summary string when a pane's visible buffer sits
    at a blocking permission/approval modal, else None.

    Conservative, pure, and unit-testable (no live TUI). The positive signal is
    the highlighted numbered option (`❯ 1. Yes`) that both the Claude Code
    permission box and the Codex approval prompt render — agent prose that merely
    mentions "do you want to" never produces that selector line. When the modal
    is found we walk upward for the nearest question line (ending in `?`) to name
    the specific ask for the operator surface; absent one we return a generic
    label so the caller still knows a modal is blocking."""
    text = strip_ansi(buffer or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for i in range(len(lines) - 1, -1, -1):
        if _MODAL_OPTION_RE.match(lines[i].strip()):
            # Found the selected option. Name the ask from the nearest question
            # line above it (skip the option lines themselves).
            for j in range(i - 1, max(i - 8, -1), -1):
                cand = lines[j].strip()
                if cand.endswith("?") and not _looks_like_ui_hint(cand):
                    return cand
            return "a permission prompt is blocking this pane"
    return None


def pane_permission_modal(pane):
    """The question summary if the pane's live buffer is at a permission modal,
    else None. Returns None on any capture failure (don't false-alarm on a read
    error — a missed modal is recoverable on the next tick)."""
    return buffer_has_permission_modal(capture_pane(pane, lines=14))


# A pane mid-turn must NEVER be nudged (the park watchdog, stall-class 3) — a
# send_keys into a working pane garbles the next prompt and the nudge is noise.
# The cross-CLI "I am running" signal is `esc to interrupt`; Claude also shows a
# live gerund spinner with an elapsed timer (`· Herding… (4m 31s · ↓ 14.7k
# tokens · still thinking)`). The PAST-tense done markers (`Crunched for 29s`,
# `Worked for 1m 53s`) deliberately do NOT match — those mean the turn finished
# and the pane is now idle, which is exactly the park we want to catch.
_WORKING_MARKERS_RE = re.compile(
    r"esc to interrupt"               # both CLIs, only while a turn runs
    r"|still thinking"                # Claude spinner tail
    r"|[·✻✶✳✦◐◓◑◒*]\s*[A-Za-z]+…"     # spinner glyph + gerund + ellipsis
    r"|[A-Za-z]+…\s*\(\s*\d",         # gerund-ellipsis immediately before "(4m…"
    re.IGNORECASE)


def buffer_is_working(buffer):
    """True if the pane's visible buffer shows an in-progress turn (a live
    spinner / interrupt hint). Pure + conservative: matches only the animated
    running signatures, never the past-tense `… for Ns` completion lines, so a
    finished-then-idle pane reads as NOT working. Plain agent prose can't match
    (the gerund must sit beside a spinner glyph or an elapsed timer)."""
    return bool(_WORKING_MARKERS_RE.search(strip_ansi(buffer or "")))


def classify_pane_state(buffer):
    """Single precedence classifier for the stall watchdog. Pure + unit-testable.
    MODAL (never keystroke) > PENDING_INPUT (only the human submits it) > WORKING
    (leave it alone) > IDLE (candidate park)."""
    if buffer_has_permission_modal(buffer) is not None:
        return "MODAL"
    if buffer_has_pending_input(buffer):
        return "PENDING_INPUT"
    if buffer_is_working(buffer):
        return "WORKING"
    return "IDLE"


# Claude Code surfaces context pressure as a "/clear to save <N>k tokens" hint
# (and variants) once the session grows heavy. okami's recurring implementer
# deaths were at ~478k / 720k / 898k tokens — a nudge cannot recover a
# context-dead pane, so the watchdog warns the operator BEFORE death.
_CONTEXT_PRESSURE_RE = re.compile(
    r"(?:/clear\s+to\s+save|save)\s+~?([\d][\d,.]*)\s*k\b", re.IGNORECASE)


def parse_context_pressure_k(buffer):
    """Return the largest context-pressure figure (in thousands of tokens) shown
    in a pane buffer, or None if no such hint is present. Pure + unit-testable."""
    text = strip_ansi(buffer or "")
    best = None
    for m in _CONTEXT_PRESSURE_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if best is None or val > best:
            best = val
    return best


def context_regime(pressure_k, warn_k, pane_state, frozen_secs, idle_threshold):
    """Map a context-pressure reading to the operator-action regime. Pure +
    unit-testable. Returns one of:

      None   — below threshold / no reading: nothing to surface.
      "live" — heavy but still recoverable. The remedy is `/compact` (or `/clear`
               at a clean boundary): it frees context and CONTINUES the session,
               no restart needed. This is the common case and what the operator
               usually wants instead of a restart.
      "dead" — heavy AND frozen-idle past the park threshold: the pane has very
               likely already died of context exhaustion. `/compact` can't revive
               a dead pane; only a relaunch (re-attach) recovers it.

    A pane only reads "dead" when it is BOTH idle (not WORKING, not at a modal /
    pending input — those are live, transient states) AND its buffer has not
    changed for at least `idle_threshold` seconds (the same park-stall threshold).
    A healthy heavy pane cycles work→idle→work, so its buffer keeps changing and
    `frozen_secs` stays low → "live". `idle_threshold <= 0` (park disabled) means
    we can't judge frozen-ness, so we never declare "dead" — always "live"."""
    if pressure_k is None or pressure_k < warn_k:
        return None
    if idle_threshold and idle_threshold > 0 and pane_state == "IDLE" \
            and frozen_secs >= idle_threshold:
        return "dead"
    return "live"


def quarantine_log_path(comms_file):
    """The single append-only quarantine log beside the comms file. Replaces the
    old one-file-per-incident sidecars (`_unparseable_<timestamp>.txt`) that
    proliferated to 47 files on the okami bed — bounded blast radius, one place
    to look."""
    return os.path.join(os.path.dirname(comms_file) or ".", "_unparseable.log")


def append_quarantine_entry(comms_file, content, reason):
    """Append one skipped/unparseable region to the consolidated quarantine log
    with a timestamped, labelled header. Best-effort: returns the log path on
    success, None on failure (the caller logs the failure but never breaks the
    relay loop over it)."""
    path = quarantine_log_path(comms_file)
    header = (f"\n===== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
              f"[{reason}] {len(content.encode('utf-8'))} bytes =====\n")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(header)
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        return path
    except Exception:
        return None


def tmux_has_attached_client(session):
    """True if at least one tmux client is currently attached to the session.
    Used by Gate 1 (was: 'Press Enter when you're attached')."""
    try:
        out = session.cmd("list-clients", "-t", session.name).stdout
        # list-clients prints one line per attached client; empty list = nobody
        if isinstance(out, list):
            return any(line.strip() for line in out)
        return bool(out and out.strip())
    except Exception:
        return False


def wait_for_or_skip(condition_fn, timeout, component, label, poll=1.5):
    """Block until condition_fn() returns True OR the operator presses Enter
    OR `timeout` seconds elapse. Returns 'auto' | 'manual' | 'timeout'.

    Replaces a blind `input()` gate with: 'auto-advance when the boot phase
    is actually done; let the operator skip the wait; never block forever.'
    """
    _log(component, f"{label} — waiting up to {timeout}s (Enter to skip)")
    start = time.time()
    while time.time() - start < timeout:
        # Check stdin non-blockingly. select() on stdin gives us 'is Enter pressed?'
        # without committing to an input() call that would block forever.
        try:
            rlist, _, _ = select.select([sys.stdin], [], [], poll)
        except (ValueError, OSError):
            # stdin is closed / not a tty — fall back to pure polling
            rlist = []
            time.sleep(poll)
        if rlist:
            try:
                sys.stdin.readline()
            except Exception:
                pass
            _log(component, f"manual advance after {int(time.time() - start)}s")
            return 'manual'
        try:
            if condition_fn():
                _log(component, f"condition met after {int(time.time() - start)}s — advancing")
                return 'auto'
        except Exception as e:
            _log(component, f"condition check raised {e!r} — continuing to poll")
    _log(component, f"timeout after {timeout}s — proceeding anyway (intervention may be needed)")
    return 'timeout'


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class ConfigError(ValueError):
    """Raised when musubi.toml is missing required keys, has the wrong shape,
    or references an agent CLI that isn't on PATH. The orchestrator catches
    this in __main__ and prints a clean message instead of a traceback."""


# Required structure for musubi.toml. Leaves of the tree are the expected
# Python type for that value. Extra keys (e.g. comms.runbook, comms.archive_dir,
# comms.stall_seconds) are allowed — they're read with .get() elsewhere.
_REQUIRED_CONFIG_SHAPE = {
    "project": {"path": str},
    "agents": {
        "opus": {"name": str, "handle": str, "cli": str},
        "coda": {"name": str, "handle": str, "cli": str},
    },
    "comms": {"file": str, "over_signal": str},
    "tmux": {"session_name": str},
}


def validate_config(cfg):
    """Walk cfg against _REQUIRED_CONFIG_SHAPE and raise ConfigError with the
    full dotted path on the first problem. Catches missing keys, wrong types,
    and empty strings — the three failure modes worth a clean error message."""
    if not isinstance(cfg, dict):
        raise ConfigError("musubi.toml: top-level must be a TOML table")

    def _walk(spec, node, path):
        if not isinstance(node, dict):
            raise ConfigError(f"{path}: expected a TOML table, got {type(node).__name__}")
        for key, expected in spec.items():
            full = f"{path}.{key}" if path else key
            if key not in node:
                raise ConfigError(f"{full}: missing required key")
            value = node[key]
            if isinstance(expected, dict):
                _walk(expected, value, full)
            else:
                if not isinstance(value, expected):
                    raise ConfigError(
                        f"{full}: expected {expected.__name__}, got {type(value).__name__}"
                    )
                if expected is str and not value.strip():
                    raise ConfigError(f"{full}: must not be empty")

    _walk(_REQUIRED_CONFIG_SHAPE, cfg, "")


def validate_cli_available(cli):
    """Raise ConfigError if `cli` is not on PATH. Called before the tmux
    session is created so a missing claude/codex install fails fast instead
    of orphaning a session with a broken pane."""
    if shutil.which(cli) is None:
        raise ConfigError(
            f"agent CLI '{cli}' not found on PATH. Install it and try again."
        )


# --- orch-6: cwd defence ----------------------------------------------------
# iCloud-synced macOS folders (Desktop, Documents, Downloads — all default-on
# on modern macOS) can invalidate the shell's working-directory handle between
# sessions, causing Node-based agent CLIs to crash on startup with
# `EPERM: process.cwd failed ... uv_cwd`. These helpers (a) verify project.path
# is enterable before agents spawn, and (b) warn loudly when the project lives
# under an iCloud-synced location even if the cwd is currently healthy.

_ICLOUD_SYNCED_PREFIXES = ("Desktop", "Documents", "Downloads")


def _is_icloud_synced_path(path):
    """Return True if `path` lives under a macOS folder that iCloud Drive
    syncs by default. We don't try to detect whether iCloud sync is actually
    enabled — too brittle, and the warning is cheap. Better to over-warn and
    let the operator dismiss it than to under-warn and have them debug a
    Node stack trace."""
    home = os.path.expanduser("~")
    try:
        rel = os.path.relpath(path, home)
    except ValueError:
        return False
    if rel.startswith(".."):
        return False
    first = rel.split(os.sep, 1)[0]
    return first in _ICLOUD_SYNCED_PREFIXES


def validate_project_path(project_path):
    """Verify `project_path` exists, is a directory, and is enterable. Warn
    if it's under an iCloud-synced macOS folder.

    Called from start_musubi BEFORE the tmux session is created so the
    operator sees an actionable error instead of an EPERM uv_cwd Node trace
    in the agent pane after spawn. See IA-QUEUE.md orch-6.
    """
    expanded = os.path.expanduser(project_path)
    if not os.path.exists(expanded):
        raise ConfigError(
            f"project.path '{project_path}' does not exist. "
            f"Update musubi.toml or restore the directory and try again."
        )
    if not os.path.isdir(expanded):
        raise ConfigError(
            f"project.path '{project_path}' is not a directory."
        )
    # os.chdir + back is the strongest enterability check on macOS — it
    # exercises the same kernel path that the agent shell will when it runs
    # `cd <project_path>`. If the directory exists in the filesystem but is
    # unreadable (e.g. permission flip, briefly unmounted volume), this
    # surfaces the failure here instead of inside the agent pane.
    saved = os.getcwd()
    try:
        os.chdir(expanded)
    except OSError as e:
        raise ConfigError(
            f"project.path '{project_path}' exists but is not enterable: {e}. "
            f"Close this terminal, open a new one, cd ~ first, then re-run."
        )
    finally:
        try:
            os.chdir(saved)
        except OSError:
            # Best-effort restore. If the saved cwd is itself stale, we can't
            # do much beyond surfacing it on the next syscall. The agent
            # spawn path uses tmux's own `cd <project_path>` anyway, so a
            # stale orchestrator-process cwd doesn't poison the panes.
            pass

    if _is_icloud_synced_path(expanded):
        _log(
            "BOOT",
            f"WARNING: project.path is under an iCloud-synced folder ({expanded})",
        )
        _log(
            "BOOT",
            "  iCloud sync can invalidate the shell's cwd handle between sessions",
        )
        _log(
            "BOOT",
            "  and cause Claude Code / Codex to crash with EPERM uv_cwd on restart.",
        )
        _log(
            "BOOT",
            "  Recommended: move the project to ~/Dev/ or any non-synced location.",
        )


# Managed-doc size thresholds (orch-2). Claude Code prints a performance
# warning around 40k chars; past ~100k the warm-start context cost is severe
# enough that launching is worse than forcing the operator to rotate first.
MANAGED_DOC_WARN_CHARS = 40_000
MANAGED_DOC_REFUSE_CHARS = 100_000

# Oya append-log rotation (burn-1). The supervisor's own audit streams —
# oyakata-log.md (one entry per activation, append-only by prompt design),
# oyakata-decisions.md (one line per PreToolUse auto-approve), and
# operator-channel.md (verbatim mirror of Oya->operator messages) — are NOT
# cycle-structured pair docs, so rotate_managed_doc can't trim them. Left
# unguarded they grow without bound and are reloaded into context every Oya
# turn; under an unattended auto-wake loop across several apps that is the
# 2026-06-30 token-burn ($100/hr, 2.5B cache-read tokens). These get a
# tail-rotation (keep the header + most-recent tail, archive the rest) so warm
# context stays cheap no matter how the operator vibes. Trigger high enough that
# a normal session never rotates mid-flight; keep generous so recent history
# survives. Override via [comms].oya_log_rotate_chars / oya_log_keep_chars.
OYA_LOG_ROTATE_CHARS = 80_000
OYA_LOG_KEEP_CHARS = 30_000

# Depth of the recently-relayed dedup window (see its use in watch_and_relay).
# Must be at least one full cycle's worth of comms messages: when the active
# comms file is truncated+rewritten mid-cycle by something external, the watcher
# re-reads it from offset 0, and only blocks still inside this window are
# recognised as already-relayed and skipped. Anything older re-relays — which is
# how a too-small window (the original 8) flooded Oya with an entire cycle on
# each shrink (field bug 2026-06-09). Sized for a realistic cycle with headroom;
# the memory cost is bounded because comms is archived+reset at boot.
RECENTLY_RELAYED_WINDOW = 1000


def _managed_doc_paths(cfg):
    """Resolve the set of managed docs whose size is guarded on boot. Paths are
    config-overridable where the orchestrator already reads them; the rest use
    the runbook's canonical locations. Returns [(label, abs_path)]."""
    project = cfg.get("project", {}).get("path", ".")

    def _abs(rel):
        return rel if os.path.isabs(rel) else os.path.join(project, rel)

    comms = cfg.get("comms", {})
    candidates = [
        ("CLAUDE.md", _abs("CLAUDE.md")),
        ("runbook", _abs(comms.get("runbook", "docs/agents/AGENT_COLLAB_RUNBOOK.md"))),
        ("capsule", _abs(comms.get("capsule", "docs/agents/current-state.md"))),
        ("agent-todo", _abs("docs/agents/agent-todo.md")),
        ("agent-handoff", _abs("docs/agents/agent-handoff.md")),
    ]
    return candidates


def _oya_append_log_paths(cfg):
    """Resolve Oya's own append-only audit streams (burn-1). These are NOT
    cycle-structured pair docs — they accrete forever and are reloaded into
    Oya's context every turn — so they get tail-rotation, not section-rotation.
    Returns [(label, abs_path)]. Independent of whether Oya is enabled: a config
    flip leaves the files behind, and a stale 1MB log still costs on the next
    boot that does enable her."""
    project = cfg.get("project", {}).get("path", ".")

    def _abs(rel):
        return rel if os.path.isabs(rel) else os.path.join(project, rel)

    oya = cfg.get("agents", {}).get("oyakata", {})
    return [
        ("oyakata-log", _abs(oya.get("log_path", "docs/agents/oyakata-log.md"))),
        ("oyakata-decisions", _abs("docs/agents/oyakata-decisions.md")),
        ("operator-channel", _abs("docs/agents/operator-channel.md")),
    ]


# An "entry" in an Oya append-log is a top-level dated section header
# (oyakata-log / operator-channel: `## 2026-06-30 ...`) or a bare ISO-timestamp
# line (oyakata-decisions: `2026-06-30T09:15 ALLOW ...`). Everything before the
# first match is preamble (title + format note) and is always preserved.
_OYA_ENTRY_START_RE = re.compile(
    r"^(?:##\s.*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})", re.MULTILINE)


_OYA_LOG_PREAMBLE_CAP = 4000


def rotate_append_log(path, keep_chars=OYA_LOG_KEEP_CHARS):
    """Tail-rotate an append-only audit log (burn-1): archive the full file, then
    rewrite it as a bounded document header + a rotation pointer + the
    most-recent tail (<= keep_chars). The tail snaps to an entry boundary when
    one falls in the keep window (clean for oyakata-log / -decisions); otherwise
    it snaps to a line boundary, so the cap holds even for operator-channel —
    whose dated headers are front-loaded and whose bulk is one giant header-less
    trailing section. Lossless — the complete prior content is copied to
    docs/agents/archive/<stem>-archive-<date>.md first.

    Returns the archive path, or None when the file already fits under keep_chars
    or can't be trimmed without eating the header."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    if len(text) <= keep_chars:
        return None  # already small enough

    starts = [m.start() for m in _OYA_ENTRY_START_RE.finditer(text)]

    # Bounded document header (title + format note). Crucially NOT "everything
    # before the first dated entry": operator-channel's first `## ` header can sit
    # 500KB in, and that bulk must be archived, not kept as preamble.
    if starts and starts[0] <= _OYA_LOG_PREAMBLE_CAP:
        preamble = text[:starts[0]]
    else:
        nl = text.rfind("\n", 0, _OYA_LOG_PREAMBLE_CAP)
        preamble = text[:nl + 1] if nl != -1 else ""

    # Keep from the earliest entry boundary whose tail still fits under
    # keep_chars; fall back to a line boundary when none falls in the window.
    cut = len(text) - keep_chars
    kept_from = next((s for s in starts if s >= cut), None)
    if kept_from is None or kept_from <= len(preamble):
        nl = text.find("\n", cut)
        kept_from = nl + 1 if nl != -1 else cut
    if kept_from <= len(preamble):
        return None  # tail would overlap the header — file too small to bother

    kept = text[kept_from:]

    archive_dir = os.path.join(os.path.dirname(path), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, f"{stem}-archive-{stamp}.md")
    if os.path.exists(archive_path):
        archive_path = os.path.join(
            archive_dir, f"{stem}-archive-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
    shutil.copy2(path, archive_path)

    pointer = (
        f"\n---\n\n> **Tail-rotated {stamp} (musubi append-log rotation, burn-1).** "
        f"Older entries are archived to `docs/agents/archive/{os.path.basename(archive_path)}` "
        f"— full prior log preserved there and in git history. This file keeps only the "
        f"most-recent tail so it stays cheap to reload every Oya turn.\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(preamble.rstrip() + "\n" + pointer + kept.lstrip())
    return archive_path


# A cycle section in a log-shaped managed doc (handoff / todo) is a `## ` header
# carrying a real date. Template/preamble headers (e.g. "## [Cycle name] —
# [YYYY-MM-DD]") have no real date and are kept as preamble.
_CYCLE_HEADER_RE = re.compile(r"^##\s.*\d{4}-\d{2}-\d{2}", re.MULTILINE)


def rotate_managed_doc(path, keep_recent=2):
    """Archive the full doc, then trim the active copy to its preamble plus the
    `keep_recent` most-recent cycle sections. Lossless — the complete prior
    content is copied to docs/agents/archive/<stem>-archive-<date>.md first.

    Assumes musubi's newest-at-top handoff convention (the template adds new
    cycle entries above older ones). Returns the archive path, or None when the
    doc has no rotatable cycle sections (≤ keep_recent dated `## ` headers) —
    e.g. an inherently-large doc like CLAUDE.md, which needs the @-import split
    (runbook-1), not rotation."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    headers = list(_CYCLE_HEADER_RE.finditer(text))
    if len(headers) <= keep_recent:
        return None

    archive_dir = os.path.join(os.path.dirname(path), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, f"{stem}-archive-{stamp}.md")
    if os.path.exists(archive_path):
        archive_path = os.path.join(
            archive_dir, f"{stem}-archive-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
    shutil.copy2(path, archive_path)

    preamble = text[:headers[0].start()]
    kept = text[headers[0].start():headers[keep_recent].start()]
    pointer = (
        f"\n---\n\n> **Rotated {stamp} (musubi managed-doc rotation).** Cycle "
        f"sections beyond the most recent {keep_recent} are archived to "
        f"`docs/agents/archive/{os.path.basename(archive_path)}` — full prior "
        f"log preserved there and in git history.\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(preamble + kept.rstrip() + "\n" + pointer)
    return archive_path


_FRESH_CAPSULE = """\
# Current State

> **Capsule-before-comms invariant:** this file is updated *before* the comms
> message that describes the change. The comms message reports reality.

**Last verified HEAD:** {head}
**Last updated:** {when}
**Active cycle:** none

## Active slices

| Agent | Slice | State | Branch | Started | Notes |
|---|---|---|---|---|---|

## Review queue

| Slice | Reviewer | Requested | Notes |
|---|---|---|---|

## Blocked items

| Slice | Owner | Blocker | Needs |
|---|---|---|---|

## Locked decisions this session

| Decision | Date set | Source-of-truth | Why locked |
|---|---|---|---|

## Dirty worktree exceptions

## Merge / push order

---

> Reset {when} by the boot size-guard — the prior capsule had bloated past the
> launch ceiling. Full prior content archived to `{archive_rel}`. The capsule is a
> current-state *snapshot*, not a log: pull history from the archive if needed.
"""


def reset_capsule(path):
    """Archive the full capsule and replace it with a fresh empty snapshot.
    The capsule is a current-state snapshot, not a cycle log, so section-rotation
    can't shrink a bloated one (the bulk is preamble/undated state) — a reset is
    the right move. Returns the archive path."""
    archive_dir = os.path.join(os.path.dirname(path), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, f"{stem}-archive-{stamp}.md")
    if os.path.exists(archive_path):
        archive_path = os.path.join(
            archive_dir, f"{stem}-archive-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
    shutil.copy2(path, archive_path)
    head = _git_head_sha(os.path.dirname(path)) or "unknown"
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    archive_rel = os.path.join("docs/agents/archive", os.path.basename(archive_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(_FRESH_CAPSULE.format(head=head, when=when, archive_rel=archive_rel))
    return archive_path


# Capsule lines that carry CURRENT-state orientation and must survive a trim —
# the commit pointer + freshness stamp + active-cycle name. Everything else that
# starts with `**` is a freeform log entry (the bloat).
_CAPSULE_KEEP_PREFIXES = ("**Last verified HEAD:", "**Last updated:",
                          "**Active cycle:")


def trim_capsule(path, keep_recent_entries=2):
    """Archive the full capsule, then rewrite it KEEPING its orientation skeleton
    and dropping the freeform `**bold**` log entries that bloat it.

    Unlike reset_capsule (which blanks to a template — the agents warm-start with
    NO idea what they were doing, the amnesia failure), this preserves the parts
    that actually orient the pair:
      - the `# ` header + the capsule-invariant blockquote,
      - the `**Last verified HEAD:**` / `**Last updated:**` / `**Active cycle:**`
        lines (the current pointer),
      - the most-recent `keep_recent_entries` freeform entries (what just
        happened), and
      - ALL `## ` structured sections (Active slices / Blocked / Locked-decisions
        tables — the real current state).
    The older freeform entries go to the archive (recoverable).

    Returns (archive_path, new_size), or None when there is no freeform bulk to
    drop (the bloat isn't log entries — let the size guard handle it; a blank
    reset is never done automatically)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # The `## ` structured sections ARE current state — keep them whole.
    m = re.search(r"^## ", text, re.MULTILINE)
    preamble, sections = (text[:m.start()], text[m.start():]) if m else (text, "")

    kept_pre, freeform = [], []
    for line in preamble.splitlines():
        s = line.strip()
        if s.startswith("# ") or s.startswith(">") or s.startswith(_CAPSULE_KEEP_PREFIXES):
            if s:
                kept_pre.append(line)
        elif s.startswith("**"):
            freeform.append(line)
        # else: blank / unknown prose between entries — drop (it's in the archive)

    # Nothing to gain if the freeform log isn't the bulk.
    if len(freeform) <= keep_recent_entries:
        return None

    archive_dir = os.path.join(os.path.dirname(path), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stamp = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, f"{stem}-archive-{stamp}.md")
    if os.path.exists(archive_path):
        archive_path = os.path.join(
            archive_dir, f"{stem}-archive-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
    shutil.copy2(path, archive_path)  # archive FULL before any rewrite

    recent = freeform[-keep_recent_entries:] if keep_recent_entries > 0 else []
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    pointer = (
        f"\n---\n\n> **Auto-trimmed {when} (boot managed-doc hygiene).** "
        f"{len(freeform) - len(recent)} older capsule log entries archived to "
        f"`docs/agents/archive/{os.path.basename(archive_path)}` — kept the current "
        f"HEAD, the {len(recent)} most-recent entries, and the structured sections. "
        f"The capsule is a snapshot, not a log.\n"
    )
    recent_block = ("\n\n" + "\n".join(recent)) if recent else ""
    body = "\n".join(kept_pre) + recent_block + "\n\n" + sections.rstrip() + "\n" + pointer
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return archive_path, os.path.getsize(path)


# Managed docs the boot auto-rotation may trim. CLAUDE.md / runbook are
# deliberately excluded — they are reference docs, not cycle logs (CLAUDE.md
# needs the @-import split, not rotation), and the size guard still warns on them.
_AUTO_ROTATABLE = frozenset({"capsule", "agent-handoff", "agent-todo"})


def auto_rotate_managed_docs(cfg):
    """Boot auto-hygiene (docs-2): non-interactively archive + trim any cycle doc
    grown past the rotate threshold, so warm-start context stays cheap WITHOUT the
    operator having to remember to rotate at cycle close. This is the durable fix
    for the recurring 'Oya lost context / 15-min spaghetti' failure — a capsule /
    handoff that silently bloated into a multi-week log.

    Default-ON; archive-safe (the full doc is copied to the archive before any
    trim). The capsule is TRIMMED (trim_capsule — keeps the orientation skeleton),
    never blanked; handoff/todo are rotated to their most-recent dated cycle
    sections (rotate_managed_doc). Returns [(label, old, new, archive), ...] for
    the operator log. Runs before check_managed_doc_sizes, which stays as the
    refuse-on-launch backstop for anything auto-rotation can't shrink."""
    comms = cfg.get("comms", {})
    if not comms.get("auto_rotate_managed_docs", True):
        return []
    threshold = comms.get("managed_doc_rotate_chars", MANAGED_DOC_WARN_CHARS)

    rotated = []
    for label, path in _managed_doc_paths(cfg):
        if label not in _AUTO_ROTATABLE:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size <= threshold:
            continue
        try:
            result = trim_capsule(path) if label == "capsule" else rotate_managed_doc(path)
        except (OSError, RuntimeError) as e:
            _log("BOOT", f"auto-rotate skipped {label} ({e}); left as-is.")
            continue
        if result is None:
            _log("BOOT", f"auto-rotate: {label} is {size:,} chars but has no "
                         f"rotatable structure — left as-is (the size guard will "
                         f"flag it; needs a manual trim).")
            continue
        archive_path = result[0] if isinstance(result, tuple) else result
        new = os.path.getsize(path)
        _log("BOOT", f"auto-rotated {label}: {size:,} -> {new:,} chars "
                     f"(full copy archived to {os.path.basename(archive_path)}).")
        rotated.append((label, size, new, archive_path))

    # Oya's append-only audit streams (burn-1): tail-rotate, not section-rotate.
    # These are the 2026-06-30 token-burn root cause — unbounded files reloaded
    # every Oya turn. Same archive-safe contract.
    oya_threshold = comms.get("oya_log_rotate_chars", OYA_LOG_ROTATE_CHARS)
    oya_keep = comms.get("oya_log_keep_chars", OYA_LOG_KEEP_CHARS)
    for label, path in _oya_append_log_paths(cfg):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size <= oya_threshold:
            continue
        try:
            archive_path = rotate_append_log(path, keep_chars=oya_keep)
        except (OSError, RuntimeError) as e:
            _log("BOOT", f"append-log auto-rotate skipped {label} ({e}); left as-is.")
            continue
        if archive_path is None:
            _log("BOOT", f"append-log {label} is {size:,} chars but has no entry "
                         f"boundary to trim on — left as-is (needs a manual look).")
            continue
        new = os.path.getsize(path)
        _log("BOOT", f"tail-rotated {label}: {size:,} -> {new:,} chars "
                     f"(full copy archived to {os.path.basename(archive_path)}).")
        rotated.append((label, size, new, archive_path))
    return rotated


def _prompt_yes_no(prompt):
    """Interactive y/N prompt. Defaults to No on empty / EOF / interrupt."""
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def check_managed_doc_sizes(cfg, interactive=None):
    """Boot guard (orch-2): warn on oversized managed docs; on docs over the
    hard ceiling, OFFER to rotate them in place rather than bombing out. Pairs
    with the runbook's rotation policy (docs-1).

    When `interactive` (defaults to whether stdin is a tty), each over-ceiling
    doc gets a `Rotate now? [y/N]` prompt; on yes it's archived + trimmed via
    rotate_managed_doc and launch continues. Docs the operator declines, docs
    with no rotatable cycle sections, or any offender in a non-interactive run
    (CI/tests) raise ConfigError as before. Missing files are skipped."""
    if interactive is None:
        interactive = sys.stdin.isatty()

    offenders = []
    for label, path in _managed_doc_paths(cfg):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > MANAGED_DOC_REFUSE_CHARS:
            offenders.append((label, path, size))
        elif size > MANAGED_DOC_WARN_CHARS:
            _log("BOOT", f"WARNING: {label} is {size:,} chars (> {MANAGED_DOC_WARN_CHARS:,}). "
                         f"Rotate at cycle close to keep warm-start context cheap.")

    # Oya's append-logs are warn-only here — never block launch on an audit
    # trail. auto_rotate_managed_docs already tail-trims them; this fires only if
    # auto-rotate is disabled or couldn't find an entry boundary (burn-1).
    oya_threshold = cfg.get("comms", {}).get("oya_log_rotate_chars", OYA_LOG_ROTATE_CHARS)
    for label, path in _oya_append_log_paths(cfg):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > oya_threshold:
            _log("BOOT", f"WARNING: Oya append-log {label} is {size:,} chars "
                         f"(> {oya_threshold:,}) and was NOT auto-trimmed — it reloads into "
                         f"Oya's context every turn. Enable auto_rotate_managed_docs or trim "
                         f"it manually (the burn-1 token-cost path).")

    remaining = []
    for label, path, size in offenders:
        # The capsule is a snapshot, not a cycle log — section-rotation can't
        # shrink a bloated one. Offer a reset instead.
        is_capsule = (label == "capsule")
        action = "reset it to a fresh snapshot" if is_capsule else "archive older cycles and rotate it"
        if interactive and _prompt_yes_no(
                f"  {label} is {size:,} chars (over the {MANAGED_DOC_REFUSE_CHARS:,} "
                f"ceiling). {action[0].upper()}{action[1:]} now? [y/N] "):
            if is_capsule:
                archived = reset_capsule(path)
                new_size = os.path.getsize(path)
                _log("BOOT", f"reset capsule (snapshot): {size:,} -> {new_size:,} chars. "
                             f"Archived to {archived}")
            else:
                archived = rotate_managed_doc(path)
                if archived is None:
                    _log("BOOT", f"{label} has no rotatable cycle sections — it needs "
                                 f"manual attention (e.g. the @-import split or a reset), "
                                 f"not section-rotation.")
                    remaining.append((label, path, size))
                    continue
                new_size = os.path.getsize(path)
                _log("BOOT", f"rotated {label}: {size:,} -> {new_size:,} chars. "
                             f"Archived to {archived}")
            if new_size > MANAGED_DOC_REFUSE_CHARS:
                _log("BOOT", f"{label} is STILL {new_size:,} chars after that — section-rotation "
                             f"wasn't enough; it needs a manual trim/reset before launch.")
                remaining.append((label, path, new_size))
        else:
            remaining.append((label, path, size))

    if remaining:
        lines = [f"  - {label} ({path}): {size:,} chars" for label, path, size in remaining]
        raise ConfigError(
            "Managed doc(s) exceed the "
            f"{MANAGED_DOC_REFUSE_CHARS:,}-char launch ceiling:\n"
            + "\n".join(lines)
            + "\nRotate older cycle sections to docs/agents/archive/ and relaunch "
              "(see the runbook's Managed-doc rotation policy)."
        )


def _git_head_summary(repo_dir):
    """Return '<short-sha> <subject>' for repo_dir's HEAD, or None if repo_dir
    is not a git checkout / git is unavailable. Best-effort, never raises."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _git_head_sha(repo_dir):
    """Return HEAD's short sha for repo_dir, or None. Used for mid-session
    staleness detection (orch-3)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _git_last_commit_ts(repo_dir, *paths):
    """Unix timestamp of the most recent commit in repo_dir, optionally
    limited to commits touching `paths`. None outside a git repo, when no
    commit touches the paths, or on any failure. Never raises."""
    cmd = ["git", "-C", repo_dir, "log", "-1", "--format=%ct"]
    if paths:
        cmd += ["--"] + list(paths)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        val = out.stdout.strip()
        if out.returncode == 0 and val:
            return int(val)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _git_commit_count_since(repo_dir, unix_ts):
    """Count commits on HEAD strictly newer than `unix_ts`. None on failure."""
    since = datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S")
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "rev-list", "--count", "HEAD",
             f"--since={since}"],
            capture_output=True, text=True, timeout=10,
        )
        val = out.stdout.strip()
        if out.returncode == 0 and val:
            return int(val)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def check_protocol_detachment(cfg):
    """Boot guard (orch-7): detect the workshop running without the protocol.

    Musubi guards docs that are too big (orch-2) and capsules that go stale
    *within* a session (capsule-staleness guard). The outer failure — the
    project's code moving for days while the capsules/comms never move at
    all, because work happened in bare sessions outside the orchestrator —
    was completely silent. Field-tested signature: 58 code commits over six
    days against capsules last updated before any of them; the next session
    then warm-starts from a contradiction soup and the operator blames the
    agents.

    Detection: newest project commit vs the newest sign of life across the
    protocol files (capsule / agent-todo / agent-handoff / comms). Per file,
    freshness = max(last commit touching it, mtime) — mtime so an
    uncommitted-but-current capsule doesn't false-positive; commit ts so the
    signal survives clones and backups. If the gap exceeds
    [orchestrator].detachment_threshold_days (default 2), return a warning
    string for the boot banner (also handed to Oya — a stale picture is
    precisely her altitude). Returns None when healthy, not a git repo, or
    nothing to compare. Limit (honest): only fires at the NEXT launch; bare
    sessions are invisible while they happen."""
    project = cfg.get("project", {}).get("path", ".")
    threshold_days = cfg.get("orchestrator", {}).get(
        "detachment_threshold_days", 2)
    head_ts = _git_last_commit_ts(project)
    if head_ts is None:
        return None  # not a git repo / no commits — nothing to compare

    protocol_paths = [path for label, path in _managed_doc_paths(cfg)
                      if label != "CLAUDE.md"]
    comms_rel = cfg.get("comms", {}).get("file", "")
    if comms_rel:
        protocol_paths.append(
            comms_rel if os.path.isabs(comms_rel)
            else os.path.join(project, comms_rel))

    newest = None
    for path in protocol_paths:
        candidates = [_git_last_commit_ts(project, path)]
        try:
            candidates.append(os.path.getmtime(path))
        except OSError:
            pass
        for ts_val in candidates:
            if ts_val is not None and (newest is None or ts_val > newest):
                newest = ts_val
    if newest is None:
        return None  # no protocol files at all — bootstrap hasn't run; the
        #              missing-docs paths are someone else's warning

    gap_days = (head_ts - newest) / 86400.0
    if gap_days <= threshold_days:
        return None

    n_commits = _git_commit_count_since(project, newest)
    commits_part = (f"{n_commits} commits" if n_commits
                    else "code commits") + " since the protocol files last moved"
    newest_date = datetime.fromtimestamp(newest).strftime("%Y-%m-%d")
    return (f"{commits_part} (gap {gap_days:.0f} days; newest protocol "
            f"update {newest_date}). The protocol has been bypassed — the "
            f"capsules/comms describe a repo that no longer exists. "
            f"Reconcile them with the code before the pair works from them.")


def check_runbook_version_drift(cfg):
    """Boot guard (orch-7, second half): compare the project's installed
    runbook version against the copy this musubi checkout would install.
    A field-report operator sat on a v1.7 fork while v1.9+ shipped every fix
    for the failure mode he then hit — and nothing told him. Returns a
    warning string when this checkout ships a NEWER runbook, else None.
    (A project runbook ahead of the checkout means the musubi clone itself
    is stale — said plainly too.)"""
    project = cfg.get("project", {}).get("path", ".")
    rel = cfg.get("comms", {}).get(
        "runbook", "docs/agents/AGENT_COLLAB_RUNBOOK.md")
    project_runbook = rel if os.path.isabs(rel) else os.path.join(project, rel)
    shipped_runbook = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "docs", "agents", "AGENT_COLLAB_RUNBOOK.md")
    try:
        with open(project_runbook, encoding="utf-8") as f:
            project_v = parse_runbook_version(f.read())
        with open(shipped_runbook, encoding="utf-8") as f:
            shipped_v = parse_runbook_version(f.read())
    except OSError:
        return None
    pv, sv = runbook_version_tuple(project_v), runbook_version_tuple(shipped_v)
    if pv is None or sv is None or pv == sv:
        return None
    if pv < sv:
        return (f"Project runbook is v{project_v}; this musubi ships "
                f"v{shipped_v} — run bootstrap.sh to refresh the managed "
                f"docs (your fork is backed up automatically; diff it first "
                f"if you've customised).")
    return (f"Project runbook is v{project_v} but this musubi checkout ships "
            f"v{shipped_v} — the musubi clone itself looks stale; "
            f"git pull it before relaunching.")


def emit_protocol_health_banner(notes):
    """Loud boot banner for orch-7 findings. `notes` is a list of warning
    strings; empty list → no output."""
    if not notes:
        return
    bar = "─" * 60
    try:
        sys.stdout.write("\a")  # terminal bell
    except Exception:
        pass
    print(f"\n{bar}")
    print("  ⚠ PROTOCOL HEALTH")
    for note in notes:
        print(f"    • {note}")
    print(f"{bar}\n", flush=True)


def recognised_handles(cfg):
    """Return the set of comms handles the running config recognises. Agents
    without a handle (e.g. the oyakata observer) are excluded — a message from
    an unrecognised handle is the orch-3 silent-divergence failure mode."""
    handles = []
    for agent in cfg.get("agents", {}).values():
        if isinstance(agent, dict) and agent.get("handle"):
            handles.append(agent["handle"])
    return handles


_BRACKETED_HANDLE_RE = re.compile(r"\[(@[A-Za-z][\w-]*)\]")


def unrecognised_handles_in(text, known_handles):
    """Return bracketed `[@HANDLE]` tokens in `text` that the running config
    does not recognise, preserving first-seen order. The orch-3 silent-discard
    failure mode: a new agent (e.g. @OYA) posts, but the running orchestrator
    was started before that handle existed in config, so its messages get
    discarded as 'unparseable'. Naming the specific unrecognised handle turns a
    silent drop into an actionable 'restart to load it' signal."""
    known = {h.lstrip("@").upper() for h in known_handles}
    found = []
    seen = set()
    for m in _BRACKETED_HANDLE_RE.finditer(text):
        handle = m.group(1)
        norm = handle.lstrip("@").upper()
        if norm not in known and norm not in seen:
            seen.add(norm)
            found.append(handle)  # preserve first-seen casing
    return found


def print_startup_banner(cfg, config_path):
    """Print a version fingerprint at startup (orch-3 mitigation 1) so the
    operator can spot — against `git log -1` in another terminal — when the
    running process is on stale code or config. The orchestrator's own repo
    dir is the source of truth for the code SHA."""
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    head = _git_head_summary(repo_dir)
    try:
        toml_mtime = datetime.fromtimestamp(os.path.getmtime(config_path)) \
            .strftime("%Y-%m-%d %H:%M")
    except OSError:
        toml_mtime = "unknown"
    agents = ", ".join(sorted(cfg.get("agents", {}).keys()))
    handles = ", ".join(recognised_handles(cfg))
    _log("BOOT", "musubi orchestrator starting")
    _log("BOOT", f"  git HEAD:           {head or 'unknown (not a git checkout)'}")
    _log("BOOT", f"  musubi.toml:        {config_path} (mtime {toml_mtime})")
    _log("BOOT", f"  agents:             {agents or 'none'}")
    _log("BOOT", f"  recognised handles: {handles or 'none'}")


def detect_eperm_uvcwd(pane_text):
    """Return True if `pane_text` contains the Node EPERM uv_cwd crash
    signature. Used during CLI-boot polling to translate the unactionable
    Node stack trace into operator-readable recovery text."""
    return "EPERM" in pane_text and "uv_cwd" in pane_text


def emit_eperm_recovery(pane_label):
    """Emit operator-readable recovery instructions when an agent pane shows
    the EPERM uv_cwd crash. Called once per pane per boot — caller is
    responsible for the dedupe."""
    _log("BOOT", f"ERROR: {pane_label} pane crashed with EPERM uv_cwd (stale cwd handle)")
    _log("BOOT", "  This means the shell's working-directory handle is invalid —")
    _log("BOOT", "  iCloud sync, a folder rename, or an unmount broke it.")
    _log("BOOT", "  Recovery:")
    _log("BOOT", "    1. Close this terminal AND the iTerm/tmux attach window.")
    _log("BOOT", "    2. Open a new terminal.")
    _log("BOOT", "    3. cd ~ first, then cd to your project root.")
    _log("BOOT", "    4. Re-run the launcher.")
    _log("BOOT", "  If this keeps happening, move the project off ~/Desktop/")
    _log("BOOT", "  (or ~/Documents, ~/Downloads) — iCloud sync is the usual cause.")


def check_required_skills(cfg):
    """Warn (but don't refuse) on missing skills declared in [requires.skills].

    Strategic-Oya (v0.3+) leans on gstack skills for the engineering-discipline
    artefacts she watches for — threat models (cso), arch reviews
    (plan-eng-review), pre-landing diff reviews (review). This check surfaces
    the dependency status at startup so the operator sees it before agents
    boot. Missing skills NEVER block startup — strategic-Oya degrades to
    advisory text when core skills are absent, and pair-only musubi works
    regardless of this check.

    The [requires.skills] block is optional. Pre-v0.3 configs that omit it
    get a silent no-op (backwards compatible).

    Skill presence is determined by the existence of `<path>/<name>/SKILL.md`,
    which matches gstack's installed layout (each skill is a directory with
    a SKILL.md inside).
    """
    block = cfg.get("requires", {}).get("skills")
    if not block:
        return  # no declaration → no check

    skill_root = os.path.expanduser(block.get("path", "~/.claude/skills/gstack"))
    core = block.get("core", [])
    recommended = block.get("recommended", [])

    if not core and not recommended:
        return  # block present but empty — nothing to verify

    def _present(name):
        return os.path.isfile(os.path.join(skill_root, name, "SKILL.md"))

    missing_core = [s for s in core if not _present(s)]
    missing_recommended = [s for s in recommended if not _present(s)]

    if missing_core:
        _log("SKILLS", f"WARN — {len(missing_core)}/{len(core)} core skill(s) MISSING under {skill_root}:")
        for s in missing_core:
            _log("SKILLS", f"  ✗ {s} (core)")
        _log("SKILLS", "Strategic-Oya discipline capabilities will degrade. Install gstack or update [requires.skills].core.")
    elif core:
        _log("SKILLS", f"OK — {len(core)}/{len(core)} core skill(s) present under {skill_root}")

    if missing_recommended:
        _log("SKILLS", f"info — {len(missing_recommended)}/{len(recommended)} recommended skill(s) not installed:")
        for s in missing_recommended:
            _log("SKILLS", f"  · {s}")


# ---------------------------------------------------------------------------
# Existing-session classification (orch-5 / Slice 5.5)
# ---------------------------------------------------------------------------

# Process names that mean "this pane has dropped back to a shell prompt" —
# i.e. the agent CLI is no longer running. The list is intentionally short
# and shell-only; we don't try to enumerate "alive" patterns because Claude
# Code, Codex, and their successors report varying process names across
# versions (e.g. `2.1.145`, `claude`, `node`). The reliable signal is the
# inverse: any non-shell foreground process means SOMETHING is running.
KNOWN_SHELLS = ("zsh", "bash", "sh", "fish", "dash", "ksh", "csh", "tcsh")


def pane_in_shell(pane):
    """True if the pane's foreground process is a known shell (i.e. the
    agent CLI has exited or been killed). Returns False on any error —
    we'd rather classify a problematic pane as 'something running' and
    prompt the operator than auto-kill an unknown state."""
    try:
        cmd = (pane.pane_current_command or "").lower()
        return cmd in KNOWN_SHELLS
    except (AttributeError, KeyError):
        return False


def classify_existing_session(session):
    """Classify an existing tmux session into one of three states:

    - 'live'      — the pair panes are running non-shell processes
                    (agent CLIs still alive). Action: auto-attach.
    - 'orphan'    — the pair panes have dropped back to shells (no agent
                    CLIs). Action: auto-kill + recreate, no operator prompt.
    - 'ambiguous' — partial death, wrong pane count, or unexpected layout.
                    Action: prompt the operator with pane-by-pane status.

    Oya pane state is informational only: a dead Oya pane in an otherwise-
    live session is still 'live' (Oya re-spawns on attach via the existing
    orchestrator flow). Oya pane is identified by cwd starting with the
    musubi repo root, mirroring `attach_to_musubi`'s detection.
    """
    try:
        panes = list(session.active_window.panes)
    except Exception:
        return "ambiguous"

    if len(panes) < 2:
        return "ambiguous"

    # All panes are shells → unambiguous corpse, regardless of layout or cwd.
    # This MUST precede Oya-pane detection: after a reboot (or a Ctrl+C'd
    # launch) the dropped-to-shell panes default to the repo-root cwd, which
    # the cwd-based `_is_oya_pane` heuristic below would mistake for the Oya
    # pane — flagging every pane as Oya, leaving zero pair panes, and
    # misclassifying a plain corpse as 'ambiguous' (spurious operator prompt).
    # No agent CLI is running in any pane, so there is no live work to lose.
    if all(pane_in_shell(p) for p in panes):
        return "orphan"

    musubi_root_path = os.path.dirname(os.path.abspath(__file__))

    def _is_oya_pane(p):
        try:
            out = p.cmd("display-message", "-p", "#{pane_current_path}").stdout
            path = (out[0] if out else "") or ""
            return path.startswith(musubi_root_path)
        except Exception:
            return False

    pair_panes = [p for p in panes if not _is_oya_pane(p)]

    # Pair must be exactly 2 panes — anything else is unexpected layout.
    if len(pair_panes) != 2:
        return "ambiguous"

    alive_pair = sum(1 for p in pair_panes if not pane_in_shell(p))

    if alive_pair == 2:
        return "live"
    if alive_pair == 0:
        return "orphan"
    return "ambiguous"


def describe_session_panes(session):
    """Return a list of (pane_id, current_command, is_shell) tuples for
    operator-facing log output. Used in the 'ambiguous' branch so the
    operator sees what state each pane is in before deciding."""
    out = []
    try:
        for p in session.active_window.panes:
            cmd = p.pane_current_command or "?"
            out.append((p.pane_id, cmd, pane_in_shell(p)))
    except Exception:
        pass
    return out


def load_config(path="musubi.toml"):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    validate_config(cfg)
    # Resolve a repo-relative comms file path against project_path so the
    # orchestrator and the agents (whose cwd is project_path) agree on one
    # absolute location. Absolute paths are passed through unchanged.
    comms_file = cfg["comms"]["file"]
    if not os.path.isabs(comms_file):
        cfg["comms"]["file"] = os.path.join(cfg["project"]["path"], comms_file)
    return cfg


# ---------------------------------------------------------------------------
# Send + relay (tmux-side; pure parsing lives in comms.py)
# ---------------------------------------------------------------------------

def send_message(pane, message, cfg=None):
    """Two-step send — paste content, then Enter separately.
    Fixes the pasted-block issue where Claude waits for Enter on long input.

    The inter-step pause is configurable via comms.send_pause_seconds. The
    default (0.5s) works for local tmux; raise it for high-latency setups
    (SSH-attached tmux, remote sessions). cfg is optional so test/util
    callers can omit it."""
    pause = (cfg or {}).get("comms", {}).get("send_pause_seconds", 0.5)
    pane.send_keys(message, enter=False)
    time.sleep(pause)
    pane.send_keys('', enter=True)


# ---------------------------------------------------------------------------
# Operator-action surface — summon the human off the firehose
# ---------------------------------------------------------------------------
# When Oya needs a bounded decision/action from the operator, she writes it to
# the operator-actions capsule. The human can't be `send_keys`'d, so delivery
# to them is an *interrupt*, not a paste: a desktop notification (pull them
# even from another app) + a pin on the tmux status bar (the one surface that
# doesn't scroll with the panes, so the ask can't get buried like a comms
# line). Both are best-effort — a missing notifier or a status-bar quirk must
# never break the relay watcher.

def notify_operator(title, message):
    """Best-effort desktop notification to summon the operator. macOS only
    (osascript); silently no-ops on other platforms or any failure."""
    if sys.platform != "darwin":
        return
    try:
        safe_msg = message.replace('"', "'")[:200]
        safe_title = title.replace('"', "'")[:80]
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "{safe_title}" '
             f'sound name "Glass"'],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def set_actions_statusbar(session, status_text):
    """Pin (or clear) the operator-actions indicator in the tmux status bar.

    status-right is set session-scoped (no `-g`) so we never touch the user's
    global tmux config. An empty `status_text` clears the pin. Best-effort —
    never raises into the watcher loop."""
    if session is None:
        return
    try:
        session.cmd("set-option", "status-right-length", "120")
        session.cmd("set-option", "status-right", status_text or "")
        if status_text:
            # Make sure the bar is visible while something is outstanding.
            session.cmd("set-option", "status", "on")
    except Exception:
        pass


def emit_action_banner(new_items, total_pending):
    """Print a prominent block to the launcher stream when new operator actions
    land, so the calm orchestrator terminal mirrors the status-bar pin. Rings
    the terminal bell once for the batch."""
    bar = "─" * 60
    try:
        sys.stdout.write("\a")  # terminal bell
    except Exception:
        pass
    print(f"\n{bar}")
    print(f"  ⚑ ACTION NEEDED FROM YOU ({total_pending} outstanding)")
    for a in new_items:
        print(f"    • {a['summary']}")
    print("  → reply to Oya in her pane to discharge it")
    print(f"{bar}\n", flush=True)


def emit_refusal_banner(guard, detail):
    """Print a prominent block when the relay starts holding messages back
    (orch-8) — same shape as the action banner so a refusing relay is as
    visible as a pending ask. Fired once per guard per episode; repeat
    refusals only bump the status-bar count. Field-tested failure mode: an
    operator hand-carried every handoff for a whole session because the
    refusal lines had scrolled away and nothing said WHY nothing moved."""
    bar = "─" * 60
    try:
        sys.stdout.write("\a")  # terminal bell
    except Exception:
        pass
    print(f"\n{bar}")
    print(f"  ⛔ RELAY HELD — {guard}")
    print(f"    • {detail}")
    print("  → the watcher is holding messages back ON PURPOSE; the writer")
    print("    pane has been told how to clear it. Nothing relays until it does.")
    print(f"{bar}\n", flush=True)


# ---------------------------------------------------------------------------
# Relay
# ---------------------------------------------------------------------------

def relay_instruction(message_block, sender, p_claude, p_codex, cfg):
    """Send the message to whichever agents need to act on it.

    OPUS  → relay to CODA only (pair-pattern)
    CODA  → relay to OPUS only (pair-pattern)
    OYAKATA → relay to BOTH agents. Oya's messages address one or both
              of the pair via the `To:` field in the message body; the
              orchestrator delivers to both panes and the addressed
              agent acts on it. Never relayed back to Oya — that loop
              is guarded inside relay_to_oyakata().
    """
    comms_file = cfg["comms"]["file"]
    over = cfg["comms"]["over_signal"]

    sender_key = sender.lower()
    from_handle = cfg["agents"].get(sender_key, {}).get(
        "handle", f"@{sender.upper()}"
    )
    instruction = (
        f"New message in {comms_file} from {from_handle}:\n\n"
        f"{message_block}\n\n"
        f"Read the comms file, action this, and append your reply with {over} when done."
    )
    if sender == "OPUS":
        print(f"\n[{ts()}] [RELAY -> CODA]")
        send_message(p_codex, instruction, cfg)
    elif sender == "CODA":
        print(f"\n[{ts()}] [RELAY -> OPUS]")
        send_message(p_claude, instruction, cfg)
    elif sender == "OYAKATA":
        print(f"\n[{ts()}] [RELAY @OYA -> OPUS + CODA]")
        send_message(p_claude, instruction, cfg)
        send_message(p_codex, instruction, cfg)
    else:
        print(f"\n[{ts()}] [RELAY] Unknown sender {sender!r}; not relaying.")


# ---------------------------------------------------------------------------
# Wake-loop circuit-breaker (burn-1 follow-up)
# ---------------------------------------------------------------------------

# Every pane keystroke-nudge (the silence watchdog + the park watchdog) provokes
# an agent turn, which reloads that agent's whole context — the per-event cost
# that, multiplied by an unattended auto-wake loop running for hours across
# several apps, was the 2026-06-30 token-burn. The size-rotation fix shrank the
# context each turn reloads; this bounds how OFTEN we provoke a turn at all.
#
# The signal is a sliding-window rate cap, not a progress check: a wake only ever
# fires while the channel is already stuck (quiet/parked past threshold), so in a
# healthy session that makes real progress, wakes are sporadic and the window
# never fills. A SUSTAINED max-rate of wakes means a sustained stuck channel that
# the nudges are not clearing — a self-feeding loop — and we stop feeding it and
# alarm the operator instead of quietly burning tokens until the cap.
WAKE_GOVERNOR_MAX_DEFAULT = 10        # nudges allowed per window before tripping
WAKE_GOVERNOR_WINDOW_DEFAULT = 3600   # window, seconds (default: 10 nudges / hour)


class WakeGovernor:
    """Sliding-window rate limiter for pane keystroke-nudges (burn-1 follow-up).

    allow(now) records the wake and returns True while under the cap; once
    `max_wakes` events fall inside `window_secs` it returns False (tripped) and
    records nothing, so the breaker self-heals as old events age out of the
    window — an enforced cooldown, no manual re-arm. max_wakes <= 0 disables it
    (always allows)."""

    def __init__(self, max_wakes=WAKE_GOVERNOR_MAX_DEFAULT,
                 window_secs=WAKE_GOVERNOR_WINDOW_DEFAULT):
        self.max_wakes = max_wakes
        self.window_secs = window_secs
        self._events = deque()
        self.tripped = False

    def _prune(self, now):
        cutoff = now - self.window_secs
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()

    def allow(self, now):
        if self.max_wakes <= 0:
            return True  # disabled
        self._prune(now)
        if len(self._events) >= self.max_wakes:
            self.tripped = True
            return False
        self.tripped = False
        self._events.append(now)
        return True

    @property
    def count(self):
        return len(self._events)


# ---------------------------------------------------------------------------
# Main watcher loop
# ---------------------------------------------------------------------------

def watch_and_relay(p_claude, p_codex, cfg, session=None, oya_boot_note=None):
    """Watch comms file for <OVER> signals and relay to the other agent.

    When [agents.oyakata].enabled is true and `session` is supplied, also
    relays each parsed message to a discovered Oya pane and emits
    capsule-edit notifications. session is optional so attach_to_musubi
    can call this without the oyakata layer if it wishes.

    `oya_boot_note` (orch-7): protocol-health warning detected at boot,
    delivered once to the Oya pane when it's discovered — the picture she
    orients from may be days behind the code, and she should say so.
    """
    comms_file = cfg["comms"]["file"]
    over = cfg["comms"]["over_signal"]
    over_re = over_pattern(over)
    stall_secs = cfg.get("comms", {}).get("stall_seconds", 45)

    print(f"\nWatching {comms_file} for {over} signals...")
    print("Press Ctrl+C to stop.\n")

    # Resume just past the last over-signal, NOT raw EOF: a raw-EOF start on a
    # live file (--attach relaunch) lands mid-message whenever an agent is
    # mid-append at that instant — the head is never read and the tail gets
    # quarantined as unparseable. Field bug, okami bed 2026-06-11.
    last_offset = resume_offset(comms_file, cfg)
    # Memory of recently-relayed blocks. Guards against re-delivery after a file
    # shrink/rotation re-read (last_offset resets to 0 and the whole active
    # comms file is re-drained) and after a mid-drain failure retry — the window
    # must cover a whole cycle, see RECENTLY_RELAYED_WINDOW. Deliberately NOT fed
    # by guard refusals: a refused message that the agent fixes (capsule updated)
    # and re-posts VERBATIM must relay, not vanish — field bug, 2026-06-06.
    recently_relayed = deque(maxlen=RECENTLY_RELAYED_WINDOW)
    last_size_seen = last_offset
    last_growth_time = time.time()
    nudged_at_size = None
    # Rolling rotation (relay-1, 2026-06-27): keep active.txt from growing
    # unbounded across a long session — the bloat that otherwise forces a manual
    # orchestrator "bounce". The watcher itself archives + resets at a fully-
    # drained, quiet boundary (see the rotation_due call below), so it can never
    # orphan a mid-compose tail the way an externally-timed truncate can.
    # rotate_max_bytes = 0 disables.
    rotate_max_bytes = cfg.get("comms", {}).get("rotate_max_bytes", 200_000)
    rotate_quiet_secs = cfg.get("comms", {}).get("rotate_quiet_seconds", 60)
    _rotate_archive_dir = resolve_archive_dir(cfg)
    # Count consecutive idle messages to break ack-of-ack chains: when both
    # agents repeatedly post "NOT STARTED / holding / awaiting" without a
    # state transition, the orchestrator stops relaying after the third one
    # and nudges the writer to either claim a slice or name a real blocker.
    idle_streak = 0
    ACK_OF_ACK_LIMIT = 3
    # Track repeated parse failures at the same content size so we don't
    # busy-loop forever on a malformed message (e.g., agent wrote <OVER>
    # without the [@HANDLE] header). After UNPARSEABLE_RETRY_LIMIT ticks on
    # the same size, advance past the content with a clear log line.
    unparseable_at_size = None
    unparseable_retries = 0
    UNPARSEABLE_RETRY_LIMIT = 3

    # Silence watchdog (idle-1). The stall nudge below only fires on a
    # half-written message (new content without the over-signal). It does NOT
    # cover the channel going FULLY quiet after everything has been relayed:
    # the pair does not self-continue after a turn, and if Oya has also parked,
    # the whole workshop sleeps until a human pokes it. That is the "they go
    # idle the moment I walk away" failure (field report 2026-06-20, which Oya
    # self-admitted: "I posted work to the coders and then went quiet … every-
    # thing fell asleep, including me"). When the channel is quiet for
    # idle_wake_secs with nothing pinned for the operator, we wake the
    # orchestration layer — the built-in equivalent of the operator's proven
    # `/loop 5m` Oya cadence. Default 300s; set [comms].idle_wake_seconds = 0
    # to disable.
    idle_wake_secs = cfg.get("comms", {}).get("idle_wake_seconds", 300)
    silence_nudges = 0
    last_silence_nudge_time = 0.0

    # Wake-loop circuit-breaker (burn-1 follow-up). Bounds how often the silence
    # and park watchdogs may keystroke-nudge a pane (each nudge = an agent turn =
    # a context reload = tokens). Sized so a healthy session's sporadic wakes
    # never trip it, but a sustained unattended self-feeding loop does — at which
    # point we suppress the nudge and alarm the operator instead of burning
    # tokens to the cap. [comms].max_wakes_per_window = 0 disables.
    wake_gov = WakeGovernor(
        max_wakes=cfg.get("comms", {}).get("max_wakes_per_window",
                                           WAKE_GOVERNOR_MAX_DEFAULT),
        window_secs=cfg.get("comms", {}).get("wake_window_seconds",
                                             WAKE_GOVERNOR_WINDOW_DEFAULT))
    _wake_was_tripped = False

    def _wake_allowed(now):
        """Gate a pane keystroke-nudge through the circuit-breaker. Returns True
        if the nudge may fire; on the trip edge surfaces ONE operator alarm and
        suppresses it. Self-heals (re-arms) once the rate falls back under cap."""
        nonlocal _wake_was_tripped
        if wake_gov.allow(now):
            if _wake_was_tripped:
                _wake_was_tripped = False
                _log("WATCHER", "wake-loop circuit-breaker re-armed — nudge rate "
                                "fell back under cap; auto-wake resumed.")
            return True
        if not _wake_was_tripped:
            _wake_was_tripped = True
            mins = wake_gov.window_secs / 60.0
            _surface_refusal("wake-runaway",
                f"auto-wake paused — {wake_gov.max_wakes} pane nudges fired in "
                f"~{mins:.0f} min and the channel is still stuck. That is the "
                f"self-feeding loop that burns tokens unattended (the 2026-06-30 "
                f"incident). Check the panes or stop the loop; auto-wake re-arms "
                f"on its own once the nudge rate falls.")
            _log("WATCHER", f"wake-loop circuit-breaker TRIPPED — suppressing "
                            f"nudges ({wake_gov.count} in window).")
        return False

    opus_handle = cfg["agents"]["opus"]["handle"]
    coda_handle = cfg["agents"]["coda"]["handle"]

    # Oyakata observation layer (optional). p_oyakata is rediscovered on each
    # tick until found, then cached. The spike script adds the pane after
    # orchestrator startup, so the initial discovery may return None.
    oya_active = oyakata_enabled(cfg) and session is not None
    p_oyakata = discover_oyakata_pane(session, cfg) if oya_active else None
    oya_pane_announced = p_oyakata is not None
    if oya_active and p_oyakata is None:
        print(f"[{ts()}] [WATCHER] Oyakata enabled in config but pane not yet "
              f"found — will retry on each tick until it appears.")
    if oya_pane_announced:
        print(f"[{ts()}] [WATCHER] Oyakata pane discovered: {p_oyakata.pane_id}")

    # orch-7: protocol-health note for Oya, delivered once on pane discovery.
    def _deliver_oya_boot_note(pane):
        send_message(pane,
            f"[ORCHESTRATOR boot check] Protocol health warning for this "
            f"project: {oya_boot_note} Factor this into your picture — the "
            f"capsules and comms you orient from may be behind the code. "
            f"Flag it to the pair if they warm-start from them uncritically.",
            cfg)
        _log("WATCHER", "delivered orch-7 protocol-health note to Oya")

    if oya_boot_note and p_oyakata is not None:
        _deliver_oya_boot_note(p_oyakata)
        oya_boot_note = None  # once only

    # Capsule-edit watcher: notify Oya when current-state.md mtime changes.
    capsule_rel = cfg["comms"].get("capsule", "docs/agents/current-state.md")
    capsule_path = capsule_rel if os.path.isabs(capsule_rel) \
        else os.path.join(cfg["project"]["path"], capsule_rel)
    try:
        last_capsule_mtime = os.path.getmtime(capsule_path)
    except FileNotFoundError:
        last_capsule_mtime = 0

    # Heartbeat / backpressure: track relays sent to Oya since Oya last
    # wrote to its log. If the gap exceeds the configured threshold, warn
    # the operator that Oya may be falling behind.
    oya_log_rel = cfg.get("agents", {}).get("oyakata", {}).get(
        "log_path", "docs/agents/oyakata-log.md")
    oya_log_path = oya_log_rel if os.path.isabs(oya_log_rel) \
        else os.path.join(cfg["project"]["path"], oya_log_rel)
    try:
        last_oya_log_mtime = os.path.getmtime(oya_log_path)
    except FileNotFoundError:
        last_oya_log_mtime = 0
    oya_pending_count = 0
    oya_threshold = cfg.get("agents", {}).get("oyakata", {}).get(
        "heartbeat_threshold", 5)
    oya_warned_at_count = None

    # Tier-2 pending-decision tracking. Each request id is added once we've
    # notified Oya; the hook deletes the request file after consuming the
    # verdict, so we don't need to remove entries on success — uuid4
    # collisions are not a concern. Memory is bounded by cycle length.
    tier2_seen_request_ids: set = set()
    tier2_permissions_enabled = oyakata_permissions_enabled(cfg)

    # Operator-action surface. Oya writes a pending item to the operator-actions
    # capsule when she needs a bounded decision from the human; we watch its
    # mtime (same pattern as the capsule-edit watcher) and, on change, pin the
    # outstanding asks to the tmux status bar + notify on genuinely-new ones.
    # The file is a state snapshot, not a log — parsed fresh on every change.
    oa_active = operator_actions_enabled(cfg) and session is not None
    oa_path = resolve_operator_actions_path(cfg) if oa_active else None
    oa_seen_keys: set = set()
    oa_last_mtime = 0
    if oa_active:
        try:
            oa_last_mtime = os.path.getmtime(oa_path)
            with open(oa_path, encoding="utf-8") as f:
                existing = parse_operator_actions(f.read())
        except FileNotFoundError:
            existing = []
        # Prime seen-keys + the pin from any already-outstanding actions so a
        # re-attach shows the pin but does NOT re-notify for old asks.
        oa_seen_keys = {a["key"] for a in existing}
        oa_status_text = format_actions_status(existing)
        set_actions_statusbar(session, oa_status_text)
        print(f"[{ts()}] [ACTION] operator-action surface active — watching "
              f"{oa_path} ({len(existing)} outstanding)")
    else:
        oa_status_text = ""

    # Operator-input relay (oyakata-11). The input half of the operator
    # console: the console pane appends the operator's messages to
    # operator-input.md, and we relay each new entry into Oya's pane — exactly
    # the path comms relays take. The operator types into a single-writer pane
    # instead of Oya's relay-fed pane, so their keystrokes are never
    # overwritten by send-keys traffic. Append-only log: we track a byte offset
    # and relay only newly-appended entries, priming the offset to current EOF
    # so pre-existing content isn't replayed on boot.
    oi_active = operator_input_enabled(cfg) and session is not None
    oi_path = resolve_operator_input_path(cfg) if oi_active else None
    oi_offset = 0
    if oi_active:
        try:
            oi_offset = os.path.getsize(oi_path)
        except FileNotFoundError:
            oi_offset = 0
        print(f"[{ts()}] [INPUT] operator-input relay active — watching "
              f"{oi_path}")

    # Relay-health surface (orch-8). A refusing relay is invisible from the
    # agent panes — the operator experiences it as "the relay is broken" and
    # starts hand-carrying messages by hand. Track refusals per guard since
    # the last successful pair relay and surface them on the SAME interrupt
    # surface as operator actions (status-bar pin + desktop notification +
    # banner), not just the scrolling watcher log. The pin clears itself the
    # moment a message relays normally.
    refusal_counts = {}    # guard name -> refusals this episode
    refusal_notified = set()  # guards already notified/bannered this episode

    def _pin_status():
        """Re-pin status-right composing both surfaces (actions + refusals)."""
        set_actions_statusbar(session, compose_status_right(
            oa_status_text, format_relay_refusal_status(refusal_counts)))

    def _surface_refusal(guard, detail):
        """Record a relay refusal and interrupt the operator on the first one
        of each guard per episode. Repeats bump the pinned count only."""
        refusal_counts[guard] = refusal_counts.get(guard, 0) + 1
        _pin_status()
        if guard not in refusal_notified:
            refusal_notified.add(guard)
            notify_operator("musubi — relay held", f"{guard}: {detail}")
            emit_refusal_banner(guard, detail)

    def _clear_refusals():
        """A message relayed normally — the episode is over; clear the pin."""
        if refusal_counts:
            _log("WATCHER", f"relay flowing again — clearing "
                            f"{sum(refusal_counts.values())} surfaced refusal(s)")
            refusal_counts.clear()
            refusal_notified.clear()
            _pin_status()

    def _wake_idle_channel(idle_s, nudge_num):
        """Idle-1: the channel has gone fully quiet with work presumably open.
        Wake the orchestration layer so the pair doesn't sleep until a human
        pokes it. Prefer Oya — she owns the overview and can re-drive the pair;
        fall back to nudging the coders directly on a pair-only bed. On a second
        nudge within the same silence, escalate to the operator surface: the
        agents aren't self-clearing, so the human should look.

        Pane-collision guard (idle-1 hardening 2026-06-22): a coder pane often
        parks with its next action TYPED BUT UNSENT (`❯ continue S2`). Keying a
        nudge into that pane appends to and garbles the pending line — which is
        why Oya refuses to comms-nudge a parked coder by hand. So we skip the
        keystroke on any pane that shows pending input and route the operator to
        clear it instead — the human is the only one who can submit that line."""
        mins = idle_s / 60.0
        skipped = []  # panes we could not safely key (unsent input present)

        def _safe_nudge(pane, label, msg):
            if pane_has_pending_input(pane):
                skipped.append(label)
                _log("WATCHER", f"idle watchdog: {label} pane has an unsent "
                                f"typed line — skipped keystroke to avoid "
                                f"garbling it; routing the operator to clear it.")
                return False
            send_message(pane, msg, cfg)
            return True

        if oya_active and p_oyakata is not None:
            _safe_nudge(p_oyakata, "Oya",
                f"[idle watchdog] The comms channel has been silent for "
                f"{idle_s:.0f}s (~{mins:.0f} min) and nothing is pinned for the "
                f"operator. You own the orchestration overview — do not let the "
                f"workshop sit idle. Check whether the open slice is actually "
                f"progressing: if a coder parked after its turn, wake it "
                f"(@OPUS / @CODA) with the next concrete step; if it's genuinely "
                f"blocked, name the blocker or pin an operator action; if the "
                f"cycle is legitimately complete and waiting on @LEAD, pin that "
                f"as an operator action so this watchdog stays quiet.")
            if not skipped:
                _log("WATCHER", f"idle watchdog: woke Oya after {idle_s:.0f}s "
                                f"silence (nudge {nudge_num}).")
        else:
            _safe_nudge(p_claude, "Opus",
                f"[idle watchdog] The comms channel has been silent for "
                f"{idle_s:.0f}s (~{mins:.0f} min). If you have an open slice, "
                f"post your next concrete step or a real blocker to the comms "
                f"file — do not park after your turn. If your work is genuinely "
                f"done and waiting on a decision, say so explicitly.")
            _safe_nudge(p_codex, "Coda",
                f"[idle watchdog] The comms channel has been silent for "
                f"{idle_s:.0f}s (~{mins:.0f} min). If you have an open slice, "
                f"post your next concrete step or a real blocker to the comms "
                f"file — do not park after your turn. If your work is genuinely "
                f"done and waiting on a decision, say so explicitly.")
            if not skipped:
                _log("WATCHER", f"idle watchdog: nudged both coders after "
                                f"{idle_s:.0f}s silence (nudge {nudge_num}).")
        # Escalate to the operator surface when (a) a persistent stall the agents
        # can't self-clear (2nd nudge), OR (b) we had to skip a pane because it
        # holds an unsent line — only the human can submit that line. A normal
        # pair relay clears the pin.
        if nudge_num >= 2 or skipped:
            detail = (f"channel silent ~{mins:.0f} min and not self-clearing — "
                      f"the pair may have parked. Check the panes.")
            if skipped:
                detail = (f"channel silent ~{mins:.0f} min; "
                          f"{'/'.join(skipped)} pane(s) have an UNSENT typed line "
                          f"— press Enter (or Ctrl-U to clear) so they submit. "
                          f"Watchdog won't key a pane with pending input.")
            _surface_refusal("idle-stall", detail)

    # Mid-session staleness detection (orch-3 mitigation 2). Capture the
    # orchestrator repo's HEAD at startup and re-check periodically; warn once
    # if it advances, because code/config changes don't take effect until the
    # process restarts. Cheap (`git rev-parse` every ~2 min, not every tick).
    _musubi_repo_dir = os.path.dirname(os.path.abspath(__file__))
    startup_head = _git_head_sha(_musubi_repo_dir)
    STALENESS_CHECK_EVERY = 40  # ticks (~2 min at 3s/tick)
    _tick_count = 0
    _staleness_warned = False

    # Context-budget watchdog (2026-06-22; dead-vs-live split 2026-06-27). A heavy
    # implementer session slows, then dies once its context fills. Watch each
    # coder pane for the "/clear to save <N>k tokens" pressure hint and surface an
    # operator warning. The remedy depends on whether the pane is still LIVE or
    # already DEAD (see context_regime):
    #   - live  -> recommend `/compact` (frees context, CONTINUES the session; no
    #              restart). This is the common case — the operator does NOT need
    #              to restart a heavy-but-running pane.
    #   - dead  -> recommend relaunch (a /compact can't recover a context-dead
    #              pane). Only reached when the pane is idle AND frozen past the
    #              park threshold.
    # Threshold in thousands of tokens; [comms].context_warn_k = 0 disables.
    # Warned-once per pane until the pressure clears (a /compact/clear/relaunch
    # drops the figure back down); a live->dead transition re-surfaces once so a
    # pane that dies after the first /compact nudge still escalates to relaunch.
    context_warn_k = cfg.get("comms", {}).get("context_warn_k", 400)
    CONTEXT_CHECK_EVERY = 10  # ticks (~30s at 3s/tick)
    _context_warned = {"Opus": False, "Coda": False}
    _context_regime = {"Opus": None, "Coda": None}   # last surfaced: None/live/dead
    _context_last_buf = {"Opus": None, "Coda": None}  # for the freeze (dead) test
    _context_frozen_since = {"Opus": time.time(), "Coda": time.time()}

    # Permission-modal watchdog (stall-class 1, 2026-06-24). A relay-dependent
    # pane blocked on a permission/approval modal is silent — no event fires and
    # a send_keys nudge lands IN the modal. Detection is always on (no config to
    # disable a safety alarm); we surface the SPECIFIC ask to the operator and
    # never keystroke. Re-armed per pane once the modal clears so a fresh prompt
    # alarms again. Same ~30s cadence as the context check — modal halts run for
    # tens of minutes, so 30s detection is ample.
    MODAL_CHECK_EVERY = 10  # ticks (~30s at 3s/tick)
    _modal_surfaced = {"Opus": False, "Coda": False, "Oya": False}

    # Per-pane park watchdog (stall-class 3, 2026-06-24). The channel-level
    # silence watchdog (idle-1) only fires when the WHOLE channel goes quiet; a
    # single coder that parks after its own non-terminal turn while the other is
    # still posting is invisible to it (channel isn't quiet). This catches that:
    # a pane that is IDLE (not working / not at a modal / no unsent line) and has
    # not changed for pane_idle_seconds gets one next-step nudge, then escalates
    # to the operator if it still doesn't self-clear. Coders only — Oya's quiet
    # is legitimate (collecting/heartbeat) and her log-mtime heartbeat + the
    # silence watchdog already cover her. [comms].pane_idle_seconds = 0 disables.
    pane_idle_secs = cfg.get("comms", {}).get("pane_idle_seconds", 240)
    PARK_CHECK_EVERY = 10  # ticks (~30s at 3s/tick)
    _park_idle_since = {"Opus": time.time(), "Coda": time.time()}
    _park_last_buf = {"Opus": None, "Coda": None}
    _park_nudges = {"Opus": 0, "Coda": 0}

    # Comms-drop watchdog (stall-class 2, 2026-06-24). The S3/S4 field bug: a
    # reviewer's verdict landed in the capsule but the comms append did NOT reach
    # EOF, so no relay fired and no event reached anyone — the implementer held
    # ~12 min for a baton that never came. The mid-cycle fix (true-EOF append)
    # addressed the cause; this is the missing DETECTOR. Signature: the capsule
    # advanced (a verdict/state landed) while the comms channel is fully relayed
    # and quiet, and no append follows within baton_grace_seconds. Far faster +
    # more diagnostic than waiting for the 300s channel-silence net. Tracked with
    # its OWN capsule-mtime so it never interferes with the Oya capsule-edit
    # watcher. [comms].baton_grace_seconds = 0 disables.
    baton_grace_secs = cfg.get("comms", {}).get("baton_grace_seconds", 90)
    try:
        _baton_capsule_mtime = os.path.getmtime(capsule_path)
    except FileNotFoundError:
        _baton_capsule_mtime = 0
    _baton_armed_at = None      # time the capsule advanced over a quiet channel
    _baton_size_at_arm = None   # comms size at arm (an append past it = baton ok)
    _baton_surfaced = False

    known_handles = recognised_handles(cfg)

    def _process_block(message_block):
        """Run ONE comms message through the full relay pipeline: duplicate
        skip → sender detection → Oya observation relay → pair-protocol
        guards → relay to the peer. Called once per block by the drain loop;
        a `return` here means "done with this block", never "skip the rest
        of the span". Raises propagate to the watcher's outer handler so the
        whole span retries with the offset untouched."""
        nonlocal idle_streak, oya_pending_count, oya_warned_at_count

        if message_block in recently_relayed:
            print(f"[{ts()}] [WATCHER] Skipping duplicate of an already-relayed "
                  f"message (span retry or rotation re-read).")
            return

        sender = detect_sender(message_block, cfg)
        if not sender:
            print(f"[{ts()}] [WATCHER] Could not detect sender — skipping.")
            return

        # Oyakata observation relay: send the parsed event to Oya BEFORE
        # the guard checks. Oya sees every message regardless of whether
        # the orchestrator subsequently refuses to relay it to the pair —
        # guard-blocked events are themselves signals worth observing.
        if oya_active and p_oyakata is not None:
            relay_to_oyakata(message_block, sender, p_oyakata, cfg)
            oya_pending_count += 1
            if oya_pending_count >= oya_threshold and oya_warned_at_count != oya_pending_count:
                print(f"[{ts()}] [WATCHER] WARNING: Oya has not written to "
                      f"{oya_log_path} since {oya_pending_count} relays "
                      f"(threshold {oya_threshold}). Possible backpressure "
                      f"or quiet collection — check the Oya pane.")
                oya_warned_at_count = oya_pending_count

        # Oya is exempt from the pair-protocol guards. Her messages are
        # Notes / Recommendations / Pauses / Escalations — not idle-result
        # acks and not state-affecting from the runbook's perspective.
        # Skip the guards entirely for OYAKATA-sender messages.
        if sender == "OYAKATA":
            relay_instruction(message_block, sender, p_claude, p_codex, cfg)
            recently_relayed.append(message_block)
            print(f"[{ts()}] [@OYA -> OPUS + CODA] Relayed.")
            return

        # Ack-of-ack guard: if this is the Nth consecutive idle message,
        # refuse to relay and prompt the writer to either claim a slice
        # or name a real blocker. Resets on any non-idle Result.
        # NOTE: refused blocks are deliberately NOT added to the
        # recently-relayed memory — an agent that fixes the cause and
        # re-posts the same message verbatim must get a fresh evaluation,
        # not a silent drop (field bug, 2026-06-06).
        result = parse_result_field(message_block)
        if is_idle_result(result):
            idle_streak += 1
            if idle_streak >= ACK_OF_ACK_LIMIT:
                writer_pane = p_claude if sender == "OPUS" else p_codex
                print(f"[{ts()}] [WATCHER] Ack-of-ack chain detected "
                      f"({idle_streak} consecutive idle messages). Refusing relay.")
                send_message(writer_pane,
                    f"Ack-of-ack guard triggered: {idle_streak} consecutive idle messages "
                    f"in the comms file. Refusing to relay. Either claim a slice with a "
                    f"concrete first action, name a real blocker, or stop responding to "
                    f"break the loop. See the runbook's Comms Protocol section.",
                    cfg
                )
                # orch-8: interrupt the operator — a held relay must not
                # hide in the scrolling watcher log.
                _surface_refusal(
                    "idle-streak",
                    f"{idle_streak} consecutive idle messages — the pair is "
                    f"acknowledging, not working. A slice claim clears it.")
                return
        else:
            idle_streak = 0

        # Capsule-staleness guard: state-affecting messages require the
        # capsule to have been updated within CAPSULE_FRESHNESS_WINDOW_SECONDS,
        # per the capsule-before-comms invariant. State-affecting covers:
        #   - Types: Review Request / Decision / Blocker (protocol-level
        #     state assertions)
        #   - Results: state-transition values from the six-state vocab
        #     (started / blocked / completed / spawned / confirmed_running)
        #     on any Type — so an Update reporting Result=started also
        #     triggers the guard. Refuse the relay and nudge the writer.
        msg_type = message_type(message_block)
        if is_state_affecting(msg_type, message_block) and capsule_is_stale(cfg):
            cap_rel = cfg["comms"].get("capsule", "docs/agents/current-state.md")
            writer_pane = p_claude if sender == "OPUS" else p_codex
            print(f"[{ts()}] [WATCHER] Capsule-stale on {msg_type!r} from {sender}. Refusing relay.")
            send_message(writer_pane,
                f"Capsule-stale guard triggered: your {msg_type!r} message was posted "
                f"without updating {cap_rel} in the last "
                f"{CAPSULE_FRESHNESS_WINDOW_SECONDS // 60} minutes. Per the runbook's "
                f"capsule-before-comms invariant, update the capsule first, then re-post.",
                cfg
            )
            # orch-8: interrupt the operator — a held relay must not hide
            # in the scrolling watcher log.
            _surface_refusal(
                "capsule-stale",
                f"{msg_type or 'state-affecting message'} from {sender} held — "
                f"the capsule ({cap_rel}) hasn't been updated. "
                f"Capsule first, then re-post.")
            return

        relay_instruction(message_block, sender, p_claude, p_codex, cfg)
        recently_relayed.append(message_block)
        print(f"[{ts()}] [{sender} -> {'CODA' if sender == 'OPUS' else 'OPUS'}] Relayed.")
        # orch-8: a normal pair relay ends any refusal episode — clear the
        # pinned warning so the surface only ever shows live problems.
        # (Deliberately NOT cleared on Oya relays above: she is guard-exempt,
        # so her messages flowing says nothing about the pair being unstuck.)
        _clear_refusals()

        # A1: on a slice claim/start, auto-fire the discipline scope sensor
        # over the receipt's declared file targets and surface any triggered
        # engineering disciplines to Oya. Self-gates on file-target presence
        # and Oya availability; forgiving authority (informs, never blocks).
        if (oya_active and p_oyakata is not None and result
                and any(s in result.lower() for s in ("claimed", "started"))):
            flag_disciplines_to_oyakata(
                message_block, p_oyakata, cfg, _musubi_repo_dir)

    while True:
        try:
            time.sleep(3)
            current_size = get_file_size(comms_file)

            # Periodic staleness check (orch-3): has the running code drifted
            # from disk? Warn once, then stay quiet to avoid log spam.
            _tick_count += 1
            if (startup_head and not _staleness_warned
                    and _tick_count % STALENESS_CHECK_EVERY == 0):
                current_head = _git_head_sha(_musubi_repo_dir)
                if current_head and current_head != startup_head:
                    _log("WATCHER", f"WARNING: musubi HEAD advanced "
                                    f"{startup_head} -> {current_head}. This process is "
                                    f"running STALE code/config — restart the orchestrator "
                                    f"to load it.")
                    _staleness_warned = True

            # Context-budget watchdog: warn the operator before a coder pane
            # dies of context exhaustion (a nudge can't recover it). Cheap —
            # capture every ~30s, not every tick.
            if context_warn_k > 0 and _tick_count % CONTEXT_CHECK_EVERY == 0:
                for pane, label in ((p_claude, "Opus"), (p_codex, "Coda")):
                    # Capture enough lines to BOTH read the pressure hint and
                    # classify the pane state (modal/working markers sit in the
                    # tail too). 40 mirrors capture_pane's default.
                    buf = capture_pane(pane, lines=40)
                    pressure = parse_context_pressure_k(buf)
                    now = time.time()
                    # Freeze tracker for the dead test: a pane whose tail keeps
                    # changing (spinner/timer/new output) is alive; one frozen
                    # past the park threshold while idle is very likely dead.
                    if buf != _context_last_buf[label]:
                        _context_last_buf[label] = buf
                        _context_frozen_since[label] = now
                    frozen_secs = now - _context_frozen_since[label]
                    regime = context_regime(
                        pressure, context_warn_k, classify_pane_state(buf),
                        frozen_secs, pane_idle_secs)
                    if regime is not None:
                        # Surface on first warn OR on a live->dead escalation, so a
                        # pane that dies after the first /compact nudge still gets
                        # the relaunch message. dead->live is not re-surfaced.
                        escalated = (_context_regime[label] == "live"
                                     and regime == "dead")
                        if not _context_warned[label] or escalated:
                            _context_warned[label] = True
                            _context_regime[label] = regime
                            guard = f"context-budget-{label.lower()}"
                            head = (f"{label} pane is at ~{pressure:.0f}k tokens "
                                    f"(>= {context_warn_k}k)")
                            if regime == "dead":
                                _surface_refusal(guard,
                                    f"{head} and has been idle/frozen ~{frozen_secs:.0f}s "
                                    f"— likely context-DEAD. /compact can't recover a "
                                    f"dead pane; relaunch it (re-attach). State is safe "
                                    f"on disk/capsule, so a fresh pane resumes from there.")
                            else:
                                _surface_refusal(guard,
                                    f"{head} but still LIVE. Run /compact in its pane at "
                                    f"the next clean boundary — it frees context and "
                                    f"CONTINUES the session (no restart). /clear only at a "
                                    f"clean boundary; relaunch only if it later goes "
                                    f"unresponsive. State is safe on disk/capsule.")
                            _log("WATCHER", f"context watchdog: {label} at "
                                            f"~{pressure:.0f}k tokens, regime={regime} "
                                            f"— warned operator.")
                    else:
                        # Pressure cleared (refresh/restart) — re-arm the warning
                        # so a fresh climb past the threshold warns again. Also
                        # clear the refusal-notify state for this guard, else
                        # _surface_refusal stays silent for the rest of the episode.
                        if _context_warned[label]:
                            guard = f"context-budget-{label.lower()}"
                            refusal_notified.discard(guard)
                            refusal_counts.pop(guard, None)
                            _pin_status()
                        _context_warned[label] = False
                        _context_regime[label] = None

            # Oya pane: lazy discovery — keep trying until found, then cache.
            if oya_active and p_oyakata is None:
                p_oyakata = discover_oyakata_pane(session, cfg)
                if p_oyakata is not None and not oya_pane_announced:
                    print(f"[{ts()}] [WATCHER] Oyakata pane discovered mid-session: "
                          f"{p_oyakata.pane_id}")
                    oya_pane_announced = True
                if p_oyakata is not None and oya_boot_note:
                    _deliver_oya_boot_note(p_oyakata)
                    oya_boot_note = None  # once only

            # Permission-modal watchdog (stall-class 1): surface any pane sitting
            # at a blocking permission/approval prompt to the operator — the only
            # one who can answer it. Never keystroke a modal. Re-arm per pane when
            # the modal clears. Covers the workers AND Oya (today's live stall was
            # Oya parked on an oyakata-log.md edit prompt).
            if _tick_count % MODAL_CHECK_EVERY == 0:
                modal_panes = [(p_claude, "Opus"), (p_codex, "Coda")]
                if oya_active and p_oyakata is not None:
                    modal_panes.append((p_oyakata, "Oya"))
                for pane, label in modal_panes:
                    question = pane_permission_modal(pane)
                    guard = f"perm-modal-{label.lower()}"
                    if question is not None:
                        if not _modal_surfaced[label]:
                            _modal_surfaced[label] = True
                            _surface_refusal(
                                guard,
                                f"{label} is blocked on a permission prompt: "
                                f"\"{question}\" — approve or deny it in the "
                                f"{label} pane. A relay nudge can't clear a modal.")
                            _log("WATCHER", f"modal watchdog: {label} blocked on "
                                            f"a permission prompt — surfaced to "
                                            f"operator ({question!r}).")
                    elif _modal_surfaced[label]:
                        # Modal answered — re-arm so the next prompt alarms, and
                        # clear this guard's refusal-notify state (mirror the
                        # context-budget re-arm) so the pin/banner can fire again.
                        refusal_notified.discard(guard)
                        refusal_counts.pop(guard, None)
                        _pin_status()
                        _modal_surfaced[label] = False
                        _log("WATCHER", f"modal watchdog: {label} modal cleared "
                                        f"— re-armed.")

            # Per-pane park watchdog (stall-class 3): catch a single coder pane
            # parked after its own turn even while the channel is not quiet.
            if pane_idle_secs > 0 and _tick_count % PARK_CHECK_EVERY == 0:
                now = time.time()
                for pane, label in ((p_claude, "Opus"), (p_codex, "Coda")):
                    buf = capture_pane(pane, lines=14)
                    if buf != _park_last_buf[label]:
                        # The pane did something — reset the idle clock + nudges.
                        _park_last_buf[label] = buf
                        _park_idle_since[label] = now
                        _park_nudges[label] = 0
                        continue
                    state = classify_pane_state(buf)
                    if state != "IDLE":
                        # Working / at a modal / holding an unsent line — not a
                        # park (those classes own it). Hold the clock at 'now' so
                        # a later transition to IDLE starts a fresh interval.
                        _park_idle_since[label] = now
                        continue
                    idle = now - _park_idle_since[label]
                    if idle < pane_idle_secs:
                        continue
                    # Parked past threshold. First time → nudge the pane with the
                    # next concrete step; persisting → escalate to the operator.
                    _park_nudges[label] += 1
                    mins = idle / 60.0
                    if _park_nudges[label] == 1 and _wake_allowed(now):
                        send_message(pane,
                            f"[park watchdog] Your pane has shown no movement for "
                            f"~{mins:.0f} min and you are not mid-turn. If you have "
                            f"an open slice, post your next concrete step or a real "
                            f"blocker to {comms_file} — do not park after your turn. "
                            f"If you are done and waiting on a decision, say so "
                            f"explicitly.", cfg)
                        _log("WATCHER", f"park watchdog: {label} parked "
                                        f"~{mins:.0f} min — nudged the pane.")
                    else:
                        _surface_refusal(f"park-{label.lower()}",
                            f"{label} pane parked ~{mins:.0f} min and not self-"
                            f"clearing after a nudge — check the pane.")
                        _log("WATCHER", f"park watchdog: {label} still parked "
                                        f"~{mins:.0f} min after nudge — surfaced "
                                        f"to operator.")
                    # Restart the interval so the next escalation waits a full
                    # pane_idle_secs rather than firing every tick.
                    _park_idle_since[label] = now

            # Comms-drop watchdog (stall-class 2): a capsule/verdict update that
            # never made it into the comms channel, leaving an agent waiting on a
            # baton that won't come. Cheap (mtime + size compares) — every tick.
            if baton_grace_secs > 0:
                try:
                    _cur_cap_m = os.path.getmtime(capsule_path)
                except FileNotFoundError:
                    _cur_cap_m = _baton_capsule_mtime
                now = time.time()
                if _cur_cap_m > _baton_capsule_mtime:
                    _baton_capsule_mtime = _cur_cap_m
                    # Arm only if the channel is fully relayed: the symptom is a
                    # capsule that moved PAST a quiet channel. If comms is still
                    # draining, a normal append is in flight — not a drop.
                    if current_size == last_offset:
                        _baton_armed_at = now
                        _baton_size_at_arm = current_size
                        _baton_surfaced = False
                    else:
                        _baton_armed_at = None
                _append_since_arm = (_baton_armed_at is not None
                                     and current_size > (_baton_size_at_arm or 0))
                if _append_since_arm:
                    # The baton flowed after we armed; disarm.
                    _baton_armed_at = None
                _armed_secs = (now - _baton_armed_at
                               if _baton_armed_at is not None else None)
                if comms_drop_due(_armed_secs, baton_grace_secs,
                                  _append_since_arm, _baton_surfaced,
                                  bool(oa_active and oa_status_text)):
                    _baton_surfaced = True
                    _surface_refusal("comms-drop",
                        f"a capsule/verdict update landed but no comms append "
                        f"followed in ~{baton_grace_secs:.0f}s and the channel "
                        f"is quiet — the relay baton may be dropped (a verdict "
                        f"in the capsule that never relayed). Check the comms "
                        f"file EOF; a waiting agent won't get its baton.")
                    _log("WATCHER", f"comms-drop watchdog: capsule advanced "
                                    f"but no comms append in {baton_grace_secs:.0f}s "
                                    f"— surfaced to operator.")

            # Capsule edit watcher: notify Oya when the capsule's mtime changes.
            if oya_active and p_oyakata is not None \
                    and cfg.get("agents", {}).get("oyakata", {}).get(
                        "notify_on_capsule_edit", True):
                try:
                    cur_capsule_mtime = os.path.getmtime(capsule_path)
                    if cur_capsule_mtime > last_capsule_mtime:
                        notify_oyakata_capsule_edit(p_oyakata, cfg)
                        oya_pending_count += 1
                        last_capsule_mtime = cur_capsule_mtime
                except FileNotFoundError:
                    pass

            # Backpressure: if Oya wrote to its log, reset the pending counter.
            if oya_active:
                try:
                    cur_oya_log_mtime = os.path.getmtime(oya_log_path)
                    if cur_oya_log_mtime > last_oya_log_mtime:
                        oya_pending_count = 0
                        oya_warned_at_count = None
                        last_oya_log_mtime = cur_oya_log_mtime
                except FileNotFoundError:
                    pass

            # Operator-action surface: when the operator-actions capsule
            # changes, re-pin the outstanding asks to the status bar and fire a
            # desktop notification for any item that wasn't outstanding before.
            # Resolving an item (Oya ticks the box) drops it from `pending`, so
            # the pin clears itself when nothing is left waiting on the human.
            if oa_active:
                try:
                    cur_oa_mtime = os.path.getmtime(oa_path)
                except FileNotFoundError:
                    cur_oa_mtime = 0
                if cur_oa_mtime != oa_last_mtime:
                    oa_last_mtime = cur_oa_mtime
                    try:
                        with open(oa_path, encoding="utf-8") as f:
                            pending = parse_operator_actions(f.read())
                    except FileNotFoundError:
                        pending = []
                    new_items = [a for a in pending if a["key"] not in oa_seen_keys]
                    for a in new_items:
                        _log("ACTION", f"Oya needs you: {a['summary']}")
                        notify_operator("musubi — action needed", a["summary"])
                    if new_items:
                        emit_action_banner(new_items, len(pending))
                    oa_seen_keys |= {a["key"] for a in pending}
                    oa_status_text = format_actions_status(pending)
                    _pin_status()

            # Operator-input relay (oyakata-11): when the console pane appends
            # the operator's message(s) to operator-input.md, relay each new
            # entry into Oya's pane. Only fires once the Oya pane is known —
            # before that the operator's words would have nowhere to land, so
            # we hold the offset and deliver when the pane appears.
            if oi_active and p_oyakata is not None:
                try:
                    cur_oi_size = os.path.getsize(oi_path)
                except FileNotFoundError:
                    cur_oi_size = 0
                if cur_oi_size < oi_offset:
                    # File shrank/recreated — reset so we don't miss new input.
                    oi_offset = 0
                if cur_oi_size > oi_offset:
                    new_input = read_new_content(oi_path, oi_offset)
                    oi_offset = cur_oi_size
                    for msg in parse_operator_input(new_input):
                        relay_operator_input_to_oyakata(msg, p_oyakata, cfg)
                        oya_pending_count += 1
                        _log("INPUT", f"relayed operator message to Oya "
                                      f"({len(msg)} chars)")

            # Tier-2 pending-decision relay (oyakata-2 slice 3).
            # Hook writes a request file when a tool call falls outside the
            # tier-1 allowlist but plausibly belongs to the active slice
            # (target file is in `git status`). The hook polls for Oya's
            # verdict; we surface the request to her here. Bounded by
            # the watcher tick (3s) — the hook's verdict timeout is
            # configured to accommodate this floor.
            if tier2_permissions_enabled and oya_active and p_oyakata is not None:
                new_t2_requests = scan_pending_tier2_requests(
                    cfg["project"]["path"], tier2_seen_request_ids
                )
                for request_id, request_path, verdict_path in new_t2_requests:
                    _log(
                        "TIER2",
                        f"new pending decision {request_id} — notifying Oya",
                    )
                    notify_oyakata_tier2_pending(
                        p_oyakata, request_id, request_path, verdict_path, cfg
                    )
                    oya_pending_count += 1

            if current_size < last_offset:
                print(f"[{ts()}] [WATCHER] Comms file shrank; resetting read offset.")
                last_offset = 0
                last_size_seen = 0

            if current_size != last_size_seen:
                last_growth_time = time.time()
                last_size_seen = current_size
                nudged_at_size = None
                silence_nudges = 0  # new activity — re-arm the silence watchdog

            if current_size == last_offset:
                # Everything written has been relayed — the one boundary where no
                # mid-compose partial exists (a trailing partial leaves
                # last_offset < current_size). This is where two things run:
                now = time.time()
                idle = now - last_growth_time

                # (relay-1) Rolling rotation: if active.txt has grown past
                # rotate_max_bytes and the channel has been quiet, archive + reset
                # it IN the watcher (no re-drain) so it never grows unbounded and
                # never needs a manual bounce. Safe here precisely because we are
                # fully drained — the archive+truncate cannot orphan a tail.
                if rotation_due(current_size, last_offset, idle,
                                rotate_max_bytes, rotate_quiet_secs):
                    try:
                        rotated = archive_and_reset_comms(comms_file, _rotate_archive_dir)
                    except (OSError, RuntimeError) as e:
                        rotated = None
                        _log("WATCHER", f"comms rolling-rotation skipped (kept file): {e}")
                    if rotated:
                        _log("WATCHER", f"comms rolling-rotation: {current_size:,}B "
                                        f">= {rotate_max_bytes:,}B, quiet {idle:.0f}s — "
                                        f"archived to {rotated}, reset to 0 bytes.")
                        last_offset = 0
                        last_size_seen = 0
                        last_growth_time = now
                        nudged_at_size = None
                        unparseable_at_size = None
                        silence_nudges = 0
                        # The baton (comms-drop) watchdog keys on comms size — the
                        # capsule is untouched by a rotation, so just re-baseline.
                        _baton_armed_at = None
                        _baton_size_at_arm = None
                        _baton_surfaced = False
                        continue

                # Silence watchdog (idle-1): if the channel stays quiet past
                # idle_wake_secs and nothing is correctly waiting on the operator,
                # wake the orchestration layer so the pair doesn't sleep.
                if idle_wake_secs > 0:
                    waiting_on_operator = bool(oa_active and oa_status_text)
                    if silence_nudge_due(idle, idle_wake_secs, silence_nudges,
                                         now - last_silence_nudge_time,
                                         waiting_on_operator) and _wake_allowed(now):
                        silence_nudges += 1
                        last_silence_nudge_time = now
                        _wake_idle_channel(idle, silence_nudges)
                continue

            new_content = read_new_content(comms_file, last_offset)

            if not over_re.search(new_content):
                idle = time.time() - last_growth_time
                if idle >= stall_secs and nudged_at_size != current_size:
                    writer = detect_writer_from_buffer(new_content, cfg)
                    if writer:
                        target = p_claude if writer == "OPUS" else p_codex
                        print(f"[{ts()}] [WATCHER] {writer} stalled {idle:.0f}s without {over} — nudging.")
                        send_message(target,
                            f"Your last message in {comms_file} is missing the {over} sentinel. "
                            f"Append exactly the literal token {over} on a new line so the orchestrator can relay your reply.",
                            cfg
                        )
                        nudged_at_size = current_size
                    else:
                        print(f"[{ts()}] [WATCHER] Stalled {idle:.0f}s without {over} but no writer detected.")
                        nudged_at_size = current_size
                else:
                    print(f"[{ts()}] [WATCHER] New content but no {over} yet — still composing.")
                continue

            message_blocks, consumed_chars = extract_messages(new_content, cfg)
            if not message_blocks:
                if unparseable_at_size != current_size:
                    # First failure on this content — print a useful diagnostic
                    # so the user can see what's actually in the file.
                    unparseable_at_size = current_size
                    unparseable_retries = 1
                    tail = new_content.strip()[-300:]
                    # orch-3 mitigation 3: if the unparseable content carries a
                    # bracketed handle the running config doesn't know, name it
                    # explicitly — this is almost always a new agent (e.g. @OYA)
                    # added to config after the orchestrator started.
                    unknown = unrecognised_handles_in(new_content, known_handles)
                    if unknown:
                        print(f"[{ts()}] [WATCHER] Unrecognised sender(s) {', '.join(unknown)} "
                              f"in active comms — these handles are not in the running config. "
                              f"Either restart the orchestrator to load them, or remove the "
                              f"message manually if it's a misconfiguration.")
                    else:
                        print(f"[{ts()}] [WATCHER] Saw {over} but no recognised handle "
                              f"({opus_handle} / {coda_handle}) in the new content.")
                    print(f"[{ts()}] [WATCHER] Content tail: ...{tail!r}")
                    print(f"[{ts()}] [WATCHER] Fix: ask the agent to repost the message with the proper "
                          f"[{opus_handle}] or [{coda_handle}] header on its own line. Will skip past this "
                          f"content after {UNPARSEABLE_RETRY_LIMIT} retries.")
                else:
                    unparseable_retries += 1
                    if unparseable_retries >= UNPARSEABLE_RETRY_LIMIT:
                        # Skip ONLY the over-closed span extract_messages
                        # accounted for (consumed_chars), never to current
                        # EOF: the file may have grown during the retry ticks,
                        # and jumping to EOF swallows the head of whatever an
                        # agent is composing right now — its orphaned tail then
                        # becomes the NEXT unparseable region (quarantine
                        # cascade, okami bed 2026-06-11).
                        skipped_bytes = len(
                            new_content[:consumed_chars].encode("utf-8"))
                        skipped_text = new_content[:consumed_chars]
                        unknown = unrecognised_handles_in(skipped_text, known_handles)
                        # Save the unparseable region to the consolidated
                        # quarantine log (one file, not a sidecar per incident).
                        qpath = append_quarantine_entry(
                            comms_file, skipped_text,
                            reason="unknown-handle" if unknown else "orphan-tail")
                        q_note = (f"Logged to {qpath}." if qpath
                                  else "(quarantine-log write FAILED — content lost in memory.)")
                        # Differentiate the two failure shapes:
                        #   unknown-handle — a REAL message from a sender the
                        #     running config doesn't know (e.g. a new agent added
                        #     after boot). orch-8: surface it, it looks like a
                        #     dead relay from the operator seat.
                        #   orphan-tail — debris with NO handle at all, the tail of
                        #     a message whose head was already relayed at a compose
                        #     boundary. Expected; log it but do NOT alarm the
                        #     operator (this is what made 47 sidecars + 47 pins of
                        #     noise on the okami bed).
                        if unknown:
                            print(f"[{ts()}] [WATCHER] WARN: giving up after {unparseable_retries} retries — "
                                  f"skipping {skipped_bytes} bytes from unrecognised sender(s) "
                                  f"{', '.join(unknown)}. {q_note} Restart the orchestrator to load "
                                  f"the handle, or ask the agent to repost under "
                                  f"[{opus_handle}] / [{coda_handle}].")
                            _surface_refusal(
                                "unparseable-drop",
                                f"skipped {skipped_bytes} bytes from unrecognised "
                                f"sender(s) {', '.join(unknown)} — {q_note}")
                        else:
                            print(f"[{ts()}] [WATCHER] orphan-tail debris ({skipped_bytes} bytes, no "
                                  f"handle) at a compose boundary — quarantined, not surfacing. {q_note}")
                        last_offset += skipped_bytes
                        unparseable_at_size = None
                        unparseable_retries = 0
                continue

            # Parse succeeded — clear any pending unparseable state.
            unparseable_at_size = None
            unparseable_retries = 0

            # Drain EVERY complete message in the read span, in write order.
            # (Field bug: extracting only the LAST block dropped every earlier
            # message whenever a fast exchange landed 2+ posts in one ~3s read
            # window.) The offset advances only AFTER the whole span is
            # processed — a mid-drain failure (tmux flicker, agent CLI
            # restart) lands in the outer handler with the offset untouched,
            # so the next tick re-reads and retries the span; already-relayed
            # blocks are skipped by the recently-relayed memory; refused
            # blocks are re-evaluated (worst case a duplicate nudge, never a
            # silent drop). The advance reaches the end of the last COMPLETE
            # block, not EOF — a still-composing partial tail stays unread
            # until its over-signal arrives instead of being jumped over.
            if len(message_blocks) > 1:
                print(f"[{ts()}] [WATCHER] {len(message_blocks)} messages in "
                      f"this read span — draining in order.")
            for message_block in message_blocks:
                _process_block(message_block)
            last_offset += len(new_content[:consumed_chars].encode("utf-8"))

        except Exception as e:
            # Anything not handled by the inner branches lands here. The relay
            # stays alive — most failures are transient (tmux pane flicker,
            # disk hiccup, agent CLI restart). KeyboardInterrupt is a
            # BaseException and propagates past this clause to __main__.
            print(f"[{ts()}] [WATCHER] Error: {type(e).__name__}: {e}", file=sys.stderr)
            print(f"[{ts()}] [WATCHER] Continuing in 10s. Ctrl+C to stop the watcher.")
            time.sleep(10)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def relay_test(p_claude, p_codex, cfg):
    """Send a simple ping to each agent and confirm the relay is live before briefing.

    Pings both agents and then waits for both panes to actually print the
    expected 'RELAY TEST SUCCESSFUL' line — not for the operator to read
    the panes and ack. If neither pane shows the magic string within the
    timeout, fall through and let the operator decide (the prompt also
    accepts Enter to skip the wait)."""
    opus_name = cfg["agents"]["opus"]["name"]
    coda_name = cfg["agents"]["coda"]["name"]

    _log("RELAY", f"sending test ping to {opus_name}")
    send_message(p_claude,
        "Relay test. Print exactly the words 'RELAY TEST SUCCESSFUL' and nothing else.",
        cfg
    )
    time.sleep(2)
    _log("RELAY", f"sending test ping to {coda_name}")
    send_message(p_codex,
        "Relay test. Print exactly the words 'RELAY TEST SUCCESSFUL' and nothing else.",
        cfg
    )

    # Count >= 2 because the prompt itself contains the string ("Print
    # exactly the words 'RELAY TEST SUCCESSFUL'"), so a single occurrence
    # means we're seeing the prompt echo, not the agent's response.
    def both_panes_show_success():
        c_text = strip_ansi(capture_pane(p_claude, 80))
        x_text = strip_ansi(capture_pane(p_codex, 80))
        return (c_text.count("RELAY TEST SUCCESSFUL") >= 2 and
                x_text.count("RELAY TEST SUCCESSFUL") >= 2)

    wait_for_or_skip(
        both_panes_show_success,
        timeout=45,
        component="RELAY",
        label="awaiting 'RELAY TEST SUCCESSFUL' response in both panes",
    )


def brief_agents(p_claude, p_codex, cfg, latest_archive=None):
    """
    Brief each agent on their identity, peer, and protocol.

    Explicitly walks the warm-start checklist so the brief works whether or
    not the project has the optional /open-sesame slash command defined. The
    docs referenced here are installed by `bootstrap.sh` from the musubi repo
    into the target project's docs/agents/ directory.

    `latest_archive` (optional) is the path to the most recent rotated comms
    transcript. When the orchestrator rotates `active.txt` on startup, the
    active file is empty and agents would lose cross-session continuity. The
    brief points them at the prior session's archive so they can pick up
    where the last cycle left off.
    """
    project_path = cfg["project"]["path"]
    runbook = cfg["comms"].get("runbook", "docs/agents/AGENT_COLLAB_RUNBOOK.md")
    operating_model = cfg["comms"].get(
        "operating_model", "docs/agents/PAIR_OPERATING_MODEL.md"
    )
    comms_file = cfg["comms"]["file"]
    over = cfg["comms"]["over_signal"]
    opus = cfg["agents"]["opus"]
    coda = cfg["agents"]["coda"]

    if latest_archive:
        comms_lines = (
            f"   - {comms_file} (active comms — empty, just rotated by the orchestrator)\n"
            f"   - {latest_archive} (prior session transcript — read this for "
            f"cross-session context; the structured handoff and capsule capture "
            f"intent, the archive captures texture)\n"
        )
    else:
        comms_lines = f"   - {comms_file} (active comms)\n"

    def warm_start_brief(self_agent, peer_agent):
        return (
            f"You are {self_agent['name']}. Your peer agent is "
            f"{peer_agent['name']} ({peer_agent['cli']}) in the adjacent pane.\n"
            f"\n"
            f"Warm-start checklist — complete in order before any work:\n"
            f"\n"
            f"1. Read the runbook (protocol authority): "
            f"{project_path}/{runbook}\n"
            f"2. Read the operating model (rationale + patterns): "
            f"{project_path}/{operating_model}\n"
            f"3. Follow the runbook's 'Startup and Recovery' checklist in full. "
            f"It now includes a Codebase Orientation step (item 11) that the "
            f"orchestrator brief does NOT duplicate — do not skip it.\n"
            f"   Key files for this project:\n"
            f"   - {project_path}/docs/agents/current-state.md (capsule)\n"
            f"   - {project_path}/docs/agents/agent-todo.md (task board)\n"
            f"   - {project_path}/docs/agents/agent-handoff.md (latest entry)\n"
            f"{comms_lines}"
            f"   - git status --short --branch (ground truth)\n"
            f"4. If a /open-sesame slash command is defined for this project, "
            f"you may run it as a shortcut for the full Startup and Recovery "
            f"checklist (which already covers codebase orientation, deliberate-"
            f"state preservation, and the slice surface scan).\n"
            f"\n"
            f"Discipline pointers — see the runbook for the rules, do not rely "
            f"on this brief to carry them:\n"
            f"  - Slice surface scan: 'Execution Protocol > Before starting a slice'\n"
            f"  - Preserve deliberate state (no silent normalisation): see the "
            f"'Preserve Deliberate State' section. This codebase has already "
            f"shipped regressions of this class — read it.\n"
            f"  - Skill / tooling discipline: in the project's CLAUDE.md / AGENTS.md\n"
            f"\n"
            f"Comms rules: append to {comms_file}; end every message with "
            f"{over} on its own line so the orchestrator can relay it. Use the "
            f"six-state vocabulary from the runbook (claimed / started / "
            f"blocked / spawned / confirmed_running / completed). Reply discipline "
            f"follows the 'Reply required' field, not orchestrator nags.\n"
            f"\n"
            f"When all steps are complete, confirm with one line: "
            f"'Startup complete. Ready.'"
        )

    send_message(p_claude, warm_start_brief(opus, coda), cfg)
    time.sleep(3)
    send_message(p_codex, warm_start_brief(coda, opus), cfg)
    time.sleep(3)

# ---------------------------------------------------------------------------
# Comms-file lock — one orchestrator per comms file
# ---------------------------------------------------------------------------
# Two orchestrators pointed at the SAME comms file corrupt the relay: each one
# truncates the active file to zero bytes at boot (archive_and_reset_comms), so
# the other sees the file shrink, resets its read offset to 0, and re-drains the
# whole cycle — plus both send-keys into the panes. This happens with a leaked /
# duplicate orchestrator on one instance, or two tomls pointing at one project
# (field bug 2026-06-09). A boot-time lock makes it structural: an orchestrator
# claims its comms file, and a second one on the same file refuses to boot
# rather than truncating under a live peer. Two DISTINCT projects have distinct
# comms files and never contend. A stale lock (owning PID dead — e.g. kill -9)
# is taken over, so a crash never wedges future launches.

def _pid_alive(pid):
    """True if a process with this PID exists (signal 0 probes without killing).
    EPERM means it exists under another user — still alive."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def comms_lock_path(comms_file_abs):
    """Lock file sits next to the comms file it guards."""
    return comms_file_abs + ".orchestrator.lock"


def read_comms_lock(lock_path):
    """Parsed lock payload, or None if missing / unreadable / malformed."""
    try:
        with open(lock_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# Lock paths this process owns — released on exit.
_held_comms_locks = set()


def acquire_comms_lock(comms_file_abs, session_name):
    """Claim exclusive orchestrator ownership of a comms file.

    Returns (True, lock_path) on success (no holder, our own re-acquire, or a
    stale holder we take over). Returns (False, holder_dict) when a LIVE peer
    orchestrator already owns it — the caller must refuse to boot."""
    lock_path = comms_lock_path(comms_file_abs)
    holder = read_comms_lock(lock_path)
    if holder and holder.get("pid") != os.getpid() and _pid_alive(holder.get("pid")):
        return (False, holder)
    payload = {
        "pid": os.getpid(),
        "session": session_name,
        "comms": comms_file_abs,
        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = lock_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, lock_path)
    except OSError as e:
        # A lock we can't write shouldn't harden into a launch blocker — warn
        # and proceed (the maxlen dedup still makes a re-read survivable).
        _log("BOOT", f"could not write comms lock {lock_path}: {e!r} — proceeding without it")
        return (True, lock_path)
    _held_comms_locks.add(lock_path)
    return (True, lock_path)


def release_comms_lock(lock_path):
    """Remove a lock this process owns (idempotent, best-effort)."""
    holder = read_comms_lock(lock_path)
    if holder and holder.get("pid") == os.getpid():
        try:
            os.remove(lock_path)
        except OSError:
            pass
    _held_comms_locks.discard(lock_path)


@atexit.register
def _release_all_comms_locks():
    for lp in list(_held_comms_locks):
        release_comms_lock(lp)


def resolve_comms_abs(cfg):
    """Absolute path to the active comms file — project-relative paths resolve
    against project.path so the lock key is cwd-independent (two orchestrators
    on one project agree on the key regardless of where they were launched)."""
    comms_file = cfg["comms"]["file"]
    if os.path.isabs(comms_file):
        return comms_file
    return os.path.join(cfg["project"]["path"], comms_file)


def _guard_single_orchestrator(cfg, session_name):
    """Acquire the comms lock or raise ConfigError naming the live peer."""
    comms_abs = resolve_comms_abs(cfg)
    ok, info = acquire_comms_lock(comms_abs, session_name)
    if not ok:
        raise ConfigError(
            f"another musubi orchestrator is already running on this comms file:\n"
            f"  {comms_abs}\n"
            f"  held by PID {info.get('pid')}, session '{info.get('session')}', "
            f"started {info.get('started')}.\n"
            f"Two orchestrators on one comms file corrupt the relay — each truncates "
            f"the other's file at boot and replays the whole cycle. Stop the other "
            f"orchestrator first (or point this instance at a different project). If "
            f"that PID is dead, delete the stale lock:\n"
            f"  {comms_lock_path(comms_abs)}"
        )


def start_musubi(config_path="musubi.toml", session_override=None):
    cfg = load_config(config_path)
    project_path = cfg["project"]["path"]
    session_name = session_override or cfg["tmux"]["session_name"]

    # Startup banner (orch-3): version fingerprint so the operator can spot a
    # stale-code / stale-config run at a glance against `git log -1`.
    print_startup_banner(cfg, config_path)

    # Pre-flight: auto-hygiene (docs-2) — archive + trim any cycle doc that
    # bloated past the rotate threshold, non-interactively, so the operator never
    # has to remember to rotate. Capsule is trimmed (skeleton kept), not blanked.
    # Runs BEFORE the size guard, which stays as the refuse backstop.
    auto_rotate_managed_docs(cfg)

    # Pre-flight: refuse to launch on egregiously oversized managed docs and
    # warn on merely-large ones (orch-2). Runs before the tmux session so the
    # operator rotates first instead of paying the context cost every boot.
    check_managed_doc_sizes(cfg)

    # Pre-flight: protocol health (orch-7). Two warn-only checks: (1) has the
    # code moved for days while the protocol files stood still (work happened
    # outside the orchestrator — capsules now describe a repo that no longer
    # exists)? (2) is the project's runbook version behind what this checkout
    # ships? Both convert silent rot into a banner the operator sees BEFORE
    # the agents warm-start from stale state. The note is also handed to Oya
    # at spawn — a stale picture is precisely her altitude.
    protocol_notes = [n for n in (check_protocol_detachment(cfg),
                                  check_runbook_version_drift(cfg)) if n]
    emit_protocol_health_banner(protocol_notes)
    oya_boot_note = " | ".join(protocol_notes) if protocol_notes else None

    # Pre-flight: verify project.path is enterable BEFORE the tmux session is
    # created. Catches the stale-cwd / iCloud-sync failure mode (orch-6) and
    # surfaces missing/renamed project directories as an actionable error
    # instead of an EPERM uv_cwd Node trace in the agent pane after spawn.
    validate_project_path(project_path)

    # Pre-flight: fail loudly if either agent CLI isn't on PATH. Cheaper than
    # discovering it after the tmux session is created and the agents' panes
    # show "command not found".
    validate_cli_available(cfg["agents"]["opus"]["cli"])
    validate_cli_available(cfg["agents"]["coda"]["cli"])

    # Pre-flight: register the oyakata-2 PreToolUse hook in the project's
    # .claude/settings.local.json when [agents.oyakata.permissions].enabled
    # is true. Idempotent; no-op when the operator hasn't opted in. Failures
    # log a PERMS line but never abort startup — the hook is convenience,
    # not a correctness dependency.
    auto_wire_pretooluse_hook(cfg, project_path)

    # Pre-flight: surface gstack skill presence (warn-only, never refuses).
    # No-op when [requires.skills] is absent. See `check_required_skills`.
    check_required_skills(cfg)

    # Make sure the comms file's directory exists and the file itself is
    # present before agents start. A missing file leads agents to invent
    # their own path based on the runbook's archive naming convention.
    comms_file = cfg["comms"]["file"]
    os.makedirs(os.path.dirname(comms_file), exist_ok=True)

    # One orchestrator per comms file. Acquire the lock BEFORE the reset below
    # truncates the file — refusing here prevents a second orchestrator from
    # zeroing a comms file a live peer is mid-cycle on (the shrink that floods
    # the relay). Stale locks (dead owner) are taken over inside acquire.
    _guard_single_orchestrator(cfg, session_name)

    # Rotate the previous session's comms out of the way so the active file
    # starts each orchestrator launch at zero bytes — agents reading it on
    # warm start don't drag prior cycles into context.
    archive_dir = resolve_archive_dir(cfg)
    # Writability pre-check (orch-1 long-tail): the defensive default in
    # resolve_archive_dir handles the /archive-at-root case, but a misconfigured
    # explicit archive_dir (or an unwritable mount) would still crash mid-rotate.
    # Surface it as an actionable error before any tmux/agent work.
    try:
        os.makedirs(archive_dir, exist_ok=True)
        if not os.access(archive_dir, os.W_OK):
            raise OSError("directory is not writable")
    except OSError as e:
        raise ConfigError(
            f"comms.archive_dir resolves to '{archive_dir}' which is not writable ({e}). "
            f"Set comms.archive_dir explicitly in musubi.toml to a writable path."
        )
    archived = archive_and_reset_comms(comms_file, archive_dir)
    if archived:
        _log("BOOT", f"archived previous comms to {archived}")
        _log("BOOT", f"reset {comms_file} to 0 bytes")

    latest_archive = find_latest_archive(archive_dir)

    server = libtmux.Server()

    # Detect an existing session with the same name and decide what to do
    # based on the live state of its panes, NOT a blanket prompt. Three
    # outcomes (see classify_existing_session above):
    #   - 'live'      → auto-attach; the operator closed terminals but
    #                   agents are still alive. No state lost.
    #   - 'orphan'    → auto-kill + recreate; the session is a corpse
    #                   from a prior cycle. Safe to clean.
    #   - 'ambiguous' → friendly prompt with pane-by-pane status so the
    #                   operator can decide without CLI vocabulary.
    existing = [s for s in server.sessions if s.name == session_name]
    if existing:
        existing_session = existing[0]
        state = classify_existing_session(existing_session)

        if state == "live":
            _log("BOOT", f"existing session '{session_name}' detected with live agents")
            _log("BOOT", "auto-attaching — your agents are still alive from the previous launch")
            _log("BOOT", f"(to scrap this session and start fresh: "
                         f"`tmux kill-session -t {session_name}` then re-run)")
            # Delegate to the existing --attach flow. Same code path the
            # developer workflow uses after editing orchestrator.py.
            return attach_to_musubi(config_path, session_override)

        if state == "orphan":
            _log("BOOT", f"existing session '{session_name}' detected with no live agents")
            _log("BOOT", "cleaning up orphan and starting fresh "
                         "(no agent state was lost — there was none to lose)")
            # Fall through. The new_session(kill_session=True) call below
            # handles the actual cleanup.

        if state == "ambiguous":
            _log("BOOT", f"existing session '{session_name}' is in an unexpected state")
            _log("BOOT", "pane status:")
            for pane_id, cmd, is_shell in describe_session_panes(existing_session):
                marker = " (shell prompt — agent CLI not running)" if is_shell else ""
                _log("BOOT", f"  {pane_id}: {cmd}{marker}")
            print()
            print(f"Some panes look alive, others don't — musubi can't tell automatically")
            print(f"whether to resume or start fresh.")
            print()
            try:
                response = input(
                    f"Start fresh? (existing session will be killed; "
                    f"any work in alive panes is lost) [y/N] "
                ).strip().lower()
            except EOFError:
                response = ""
            if response not in ("y", "yes"):
                _log("BOOT", "aborted — no tmux session was modified")
                _log("BOOT", f"(to inspect the session manually: tmux attach -t {session_name})")
                sys.exit(0)
            # Fall through to new_session(kill_session=True).

    session = server.new_session(session_name=session_name, kill_session=True)
    session.cmd('set', '-g', 'mouse', 'on')
    # Mouse-scroll drops a pane into copy-mode (the yellow status bar). tmux's
    # default escape-time is 500ms, which makes the Escape that exits copy-mode
    # feel dead — you end up mashing it while another pane prints live. 10ms is
    # effectively instant but keeps a hair of margin for terminals that decode
    # Escape sequences, so copy-mode exits on the first Escape press.
    # (Scroll-to-bottom already auto-exits via tmux's default `copy-mode -e`
    # wheel binding, so a stray scroll doesn't strand you.)
    session.cmd('set', '-sg', 'escape-time', '10')
    # escape-time alone isn't enough when trackpad momentum keeps re-entering
    # copy-mode faster than you can press Escape (you end up mashing Enter to get
    # out). scripts/tmux-copymode.conf adds bindings so a left-click / Enter / q
    # cancels copy-mode on the first try and focuses the clicked pane — see that
    # file for the full rationale. Passing the chained `select-pane \; cancel`
    # binding through session.cmd() argv doesn't work (tmux splits on the `;`),
    # so we source it as a snippet instead.
    _copymode_conf = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "scripts", "tmux-copymode.conf"
    )
    if os.path.exists(_copymode_conf):
        try:
            session.cmd('source-file', _copymode_conf)
        except Exception as e:
            _log("BOOT", f"copy-mode hardening skipped: {e!r}")
    else:
        _log("BOOT", f"copy-mode hardening skipped: {_copymode_conf} not found")

    window = session.active_window
    p_claude = window.active_pane
    p_codex = window.split(direction=PaneDirection.Right)

    # Optional per-pane background tint (opt-in via the launcher's --pane-tint
    # flag → MUSUBI_PANE_TINT=1). Gives each pane a slightly different dark-grey
    # background so the column boundary reads at a glance. Oya's pane is tinted
    # separately by attach-oya.sh (it doesn't exist yet here). Defaults are tuned
    # for dark terminals; override per-pane with MUSUBI_TINT_OPUS / _CODA.
    if os.environ.get("MUSUBI_PANE_TINT") == "1":
        opus_bg = os.environ.get("MUSUBI_TINT_OPUS", "colour232")
        coda_bg = os.environ.get("MUSUBI_TINT_CODA", "colour240")
        try:
            p_claude.cmd("select-pane", "-P", f"bg={opus_bg}")
            p_codex.cmd("select-pane", "-P", f"bg={coda_bg}")
            _log("BOOT", f"pane tint on — Opus {opus_bg}, Coda {coda_bg}")
        except Exception as e:
            _log("BOOT", f"pane tint skipped: {e!r}")

    _log("BOOT", f"session '{session_name}' created")
    _log("BOOT", f"attach in another terminal with: tmux attach -t {session_name}")

    # Gate 1 (was: 'Press Enter when you're attached'). Auto-advance when at
    # least one tmux client is attached to the session. With launch_musubi.sh,
    # the second iTerm window auto-attaches a few seconds after this point.
    wait_for_or_skip(
        lambda: tmux_has_attached_client(session),
        timeout=60,
        component="BOOT",
        label="waiting for a tmux client to attach to this session",
    )

    quoted_path = shlex.quote(project_path)
    _log("BOOT", f"starting {cfg['agents']['opus']['name']} CLI in left pane")
    p_claude.send_keys(f"cd {quoted_path} && {cfg['agents']['opus']['cli']}", enter=True)
    time.sleep(2)
    _log("BOOT", f"starting {cfg['agents']['coda']['name']} CLI in right pane")
    p_codex.send_keys(f"cd {quoted_path} && {cfg['agents']['coda']['cli']}", enter=True)

    # Gate 2 (was: 'Press Enter when both are showing their prompts'). Poll
    # both panes for known CLI ready indicators (Claude Code's TUI border /
    # welcome banner; Codex's prompt). Heuristic — if it misses, the timeout
    # plus operator Enter still moves forward.
    #
    # Also watch for the EPERM uv_cwd crash signature (orch-6). If a pane shows
    # it, emit operator-readable recovery text once per pane. Detection is
    # passive — we don't bail out of the polling loop on EPERM because the
    # operator might still want to inspect the pane and the timeout-plus-Enter
    # gate gives them a way through.
    eperm_emitted = {"claude": False, "codex": False}

    def both_clis_ready():
        # Claude Code 2.x renders a bordered input box once ready ("╭"). Codex
        # CLI shows a prompt with "❯" or similar. Match permissively.
        claude_text = strip_ansi(capture_pane(p_claude, 60))
        codex_text = strip_ansi(capture_pane(p_codex, 60))
        if not eperm_emitted["claude"] and detect_eperm_uvcwd(claude_text):
            emit_eperm_recovery(cfg["agents"]["opus"]["name"])
            eperm_emitted["claude"] = True
        if not eperm_emitted["codex"] and detect_eperm_uvcwd(codex_text):
            emit_eperm_recovery(cfg["agents"]["coda"]["name"])
            eperm_emitted["codex"] = True
        claude_ready = any(m in claude_text for m in ("╭", "Welcome", "/help"))
        codex_ready = any(m in codex_text for m in ("╭", "Welcome", "❯", "▍"))
        return claude_ready and codex_ready

    wait_for_or_skip(
        both_clis_ready,
        timeout=90,
        component="BOOT",
        label="waiting for both CLIs to finish booting",
    )

    p_claude.select()

    # Oya auto-spawn (if enabled in musubi.toml). Happens AFTER the pair CLIs
    # are up so the orchestrator's Oya-pane discovery sees the freshly-added
    # pane immediately on its next watcher tick. Spawn is fire-and-forget —
    # attach-oya.sh handles settings.local.json + claude launch + prompt
    # auto-paste + READY signal in Oya's pane.
    p_oya_seed = spawn_oya_if_enabled(cfg, config_path, session)
    if p_oya_seed is not None:
        _log("OYA", "pane is up; Oya will run her own startup checklist in parallel")

    # Gate 3 was: 'Press Enter to run the relay test'. No condition — just
    # run it. relay_test() itself now auto-advances on 'RELAY TEST SUCCESSFUL'.
    _log("RELAY", "running relay test (pinging pair)")
    relay_test(p_claude, p_codex, cfg)

    _log("BRIEF", "sending warm-start briefings to pair")
    brief_agents(p_claude, p_codex, cfg, latest_archive=latest_archive)

    # Gate 5 (was: 'Press Enter to start the relay watcher'). Wait for both
    # pair agents to print 'Startup complete. Ready.' as the briefing
    # instructs them to. Same count >= 2 trick as the relay-test gate: the
    # briefing prompt itself quotes the string, so a single occurrence is
    # the prompt echo, not the agent's response.
    def pair_briefed():
        c_text = strip_ansi(capture_pane(p_claude, 120))
        x_text = strip_ansi(capture_pane(p_codex, 120))
        return (c_text.count("Startup complete. Ready") >= 2 and
                x_text.count("Startup complete. Ready") >= 2)

    wait_for_or_skip(
        pair_briefed,
        timeout=180,
        component="BRIEF",
        label="waiting for both agents to print 'Startup complete. Ready.'",
    )

    _log("WATCHER", "all gates cleared — starting relay watcher")
    watch_and_relay(p_claude, p_codex, cfg, session=session,
                    oya_boot_note=oya_boot_note)


def attach_to_musubi(config_path="musubi.toml", session_override=None):
    """Reuse an existing tmux session and resume just the watcher loop.

    Use after editing orchestrator.py: Ctrl+C the running watcher, then
    re-run with --attach to pick up the new code without tearing down
    the agents' tmux session or re-briefing them.
    """
    cfg = load_config(config_path)
    session_name = session_override or cfg["tmux"]["session_name"]

    # --attach deliberately skips boot work (no auto-rotate, no comms reset), so a
    # bloated capsule/handoff sails straight through. Warn loudly so the operator
    # knows a heavy/forgetful pair is the docs, not the model — and that a clean
    # `launch_musubi.sh` boot (not --attach) is what auto-trims them.
    for label, path in _managed_doc_paths(cfg):
        if label not in _AUTO_ROTATABLE:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > MANAGED_DOC_WARN_CHARS:
            _log("BOOT", f"WARNING: {label} is {size:,} chars (> {MANAGED_DOC_WARN_CHARS:,}) "
                         f"— --attach does NOT trim it. Heavy/forgetful agents are this "
                         f"bloat, not the model. Do a clean `launch_musubi.sh` boot to "
                         f"auto-archive + trim it.")

    # One orchestrator per comms file here too: --attach doesn't truncate, but
    # two watchers on one comms file still double-relay into the panes. A live
    # peer means this resume is a mistake — refuse rather than fight it.
    _guard_single_orchestrator(cfg, session_name)

    server = libtmux.Server()
    matches = [s for s in server.sessions if s.name == session_name]
    if not matches:
        print(f"No tmux session named '{session_name}' found.")
        print(f"Start a fresh one with: python orchestrator.py")
        sys.exit(1)

    session = matches[0]
    panes = session.active_window.panes
    if len(panes) < 2:
        print(f"Session '{session_name}' has {len(panes)} pane(s); expected at least 2.")
        sys.exit(1)

    # Filter out the Oya pane (if present) by pane_current_path before pair
    # identification. Oya's cwd is inside the musubi root (set by
    # attach-oya.sh); the pair's cwd is the target project. Without this
    # filter, Claude Code's TUI title overwrite + first-two-panes fallback
    # could pick the Oya pane as @OPUS after --attach.
    musubi_root_path = os.path.dirname(os.path.abspath(__file__))

    def _is_oya_pane(p):
        try:
            out = p.cmd("display-message", "-p", "#{pane_current_path}").stdout
            path = (out[0] if out else "") or ""
            return path.startswith(musubi_root_path)
        except Exception:
            return False

    pair_panes = [p for p in panes if not _is_oya_pane(p)]
    if len(pair_panes) < 2:
        print(f"Session '{session_name}' has {len(pair_panes)} pair pane(s) "
              f"(excluding Oya); expected 2.")
        sys.exit(1)

    # Pick Opus + Coda by title when possible. Title-substring works on
    # freshly-attached sessions but Claude Code's TUI overwrites the title
    # with response headlines within seconds, so we fall back to ordered
    # assignment among the pair panes (Opus is created first by
    # start_musubi, then Coda — see window.split() order).
    opus_pane = next((p for p in pair_panes if "OPUS" in (
        p.cmd("display-message", "-p", "#{pane_title}").stdout[:1] or [""])[0]), None)
    coda_pane = next((p for p in pair_panes if "CODA" in (
        p.cmd("display-message", "-p", "#{pane_title}").stdout[:1] or [""])[0]), None)
    p_claude = opus_pane or pair_panes[0]
    p_codex = coda_pane or pair_panes[1]

    _log("BOOT", f"re-attached to session '{session_name}' — resuming watcher only")
    _log("BOOT", f"opus pane: {p_claude.pane_id}; coda pane: {p_codex.pane_id}")

    # Liveness check: probe each pane's `pane_dead` status + current command.
    # A pane whose process exited (agent CLI crashed, user accidentally
    # killed the CLI) will show pane_dead=1 or have no current_command. The
    # watcher relays via send-keys regardless; a dead pane silently swallows
    # the keystrokes and no error surfaces. Better to fail loudly here than
    # to relay into a black hole.
    def _pane_health(pane, role):
        try:
            out = pane.cmd("display-message", "-p",
                           "#{pane_dead}|#{pane_current_command}").stdout
            raw = (out[0] if out else "") or ""
            dead_str, _, cmd = raw.partition("|")
            dead = dead_str.strip() == "1"
            cmd = cmd.strip()
        except Exception as e:
            return False, f"probe failed: {e!r}"
        if dead:
            return False, f"pane {pane.pane_id} is DEAD (process exited)"
        if not cmd or cmd in ("zsh", "bash", "sh", "fish"):
            # Pane is alive but only a shell is running — the agent CLI exited.
            return False, f"pane {pane.pane_id} has only '{cmd or 'no'}' running; agent CLI ({role}) appears to have exited"
        return True, f"pane {pane.pane_id} alive (running '{cmd}')"

    opus_ok, opus_msg = _pane_health(p_claude, "Opus")
    coda_ok, coda_msg = _pane_health(p_codex, "Coda")
    _log("BOOT", f"liveness — opus: {opus_msg}")
    _log("BOOT", f"liveness — coda: {coda_msg}")
    if not (opus_ok and coda_ok):
        _log("BOOT", "one or both agent panes are not responsive. The watcher would relay into a dead pane.")
        _log("BOOT", "options: start the agent CLI manually in the failed pane, OR kill the session and run a fresh launch.")
        try:
            response = input("Resume anyway? [y/N] ").strip().lower()
        except EOFError:
            response = ""
        if response not in ("y", "yes"):
            _log("BOOT", "aborted — pane state was bad and operator declined to continue")
            sys.exit(1)

    try:
        input("Press Enter to resume, or Ctrl+C to abort... ")
    except EOFError:
        _log("BOOT", "aborted (no tty)")
        sys.exit(0)
    watch_and_relay(p_claude, p_codex, cfg, session=session)


def main(argv=None):
    """Console entry point (pyproject `musubi` script) and `python orchestrator.py`.
    Returns a process exit code; never raises for the expected error paths."""
    # Fail fast on native Windows. Musubi's runtime is tmux + libtmux, which
    # do not run on native Windows (cmd/PowerShell); a launch there fails deep
    # inside the relay with confusing errors that read like portability bugs.
    # Windows is out of scope by design — run under WSL2, where the Linux path
    # works unchanged. (WSL reports as 'linux', so this only trips native Win.)
    if sys.platform.startswith("win"):
        print(
            "musubi: native Windows is not supported (the runtime is tmux + "
            "libtmux). Run musubi under WSL2 instead — install WSL, clone the "
            "repo inside your Linux home, and launch from the WSL shell. "
            "See the Prerequisites section of the README.",
            file=sys.stderr,
        )
        return 2

    import argparse
    parser = argparse.ArgumentParser(description="Musubi orchestrator: launch or re-attach the agent relay.")
    parser.add_argument("config", nargs="?", default="musubi.toml", help="Path to musubi.toml (default: musubi.toml)")
    parser.add_argument("session", nargs="?", default=None, help="Override tmux session name from config")
    parser.add_argument("--attach", action="store_true", help="Reuse existing tmux session and resume only the watcher (skips briefing/relay test).")
    args = parser.parse_args(argv)

    try:
        if args.attach:
            attach_to_musubi(args.config, args.session)
        else:
            start_musubi(args.config, args.session)
    except ConfigError as e:
        print(f"musubi: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"musubi: config file not found: {e.filename}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # Ctrl+C during the watcher (or any setup prompt). The tmux session
        # and agent panes are left intact so the user can resume with --attach.
        print("\nmusubi: stopped by user. Tmux session and agent panes are unchanged.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
