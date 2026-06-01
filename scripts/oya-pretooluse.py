#!/usr/bin/env python3
"""oya-pretooluse.py — Claude Code PreToolUse hook for oyakata-2.

Two tiers:

  Tier 1 — Static allowlist (slices 1 + 2). Read-only ops (`Read`, `Grep`,
    `Glob`, `NotebookRead`) and a narrow Bash subset (`git status|log|diff|
    show|branch|...`, `pwd`, `ls`, `cat`, …) are auto-approved without
    consulting anyone. Any shell metachar in the Bash command defers.

  Tier 2 — Oya-as-decider (slice 3, this file). When a tool call IS NOT in
    tier-1 but IS plausibly in-context (an `Edit`/`Write`/`NotebookEdit`
    targeting a file already in `git status` — modified or untracked),
    write a request JSON to `docs/agents/oyakata-pending/` and poll for
    Oya's verdict. Verdict `allow` → approve; verdict `defer` or timeout
    → fall through to operator prompt.

Everything else still falls through to Claude Code's normal permission flow.

Graceful degrade. If no orchestrator is running, or Oya isn't enabled, or
the project isn't a git repo, the tier-2 path bails out cheaply and the
hook returns the same defer it would have without tier-2.

Failure mode. This hook NEVER blocks tool execution permanently. Every
error path exits 0 with no output (CC interprets that as "no decision —
apply normal flow"). The TIER2_VERDICT_TIMEOUT_S budget caps how long
a single call can wait. Worst case the operator sees the prompt they
would have seen without the hook.

Decision logging. Every outcome — tier-1 ALLOW, tier-2 ALLOW, tier-2
DEFER, plain DEFER — appends a one-line entry to
`docs/agents/oyakata-decisions.md` so the operator and Oya have a
durable audit trail.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone


# --- Allowlist ---------------------------------------------------------------
#
# Tools that are read-only by construction: always auto-approved.
UNCONDITIONAL_TOOLS = frozenset({
    "Read",
    "Grep",
    "Glob",
    "NotebookRead",
})

# Bash commands considered safely read-only. Each pattern matches the WHOLE
# command string from the start. The command-head pattern must be paired with
# the no-shell-metachars check below — a head match alone is not enough,
# because `git status | tee statefile.txt` still mutates state.
#
# Conservative by design. If you can't tell at a glance whether a pattern is
# read-only, leave it off this list. The cost of a false-negative (extra
# permission prompt) is zero; the cost of a false-positive (auto-approved
# state change) is trust loss.
SAFE_BASH_PATTERNS = tuple(
    re.compile(p) for p in (
        # git read-only operations
        r"^git\s+status(\s|$)",
        r"^git\s+log(\s|$)",
        r"^git\s+diff(\s|$)",
        r"^git\s+show(\s|$)",
        r"^git\s+branch(\s+(-l|--list|-a|-r|-v))*\s*$",
        r"^git\s+rev-parse(\s|$)",
        r"^git\s+config\s+--get(\s|$)",
        r"^git\s+config\s+--list(\s|$)",
        r"^git\s+remote(\s+(-v|--verbose))?\s*$",
        r"^git\s+ls-files(\s|$)",
        r"^git\s+ls-tree(\s|$)",
        r"^git\s+blame(\s|$)",
        # filesystem read-only (metadata only)
        r"^pwd\s*$",
        r"^whoami\s*$",
        r"^date(\s|$)",
        r"^ls(\s|$)",
        r"^wc(\s|$)",
        r"^file\s+\S",
        r"^stat\s+\S",
        # shell introspection (read-only by definition)
        r"^which\s+\S",
        r"^command\s+-v\s+\S",
        r"^type\s+\S",
        r"^echo(\s|$)",
    )
)
# DELIBERATELY NOT auto-approved (were in earlier revisions, removed for safety):
#   cat / head / tail  — disclose arbitrary file *contents* (`cat ~/.ssh/id_rsa`,
#                        `cat .env`). Normal file reads route through the Read
#                        tool, which Claude Code path-scopes; there is no benign
#                        reason to auto-approve raw `cat` of an arbitrary path.
#   printenv / env     — dump the environment, including any exported API keys.
# The cost of deferring these is one permission prompt; the cost of
# auto-approving them is silent secret disclosure. Defer wins.

# Any of these in the command means "DON'T auto-approve, defer." The shell
# metacharacters that compose commands or redirect output. If any of them
# appear anywhere in the command string — quoted or not — we conservatively
# refuse to auto-approve. This is over-strict (e.g. `git log --grep="foo|bar"`
# won't auto-approve because of the pipe inside the quoted regex) but the
# cost is zero (operator just answers the prompt manually) and the safety
# margin is large.
#
# `\n` and `\r` are in this list because the SAFE_BASH_PATTERNS anchor only at
# the START of the string (`re.match`). Without the newline fence, a command
# whose first line is allow-listed would auto-approve a SECOND line carrying an
# arbitrary payload — e.g. "git status\nrm -rf /" matches `^git\s+status` and
# would run the rm. Claude Code passes a multi-line command to one shell, so the
# whole payload executes. Treat any newline as a command separator and defer.
DANGEROUS_SHELL_TOKENS = (
    "|",
    ">",
    "<",
    ";",
    "&",
    "$(",
    "`",
    "$((",
    "\n",
    "\r",
)


# --- Allowlist matcher -------------------------------------------------------

def classify_bash(command: str) -> tuple[bool, str]:
    """Return (auto_approve, reason). Reason is operator-readable."""
    if any(tok in command for tok in DANGEROUS_SHELL_TOKENS):
        return False, "contains shell metacharacter (chain/pipe/redirect)"
    for pattern in SAFE_BASH_PATTERNS:
        if pattern.match(command):
            return True, f"matches tier-1 read-only pattern: {pattern.pattern}"
    return False, "no tier-1 read-only pattern matched"


def classify(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    """Decide whether to auto-approve.

    Returns (auto_approve, reason). Caller uses the reason to populate
    permissionDecisionReason on allow, and to populate the decision log on
    both outcomes.
    """
    if tool_name in UNCONDITIONAL_TOOLS:
        return True, f"tier-1 unconditional ({tool_name} is read-only by construction)"
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not isinstance(command, str):
            return False, "Bash tool_input.command not a string"
        return classify_bash(command)
    return False, f"tool '{tool_name}' is not in the tier-1 allowlist"


# --- Decision logging --------------------------------------------------------

def _log_path() -> str:
    """Where the audit trail lives. Relative to the hook's cwd, which equals
    the project root (Claude Code's cwd when the hook fires).

    The `OYAKATA_DECISIONS_LOG` env var overrides the default. Lets tests
    isolate to a tmpdir; operators can also redirect the log without
    relying on cwd discipline.
    """
    override = os.environ.get("OYAKATA_DECISIONS_LOG")
    if override:
        return override
    return os.path.join("docs", "agents", "oyakata-decisions.md")


def _ensure_log_initialised(path: str) -> None:
    """Create the log file with a header if it doesn't exist yet. Idempotent."""
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# oyakata-decisions — auto-approve audit trail\n"
            "\n"
            "Each entry records a PreToolUse hook decision. Format:\n"
            "`<ISO timestamp> <decision> <tool> <reason> :: <command-or-input>`\n"
            "\n"
            "Decisions:\n"
            "- `ALLOW` — hook auto-approved (no permission prompt was shown).\n"
            "- `DEFER` — hook fell through; Claude Code applied its normal\n"
            "  permission flow (settings allowlist or operator prompt).\n"
            "\n"
            "Slice 1 (v0.2.0) is Opus-only with a static tier-1 allowlist.\n"
            "Full ladder + Oya-as-decider is queued (IA-QUEUE oyakata-2).\n"
            "\n"
            "---\n"
            "\n"
        )


