#!/usr/bin/env python3
"""upgrade_project.py — audit + safely apply musubi framework updates.

Audit-first design. Run against any project that bootstrapped musubi
before today's framework changes; it tells you what would change before
changing anything. Fool-proof for non-technical operators: defaults to
read-only audit, prompts before any write, auto-backs-up every file it
modifies, and is fully idempotent (re-running after apply shows "all
up to date").

What it detects:

  - Missing strategic-Oya discipline rules in the project's live
    rules-ledger.yml (additive — preserves all existing counters).
  - Missing [requires.skills] block in the project's musubi.toml
    (appends commented block; operator chooses whether to enable).

What it never touches:

  - Existing rule counters (fires/catches/bypasses/skipped/silent_misses)
  - Cycle-summary entries
  - Reviewer-calibration entries
  - Any rule whose `id` already exists in the target ledger
  - musubi.toml values; the [requires.skills] block is added commented

Usage:

  python scripts/upgrade_project.py /path/to/target            # audit
  python scripts/upgrade_project.py /path/to/target --apply    # interactive
  python scripts/upgrade_project.py /path/to/target --apply --yes
                                                                # scripted

If no target path is given, the script reads `project.path` from the
musubi.toml in the musubi repo root and audits that target.

Exit codes:
  0 — audit found no changes needed (or apply completed)
  1 — audit found changes (non-zero exit useful for CI checks)
  2 — error reading target files / invalid path
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run `pip install pyyaml` (or `pip install -r requirements.txt`).",
          file=sys.stderr)
    sys.exit(2)

# Python 3.11+ has tomllib; older falls back to tomli (in requirements.txt).
try:
    import tomllib
except ImportError:
    import tomli as tomllib


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MUSUBI_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_LEDGER = MUSUBI_ROOT / "templates" / "rules-ledger.yml.template"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_yaml_file(path):
    """Load YAML; substitute template placeholders so the file parses."""
    with open(path) as f:
        text = f.read()
    # Templates use <PROJECT-SLUG> and <SET-AT-BOOTSTRAP> placeholders so
    # they don't parse as valid YAML. We substitute these into safe values
    # JUST for loading — the original file on disk stays untouched.
    text = (text.replace("<PROJECT-SLUG>", "_template_placeholder_")
                .replace("<SET-AT-BOOTSTRAP>", "1970-01-01T00:00:00Z"))
    return yaml.safe_load(text)


def load_target_musubi_toml(target_path):
    """Read target's musubi.toml. Returns (config_dict, toml_text) or
    (None, None) if the file doesn't exist."""
    toml_path = Path(target_path) / "musubi.toml"
    if not toml_path.exists():
        return None, None
    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)
    with open(toml_path) as f:
        text = f.read()
    return cfg, text


def resolve_target_from_repo():
    """If no target given on CLI, read project.path from this musubi
    repo's musubi.toml. Lets the script work as 'audit the project this
    musubi install is pointing at'."""
    repo_toml = MUSUBI_ROOT / "musubi.toml"
    if not repo_toml.exists():
        return None
    try:
        with open(repo_toml, "rb") as f:
            cfg = tomllib.load(f)
        return cfg.get("project", {}).get("path")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Audit: rules-ledger
# ---------------------------------------------------------------------------

def audit_ledger(target_path):
    """Return dict with:
      template_rules: list of rule ids in framework template
      target_rules:   list of rule ids in target's live ledger
      missing:        list of full rule dicts to append (template - target)
      target_ledger_path: absolute path to target ledger
      target_ledger:  parsed target YAML (None if file absent)
      parse_error:    str message if target couldn't be parsed
    """
    target_ledger_path = Path(target_path) / "docs" / "agents" / "rules-ledger.yml"

    template = load_yaml_file(TEMPLATE_LEDGER)
    template_rules = template.get("rules") or []
    template_ids = [r["id"] for r in template_rules]

    if not target_ledger_path.exists():
        return {
            "template_rules": template_ids,
            "target_rules": [],
            "missing": template_rules,
            "target_ledger_path": target_ledger_path,
            "target_ledger": None,
            "parse_error": None,
        }

    try:
        target = load_yaml_file(target_ledger_path)
    except yaml.YAMLError as e:
        return {
            "template_rules": template_ids,
            "target_rules": [],
            "missing": [],
            "target_ledger_path": target_ledger_path,
            "target_ledger": None,
            "parse_error": f"target ledger could not be parsed: {e}",
        }

    target_rules = (target or {}).get("rules") or []
    target_ids = {r["id"] for r in target_rules if isinstance(r, dict) and "id" in r}

    missing = [r for r in template_rules if r["id"] not in target_ids]

    return {
        "template_rules": template_ids,
        "target_rules": [r["id"] for r in target_rules if isinstance(r, dict) and "id" in r],
        "missing": missing,
        "target_ledger_path": target_ledger_path,
        "target_ledger": target,
        "parse_error": None,
    }


