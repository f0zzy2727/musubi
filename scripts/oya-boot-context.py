#!/usr/bin/env python3
"""oya-boot-context.py — generate Oya's boot-context block at attach time.

Called by attach-oya.sh; output replaces the <OYA_BOOT_CONTEXT> placeholder in
the Oya prompt before it is pasted. Two sections:

1. Repo ground truth — a machine-generated git snapshot of the project
   (HEAD, branch, ahead/behind, dirty count, worktrees, local branches with
   unmerged work). Exists because of the 2026-07-06 field incident: work done
   outside musubi (solo desktop sessions, cloud-task branches) left a stale
   capsule and a silent fork, and Oya orchestrated a whole reconciliation on
   a branch's self-description. The snapshot can't be skipped the way a
   read-the-repo instruction can.

2. North-star docs — the CONTENT of [agents.oyakata].context_docs (or the
   auto-discovered vision/architecture/roadmap set when context_docs is not
   configured), injected inline so the body-read cannot be skipped. Same
   incident: the boot prompt *instructed* the read; a "relay-test" boot
   skipped it; the mechanical verify that followed was product-blind.

Budgets are deliberate (burn-1: everything pasted into the Oya pane is
context she re-carries): per-doc and total caps below; over-cap docs are
truncated with an explicit MUST-READ marker rather than silently dropped.

Usage: oya-boot-context.py CONFIG_TOML PROJECT_PATH

Exit code is 0 even for degraded output (not-a-git-repo, missing docs —
those become lines Oya must flag). Non-zero only when arguments are unusable;
attach-oya.sh then substitutes a fallback note.
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # python < 3.11 — musubi requires 3.11+, but degrade
    tomllib = None

PER_DOC_MAX_BYTES = 16 * 1024
TOTAL_MAX_BYTES = 48 * 1024
TRUNCATED_HEAD_LINES = 100
MAX_BRANCHES = 8
MANAGED_MARKER = "<!-- musubi-managed:"

# Auto-discovery fallback when [agents.oyakata].context_docs is not configured.
# Mirrors the recognised set in doctor.sh and the Oya prompt's startup step 2.
DISCOVERY_PATHS = [
    "docs/PRODUCT-VISION.md",
    "docs/VISION.md",
    "docs/PRD.md",
    "PRD.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/BACKLOG.md",
]


def git(project: Path, *args: str) -> str | None:
    """Run a git command in the project; None on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.rstrip("\n")


