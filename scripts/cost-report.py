#!/usr/bin/env python3
"""cost-report.py — honest token accounting for a musubi run (Claude side).

Answers the skeptic's "be honest about what it costs" by reading the REAL
usage data Claude Code writes to its local session logs
(`~/.claude/projects/**/*.jsonl`, the same source `ccusage` reads) and summing
the tokens. No fabricated dollar figure, no estimated meter — just the counts
that actually happened, with the cost framing stated honestly.

HONEST LIMITATIONS (read before trusting the number):
  - **Claude side only.** Codex does not expose per-turn token usage in its logs
    (`~/.codex/history.jsonl` carries no token counts), so the pair's *other*
    half is not included here. This is a floor, not the full pair total.
  - **Per time-window, not per musubi-cycle.** Claude Code logs are per-session
    by timestamp; there's no cycle marker to attribute against. Use `--since`
    to bound a window; you can't slice it to a single slice.
  - **Reads an undocumented local format.** Claude Code's JSONL schema can change
    between versions; if the numbers look wrong, the schema probably moved.

WHAT IT COSTS, framed honestly: under a flat Pro/Max-style subscription the
marginal dollar cost of these tokens is ~zero — you pay for the seat. On
metered API, multiply the tokens below by your plan's per-token rate. This tool
deliberately does NOT print a dollar figure, because the honest answer depends
entirely on which of those two worlds you're in.

Usage:
  cost-report.py                         # all Claude sessions on this machine
  cost-report.py --since 2026-05-29      # only messages on/after this date
  cost-report.py --project musubi        # only sessions whose cwd contains this
  cost-report.py --format json

Exit codes:
  0  report printed
  2  Claude projects dir not found
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

_DEFAULT_DIR = os.path.expanduser("~/.claude/projects")
_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def iter_usage(projects_dir, since=None, project=None):
    """Yield (usage_dict, cwd) for every assistant message with token usage.
    `since` is an ISO date string (compared lexically against the ISO
    timestamp, which sorts correctly); `project` is a cwd substring filter."""
    for path in glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    msg = rec.get("message")
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    if since:
                        ts = rec.get("timestamp", "")
                        if ts and ts[:10] < since:
                            continue
                    cwd = rec.get("cwd", "")
                    if project and project not in cwd:
                        continue
                    yield usage, cwd
        except OSError:
            continue


def tally(projects_dir, since=None, project=None):
    totals = {k: 0 for k in _TOKEN_FIELDS}
    messages = 0
    for usage, _cwd in iter_usage(projects_dir, since, project):
        messages += 1
        for k in _TOKEN_FIELDS:
            totals[k] += int(usage.get(k, 0) or 0)
    totals["messages"] = messages
    totals["billable_input"] = totals["input_tokens"] + totals["cache_creation_input_tokens"]
    return totals


def format_text(t, since, project):
    scope = []
    if since:
        scope.append(f"since {since}")
    if project:
        scope.append(f"project~={project!r}")
    scope_s = ", ".join(scope) if scope else "all sessions on this machine"
    lines = [
        "=== musubi token report (Claude side only) ===",
        f"Scope: {scope_s}",
        f"Assistant messages: {t['messages']:,}",
        f"  input tokens:          {t['input_tokens']:,}",
        f"  cache-creation tokens: {t['cache_creation_input_tokens']:,}",
        f"  cache-read tokens:     {t['cache_read_input_tokens']:,}",
        f"  output tokens:         {t['output_tokens']:,}",
        "",
        "Cost framing (honest): under a flat Pro/Max subscription these tokens",
        "cost ~zero at the margin. On metered API, multiply by your per-token rate.",
        "Codex's half of the pair is NOT included — it doesn't log per-turn usage.",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Honest Claude-side token accounting for a musubi run.")
    parser.add_argument("--claude-dir", default=_DEFAULT_DIR,
                        help="Claude Code projects dir (default: ~/.claude/projects)")
    parser.add_argument("--since", help="only messages on/after this ISO date (YYYY-MM-DD)")
    parser.add_argument("--project", help="only sessions whose cwd contains this substring")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.claude_dir):
        print(f"ERROR: Claude projects dir not found: {args.claude_dir}\n"
              f"(Claude Code hasn't logged any sessions here, or it's installed elsewhere.)",
              file=sys.stderr)
        return 2

    t = tally(args.claude_dir, args.since, args.project)
    if args.format == "json":
        print(json.dumps({"scope": {"since": args.since, "project": args.project}, "totals": t}, indent=2))
    else:
        print(format_text(t, args.since, args.project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