# ---------------------------------------------------------------------------
# Audit: musubi.toml
# ---------------------------------------------------------------------------

def audit_musubi_toml(toml_path):
    """Return dict describing whether [requires.skills] block exists.

    NOTE: musubi.toml lives in the musubi framework clone (alongside
    orchestrator.py), NOT in the target project directory. It's the
    framework's runtime configuration file that points at the target via
    `project.path`. We audit the framework's config because that's what
    the orchestrator reads at startup.
    """
    toml_path = Path(toml_path)
    if not toml_path.exists():
        return {
            "toml_path": toml_path,
            "exists": False,
            "active": False,
            "commented_present": False,
        }

    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)
    text = toml_path.read_text()

    # Check both: parsed (uncommented) and commented presence
    has_block_active = bool("requires" in cfg and "skills" in cfg.get("requires", {}))
    has_block_commented = "# [requires.skills]" in text

    return {
        "toml_path": toml_path,
        "exists": True,
        "active": has_block_active,
        "commented_present": has_block_commented,
    }


# ---------------------------------------------------------------------------
# Apply: rules-ledger (append-only, preserves counters)
# ---------------------------------------------------------------------------

# Match a top-level YAML key at column 0: starts with letter/underscore,
# followed by word chars, then `:`. This is the YAML structural marker we
# use to find the END of the `rules:` list — comment markers in projects'
# live ledgers drift over time (qualifiers added, headers rewritten), so
# we anchor on structure, not free-text.
_TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z_]\w*:")


def find_rules_list_end(target_text):
    """Find the line index where the `rules:` list ends.

    Returns the 0-based line index of the FIRST top-level YAML key after
    `rules:` (i.e. the line `reviewer_calibration:` or `cycle_summary:`
    or whatever comes next). New rules must be inserted BEFORE this line
    to remain part of the `rules:` list rather than getting absorbed into
    the next section as YAML list items.

    Returns None if `rules:` cannot be located or if no terminating key
    follows it (defensive — caller bails rather than write garbage).
    """
    lines = target_text.splitlines()

    rules_line = None
    for i, line in enumerate(lines):
        # Match `rules:` at column 0 (top-level key)
        if line.startswith("rules:"):
            rules_line = i
            break

    if rules_line is None:
        return None

    for i in range(rules_line + 1, len(lines)):
        if _TOP_LEVEL_KEY_RE.match(lines[i]):
            return i

    return None


def apply_ledger_merge(audit, ledger_path):
    """Append the missing rules to the target ledger.

    Implementation: text-level insertion at the structural end of the
    `rules:` list (just before the next top-level YAML key, typically
    `reviewer_calibration:` or `cycle_summary:`). Anchoring on structure
    rather than a comment header keeps the merge robust against
    project-side ledger drift (headers get rewritten, qualifiers added).
    Preserves every existing byte of the target ledger — counters,
    comments, whitespace, ordering — and only adds new content. No YAML
    re-emission (which would lose comments and reformat the file).
    """
    if not audit["missing"]:
        return None  # nothing to do

    # Read the framework template as text. We'll extract the strategic-
    # discipline section verbatim and inject it into the target.
    template_text = TEMPLATE_LEDGER.read_text()

    # Build a per-rule lookup of YAML blocks from the template by parsing
    # rule boundaries (each starts with "  - id: <id>\n").
    rule_blocks = _extract_rule_blocks(template_text)

    missing_ids = [r["id"] for r in audit["missing"]]
    missing_blocks = [rule_blocks[rid] for rid in missing_ids if rid in rule_blocks]

    if not missing_blocks:
        # Defensive: parsed YAML thought rules were missing, but text
        # extraction failed. Bail rather than write garbage.
        raise RuntimeError("could not extract missing rule blocks from template")

    target_text = ledger_path.read_text()
    insertion_line = find_rules_list_end(target_text)
    if insertion_line is None:
        raise RuntimeError(
            "could not find end of `rules:` list in target ledger. "
            "Ledger may be malformed or use an unexpected top-level structure. "
            "Aborting to avoid writing garbage; please inspect the file manually."
        )

    today = _dt.date.today().isoformat()
    insertion_text = (
        f"\n  # ─── Strategic-Oya disciplines (added by upgrade_project.py {today}) ───\n\n"
        + "\n".join(missing_blocks).rstrip("\n")
        + "\n\n"
    )

    lines = target_text.splitlines(keepends=True)
    new_text = (
        "".join(lines[:insertion_line])
        + insertion_text
        + "".join(lines[insertion_line:])
    )

    backup_path = _backup_file(ledger_path)
    ledger_path.write_text(new_text)
    return {"backup": backup_path, "added_ids": missing_ids}


