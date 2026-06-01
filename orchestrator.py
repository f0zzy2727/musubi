import libtmux
import select
import subprocess
import time
import re
import os
import shlex
import shutil
import sys
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
    over_pattern,
    detect_writer_from_buffer,
    extract_last_message,
    parse_result_field,
    message_type,
    is_idle_result,
    is_state_affecting,
    capsule_path,
    capsule_is_stale,
    CAPSULE_FRESHNESS_WINDOW_SECONDS,
    detect_sender,
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


def pane_contains(pane, needle, lines=80):
    """Convenience: True if `needle` appears in the last N lines of the pane.
    Strips ANSI so the match works even when the CLI is using colour codes."""
    return needle in strip_ansi(capture_pane(pane, lines))


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
# Main watcher loop
# ---------------------------------------------------------------------------

def watch_and_relay(p_claude, p_codex, cfg, session=None):
    """Watch comms file for <OVER> signals and relay to the other agent.

    When [agents.oyakata].enabled is true and `session` is supplied, also
    relays each parsed message to a discovered Oya pane and emits
    capsule-edit notifications. session is optional so attach_to_musubi
    can call this without the oyakata layer if it wishes.
    """
    comms_file = cfg["comms"]["file"]
    over = cfg["comms"]["over_signal"]
    over_re = over_pattern(over)
    stall_secs = cfg.get("comms", {}).get("stall_seconds", 45)

    print(f"\nWatching {comms_file} for {over} signals...")
    print("Press Ctrl+C to stop.\n")

    last_offset = get_file_size(comms_file)
    last_relayed_block = None
    last_size_seen = last_offset
    last_growth_time = time.time()
    nudged_at_size = None
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

    # Mid-session staleness detection (orch-3 mitigation 2). Capture the
    # orchestrator repo's HEAD at startup and re-check periodically; warn once
    # if it advances, because code/config changes don't take effect until the
    # process restarts. Cheap (`git rev-parse` every ~2 min, not every tick).
    _musubi_repo_dir = os.path.dirname(os.path.abspath(__file__))
    startup_head = _git_head_sha(_musubi_repo_dir)
    STALENESS_CHECK_EVERY = 40  # ticks (~2 min at 3s/tick)
    _tick_count = 0
    _staleness_warned = False

    known_handles = recognised_handles(cfg)

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

            # Oya pane: lazy discovery — keep trying until found, then cache.
            if oya_active and p_oyakata is None:
                p_oyakata = discover_oyakata_pane(session, cfg)
                if p_oyakata is not None and not oya_pane_announced:
                    print(f"[{ts()}] [WATCHER] Oyakata pane discovered mid-session: "
                          f"{p_oyakata.pane_id}")
                    oya_pane_announced = True

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

            if current_size == last_offset:
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

            message_block = extract_last_message(new_content, cfg)
            if not message_block:
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
                        skipped_bytes = current_size - last_offset
                        # Save the unparseable region to a sidecar so the
                        # operator can recover if a real message was in it.
                        # Sidecar path: alongside the comms file, named
                        # `_unparseable_<HHMMSS>.txt`. Best-effort write —
                        # failure here is logged but doesn't break the loop.
                        try:
                            sidecar_dir = os.path.dirname(comms_file) or "."
                            sidecar = os.path.join(
                                sidecar_dir,
                                f"_unparseable_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                            with open(comms_file, "r", encoding="utf-8", errors="replace") as cf:
                                cf.seek(last_offset)
                                content = cf.read(skipped_bytes)
                            with open(sidecar, "w", encoding="utf-8") as sc:
                                sc.write(content)
                            sidecar_note = f"Saved to {sidecar}."
                        except Exception as e:
                            sidecar_note = f"(Sidecar save FAILED: {e!r} — content lost in memory.)"
                        print(f"[{ts()}] [WATCHER] WARN: giving up after {unparseable_retries} retries — "
                              f"skipping {skipped_bytes} unparseable bytes. {sidecar_note} If a real "
                              f"message was lost, ask the agent to re-send it with a proper "
                              f"[{opus_handle}] / [{coda_handle}] header.")
                        last_offset = current_size
                        unparseable_at_size = None
                        unparseable_retries = 0
                continue

            # Parse succeeded — clear any pending unparseable state.
            unparseable_at_size = None
            unparseable_retries = 0
            last_offset = current_size

            if message_block == last_relayed_block:
                continue

            sender = detect_sender(message_block, cfg)
            if not sender:
                print(f"[{ts()}] [WATCHER] Could not detect sender — skipping.")
                continue

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
                last_relayed_block = message_block
                relay_instruction(message_block, sender, p_claude, p_codex, cfg)
                print(f"[{ts()}] [@OYA -> OPUS + CODA] Relayed.")
                continue

            # Ack-of-ack guard: if this is the Nth consecutive idle message,
            # refuse to relay and prompt the writer to either claim a slice
            # or name a real blocker. Resets on any non-idle Result.
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
                    last_relayed_block = message_block
                    continue
            else:
                idle_streak = 0

            # Capsule-staleness guard: state-affecting messages require the
            # capsule to have been updated within CAPSULE_FRESHNESS_WINDOW_SECONDS,
            # per the capsule-before-comms invariant. State-affecting now covers:
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
                last_relayed_block = message_block
                continue

            last_relayed_block = message_block
            relay_instruction(message_block, sender, p_claude, p_codex, cfg)
            print(f"[{ts()}] [{sender} -> {'CODA' if sender == 'OPUS' else 'OPUS'}] Relayed.")

            # A1: on a slice claim/start, auto-fire the discipline scope sensor
            # over the receipt's declared file targets and surface any triggered
            # engineering disciplines to Oya. Self-gates on file-target presence
            # and Oya availability; forgiving authority (informs, never blocks).
            if (oya_active and p_oyakata is not None and result
                    and any(s in result.lower() for s in ("claimed", "started"))):
                flag_disciplines_to_oyakata(
                    message_block, p_oyakata, cfg, _musubi_repo_dir)

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

def start_musubi(config_path="musubi.toml", session_override=None):
    cfg = load_config(config_path)
    project_path = cfg["project"]["path"]
    session_name = session_override or cfg["tmux"]["session_name"]

    # Startup banner (orch-3): version fingerprint so the operator can spot a
    # stale-code / stale-config run at a glance against `git log -1`.
    print_startup_banner(cfg, config_path)

    # Pre-flight: refuse to launch on egregiously oversized managed docs and
    # warn on merely-large ones (orch-2). Runs before the tmux session so the
    # operator rotates first instead of paying the context cost every boot.
    check_managed_doc_sizes(cfg)

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
    watch_and_relay(p_claude, p_codex, cfg, session=session)


def attach_to_musubi(config_path="musubi.toml", session_override=None):
    """Reuse an existing tmux session and resume just the watcher loop.

    Use after editing orchestrator.py: Ctrl+C the running watcher, then
    re-run with --attach to pick up the new code without tearing down
    the agents' tmux session or re-briefing them.
    """
    cfg = load_config(config_path)
    session_name = session_override or cfg["tmux"]["session_name"]

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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Musubi orchestrator: launch or re-attach the agent relay.")
    parser.add_argument("config", nargs="?", default="musubi.toml", help="Path to musubi.toml (default: musubi.toml)")
    parser.add_argument("session", nargs="?", default=None, help="Override tmux session name from config")
    parser.add_argument("--attach", action="store_true", help="Reuse existing tmux session and resume only the watcher (skips briefing/relay test).")
    args = parser.parse_args()

    try:
        if args.attach:
            attach_to_musubi(args.config, args.session)
        else:
            start_musubi(args.config, args.session)
    except ConfigError as e:
        print(f"musubi: {e}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"musubi: config file not found: {e.filename}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        # Ctrl+C during the watcher (or any setup prompt). The tmux session
        # and agent panes are left intact so the user can resume with --attach.
        print("\nmusubi: stopped by user. Tmux session and agent panes are unchanged.", file=sys.stderr)
        sys.exit(130)
