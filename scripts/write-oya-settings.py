#!/usr/bin/env python3
"""write-oya-settings.py — emit Oya's scoped .claude/settings.local.json.

Called by scripts/attach-oya.sh in place of a shell heredoc (robust-1). The
heredoc interpolated $TARGET / $MUSUBI_ROOT straight into JSON, so a project
path containing a quote, backslash, or `$` would corrupt the generated file —
and it violated CLAUDE.md rule #1 ("write file content with tools, not
heredocs; `$`/quotes corrupt silently"). Here the paths are substituted in
Python and the whole document is rendered with json.dump, which escapes any
special character correctly.

The allowlist is the exact set Oya's startup checklist needs — Read on the
project + musubi tree, Edit/Write on her own log/comms/instrumentation files,
and a few read-only tmux/date/ls Bash commands. No broader trust. It mirrors
the deferring discipline of scripts/oya-pretooluse.py (no unscoped cat/grep).

Usage:
  write-oya-settings.py <target_path> <musubi_root> <out_path>
"""
from __future__ import annotations

import json
import os
import sys


def build_settings(target: str, musubi_root: str) -> dict:
    """Return the settings dict with paths substituted. Trailing slashes are
    stripped so the `/**` globs read cleanly regardless of how the caller
    passed the paths."""
    t = target.rstrip("/")
    m = musubi_root.rstrip("/")
    allow = [
        f"Read({t}/**)",
        f"Read({m}/**)",
        f"Edit({t}/docs/agents/oyakata-log.md)",
        f"Edit({t}/docs/agents/comms/active.txt)",
        f"Edit({t}/docs/agents/operator-actions.md)",
        f"Write({t}/docs/agents/operator-actions.md)",
        f"Edit({t}/docs/agents/operator-channel.md)",
        f"Write({t}/docs/agents/operator-channel.md)",
        f"Edit({t}/docs/agents/asymmetry/**)",
        f"Edit({t}/docs/agents/rules-ledger.yml)",
        f"Edit({t}/docs/agents/shadow-review/**)",
        f"Edit({t}/docs/agents/operator-critique/**)",
        f"Edit({t}/docs/agents/oyakata-pending/**)",
        f"Write({t}/docs/agents/oyakata-log.md)",
        f"Write({t}/docs/agents/asymmetry/**)",
        f"Write({t}/docs/agents/rules-ledger.yml)",
        f"Write({t}/docs/agents/shadow-review/**)",
        f"Write({t}/docs/agents/operator-critique/**)",
        f"Write({t}/docs/agents/oyakata-pending/**)",
        f"Read({t}/docs/agents/oyakata-pending/**)",
        "Bash(tmux list-panes:*)",
        "Bash(tmux capture-pane:*)",
        "Bash(tmux list-sessions:*)",
        "Bash(date:*)",
        "Bash(ls:*)",
        "Bash(wc:*)",
        "Bash(pwd)",
    ]
    return {"permissions": {"allow": allow}}


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: write-oya-settings.py <target_path> <musubi_root> <out_path>",
            file=sys.stderr,
        )
        return 2
    target, musubi_root, out_path = argv[1], argv[2], argv[3]
    data = build_settings(target, musubi_root)
    # Atomic write: tmp + rename so a half-written file never replaces a good one.
    tmp_path = out_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, out_path)
    except OSError as e:
        print(f"write-oya-settings: could not write {out_path}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