def _extract_rule_blocks(template_text):
    """Parse template_text into a dict mapping rule id -> YAML block text.

    A 'block' starts at the line `  - id: <id>` and runs until the next
    `  - id:` line OR a top-level section marker (line starting `#` at
    column 0). The block includes trailing blank lines and any preceding
    inline comment lines belonging to it (not implemented — simple version
    is fine for this use case)."""
    lines = template_text.splitlines(keepends=True)
    blocks = {}
    current_id = None
    current_lines = []

    def flush():
        nonlocal current_id, current_lines
        if current_id is not None:
            blocks[current_id] = "".join(current_lines)
        current_id = None
        current_lines = []

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- id:"):
            flush()
            current_id = stripped.split(":", 1)[1].strip()
            current_lines = [line]
        elif current_id is not None:
            # Stop at next rule, top-level YAML key, or section marker
            if (stripped.startswith("- id:")
                    or line.startswith("#")
                    or (line.strip() and not line.startswith(" "))):
                flush()
                # Re-process this line if it starts a new rule
                if stripped.startswith("- id:"):
                    current_id = stripped.split(":", 1)[1].strip()
                    current_lines = [line]
            else:
                current_lines.append(line)

    flush()
    return blocks


def _backup_file(path):
    """Copy <path> to <path>.backup-YYYYMMDD-HHMMSS. Returns backup path."""
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".backup-{ts}")
    shutil.copy2(path, backup_path)
    return backup_path


# ---------------------------------------------------------------------------
# Apply: musubi.toml (append commented block)
# ---------------------------------------------------------------------------

REQUIRES_BLOCK_SNIPPET = """
# --- Added by upgrade_project.py: [requires.skills] block for strategic-Oya v0.3+ ---
# Strategic-Oya leans on gstack for engineering-discipline artefacts. Uncomment
# the block below to enable the bootstrap-time skill presence check. Pair-only
# musubi works fine without it.
#
# See <musubi-root>/docs/operator/strategic-disciplines.md for what each skill
# is used for and the framework's stance on the gstack dependency.
#
# [requires.skills]
# core = ["cso", "plan-eng-review", "review"]
# recommended = ["plan-ceo-review", "office-hours", "investigate", "codex", "canary", "qa", "design-review"]
# path = "~/.claude/skills/gstack"
"""


