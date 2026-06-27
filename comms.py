"""Comms file parsing + state classification + file IO.

Pure functions — no tmux dependency, no orchestrator state. Importable from
tests without dragging in libtmux. The watcher loop in orchestrator.py
composes these into the relay pipeline.
"""

import os
import re
import shutil
from datetime import datetime


# ---------------------------------------------------------------------------
# String + file utilities
# ---------------------------------------------------------------------------

def strip_ansi(text):
    return re.sub(r'\x1B\[[0-9;]*[mGKHF]', '', text)


def get_file_size(path):
    try:
        return os.path.getsize(path)
    except FileNotFoundError:
        return 0


def archive_and_reset_comms(comms_file, archive_dir=None):
    """If the active comms file has content, copy it to a timestamped archive
    and truncate the original to zero bytes. Called on orchestrator startup so
    the active file does not grow across sessions and bloat agent warm-start
    context. No-op if the file is missing or already empty.

    Default archive directory is `<comms_parent>/../archive/` (i.e. sibling of
    the comms file's parent dir, matching the runbook's
    `docs/agents/comms/` ↔ `docs/agents/archive/` convention). Override via
    `comms.archive_dir` in musubi.toml.
    """
    if not os.path.exists(comms_file) or os.path.getsize(comms_file) == 0:
        # Nothing to archive — make sure the file exists empty for the agents.
        open(comms_file, 'a').close()
        return None

    if archive_dir is None:
        comms_dir = os.path.dirname(comms_file)
        archive_dir = os.path.join(os.path.dirname(comms_dir), "archive")

    os.makedirs(archive_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive_path = os.path.join(archive_dir, f"agent_comms_{stamp}.txt")

    # Copy first, verify, then truncate. Comms history is unrecoverable if lost
    # mid-rotate, so refuse to zero the source unless the archive matches.
    shutil.copy2(comms_file, archive_path)
    if os.path.getsize(archive_path) != os.path.getsize(comms_file):
        raise RuntimeError(
            f"Archive copy size mismatch — refusing to truncate {comms_file}"
        )
    open(comms_file, 'w').close()
    return archive_path


def resolve_archive_dir(cfg):
    """Resolve where rotated comms transcripts live. Mirrors the default
    inside archive_and_reset_comms so callers don't have to duplicate the
    fallback logic.

    Defensive default (orch-1): the convention `<comms_parent>/../archive`
    resolves to `/archive` (read-only root) when the comms file lives directly
    under a top-level dir such as the legacy `/tmp/agent_comms.txt`. When the
    convention would land at the filesystem root, fall back to a writable
    project-local path instead of crashing on first rotation.
    """
    archive_dir = cfg["comms"].get("archive_dir")
    if archive_dir:
        if not os.path.isabs(archive_dir):
            archive_dir = os.path.join(cfg["project"]["path"], archive_dir)
        return archive_dir
    # Default: sibling of the comms file's parent dir.
    comms_file = cfg["comms"]["file"]
    comms_parent = os.path.dirname(os.path.dirname(comms_file))
    if comms_parent in ("", "/", os.path.sep) or comms_parent == os.path.dirname(comms_parent):
        # Convention would resolve to the filesystem root (e.g. comms at
        # /tmp/agent_comms.txt -> /archive). Use a project-local archive dir.
        project_path = cfg.get("project", {}).get("path", ".")
        return os.path.join(project_path, "docs/agents/archive")
    return os.path.join(comms_parent, "archive")


def find_latest_archive(archive_dir):
    """Return the path to the most recent agent_comms_*.txt in archive_dir,
    or None if the dir is missing or empty. Used to point fresh agents at the
    prior session's transcript on warm start."""
    if not archive_dir or not os.path.isdir(archive_dir):
        return None
    candidates = [
        os.path.join(archive_dir, f)
        for f in os.listdir(archive_dir)
        if f.startswith("agent_comms_") and f.endswith(".txt")
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def read_new_content(path, from_offset):
    """Read only the content added since the last known offset.

    Missing file is treated as 'no new content' (the agents may not have
    written yet). Binary garbage in the buffer is replaced rather than
    raising, so a stray non-UTF-8 byte from a terminal escape doesn't take
    down the watcher. Other I/O errors propagate so the watcher's outer
    handler can log them and continue."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(from_offset)
            return f.read()
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Comms message parsing
# ---------------------------------------------------------------------------

def over_pattern(over_signal):
    """Tolerant regex for the over sentinel — accepts variants like
    `<OVER>`, `</OVER>`, `<over>`, `< OVER >`, `<OVER/>`."""
    inner = over_signal.strip("<>/ \t")
    return re.compile(rf"<\s*/?\s*{re.escape(inner)}\s*/?\s*>", re.IGNORECASE)


def detect_writer_from_buffer(buffer, cfg):
    """Identify the agent currently writing by scanning the buffer for the
    latest bracketed handle. Returns 'OPUS'/'CODA' or None.

    Tolerant of bracket variants: matches `[@CODA]`, `[[@CODA]]`, and similar
    by accepting any sequence of opening brackets around the handle. The
    canonical form is single-bracket but we don't want a typo-shaped variant
    to silently drop the message.

    Iterates only over participant agents (those with a `handle` key) so
    observer-style entries like [agents.oyakata] are skipped.
    """
    latest_idx = -1
    latest_key = None
    for key, agent in cfg["agents"].items():
        handle = agent.get("handle")
        if not handle:
            continue  # observer agent (e.g. oyakata) — no comms handle
        # Match `[@HANDLE]` or `[[@HANDLE]]` etc. — any number of opening
        # brackets immediately before the handle, then matching closers.
        pattern = re.compile(r"\[+\s*" + re.escape(handle) + r"\s*\]+")
        match = None
        for m in pattern.finditer(buffer):
            match = m  # keep advancing to find the last one
        if match is None:
            continue
        idx = match.start()
        if idx > latest_idx:
            latest_idx = idx
            latest_key = key
    return latest_key.upper() if latest_key else None


def operator_handle(cfg):
    """The operator's comms handle from `[operator].handle`, default `@LEAD`.

    The runbook documents the human lead under the role handle `@LEAD`, but
    real beds give the operator a personal handle (e.g. `@MICHI`). Everything
    the orchestrator or Oya emits ABOUT the operator at runtime must use this
    value — a session that keeps saying `@LEAD` when the bed has a named
    operator splits the operator's identity across two handles (field report
    2026-06-12). Tolerant of a missing leading `@`."""
    op = cfg.get("operator", {}) if isinstance(cfg, dict) else {}
    handle = op.get("handle") if isinstance(op, dict) else None
    if not handle or not str(handle).strip():
        return "@LEAD"
    handle = str(handle).strip()
    return handle if handle.startswith("@") else "@" + handle


def _all_configured_handles(cfg):
    """All comms-participating handles from cfg, including optional Oya.
    Returns a list like ['@OPUS', '@CODA', '@OYA']. Order is opus, coda,
    then any others (e.g. oyakata) per cfg insertion order."""
    handles = []
    for agent in cfg.get("agents", {}).values():
        h = agent.get("handle")
        if h:
            handles.append(h)
    return handles


# The cosmetic separator line agents write between comms messages. Treated as
# noise by the parser — message boundaries are defined by the over-signal, so
# a missing or doubled separator can't merge or split messages.
_BLOCK_SEPARATOR = "---------------------------------------------------"


def resume_offset(path, cfg):
    """Byte offset a (re)starting watcher should resume from: just PAST the
    end of the last over-signal in the file, so a message an agent is
    mid-composing at boot is read whole once its over-signal lands.

    The old behaviour (resume at raw EOF) orphaned in-flight messages on a
    watcher restart (`--attach` after a code edit): the head written before
    boot was never read, and the tail arrived with no [@HANDLE] header — three
    retry ticks later it was quarantined to an `_unparseable_` sidecar and the
    message silently never relayed. Field bug, okami bed 2026-06-11: four
    orphaned tails in one morning of attach-relaunch iteration.

    Falls back to EOF when the file has no over-signal at all (fresh or
    preamble-only file) — there is no in-flight message to protect before the
    first over-signal ever written, and re-reading a preamble that never
    parses would churn the unparseable path. Missing file is 0.

    Note this protects the MID-COMPOSE message only. A message COMPLETED while
    the watcher was down still ends before the last over-signal and is not
    re-relayed (re-draining the whole file would re-deliver the entire cycle —
    the per-process recently-relayed memory is empty at boot)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        return 0
    over_re = over_pattern(cfg["comms"]["over_signal"])
    last_end = None
    for m in over_re.finditer(content):
        last_end = m.end()
    if last_end is None:
        return get_file_size(path)
    return len(content[:last_end].encode("utf-8"))


def extract_messages(new_content, cfg):
    """All complete message blocks in `new_content`, in WRITE ORDER, plus how
    far into the content the last complete block reaches.

    Returns `(blocks, consumed_chars)`:
      - `blocks`: list of message strings, each closed by the over-signal and
        carrying at least one configured `[@HANDLE]` (lenient substring match,
        same family as extract_last_message). Over-closed spans with NO
        recognised handle are junk (TUI noise, stray pastes) and are dropped
        from the list but still counted as consumed.
      - `consumed_chars`: character index just past the LAST over-signal —
        i.e. the prefix of `new_content` that has been fully accounted for.
        Anything after it is a still-composing partial message the caller
        must NOT skip past (field bug: the old advance-to-EOF jumped over
        partial tails, losing the message when its over-signal arrived).

    History: the predecessor returned only the LAST block of a read span, and
    the watcher then advanced past the whole span — so whenever two or more
    messages landed in one ~3s read window (a normal fast pair exchange),
    every message but the last was silently dropped. Field-diagnosed
    2026-06-06 on a second operator's deployment (independently root-caused
    by the deployment's own Oya, who reached the same two defects)."""
    over_re = over_pattern(cfg["comms"]["over_signal"])
    handles = _all_configured_handles(cfg)

    blocks = []
    consumed_chars = 0
    prev_end = 0
    for m in over_re.finditer(new_content):
        raw = new_content[prev_end:m.end()]
        prev_end = m.end()
        consumed_chars = m.end()
        block = raw.replace(_BLOCK_SEPARATOR, "").strip()
        if block and any(h in block for h in handles):
            blocks.append(block)
    return blocks, consumed_chars


def extract_last_message(new_content, cfg):
    """Pull the last full message block containing ANY configured handle and <OVER>.

    Substring match on the handle (e.g. `@OPUS`) is intentionally lenient —
    accepts both `[@OPUS]` and `[[@OPUS]]` bracket variants. The over_pattern
    regex is also lenient (`<OVER>`, `</OVER>`, `< OVER >`, etc.).

    Accepts messages from any configured agent including the optional Oya
    layer — an [@OYA] Note that doesn't address @OPUS or @CODA in the body
    still parses cleanly so the relay can route it appropriately.

    Rebased on extract_messages() — kept for tooling/tests that genuinely
    want only the newest block. The watcher itself drains ALL blocks."""
    blocks, _ = extract_messages(new_content, cfg)
    return blocks[-1] if blocks else None


def parse_result_field(message_block):
    """Extract the Result line value from a message block."""
    if not message_block:
        return None
    m = re.search(r"^Result:\s*(.+?)$", message_block, re.MULTILINE)
    return m.group(1).strip() if m else None


def message_type(message_block):
    """Extract the Type field (e.g. 'Review Request', 'Update', 'Decision')."""
    if not message_block:
        return None
    m = re.search(r"^Type:\s*(.+?)$", message_block, re.MULTILINE)
    return m.group(1).strip() if m else None


# Result-line values that indicate the agent has nothing concretely in flight.
# A streak of ≥3 of these across consecutive messages is an ack-of-ack chain.
_IDLE_RESULT_PATTERNS = (
    "not started",
    "nothing claimed",
    "idle",
    "holding",
    "no slice",
    "awaiting",
)


def is_idle_result(result):
    """True if a Result value indicates no concrete execution. Case-insensitive.
    Used to detect ack-of-ack chains where agents repeatedly acknowledge each
    other's idleness instead of breaking the loop."""
    if not result:
        return True
    lowered = result.strip().lower()
    if lowered == "claimed":
        # bare 'claimed' with no further state — counts as idle for streak purposes
        return True
    return any(pat in lowered for pat in _IDLE_RESULT_PATTERNS)


def silence_nudge_due(idle_secs, idle_wake_secs, silence_nudges,
                      since_last_nudge, waiting_on_operator):
    """Decide whether the silence watchdog (idle-1) should nudge now.

    Pure predicate so the watcher loop's decision is testable in isolation.
    The channel has gone fully quiet (everything written is relayed); we wake
    the orchestration layer when:

      - the watchdog is enabled (idle_wake_secs > 0), AND
      - the quiet has lasted at least idle_wake_secs, AND
      - nothing is correctly pinned waiting on the operator (if work is parked
        on a human decision, silence is expected — stay quiet), AND
      - either we haven't nudged this silence episode yet, or a full
        idle_wake_secs has elapsed since the last nudge (so we re-nudge /
        escalate at a steady cadence rather than every tick).

    `silence_nudges` is the count already sent this episode (reset to 0 on any
    new comms activity); `since_last_nudge` is seconds since the last nudge.
    """
    if idle_wake_secs <= 0:
        return False
    if idle_secs < idle_wake_secs:
        return False
    if waiting_on_operator:
        return False
    return silence_nudges == 0 or since_last_nudge >= idle_wake_secs


def rotation_due(current_size, last_offset, idle_secs, max_bytes, quiet_secs):
    """Decide whether the watcher should roll the active comms file to an archive
    now (relay-1). Pure predicate so the watcher loop's decision is testable.

    Rotation keeps `active.txt` from growing unbounded across a long session —
    the bloat that otherwise forces a manual orchestrator "bounce". It is SAFE
    only at a fully-drained boundary:

      - `current_size == last_offset` — everything written has been relayed AND
        there is no mid-compose partial (the drain advances `last_offset` only
        past complete `<OVER>` blocks, so a trailing partial leaves
        `last_offset < current_size`). Archiving here cannot orphan a tail the
        way an externally-timed bounce/truncate can.
      - `current_size >= max_bytes` — only roll a file that has actually grown.
      - `idle_secs >= quiet_secs` — the channel has been quiet, so we don't
        split a live exchange across two archive files.

    `max_bytes <= 0` disables rotation entirely.
    """
    if max_bytes <= 0:
        return False
    if current_size != last_offset:
        return False
    if current_size < max_bytes:
        return False
    return idle_secs >= quiet_secs


def comms_drop_due(armed_secs, baton_grace_secs, append_since_arm,
                   already_surfaced, waiting_on_operator):
    """Decide whether the comms-drop watchdog (stall-class 2) should surface now.

    Pure predicate so the watcher loop's decision is testable in isolation. The
    alarm fires when a capsule/verdict update advanced over a fully-relayed,
    quiet channel and no comms append followed — the S3/S4 dropped-baton bug. We
    surface when:

      - the watchdog is enabled (baton_grace_secs > 0), AND
      - the check is armed (armed_secs is the seconds since the capsule advanced
        over a quiet channel; None means not armed), AND
      - no comms append has landed since arming (append_since_arm is False — an
        append means the baton flowed and there is no drop), AND
      - we haven't already surfaced this episode, AND
      - nothing is correctly pinned waiting on the operator (a capsule update at
        a cycle boundary that's legitimately parked on a human decision is not a
        drop), AND
      - the grace window has fully elapsed.
    """
    if baton_grace_secs <= 0:
        return False
    if armed_secs is None:
        return False
    if append_since_arm:
        return False
    if already_surfaced:
        return False
    if waiting_on_operator:
        return False
    return armed_secs >= baton_grace_secs


# Message types that assert state worth reflecting in the capsule. The
# capsule-before-comms invariant says any such message must be posted only
# after docs/agents/current-state.md is updated.
_STATE_AFFECTING_TYPES = frozenset({
    "review request",
    "decision",
    "blocker",
})


# Result values that indicate a slice transitioned execution state (the
# runbook's six-state vocab: `claimed` / `started` / `blocked` / `spawned` /
# `confirmed_running` / `completed`). Any message reporting these is
# implicitly state-affecting regardless of its Type — the capsule should be
# updated to reflect the transition before the comms message goes out.
#
# Note: bare `claimed` is also classified as idle for the ack-of-ack guard
# (see _IDLE_RESULT_PATTERNS), but it IS state-affecting on the first
# transition. Both guards may fire on the same message — they're independent.
_STATE_TRANSITION_RESULTS = frozenset({
    "claimed",
    "started",
    "blocked",
    "spawned",
    "confirmed_running",
    "confirmed running",  # tolerate space-instead-of-underscore variant
    "completed",
})


def _result_is_state_transition(result):
    """True if a Result value names a six-state-vocab execution-state
    transition. Case-insensitive; tolerant of extra qualifying text after
    the state (e.g. `blocked — waiting on @LEAD` still matches `blocked`)."""
    if not result:
        return False
    lowered = result.strip().lower()
    # Exact match on a state word, OR state word followed by punctuation/space
    # (e.g. "blocked — reason" or "completed.").
    for state in _STATE_TRANSITION_RESULTS:
        if lowered == state:
            return True
        if lowered.startswith(state) and len(lowered) > len(state):
            next_char = lowered[len(state)]
            if not next_char.isalnum() and next_char != "_":
                return True
    return False


def is_state_affecting(msg_type, message_block=None):
    """True if this message asserts a state the capsule should reflect.

    Two independent triggers (either fires):
      1. Type in {Review Request, Decision, Blocker} — these are
         protocol-level state assertions regardless of Result.
      2. Result names a state transition from the six-state vocab
         (`started`, `blocked`, `completed`, etc.) — these are slice-level
         state transitions that the capsule should reflect before the
         comms message claims them.

    Backward-compat: callers that pass only msg_type get the Type-based
    check (original v1 behaviour). The Result-based check requires
    message_block so the watcher can pass the full message and trigger
    on Update messages that report state transitions.
    """
    if msg_type and msg_type.strip().lower() in _STATE_AFFECTING_TYPES:
        return True
    if message_block:
        result = parse_result_field(message_block)
        if _result_is_state_transition(result):
            return True
    return False


# ---------------------------------------------------------------------------
# Capsule state
# ---------------------------------------------------------------------------

def capsule_path(cfg):
    """Resolve the capsule path. Relative paths are anchored at project.path."""
    rel = cfg["comms"].get("capsule", "docs/agents/current-state.md")
    if os.path.isabs(rel):
        return rel
    return os.path.join(cfg["project"]["path"], rel)


# Window (seconds) within which the capsule must have been touched before a
# state-affecting message. Generous enough that an agent who updates the
# capsule and then writes comms within the next two minutes passes.
CAPSULE_FRESHNESS_WINDOW_SECONDS = 120


def capsule_is_stale(cfg, now=None):
    """True if the capsule wasn't modified within CAPSULE_FRESHNESS_WINDOW_SECONDS.
    Skipped silently if the capsule path doesn't exist (some projects don't
    use the capsule pattern)."""
    import time
    path = capsule_path(cfg)
    if not os.path.exists(path):
        return False
    if now is None:
        now = time.time()
    return (now - os.path.getmtime(path)) > CAPSULE_FRESHNESS_WINDOW_SECONDS


# ---------------------------------------------------------------------------
# Operator-action surface (the operator-actions capsule)
# ---------------------------------------------------------------------------
# Oya writes a *pending* item here whenever she needs the operator to make a
# bounded decision / take an action before work can proceed (set a stop,
# approve a deploy, choose A vs B). The orchestrator surfaces these on a
# non-scrolling surface (tmux status bar) + a desktop notification, so a
# needed decision can't get buried in pane scroll the way a comms line does.
#
# The file is a *capsule* — a snapshot of what's still outstanding for the
# operator — not a log. Pending = unchecked markdown checkboxes; once the
# operator discharges an item Oya ticks the box (moves it to Resolved). These
# parse helpers are pure so the watcher logic stays testable without tmux.

# A pending action is a top-level (≤3 leading spaces) unchecked checkbox item.
# Deeper indentation is treated as continuation detail, not a separate action.
_ACTION_PENDING_RE = re.compile(r'^[ \t]{0,3}[-*]\s+\[ \]\s+(.+?)\s*$', re.MULTILINE)

# Metadata separators that trail the imperative headline (" — _asked …_").
# Split on the first one to get a clean status-bar summary.
_ACTION_META_SEPARATORS = (" — ", " – ", " -- ", " - ")


def _action_key(headline):
    """Stable identity for a pending action: the headline with markdown bold
    stripped and whitespace collapsed. Used to tell a genuinely-new action
    (fire a notification) from one already outstanding (just keep it pinned)."""
    return re.sub(r'\s+', ' ', headline.replace("**", "").strip())


def _action_summary(headline):
    """Short, human-facing form of the headline for the status bar: bold
    stripped, trailing `— _asked …_` metadata dropped."""
    s = headline.replace("**", "").strip()
    for sep in _ACTION_META_SEPARATORS:
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    return s


def parse_operator_actions(text):
    """Parse the operator-actions capsule body into a list of pending actions,
    in document order. Each item is a dict: {key, summary, headline}.

    Pending = top-level unchecked `- [ ]` / `* [ ]` checkbox items. Resolved
    (`- [x]`) items are intentionally excluded — the capsule's job is to show
    only what's still waiting on the operator."""
    actions = []
    for m in _ACTION_PENDING_RE.finditer(text):
        headline = m.group(1)
        actions.append({
            "key": _action_key(headline),
            "summary": _action_summary(headline),
            "headline": headline.strip(),
        })
    return actions


def format_actions_status(pending):
    """Build the tmux status-bar string for the current outstanding actions.
    Empty list → "" (clears the pin). One action → its summary; several → a
    count plus the first summary so the operator sees there's a queue."""
    if not pending:
        return ""
    head = pending[0]["summary"]
    n = len(pending)
    if n == 1:
        return f"⚑ AWAITING YOU: {head}"
    return f"⚑ {n} AWAITING YOU: {head} (+{n - 1} more)"


def format_relay_refusal_status(refusal_counts):
    """Status-bar segment for active relay refusals (orch-8). From the operator
    seat a refusing relay is indistinguishable from a broken one — the refusal
    line scrolls away in the watcher log and the agents just look idle. This
    pins the WHY on the one surface that doesn't scroll. Empty dict → ""
    (clears the segment). `refusal_counts` maps guard name → refusals since
    the last successful pair relay, e.g. {"capsule-stale": 3}."""
    if not refusal_counts:
        return ""
    parts = [f"{guard} ×{n}" for guard, n in sorted(refusal_counts.items())]
    return "⛔ RELAY HELD: " + ", ".join(parts)


def compose_status_right(*segments):
    """Join non-empty status-bar segments (operator actions, relay refusals)
    into one status-right string so the surfaces share the bar instead of
    clobbering each other. All segments empty → "" (clears the pin)."""
    return " | ".join(s for s in segments if s)


# Runbook version header as installed by bootstrap, e.g. `**Version:** 1.10`.
# Forks may append provenance after the number (e.g. "(forked from musubi
# 2026-05-10 ...)") — tolerated, not captured.
_RUNBOOK_VERSION_RE = re.compile(
    r"^\*\*Version:\*\*\s*([0-9]+(?:\.[0-9]+)*)", re.MULTILINE)


def parse_runbook_version(text):
    """Extract the numeric version from a runbook's `**Version:** X.Y` header.
    Returns the version string (e.g. '1.10') or None if no header is found."""
    m = _RUNBOOK_VERSION_RE.search(text or "")
    return m.group(1) if m else None


def runbook_version_tuple(version):
    """'1.10' → (1, 10) for numeric comparison ('1.9' < '1.10' must hold,
    which plain string comparison gets wrong). None/garbage → None."""
    if not version:
        return None
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Sender detection (canonical form)
# ---------------------------------------------------------------------------

def detect_sender(message_block, cfg):
    """Returns 'OPUS' or 'CODA' (uppercase) based on the [@HANDLE] header.

    The sender wraps their own handle in brackets in the message header
    (e.g. `[@CODA] [2026-04-30] [08:31 UTC]`). The body addresses the peer
    with a bare `@HANDLE`, so any matcher that accepts either form will
    misidentify the sender as the addressee. We pick the bracketed handle
    that appears earliest in the block.

    Tolerant of `[@HANDLE]` and `[[@HANDLE]]` bracket variants — same regex
    family as detect_writer_from_buffer. Bare `@HANDLE` (no brackets) is
    deliberately not matched because that's how messages address the peer.
    """
    if not message_block:
        return None

    earliest_idx = None
    earliest_key = None
    for key, agent in cfg["agents"].items():
        handle = agent.get("handle")
        if not handle:
            continue  # observer agent (e.g. oyakata) — no comms handle
        pattern = re.compile(r"\[+\s*" + re.escape(handle) + r"\s*\]+")
        m = pattern.search(message_block)
        if m is None:
            continue
        idx = m.start()
        if earliest_idx is None or idx < earliest_idx:
            earliest_idx = idx
            earliest_key = key

    return earliest_key.upper() if earliest_key else None