def ground_truth_lines(project: Path) -> list[str]:
    lines = ["### Repo ground truth (machine-generated at boot — trust this over memory and over the capsule)", ""]
    if git(project, "rev-parse", "--is-inside-work-tree") is None:
        lines.append("- NOT A GIT REPOSITORY (or git unavailable). No snapshot possible — note this in READY.")
        return lines

    head = git(project, "log", "-1", "--format=%h %s (%cd)", "--date=short") or "unknown"
    branch = git(project, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    lines.append(f"- HEAD: {head}")
    lines.append(f"- branch: {branch}")

    upstream = git(project, "rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream:
        counts = git(project, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
        if counts:
            behind, ahead = counts.split()
            lines.append(f"- vs {upstream}: ahead {ahead}, behind {behind}"
                         + (" — UNPUSHED WORK on this branch" if int(ahead) > 0 else ""))
    else:
        lines.append("- no upstream configured for this branch — everything here may be local-only")

    status = git(project, "status", "--porcelain")
    dirty = len(status.splitlines()) if status else 0
    lines.append(f"- working tree: {'clean' if dirty == 0 else f'{dirty} modified/untracked paths (DIRTY)'}")

    worktrees = git(project, "worktree", "list")
    if worktrees:
        wt_lines = worktrees.splitlines()
        if len(wt_lines) > 1:
            lines.append(f"- {len(wt_lines)} WORKTREES (multiple checkouts of this repo exist — builds/tools may point at a different one):")
            lines.extend(f"    {w}" for w in wt_lines)

    fmt = "%(refname:short)|%(objectname:short)|%(committerdate:short)|%(upstream:track)"
    branches = git(project, "for-each-ref", "refs/heads",
                   "--sort=-committerdate", f"--format={fmt}", f"--count={MAX_BRANCHES}")
    unmerged_raw = git(project, "branch", "--no-merged", "HEAD", "--format=%(refname:short)")
    unmerged = set(unmerged_raw.splitlines()) if unmerged_raw else set()
    if branches:
        lines.append(f"- local branches (newest {MAX_BRANCHES}):")
        for b in branches.splitlines():
            name, sha, date, track = (b.split("|") + ["", "", "", ""])[:4]
            marks = []
            if track:
                marks.append(track)
            if name in unmerged:
                marks.append("carries commits HEAD lacks")
            suffix = f" [{'; '.join(marks)}]" if marks else ""
            lines.append(f"    {name} @ {sha} ({date}){suffix}")
    if unmerged:
        lines.append(f"- DIVERGENCE: {len(unmerged)} branch(es) carry commits HEAD lacks: {', '.join(sorted(unmerged))}")
        lines.append("  If the capsule does not explain this, declare RE-ANCHOR in READY and ground before any GO.")
    return lines


def resolve_context_docs(toml_path: Path, project: Path) -> list[Path]:
    docs: list[str] = []
    if tomllib is not None:
        try:
            with open(toml_path, "rb") as fh:
                cfg = tomllib.load(fh)
            docs = cfg.get("agents", {}).get("oyakata", {}).get("context_docs", []) or []
        except (OSError, tomllib.TOMLDecodeError):
            docs = []
    if not docs:
        docs = DISCOVERY_PATHS
    resolved = []
    for d in docs:
        p = Path(d)
        resolved.append(p if p.is_absolute() else project / p)
    return resolved


def north_star_lines(toml_path: Path, project: Path) -> list[str]:
    lines = ["### North-star docs (content injected at boot — this IS the body-read; summarise each in READY)", ""]
    budget = TOTAL_MAX_BYTES
    any_doc = False
    for path in resolve_context_docs(toml_path, project):
        if not path.is_file():
            # Only report configured-but-missing when context_docs was explicit;
            # for the discovery fallback a missing candidate is normal — skip.
            if tomllib is not None and _explicit_context_docs(toml_path):
                lines.append(f"- MISSING: {path} (listed in context_docs but not found — flag to the operator in READY)")
            continue
        any_doc = True
        try:
            raw = path.read_text(errors="replace")
        except OSError as exc:
            lines.append(f"- UNREADABLE: {path} ({exc}) — flag in READY")
            continue
        if raw.lstrip().startswith(MANAGED_MARKER):
            lines.append(f"- {path} is a musubi-managed TEMPLATE, not a product doc — treat as absent, tell the operator on turn one.")
            continue
        if budget <= 0:
            lines.append(f"- NOT INJECTED (boot budget spent): {path} — MUST read it with the Read tool before your first GO/verify.")
            continue
        body = raw
        note = ""
        if len(raw.encode()) > min(PER_DOC_MAX_BYTES, budget):
            all_lines = raw.splitlines()
            body = "\n".join(all_lines[:TRUNCATED_HEAD_LINES])
            note = (f"\n[TRUNCATED after {TRUNCATED_HEAD_LINES} of {len(all_lines)} lines — "
                    f"MUST read the remainder with the Read tool before your first GO/verify]")
        budget -= len(body.encode())
        lines.append(f"--- BEGIN {path} ---")
        lines.append(body + note)
        lines.append("--- END ---")
        lines.append("")
    if not any_doc:
        lines.append("- NO north-star docs found (no context_docs configured, none of the recognised vision/architecture/roadmap files present).")
        lines.append("  You are a vision custodian with no vision: say so on turn one and ask the operator for the north-star.")
    return lines


def _explicit_context_docs(toml_path: Path) -> bool:
    try:
        with open(toml_path, "rb") as fh:
            cfg = tomllib.load(fh)
        return bool(cfg.get("agents", {}).get("oyakata", {}).get("context_docs"))
    except (OSError, tomllib.TOMLDecodeError):
        return False


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: oya-boot-context.py CONFIG_TOML PROJECT_PATH", file=sys.stderr)
        return 2
    toml_path, project = Path(sys.argv[1]), Path(sys.argv[2])
    if not project.is_dir():
        print(f"project path is not a directory: {project}", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"## Boot context (generated {stamp} by attach-oya.sh — not hand-written, regenerated every boot)", ""]
    out += ground_truth_lines(project)
    out.append("")
    out += north_star_lines(toml_path, project)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