def log_decision(
    decision: str,
    tool_name: str,
    reason: str,
    summary: str,
) -> None:
    """Append a one-line audit entry. Best-effort — never raise.

    `decision` is 'ALLOW' or 'DEFER'.
    `summary` is a short, single-line preview of the tool input (command for
    Bash; file_path for Read; pattern for Grep; etc.).
    """
    try:
        path = _log_path()
        _ensure_log_initialised(path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Collapse the summary to a single line + truncate. Logs are skim-readable.
        single_line = " ".join(summary.split())[:160]
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {decision} {tool_name} :: {reason} :: {single_line}\n")
    except Exception:
        # Logging must never block the tool flow. If the log write fails
        # (read-only volume, permissions, disk full), continue silently.
        pass


def _summarise_input(tool_name: str, tool_input: dict) -> str:
    """One-line preview for the log entry."""
    if tool_name == "Bash":
        return tool_input.get("command", "")
    if tool_name in ("Read", "NotebookRead", "Edit", "Write", "NotebookEdit"):
        return tool_input.get("file_path", "")
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"pattern={pattern} path={path}".strip()
    if tool_name == "Glob":
        return tool_input.get("pattern", "")
    return json.dumps(tool_input, separators=(",", ":"))[:160]


# --- Tier 2: Oya-as-decider --------------------------------------------------
#
# Constants pulled from oyakata.py via duplication. The hook script can't
# import the orchestrator package without dragging in libtmux + the rest
# of the runtime stack — keep these inline and keep the symbol names
# matching so a future refactor (shared `permissions_consts.py`) is mechanical.
TIER2_PENDING_DIR = os.path.join("docs", "agents", "oyakata-pending")
TIER2_VERDICT_TIMEOUT_S = 20
TIER2_VERDICT_POLL_INTERVAL_S = 0.5

# Tool calls eligible for tier-2 routing. State-changing tools that can
# plausibly be in-scope for the active slice if their target file is
# already in motion. Bash writes are deliberately NOT in this set yet —
# the metachar fence + command-head match would all be defer cases, and
# routing those through Oya for verdict adds latency without much benefit.
# Promotable in a later slice once Oya's prompt has tier-2 reasoning chops.
TIER2_TOOL_NAMES = frozenset({
    "Edit",
    "Write",
    "NotebookEdit",
})


def _git_in_motion_files(project_root: str) -> set[str]:
    """Return absolute paths of files currently in `git status --porcelain`
    (modified, added, untracked). Empty set on any failure — non-git
    directories, missing git binary, etc. The caller treats "no in-motion
    set" as "no tier-2 candidates."

    Cheap subprocess: porcelain status on a project of any normal size
    is sub-100ms. We tolerate the cost because the hook only reaches
    this path on Edit/Write/NotebookEdit calls that fell through tier-1.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", project_root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode != 0:
        return set()

    in_motion: set[str] = set()
    for line in proc.stdout.splitlines():
        # Porcelain format: 2-char status, space, path. Untracked is "?? path".
        # Renames are "R  old -> new"; take the new path.
        if len(line) < 4:
            continue
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        # Strip quoting that porcelain adds for paths with special chars.
        if path_part.startswith('"') and path_part.endswith('"'):
            path_part = path_part[1:-1]
        in_motion.add(os.path.abspath(os.path.join(project_root, path_part)))
    return in_motion


def is_tier2_candidate(tool_name: str, tool_input: dict, project_root: str | None = None) -> tuple[bool, str]:
    """Decide whether a tool call should be routed to Oya for tier-2 verdict.

    Returns (is_candidate, reason). A candidate is:
      - tool ∈ {Edit, Write, NotebookEdit}
      - tool_input.file_path resolves to a real path
      - that path is currently in `git status` (modified or untracked)

    If git status fails (non-git project, git missing), no calls are
    candidates — they fall through to defer.
    """
    if tool_name not in TIER2_TOOL_NAMES:
        return False, f"tool '{tool_name}' is not a tier-2 eligible tool"
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return False, "no file_path in tool_input"
    if project_root is None:
        project_root = os.getcwd()
    abs_target = os.path.abspath(file_path)
    in_motion = _git_in_motion_files(project_root)
    if not in_motion:
        return False, "git status is empty or unavailable"
    if abs_target in in_motion:
        return True, "file is in `git status` (in-scope for current cycle)"
    return False, "file is not in `git status` (out of cycle scope)"


def _pending_dir(project_root: str | None = None) -> str:
    """Absolute path to the pending-decisions directory."""
    if project_root is None:
        project_root = os.getcwd()
    return os.path.join(project_root, TIER2_PENDING_DIR)


def _write_request_atomically(request_path: str, payload: dict) -> bool:
    """Tmp + rename so a partially-written file never appears to the
    orchestrator's watcher. Returns True on success, False on any failure."""
    try:
        os.makedirs(os.path.dirname(request_path), exist_ok=True)
        tmp_path = request_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp_path, request_path)
        return True
    except OSError:
        return False