def apply_toml_append(toml_audit):
    """Append the commented [requires.skills] block to the target's musubi.toml.

    Operator-friendly: appends as COMMENTS so musubi behaviour doesn't
    change. Operator decides whether to uncomment to actually enable
    strategic-Oya.
    """
    if not toml_audit["exists"]:
        return None
    if toml_audit["active"] or toml_audit["commented_present"]:
        return None

    toml_path = toml_audit["toml_path"]
    backup_path = _backup_file(toml_path)
    with open(toml_path, "a") as f:
        f.write(REQUIRES_BLOCK_SNIPPET)
    return {"backup": backup_path}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_audit_report(target_path, ledger_audit, toml_audit):
    print("=" * 70)
    print(f"musubi project audit — {target_path}")
    print("=" * 70)
    print()

    # Ledger section
    if ledger_audit["parse_error"]:
        print("Rules ledger:")
        print(f"  ERROR — {ledger_audit['parse_error']}")
        print(f"  Path: {ledger_audit['target_ledger_path']}")
        print("  Cannot audit. Resolve the parse error before re-running.")
    elif ledger_audit["target_ledger"] is None:
        print("Rules ledger:")
        print(f"  NOT FOUND at {ledger_audit['target_ledger_path']}")
        print("  Suggestion: this project hasn't been bootstrapped yet.")
        print("  Run `./bootstrap.sh <target>` from the musubi repo first.")
    else:
        target_count = len(ledger_audit["target_rules"])
        template_count = len(ledger_audit["template_rules"])
        missing_count = len(ledger_audit["missing"])

        print(f"Rules ledger ({ledger_audit['target_ledger_path']}):")
        print(f"  Has {target_count} rules. Framework template has {template_count}.")
        if missing_count == 0:
            print("  ✓ All framework rules are present. Live counter data preserved.")
        else:
            print(f"  → {missing_count} new framework rules missing from this project's ledger:")
            for rule in ledger_audit["missing"]:
                rule_type = rule.get("type", "?")
                added = (rule.get("provenance", {}) or {}).get("added_on", "?")
                print(f"      - {rule['id']}  ({rule_type}, added {added})")
            print("  These would be APPENDED with zero counters; existing rules untouched.")
    print()

    # musubi.toml section (framework config, lives in musubi clone)
    print(f"musubi.toml ({toml_audit['toml_path']}):")
    if not toml_audit["exists"]:
        print("  NOT FOUND.")
        print("  Suggestion: copy musubi.toml.example to musubi.toml and edit project.path.")
    elif toml_audit["active"]:
        print("  ✓ [requires.skills] block is active. Strategic-Oya v0.3 prereq enabled.")
    elif toml_audit["commented_present"]:
        print("  ✓ [requires.skills] block is present (commented).")
        print("    Uncomment to enable strategic-Oya prereq check at startup.")
    else:
        print("  → [requires.skills] block is missing.")
        print("    Would APPEND a commented block at end of file.")
        print("    Operator decides whether to uncomment.")
    print()

    # Summary
    has_changes = (
        (not ledger_audit["parse_error"]
         and ledger_audit["target_ledger"] is not None
         and ledger_audit["missing"])
        or
        (toml_audit["exists"]
         and not toml_audit["active"]
         and not toml_audit["commented_present"])
    )

    if has_changes:
        print("SUMMARY: changes available. Re-run with `--apply` to apply.")
        print("  All writes are backed up to <file>.backup-YYYYMMDD-HHMMSS.")
    else:
        print("SUMMARY: project is up to date. No changes needed.")

    print()
    return has_changes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit + safely apply musubi framework updates to a project.",
    )
    parser.add_argument("target", nargs="?", default=None,
                        help="Path to target project. Defaults to the project "
                             "named in this musubi repo's musubi.toml.")
    parser.add_argument("--apply", action="store_true",
                        help="Apply detected changes (prompts for confirmation "
                             "unless --yes).")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt (for scripted use).")
    args = parser.parse_args(argv)

    target_path = args.target or resolve_target_from_repo()
    if not target_path:
        print("ERROR: no target path given and could not resolve project.path "
              "from this musubi repo's musubi.toml.", file=sys.stderr)
        return 2

    target_path = os.path.expanduser(target_path)
    if not os.path.isdir(target_path):
        print(f"ERROR: target path is not a directory: {target_path}",
              file=sys.stderr)
        return 2

    ledger_audit = audit_ledger(target_path)
    # The musubi.toml lives in MUSUBI_ROOT (framework config, not target).
    toml_audit = audit_musubi_toml(MUSUBI_ROOT / "musubi.toml")

    has_changes = print_audit_report(target_path, ledger_audit, toml_audit)

    if not args.apply:
        return 1 if has_changes else 0

    if not has_changes:
        print("Nothing to apply.")
        return 0

    if not args.yes:
        try:
            response = input("\nApply these changes? [y/N] ").strip().lower()
        except EOFError:
            response = ""
        if response not in ("y", "yes"):
            print("aborted — no files were modified.")
            return 0

    # Apply phase
    print()
    print("Applying changes...")
    if ledger_audit["missing"] and ledger_audit["target_ledger"] is not None:
        result = apply_ledger_merge(ledger_audit, ledger_audit["target_ledger_path"])
        if result:
            print(f"  ✓ Added {len(result['added_ids'])} rules to ledger")
            print(f"    Backup: {result['backup']}")

    if (toml_audit["exists"] and not toml_audit["active"]
            and not toml_audit["commented_present"]):
        result = apply_toml_append(toml_audit)
        if result:
            print(f"  ✓ Added commented [requires.skills] block to musubi.toml")
            print(f"    Backup: {result['backup']}")
            print(f"    Open {toml_audit['toml_path']} to uncomment when ready.")

    print()
    print("Done. Re-run without --apply to confirm everything is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
