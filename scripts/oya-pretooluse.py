#!/usr/bin/env python3
"""oya-pretooluse.py — Claude Code PreToolUse hook for oyakata-2.

Two tiers:

  Tier 1 — Static allowlist (slices 1 + 2; hardened by sec-1 2026-06-16).
    Read-only ops (`Read`, `Grep`, `Glob`, `NotebookRead`) and a narrow
    METADATA-ONLY Bash subset (`git status|branch|rev-parse|ls-files`, `pwd`,
    `ls`, `stat`, …) are auto-approved. Content/config-disclosing reads
    (`git show|diff|log`, `git config`, `git remote`) DEFER by default — they
    leak secrets — and re-enable only under `[security].repo_has_no_secrets`.
    Any shell metachar OR `$` expansion in the Bash command defers.

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

# Bash commands are split into two tiers by DISCLOSURE risk, not just by whether
# they mutate state. The audit (sec-1, 2026-06-16) showed that "non-mutating" is
# not the same as "safe to auto-approve": a read can still leak secrets. Each
# pattern matches the WHOLE command from the start and must be paired with the
# no-shell-metachar + no-`$`-expansion fence below — a head match alone is not
# enough, because `git status | tee statefile.txt` still mutates state.
#
#   METADATA_SAFE — reveal only metadata (status, refs, names, file stats).
#     Always auto-approved.
#   DISCLOSE      — reveal file CONTENT or config/credentials (git show/diff/log,
#     git config, git remote, git blame). Deferred BY DEFAULT; auto-approved only
#     when the operator has explicitly opted in (env flag below, set from
#     `[security].repo_has_no_secrets`). Default-off so the safe default never
#     leaks.
#
# Conservative by design. If you can't tell at a glance whether a pattern is
# metadata-only, put it in DISCLOSE (or leave it off entirely). The cost of a
# false-negative (extra prompt) is zero; the cost of a false-positive
# (auto-approved disclosure) is silent secret leakage + trust loss.
METADATA_SAFE_PATTERNS = tuple(
    re.compile(p) for p in (
        # git — metadata only (status, refs, names, tracking). No file content.
        r"^git\s+status(\s|$)",
        r"^git\s+branch(\s+(-l|--list|-a|-r|-v))*\s*$",
        r"^git\s+rev-parse(\s|$)",
        r"^git\s+ls-files(\s|$)",
        r"^git\s+ls-tree(\s|$)",
        # git log ONLY in the --oneline summary form (subjects, not patches).
        # General `git log` is in DISCLOSE — `git log -p`/`-G`/`-S` show content.
        r"^git\s+log\s+--oneline(\s+-n\s+\d+|\s+-\d+)?\s*$",
        # filesystem — metadata only (paths, sizes, types). No content.
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
    )
)

# Reveal file CONTENT or config/credentials. Deferred unless the operator opts in.
DISCLOSE_PATTERNS = tuple(
    re.compile(p) for p in (
        r"^git\s+show(\s|$)",                      # `git show HEAD:.env` → tracked secret
        r"^git\s+diff(\s|$)",                      # working-tree / staged content
        r"^git\s+log(\s|$)",                       # general log incl. -p/-G/-S patch output
        r"^git\s+blame(\s|$)",                     # prints file content lines
        r"^git\s+config\s+--get(\s|$)",            # may read http.extraheader / tokens
        r"^git\s+config\s+--list(\s|$)",           # dumps all config incl. credentials
        r"^git\s+remote(\s+(-v|--verbose))?\s*$",  # URLs may embed user:token@host
    )
)
# DELIBERATELY NOT auto-approved at all (no opt-in re-enables these):
#   printenv / env     — dump the environment, including exported API keys.
#   echo               — removed (was auto-approved): near-zero benefit and the
#                        cleanest env-expansion vector (`echo $TOKEN`). With `$`
#                        now fenced it would be inert anyway, but it earns nothing.


# --- Repo-scoped orientation reads (2026-06-24) ------------------------------
# The single biggest source of per-session permission friction is the agents'
# boot orientation: they hammer `sed -n`, `tail`, `head`, `cat`, `nl`, `rg`,
# `grep` over project files every session, all deferred to a prompt. These read
# file CONTENT, so sec-1 rightly keeps them off the unconditional allowlist —
# but `cat ~/.ssh/id_rsa` and `cat src/app.ts` are NOT the same risk. The danger
# is an ARBITRARY-path read; an in-repo read under a repo that has declared it
# holds no secrets is exactly what `[security].repo_has_no_secrets` already
# asserts. So: auto-approve these reads ONLY when (a) the opt-in is set AND
# (b) every path argument is repo-RELATIVE (no leading `/` or `~`, no `..`
# traversal). An absolute/home/parent path still defers even under the opt-in —
# a strictly tighter guarantee than the old blanket exclusion, with the daily
# friction removed for opted-in beds.
REPO_READ_TOOLS = frozenset({
    "cat", "head", "tail", "nl", "rg", "grep", "less", "more",
})


# Filenames that are secret-bearing even inside a repo. `repo_has_no_secrets`
# asserts the SOURCE holds no secrets — it never licenses reading these. Matched
# on the basename so a path prefix can't smuggle them in.
_SECRET_BASENAME_RE = re.compile(
    r"(?i)(^\.env($|\.)|(^|\.)(pem|key|p12|pfx|keystore|jks)$|"
    r"^(id_rsa|id_ed25519|id_dsa|id_ecdsa)$|^\.?(npmrc|netrc|pgpass|htpasswd)$|"
    r"credentials?$|secrets?($|\.))")


def _is_unsafe_read_token(token: str) -> bool:
    """True if a token denotes a path we must not auto-approve reading: one that
    could escape the repo root (absolute / home / `..`), OR a secret-bearing
    filename even inside the repo (`.env`, `*.key`, `id_rsa`, …)."""
    # Strip surrounding quotes FIRST: a leading quote (`cat "/etc/passwd"`) must
    # not mask an absolute/home path from the repo-escape check below. The
    # metachar fence has already removed `$`/backtick/pipe, so quotes here are
    # only path delimiters, never expansion vectors.
    token = token.strip("'\"")
    if token.startswith(("/", "~")):
        return True
    segments = token.split("/")
    if ".." in segments:
        return True
    basename = segments[-1].strip("'\"")
    return bool(_SECRET_BASENAME_RE.search(basename))


def classify_repo_read(command: str) -> tuple[bool, str]:
    """Return (is_repo_scoped_read, reason). True only for a content-read tool
    whose every path argument stays inside the repo. Pure; the metachar fence in
    classify_bash has already guaranteed no pipe/redirect/`$`/subshell, so a
    plain whitespace split is a safe tokeniser here."""
    parts = command.split()
    if not parts:
        return False, ""
    tool = parts[0]
    if tool not in REPO_READ_TOOLS:
        return False, ""
    # sed is a special case: only the read-and-print form, never in-place edit.
    if tool == "sed":
        return False, ""  # handled by the explicit sed clause below
    for tok in parts[1:]:
        if tok.startswith("-"):
            continue  # a flag, not a path
        if _is_unsafe_read_token(tok):
            return False, f"unsafe read target (outside repo or secret-bearing): {tok}"
    return True, f"repo-scoped content read ({tool})"


def classify_sed_read(command: str) -> tuple[bool, str]:
    """`sed -n '<range>p' <file>` is the agents' most-used orientation read.
    Auto-approvable only as the non-mutating read-print form (`-n`, never `-i`)
    over a repo-relative file."""
    parts = command.split()
    if not parts or parts[0] != "sed":
        return False, ""
    if any(p == "-i" or p.startswith("-i") for p in parts):
        return False, "sed -i edits in place"
    if "-n" not in parts:
        return False, "sed without -n is not a plain read"
    for tok in parts[1:]:
        if tok.startswith("-"):
            continue
        # Quoted ranges/scripts (e.g. '1,5p') carry no path separator and stay.
        if _is_unsafe_read_token(tok):
            return False, f"sed reads an unsafe target (outside repo or secret-bearing): {tok}"
    return True, "repo-scoped sed read (-n)"


# --- Blast-radius gate (blast-1, 2026-06-24) ---------------------------------
# A different axis from the disclosure tiers above. Those ask "does this leak
# secrets?"; this asks "is this an expensive / irreversible / fan-out ACTION?"
# Field report (Michael, 1-in-a-billion bed): "apply this to the other apps"
# became "re-clone every voice for the other apps" — an API spend that overwrote
# resources that already existed, hand-stopped by the operator; neither peer nor
# Oya flagged it. The existing tiers only DEFER such a command (a generic prompt
# with no blast-radius framing). This gate POSITIVELY flags it and returns a hard
# `deny` whose reason instructs the agent to state the blast radius (count, cost,
# reversibility) and get an operator confirm BEFORE acting — the deny text is
# returned to the agent, so it converts a silent overreach into a forced surface.
#
# Conservative + high-precision: each pattern is an unambiguously destructive,
# irreversible, money-spending, or broadly-fanned-out action. A false positive is
# one extra confirm; a false negative is a recloned account. Coverage is partial
# BY CONSTRUCTION — this hook sees only Opus Bash, never Codex or in-app/API
# actions, so the runbook discipline rule (blast-1 Part B) is the primary net and
# this is the mechanical backstop for the shell-command slice of it.
#
# `(?i)` per-pattern; matched with `re.search` (the verb can sit anywhere in the
# command, not only at the start — unlike the anchored allowlist above).
BLAST_RADIUS_PATTERNS = tuple(
    (re.compile(p), label) for p, label in (
        # Irreversible filesystem / VCS destruction.
        (r"(?i)\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "recursive force-delete (rm -rf)"),
        (r"(?i)\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", "force-push (rewrites remote history)"),
        (r"(?i)\bgit\s+reset\s+--hard\b", "git reset --hard (discards working tree)"),
        (r"(?i)\bgit\s+clean\s+-[a-z]*f", "git clean -f (deletes untracked files)"),
        (r"(?i)\bfind\b.*\s-delete\b", "find -delete (bulk delete)"),
        (r"(?i)\bxargs\b.*\b(rm|delete|destroy)\b", "xargs into a delete (fan-out delete)"),
        # Destructive data / infra operations.
        (r"(?i)\b(drop|truncate)\s+(table|database|schema)\b", "SQL DROP/TRUNCATE (irreversible data loss)"),
        (r"(?i)\bdelete\s+from\b(?!.*\bwhere\b)", "DELETE without WHERE (whole-table wipe)"),
        (r"(?i)\bterraform\s+destroy\b", "terraform destroy (tears down infra)"),
        (r"(?i)\bkubectl\s+delete\b", "kubectl delete (removes live resources)"),
        (r"(?i)\b(docker|podman|kubectl)\b.*\bprune\b", "container/image prune (bulk removal)"),
        (r"(?i)\baws\s+s3\s+(rb|rm)\b", "aws s3 bucket/object removal"),
        # Money-spending / external-resource creation, especially at scale.
        (r"(?i)\b(clone|create|generate|synthesi[sz]e)\b.*\b(voice|voices|model|models)\b", "voice/model create/clone (API spend; may overwrite existing)"),
        (r"(?i)(?:^|\s)--?all\b.*\b(clone|create|delete|remove|regenerate|reset|overwrite)\b", "fan-out over --all with a create/delete verb"),
        (r"(?i)\b(clone|create|delete|remove|regenerate|reset|overwrite)\b.*(?:^|\s)--?all\b", "create/delete verb fanned out over --all"),
        (r"(?i)\bfor\b.+\bin\b.+;\s*do\b.*\b(clone|create|delete|remove|rm|push|deploy|destroy)\b", "loop fanning a costly/destructive action over many targets"),
    )
)


def classify_blast_radius(command: str) -> tuple[bool, str | None]:
    """Return (is_high_blast, reason). reason is None when no pattern matches.

    Pure + high-precision: only unambiguously destructive / irreversible / money-
    spending / fan-out actions. The reason names the specific class so the deny
    text can tell the agent exactly what to declare before retrying."""
    if not isinstance(command, str) or not command.strip():
        return False, None
    for pattern, label in BLAST_RADIUS_PATTERNS:
        if pattern.search(command):
            return True, label
    return False, None


def _disclosure_opt_in() -> bool:
    """True when the operator has declared the repo holds no secrets worth
    protecting from a read — `[security].repo_has_no_secrets`, surfaced to the
    hook as MUSUBI_REPO_HAS_NO_SECRETS. Default False: the safe default never
    auto-approves a content/config disclosure."""
    return os.environ.get("MUSUBI_REPO_HAS_NO_SECRETS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

# Any of these in the command means "DON'T auto-approve, defer." The shell
# metacharacters that compose commands or redirect output. If any of them
# appear anywhere in the command string — quoted or not — we conservatively
# refuse to auto-approve. This is over-strict (e.g. `git log --grep="foo|bar"`
# won't auto-approve because of the pipe inside the quoted regex) but the
# cost is zero (operator just answers the prompt manually) and the safety
# margin is large.
#
# `\n` and `\r` are in this list because the allowlist patterns anchor only at
# the START of the string (`re.match`). Without the newline fence, a command
# whose first line is allow-listed would auto-approve a SECOND line carrying an
# arbitrary payload — e.g. "git status\nrm -rf /" matches `^git\s+status` and
# would run the rm. Claude Code passes a multi-line command to one shell, so the
# whole payload executes. Treat any newline as a command separator and defer.
# `$` (bare) is fenced because ANY expansion can disclose a secret without a
# pipe or subshell: `echo $TOKEN`, `ls $HOME`, `git show $REF` all let the shell
# substitute an env var / path the allowlist never saw. This subsumes `$(` and
# `$((` (kept below for explicitness). Cost: a read-only command containing a
# literal `$` defers to a prompt — cheap; the leak it prevents is not.
DANGEROUS_SHELL_TOKENS = (
    "|",
    ">",
    "<",
    ";",
    "&",
    "$",
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
        return False, "contains shell metacharacter (chain/pipe/redirect/expansion)"
    for pattern in METADATA_SAFE_PATTERNS:
        if pattern.match(command):
            return True, f"matches tier-1 metadata-only pattern: {pattern.pattern}"
    for pattern in DISCLOSE_PATTERNS:
        if pattern.match(command):
            if _disclosure_opt_in():
                return True, (
                    "matches content/config pattern; disclosure opt-in enabled "
                    f"([security].repo_has_no_secrets): {pattern.pattern}"
                )
            return False, (
                "discloses file content or config; deferred by default "
                f"(set [security].repo_has_no_secrets to opt in): {pattern.pattern}"
            )
    # Repo-scoped orientation reads (sed -n / tail / head / cat / nl / rg / grep
    # of an in-repo path). Same disclosure opt-in as above, plus a path-scope
    # check so an out-of-repo read still defers even under the opt-in.
    for is_read, rr_reason in (classify_sed_read(command),
                               classify_repo_read(command)):
        if is_read:
            if _disclosure_opt_in():
                return True, (
                    "repo-scoped read; disclosure opt-in enabled "
                    f"([security].repo_has_no_secrets): {rr_reason}"
                )
            return False, (
                "repo-scoped read; deferred by default "
                f"(set [security].repo_has_no_secrets to opt in): {rr_reason}"
            )
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

    summary = _summarise_input(tool_name, tool_input)

    # Blast-radius gate (blast-1): checked FIRST so it overrides any allowlist
    # match — a high-blast action is never auto-approved, even if a future
    # allowlist would. Hard `deny`, with a reason returned to the agent that
    # forces it to declare the blast radius and get an operator confirm before
    # retrying. Converts a silent overreach into a surfaced decision.
    if tool_name == "Bash":
        is_blast, blast_reason = classify_blast_radius(
            tool_input.get("command", ""))
        if is_blast:
            log_decision("BLAST-DENY", tool_name, blast_reason, summary)
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"musubi blast-radius gate: {blast_reason}. This is an "
                        f"expensive/irreversible/fan-out action. STOP — do not run "
                        f"it yet. Post the exact blast radius to comms first (how "
                        f"many targets, what cost, is it reversible, does it "
                        f"overwrite anything that already exists) and get an "
                        f"explicit operator confirm before retrying."
                    ),
                }
            }
            sys.stdout.write(json.dumps(output))
            return 0

    auto_approve, reason = classify(tool_name, tool_input)

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