def _poll_for_verdict(verdict_path: str, deadline: float) -> dict | None:
    """Wait for the verdict file to appear; parse and return its JSON.
    Returns None on timeout, file-disappears, or parse failure."""
    while time.time() < deadline:
        if os.path.exists(verdict_path):
            try:
                with open(verdict_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return None
        time.sleep(TIER2_VERDICT_POLL_INTERVAL_S)
    return None


def _cleanup(*paths: str) -> None:
    """Best-effort delete of request + verdict files after consumption.
    Failures are silent — the durable audit lives in oyakata-decisions.md."""
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def consult_oya(tool_name: str, tool_input: dict, project_root: str | None = None) -> tuple[str, str]:
    """Write a tier-2 request file and wait for Oya's verdict.

    Returns (decision, reason). `decision` is 'allow' or 'defer'. Timeouts,
    Oya being offline, and malformed verdict files all collapse to 'defer'
    — the hook's safety contract is that tier-2 NEVER blocks tool flow
    indefinitely and NEVER auto-approves when it can't get an explicit
    allow verdict.

    Request payload schema (Oya reads this; keep it stable):
      {
        "request_id": str,         # UUID
        "timestamp": str,          # ISO UTC
        "tool_name": str,
        "tool_input": dict,        # verbatim from CC
        "tier_2_signal": str,      # why this was routed to tier-2
        "cwd": str                 # project root where the hook fired
      }

    Verdict payload schema (Oya writes this):
      {
        "verdict": "allow" | "defer",
        "reason": str
      }
    """
    if project_root is None:
        project_root = os.getcwd()

    request_id = uuid.uuid4().hex
    pending_dir = _pending_dir(project_root)
    request_path = os.path.join(pending_dir, f"{request_id}.request.json")
    verdict_path = os.path.join(pending_dir, f"{request_id}.verdict.json")

    payload = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tier_2_signal": "file in `git status` (in-scope for current cycle)",
        "cwd": project_root,
    }

    if not _write_request_atomically(request_path, payload):
        return "defer", "could not write tier-2 request file"

    deadline = time.time() + TIER2_VERDICT_TIMEOUT_S
    verdict = _poll_for_verdict(verdict_path, deadline)
    _cleanup(request_path, verdict_path)

    if verdict is None:
        return "defer", f"Oya did not respond within {TIER2_VERDICT_TIMEOUT_S}s"
    if not isinstance(verdict, dict):
        return "defer", "Oya verdict was not a JSON object"
    decision = verdict.get("verdict")
    reason = str(verdict.get("reason", ""))[:200] or "(no reason given)"
    if decision == "allow":
        return "allow", f"Oya verdict — {reason}"
    return "defer", f"Oya verdict — {reason}"


