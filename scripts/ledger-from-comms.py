#!/usr/bin/env python3
"""ledger-from-comms.py — mechanical rules-ledger fire counting from comms.

Reconstructs (and optionally writes back) the `fires` counters in a
project's `rules-ledger.yml` by scanning one or more comms files for each
rule's `citation_pattern`. Replaces the manual cycle-close counter-update
that previously depended on Oya remembering to do it — the human dependency
that left the Codebase A ledger at backfill-zero across multiple real cycles.

This is protocol-1 Tier 1 item 3 ("auto-generate rules-ledger updates from
comms"). It makes the *fire* counters mechanical. Catches / bypasses / skips /
silent_misses remain judgement calls — Oya still writes the `notable_signals`
commentary and those counters; only fires become mechanical here.

What counts as a fire (mechanical proxy)
----------------------------------------
A rule fires in a comms *message* when that message contains the rule's
`citation_pattern` substring. Fires are counted per-message (one block that
repeats a pattern five times is one fire event, not five), which is the
closest mechanical proxy to the schema's "the citation shaped this comms
event" bar. Routine passing mentions are over-counted by any purely
mechanical scan — the operator/Oya refines load-bearing vs passing in the
ledger's `notes` / `notable_signals`. Treat fire counts as a TREND proxy, not
an audit: a grep can't tell a load-bearing citation from a passing mention, so
the robust signal here is zero-fire (a rule nobody cited), not the precise
magnitude of a non-zero count. The schema's other fire sources
(orchestrator guard-refusal logs, Oya's retrospective observations) are out
of scope for a comms-only scan.

Cycle attribution
-----------------
A comms *archive* file is named `comms-<cycle-slug>.txt`; the cycle slug is
derived by stripping the `comms-` prefix and `.txt` suffix. For a live
`active.txt` (or any non-conforming name) pass `--cycle <slug>` to attribute
its fires, otherwise the file stem is used.

Output / write-back
-------------------
  --format text (default) — human-scannable fires-per-rule-per-cycle report
  --format json           — machine-consumable report
  --apply                 — write reconstructed `fires` counters back into the
                            ledger via targeted text edits (every comment and
                            provenance block preserved byte-for-byte; only the
                            single-line `fires: { ... }` per rule is rewritten).
                            Auto-backs-up the ledger first. Idempotent:
                            recomputed from scratch each run.

Invocation
----------
  # audit one archive
  ledger-from-comms.py --ledger docs/agents/rules-ledger.yml \\
      --comms docs/agents/archive/comms-2026-05-15-token-cleanup-001.txt

  # audit every archive (cycle slug per file), JSON
  ledger-from-comms.py --ledger docs/agents/rules-ledger.yml \\
      --comms-glob 'docs/agents/archive/comms-*.txt' --format json

  # reconstruct and write back
  ledger-from-comms.py --ledger docs/agents/rules-ledger.yml \\
      --comms-glob 'docs/agents/archive/comms-*.txt' --apply

Exit codes
----------
  0  report produced (or --apply completed)
  1  --check mode and the ledger's on-disk fires differ from reconstructed
  2  invalid arguments / unreadable ledger / pyyaml missing
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob as _glob
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    print(
        "ERROR: pyyaml not installed. Run `pip install pyyaml` "
        "(or `pip install -r requirements.txt`).",
        file=sys.stderr,
    )
    sys.exit(2)


# Message-block separator used in comms files: a run of 10+ dashes on its own
# line (the orchestrator writes `---------------------------------------------------`).
_BLOCK_SEP = re.compile(r"^-{10,}\s*$", re.MULTILINE)


@dataclass
class Rule:
    id: str
    citation_pattern: str


@dataclass
class RuleFire:
    rule_id: str
    citation_pattern: str
    total: int = 0
    by_cycle: dict = field(default_factory=dict)  # {cycle-slug: count}


# ---------------------------------------------------------------------------
# Ledger reading (read-only parse for rule ids + citation patterns)
# ---------------------------------------------------------------------------

def load_rules(ledger_path):
    """Parse the ledger YAML and return [Rule(...)] for every rule that
    declares a citation_pattern. Read-only — never mutates the file."""
    with open(ledger_path) as f:
        data = yaml.safe_load(f)
    if not data or "rules" not in data:
        return []
    rules = []
    for entry in data["rules"]:
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id")
        pattern = entry.get("citation_pattern")
        if rid and pattern:
            rules.append(Rule(id=rid, citation_pattern=pattern))
    return rules


# ---------------------------------------------------------------------------
# Comms scanning
# ---------------------------------------------------------------------------

def cycle_slug_for(comms_path, override=None):
    """Derive the cycle slug for a comms file. `comms-<slug>.txt` -> <slug>;
    otherwise the file stem. An explicit --cycle override always wins."""
    if override:
        return override
    stem = os.path.basename(comms_path)
    if stem.endswith(".txt"):
        stem = stem[: -len(".txt")]
    if stem.startswith("comms-"):
        stem = stem[len("comms-"):]
    return stem


def split_messages(text):
    """Split comms text into message blocks on the dashed separator line.
    Empty blocks (leading/trailing/duplicate separators) are dropped."""
    return [b for b in _BLOCK_SEP.split(text) if b.strip()]


def count_fires(rules, text, cycle, accumulator):
    """For each rule, count the comms message-blocks in `text` that contain
    its citation_pattern (case-insensitive). Adds to `accumulator`
    ({rule_id: RuleFire}) in place, attributing to `cycle`."""
    blocks = split_messages(text)
    # Pre-compile case-insensitive literal matchers once per rule.
    matchers = {r.id: re.compile(re.escape(r.citation_pattern), re.IGNORECASE)
                for r in rules}
    for rule in rules:
        rx = matchers[rule.id]
        hits = sum(1 for block in blocks if rx.search(block))
        if hits:
            fire = accumulator[rule.id]
            fire.total += hits
            fire.by_cycle[cycle] = fire.by_cycle.get(cycle, 0) + hits


def reconstruct(rules, comms_files, cycle_override=None):
    """Scan all comms_files and return {rule_id: RuleFire} with fires
    attributed by cycle. Files that can't be read are skipped with a stderr
    note (a malformed archive must not abort a multi-file reconstruction)."""
    accumulator = {r.id: RuleFire(rule_id=r.id, citation_pattern=r.citation_pattern)
                   for r in rules}
    for path in comms_files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"  (skipped unreadable comms file {path}: {e})", file=sys.stderr)
            continue
        cycle = cycle_slug_for(path, cycle_override)
        count_fires(rules, text, cycle, accumulator)
    return accumulator


# ---------------------------------------------------------------------------
# Write-back — targeted text edit of the single-line `fires: { ... }` per rule
# ---------------------------------------------------------------------------

def _format_by_cycle(by_cycle):
    """Render a by_cycle dict as inline YAML flow mapping, sorted by slug for
    a stable, diff-friendly result. Empty -> {}."""
    if not by_cycle:
        return "{}"
    parts = [f"{slug}: {count}" for slug, count in sorted(by_cycle.items())]
    return "{ " + ", ".join(parts) + " }"


def render_fires_line(indent, fire):
    """Produce the replacement `fires: { ... }` line (no trailing newline)."""
    return (f"{indent}fires: {{ total: {fire.total}, "
            f"by_cycle: {_format_by_cycle(fire.by_cycle)} }}")


# Top-level rule boundary: `  - id: <slug>` lines in the `rules:` list.
_RULE_HEAD = re.compile(r"^[ \t]*- id:[ \t]*(?P<id>\S+)[ \t]*$", re.MULTILINE)

# A `fires:` mapping in either YAML form within a single rule block:
#   flow:     `    fires: { total: 0, by_cycle: {} }`
#   expanded: `    fires:\n      total: 0\n      by_cycle: {...}`
# The expanded arm consumes only lines indented strictly deeper than `fires:`
# (the `(?P=indent)[ \t]` backref guarantees a sibling key like `catches:` at
# the same indent terminates the match).
_FIRES_MAPPING = re.compile(
    r"^(?P<indent>[ \t]*)fires:[ \t]*"
    r"(?:\{.*\}[ \t]*$|$(?:\n(?P=indent)[ \t].*)*)",
    re.MULTILINE,
)


def _split_rule_blocks(text):
    """Split ledger text into [(rule_id_or_None, block_text)] segments, one per
    top-level rule (plus a leading preamble with id None). Concatenating every
    block_text reproduces the input byte-for-byte."""
    matches = list(_RULE_HEAD.finditer(text))
    if not matches:
        return [(None, text)]
    segments = []
    if matches[0].start() > 0:
        segments.append((None, text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segments.append((m.group("id"), text[m.start():end]))
    return segments


def load_existing_fires(ledger_path):
    """Read each rule's current fires.by_cycle from the ledger (yaml, read-only).
    Returns {rule_id: {cycle: count}}. Used to MERGE a cycle-close scan into the
    accumulated history rather than overwrite it."""
    with open(ledger_path) as f:
        data = yaml.safe_load(f)
    out = {}
    for entry in (data or {}).get("rules", []) or []:
        if isinstance(entry, dict) and entry.get("id"):
            fires = entry.get("fires") or {}
            out[entry["id"]] = dict(fires.get("by_cycle") or {})
    return out


def merge_fires(accumulator, existing):
    """Merge this scan's per-cycle fires into the existing per-cycle history.
    Cycles in the current scan overwrite their own entry (idempotent re-runs);
    cycles only in history are preserved. This is the core of cycle-close:
    running over just the active cycle ADDS it without wiping prior cycles —
    the bug that an overwrite-only apply would cause. Returns {rid: RuleFire}."""
    merged = {}
    for rid, fire in accumulator.items():
        by_cycle = dict(existing.get(rid, {}))
        by_cycle.update(fire.by_cycle)  # current scan wins per cycle
        m = RuleFire(rule_id=rid, citation_pattern=fire.citation_pattern)
        m.by_cycle = by_cycle
        m.total = sum(by_cycle.values())
        merged[rid] = m
    return merged


def apply_fires(ledger_text, accumulator):
    """Return (new_text, changed_count). Rewrites each rule's `fires:` mapping
    (flow OR expanded form) to the given counts as a normalized single-line flow
    mapping, preserving every other byte (comments, provenance prose,
    catches/bypasses/skips counters). Callers pass a MERGED accumulator (see
    merge_fires) so history is preserved."""
    out = []
    changed = 0
    for rule_id, block in _split_rule_blocks(ledger_text):
        fire = accumulator.get(rule_id) if rule_id else None
        if fire is None:
            out.append(block)
            continue

        def _repl(m, fire=fire):
            return render_fires_line(m.group("indent"), fire)

        new_block, n = _FIRES_MAPPING.subn(_repl, block, count=1)
        if n and new_block != block:
            changed += 1
        out.append(new_block)
    return "".join(out), changed


def backup_path_for(path):
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{path}.backup-{stamp}"


def _set_meta_line(text, key, value):
    """Replace the first top-level `<key>: ...` line (anchored, so commented
    `# <key>:` mentions lower in the file are untouched)."""
    rx = re.compile(rf"^{re.escape(key)}:[ \t]*.*$", re.MULTILINE)
    new, n = rx.subn(lambda _m: f"{key}: {value}", text, count=1)
    return new if n else text


def current_cycle_in(text):
    m = re.search(r"^last_updated_cycle:[ \t]*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def latest_cycle(accumulator):
    """Most-recent cycle slug across all reconstructed fires. Best-effort —
    relies on date-bearing slugs sorting correctly; for cycle-close the caller
    should pass --cycle explicitly rather than depend on this."""
    cycles = set()
    for fire in accumulator.values():
        cycles.update(fire.by_cycle.keys())
    return max(cycles) if cycles else None


def apply_metadata(text, when, cycle):
    """Stamp top-level last_updated_at (always) and last_updated_cycle (when a
    cycle is known) so the ledger header reflects the latest close."""
    text = _set_meta_line(text, "last_updated_at", when)
    if cycle:
        text = _set_meta_line(text, "last_updated_cycle", cycle)
    return text


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _fired_sorted(accumulator):
    fired = [f for f in accumulator.values() if f.total > 0]
    fired.sort(key=lambda f: (-f.total, f.rule_id))
    return fired


def format_text(accumulator, comms_files):
    fired = _fired_sorted(accumulator)
    silent = sorted(r for r, f in accumulator.items() if f.total == 0)
    lines = []
    lines.append("=== Rules-ledger fires reconstructed from comms ===")
    lines.append("(fire counts are a TREND proxy, not an audit: a grep can't tell a "
                 "load-bearing citation from a passing mention — zero-fire is the robust signal)")
    lines.append(f"Comms files scanned: {len(comms_files)}")
    lines.append(f"Rules with fires: {len(fired)} / {len(accumulator)}")
    lines.append("")
    if fired:
        for fire in fired:
            lines.append(f"• {fire.rule_id}  —  {fire.total} fire(s)")
            for slug, count in sorted(fire.by_cycle.items()):
                lines.append(f"    {slug}: {count}")
        lines.append("")
    if silent:
        lines.append(f"Silent rules (zero fires across scanned comms): {len(silent)}")
        for rid in silent:
            lines.append(f"    - {rid}")
        lines.append("")
        lines.append("(Zero fires across scanned comms is a pruning/refinement")
        lines.append(" signal per rules-ledger-schema.md — investigate before acting.)")
    return "\n".join(lines)


def format_json(accumulator, comms_files):
    return json.dumps({
        "summary": {
            "comms_files_scanned": len(comms_files),
            "rules_total": len(accumulator),
            "rules_with_fires": sum(1 for f in accumulator.values() if f.total > 0),
        },
        "fires": {
            f.rule_id: {"total": f.total, "by_cycle": f.by_cycle}
            for f in accumulator.values()
        },
    }, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_comms(args):
    files = list(args.comms or [])
    if args.comms_glob:
        files.extend(sorted(_glob.glob(args.comms_glob)))
    # De-dupe while preserving order.
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reconstruct rules-ledger fire counters from comms files."
    )
    parser.add_argument("--ledger", required=True,
                        help="path to the project's rules-ledger.yml")
    parser.add_argument("--comms", nargs="*",
                        help="comms file path(s) to scan")
    parser.add_argument("--comms-glob",
                        help="glob of comms files to scan (e.g. 'archive/comms-*.txt')")
    parser.add_argument("--cycle",
                        help="override cycle slug for all scanned files "
                             "(default: derive per-file from filename)")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="report format (default: text)")
    parser.add_argument("--apply", action="store_true",
                        help="merge reconstructed fires into the ledger + stamp "
                             "header metadata (auto-backs-up first; preserves all "
                             "comments and prior cycles)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if on-disk fires differ from reconstructed "
                             "(CI currency gate; never writes)")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.ledger):
        parser.error(f"ledger not found: {args.ledger}")
    comms_files = _resolve_comms(args)
    if not comms_files:
        parser.error("must provide --comms and/or --comms-glob (matched no files)")

    try:
        rules = load_rules(args.ledger)
    except (OSError, yaml.YAMLError) as e:
        print(f"ERROR: cannot read ledger {args.ledger}: {e}", file=sys.stderr)
        return 2
    if not rules:
        print(f"ERROR: no rules with citation_pattern found in {args.ledger}",
              file=sys.stderr)
        return 2

    accumulator = reconstruct(rules, comms_files, args.cycle)

    # Report (always printed to stdout).
    if args.format == "json":
        print(format_json(accumulator, comms_files))
    else:
        print(format_text(accumulator, comms_files))

    if args.apply or args.check:
        with open(args.ledger) as f:
            original = f.read()
        # Merge this scan's cycles into the existing per-cycle history so a
        # cycle-close run over just the active cycle adds it without wiping
        # prior cycles.
        existing = load_existing_fires(args.ledger)
        merged = merge_fires(accumulator, existing)
        new_text, changed = apply_fires(original, merged)
        if args.check:
            if new_text != original:
                print("\nCHECK: ledger fires are stale vs comms — re-run with --apply.",
                      file=sys.stderr)
                return 1
            print("\nCHECK: ledger fires are current.", file=sys.stderr)
            return 0
        # Header metadata: stamp last_updated_at + last_updated_cycle so the
        # ledger header reflects this close (step 5 of the cycle-close contract,
        # now mechanical). Cycle = --cycle override, else the latest scanned.
        target_cycle = args.cycle or latest_cycle(accumulator)
        cycle_stale = target_cycle is not None and current_cycle_in(original) != target_cycle
        if new_text == original and not cycle_stale:
            print("\nLedger already current — no fires or metadata changed.",
                  file=sys.stderr)
            return 0
        when = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_text = apply_metadata(new_text, when, target_cycle)
        backup = backup_path_for(args.ledger)
        shutil.copy2(args.ledger, backup)
        with open(args.ledger, "w") as f:
            f.write(new_text)
        print(f"\nUpdated fires on {changed} rule(s); stamped "
              f"last_updated_cycle={target_cycle or 'unchanged'}. Backup: {backup}",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