# --- Main --------------------------------------------------------------------

def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        # Malformed input — defer. Never block.
        return 0

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    auto_approve, reason = classify(tool_name, tool_input)
    summary = _summarise_input(tool_name, tool_input)

    if auto_approve:
        log_decision("ALLOW", tool_name, reason, summary)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": f"oyakata-2 tier-1 allowlist: {reason}",
            }
        }
        sys.stdout.write(json.dumps(output))
        return 0

    # Tier-2 path: tool is not in the tier-1 allowlist, but might still be
    # in-scope for the current cycle. Route to Oya for a verdict if (and only
    # if) the tool affects a file already in `git status`. Otherwise fall
    # through to the defer path below.
    is_t2, t2_reason = is_tier2_candidate(tool_name, tool_input)
    if is_t2:
        decision, decision_reason = consult_oya(tool_name, tool_input)
        if decision == "allow":
            log_decision("ALLOW", tool_name, f"tier-2 {decision_reason}", summary)
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": f"oyakata-2 tier-2: {decision_reason}",
                }
            }
            sys.stdout.write(json.dumps(output))
            return 0
        # Tier-2 defer (Oya said no, or timed out) — fall through to the
        # normal defer path so CC's standard prompt fires.
        log_decision("DEFER", tool_name, f"tier-2 {decision_reason}", summary)
        return 0

    # Defer: log the no-op and exit 0 with no output. Claude Code will
    # apply its normal permission flow.
    log_decision("DEFER", tool_name, reason, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
