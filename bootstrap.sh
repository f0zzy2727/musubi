#!/usr/bin/env bash
# bootstrap.sh — install musubi files into a target project.
#
# Usage:
#   ./bootstrap.sh [target-project-path]      # defaults to $PWD
#   ./bootstrap.sh --dry-run [target]         # print what would change, don't write
#   ./bootstrap.sh --force [target]           # refresh musubi-managed docs even
#                                              # if their <!-- musubi-managed -->
#                                              # marker has been removed (i.e.,
#                                              # re-sync forks). A fork is backed
#                                              # up to <name>.fork-backup-<stamp>
#                                              # before it is replaced — never
#                                              # clobbered. Symlinked docs are
#                                              # swapped for real files.
#   ./bootstrap.sh --update                   # safe propagation: read project.path
#                                              # from musubi.toml, show dry-run preview,
#                                              # prompt, then apply. Run after
#                                              # `git pull origin main` in the musubi
#                                              # clone to push updates to the target.
#   ./bootstrap.sh --update --yes             # same, but skip the confirmation prompt
#                                              # (intended for CI / scripted use)
#   ./bootstrap.sh --check [target]           # verify install currency without
#                                              # writing; exits non-zero if any
#                                              # file/dir/block is missing or stale
#                                              # (CI currency gate). Implies --dry-run.
#
# What it does (idempotent — safe to re-run after every musubi update):
#
#   docs/agents/AGENT_COLLAB_RUNBOOK.md   <- refreshed (managed)
#   docs/agents/AGENT_COLLAB_RUNBOOK_REFERENCE.md <- refreshed (managed; on-demand)
#   docs/agents/PAIR_OPERATING_MODEL.md   <- refreshed (managed)
#   docs/operator/DEV_STRATEGY.md         <- refreshed (managed; operator-facing, not auto-imported)
#   docs/agents/IaA.md                    <- refreshed (managed)
#   docs/agents/current-state.md          <- created if absent (project-owned)
#   docs/agents/agent-todo.md             <- created if absent (project-owned)
#   docs/agents/agent-handoff.md          <- created if absent (project-owned)
#   docs/agents/comms/                    <- created if absent
#   docs/agents/archive/                  <- created if absent
#   scripts/guard-staged-scope.sh         <- created if absent (executable)
#   scripts/ci-baseline.sh                <- created if absent (executable)
#   .claude/commands/open-sesame.md       <- created if absent
#   CLAUDE.md                             <- block injected (idempotent)
#   AGENTS.md                             <- block injected (idempotent)
#   .gitignore                            <- docs/agents/comms/ added if missing
#
# CLAUDE.md / AGENTS.md merge strategy:
#   - File absent      -> created from templates/CLAUDE.md.template
#                         (or AGENTS.md.template), block already at the bottom.
#   - Marker present   -> content between <!-- musubi:start --> and
#                         <!-- musubi:end --> is replaced atomically.
#   - Marker absent    -> the block is appended at EOF with a separator. User's
#                         existing content is preserved verbatim above it.
#
# Managed-doc fork detection:
#   Each managed doc carries a <!-- musubi-managed --> marker on line 1. If a
#   user has stripped this marker (i.e., forked the file), bootstrap shows a
#   diff and skips the refresh — unless --force is passed.

set -euo pipefail

# ---------------------------------------------------------------------------
# Args + paths
# ---------------------------------------------------------------------------

DRY_RUN=0
FORCE=0
UPDATE=0
ASSUME_YES=0
CHECK=0
DRIFT=0
TARGET=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force)   FORCE=1; shift ;;
    --update)  UPDATE=1; shift ;;
    --yes|-y)  ASSUME_YES=1; shift ;;
    # --check: verify install currency without writing. Implies --dry-run and
    # tracks a drift counter; exits non-zero if anything is missing or stale,
    # so it doubles as a CI currency gate. (A2)
    --check)   CHECK=1; DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '1,52p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      if [ -z "$TARGET" ]; then
        TARGET="$1"; shift
      else
        echo "bootstrap: unexpected argument: $1" >&2
        exit 2
      fi
      ;;
  esac
done

MUSUBI_ROOT="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# --update mode: resolve target from musubi.toml, preview, prompt, apply.
# Re-invokes this script with --dry-run, then (on confirmation) with apply.
# ---------------------------------------------------------------------------

if [ "$UPDATE" -eq 1 ]; then
  if [ -n "$TARGET" ]; then
    echo "bootstrap: --update reads the target from musubi.toml; do not pass a path." >&2
    exit 2
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "bootstrap: --update implies its own dry-run preview; remove --dry-run." >&2
    exit 2
  fi

  TOML="$MUSUBI_ROOT/musubi.toml"
  if [ ! -f "$TOML" ]; then
    echo "bootstrap: $TOML not found." >&2
    echo "  Copy musubi.toml.example to musubi.toml and set [project] path = ..." >&2
    exit 2
  fi

  RESOLVED_TARGET="$(python3 - "$TOML" <<'PY'
import sys, pathlib, re
text = pathlib.Path(sys.argv[1]).read_text()
in_project = False
path = None
for line in text.splitlines():
    s = line.strip()
    if not s or s.startswith("#"):
        continue
    if s.startswith("[") and s.endswith("]"):
        in_project = (s == "[project]")
        continue
    if in_project:
        m = re.match(r'path\s*=\s*"([^"]+)"', s) or re.match(r"path\s*=\s*'([^']+)'", s)
        if m:
            path = m.group(1)
            break
if not path:
    sys.exit("musubi.toml: [project] path = \"...\" not found")
print(path)
PY
)"

  if [ -z "$RESOLVED_TARGET" ]; then
    echo "bootstrap: failed to read project.path from $TOML" >&2
    exit 2
  fi

  if [ ! -d "$RESOLVED_TARGET" ]; then
    echo "bootstrap: project.path '$RESOLVED_TARGET' is not a directory." >&2
    exit 2
  fi

  RESOLVED_TARGET="$(cd "$RESOLVED_TARGET" && pwd)"

  echo "musubi: source = $MUSUBI_ROOT"
  echo "musubi: target = $RESOLVED_TARGET (from musubi.toml)"
  echo ""
  echo "─── preview (dry-run): managed docs + scripts ───"
  FORCE_FLAG=""
  [ "$FORCE" -eq 1 ] && FORCE_FLAG="--force"
  "$0" --dry-run $FORCE_FLAG "$RESOLVED_TARGET"
  echo ""
  echo "─── preview (audit): rules-ledger + musubi.toml ───"
  # upgrade_project.py returns exit 1 in audit mode if it found changes —
  # that's expected, not an error. set -e is on, so guard with || true.
  python3 "$MUSUBI_ROOT/scripts/upgrade_project.py" "$RESOLVED_TARGET" || true
  echo "─── end preview ───"
  echo ""

  if [ "$ASSUME_YES" -eq 1 ]; then
    echo "musubi: --yes set, applying without prompt."
  else
    printf "Apply these changes to %s? [y/N] " "$RESOLVED_TARGET"
    read -r REPLY </dev/tty || REPLY=""
    case "$REPLY" in
      y|Y|yes|YES) ;;
      *)
        echo "musubi: aborted. No changes written."
        exit 0
        ;;
    esac
  fi

  echo ""
  echo "─── applying: managed docs + scripts ───"
  # Use a subshell, not exec, so control returns here for the upgrade step.
  "$0" $FORCE_FLAG "$RESOLVED_TARGET"

  echo ""
  echo "─── applying: rules-ledger + musubi.toml upgrades ───"
  # Operator already consented to "apply these changes" above; pass --yes
  # to skip a second prompt. The upgrade script auto-backs-up every file
  # it modifies (<file>.backup-YYYYMMDD-HHMMSS).
  python3 "$MUSUBI_ROOT/scripts/upgrade_project.py" "$RESOLVED_TARGET" --apply --yes

  exit 0
fi

TARGET="${TARGET:-$(pwd)}"
TARGET="$(cd "$TARGET" && pwd)"

if [ "$MUSUBI_ROOT" = "$TARGET" ]; then
  echo "bootstrap: refusing to install musubi into the musubi repo itself." >&2
  echo "  pass a target path: $0 /path/to/your/project" >&2
  exit 2
fi

if [ ! -d "$TARGET" ]; then
  echo "bootstrap: target '$TARGET' is not a directory." >&2
  exit 2
fi

echo "musubi: source = $MUSUBI_ROOT"
echo "musubi: target = $TARGET"
[ "$DRY_RUN" -eq 1 ] && echo "musubi: DRY RUN — no files will be written."
[ "$FORCE"  -eq 1 ] && echo "musubi: --force — forks will be backed up (.fork-backup-<stamp>) then re-synced to the musubi version."
echo ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Record a drift item in --check mode. No-op otherwise.
note_drift() {
  if [ "$CHECK" -eq 1 ]; then
    DRIFT=$((DRIFT + 1))
    echo "  ⚠ drift: $1"
  fi
}

ensure_dir() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    note_drift "missing directory $dir"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] mkdir -p $dir"
    else
      mkdir -p "$dir"
      echo "  + mkdir $dir"
    fi
  fi
}

copy_if_absent() {
  local src="$1"
  local dst="$2"
  local desc="${3:-$dst}"
  if [ ! -f "$dst" ]; then
    note_drift "missing file $desc"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] cp $src $dst"
    else
      cp "$src" "$dst"
      echo "  + created $desc"
    fi
  else
    echo "  = kept $desc (already exists)"
  fi
}

managed_marker_present() {
  # First line of file should contain '<!-- musubi-managed:'
  local file="$1"
  [ -f "$file" ] && head -n 1 "$file" | grep -q '<!-- musubi-managed:'
}

refresh_managed() {
  # Refresh a musubi-managed doc — runbook / PAIR / DEV.
  # If destination is a fork (no marker), warn and skip unless --force.
  local src="$1"
  local dst="$2"
  local desc="${3:-$dst}"

  if [ ! -f "$dst" ]; then
    note_drift "missing managed doc $desc"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] cp $src $dst"
    else
      cp "$src" "$dst"
      echo "  + created $desc"
    fi
    return
  fi

  if managed_marker_present "$dst"; then
    # In --check mode, only a content difference is drift (a re-copy of
    # identical bytes is not).
    if [ "$CHECK" -eq 1 ]; then
      if ! cmp -s "$src" "$dst"; then
        note_drift "stale managed doc $desc (differs from musubi version)"
      fi
      return
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] cp $src $dst (refresh)"
    else
      cp "$src" "$dst"
      echo "  ~ refreshed $desc"
    fi
    return
  fi

  # No marker — looks like a fork.
  if [ "$CHECK" -eq 1 ]; then
    note_drift "$desc is a fork (no musubi-managed marker) — not tracked against musubi"
    return
  fi
  if [ "$FORCE" -eq 1 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] back up fork + force-resync $desc"
    else
      # Never clobber a customised file. Back up the fork first; `cp -L` follows
      # a symlink so the backup captures the real content, not the link. If dst
      # is a symlink, remove it so we write a real file (not through the link).
      local backup
      backup="${dst}.fork-backup-$(date +%Y%m%d-%H%M%S)"
      cp -L "$dst" "$backup" 2>/dev/null || cp "$dst" "$backup"
      [ -L "$dst" ] && rm -f "$dst"
      cp "$src" "$dst"
      echo "  ! force-resynced $desc — fork backed up to $(basename "$backup")"
    fi
    return
  fi

  echo "  ! skipped $desc — looks like a fork (no <!-- musubi-managed --> marker)."
  if command -v diff >/dev/null 2>&1; then
    echo "    Diff against musubi version (first 40 lines):"
    diff -u "$dst" "$src" 2>/dev/null | head -n 40 | sed 's/^/      /' || true
    echo "    Re-run with --force to overwrite (your fork is backed up to a"
    echo "    .fork-backup-<timestamp> file first), or merge manually."
  fi
}

inject_block() {
  # Inject (or refresh) a musubi block into CLAUDE.md / AGENTS.md.
  #   $1 = target file path
  #   $2 = block source path (the literal block content, including markers)
  #   $3 = header template path (header text only — concatenated with block_src
  #        when target is absent so the block has a single source of truth)
  #   $4 = description for log output
  local target="$1"
  local block_src="$2"
  local template_src="$3"
  local desc="$4"

  if [ ! -f "$target" ]; then
    note_drift "missing $desc (file absent — musubi block not injected)"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] write $target  (header from $template_src + block from $block_src)"
    else
      cat "$template_src" "$block_src" > "$target"
      echo "  + created $desc from header + block"
    fi
    return
  fi

  if grep -qE '^<!-- musubi:start -->[[:space:]]*$' "$target"; then
    # In --check mode, drift = the injected block slice differs from the
    # current musubi block source.
    if [ "$CHECK" -eq 1 ]; then
      if ! python3 - "$target" "$block_src" <<'PY'
import sys, pathlib, re
text = pathlib.Path(sys.argv[1]).read_text()
block = pathlib.Path(sys.argv[2]).read_text().rstrip()
# Markers are matched anchored to their own line — the CLAUDE.md/AGENTS.md
# header templates mention the markers inline in prose, and a naive
# text.find() would match that prose instead of the real block.
ms = re.search(r"^<!-- musubi:start -->[ \t]*$", text, re.M)
me = re.search(r"^<!-- musubi:end -->[ \t]*$", text, re.M)
if not ms or not me or me.start() < ms.start():
    sys.exit(1)
current = text[ms.start():me.end()].rstrip()
sys.exit(0 if current == block else 1)
PY
      then
        note_drift "stale musubi block in $desc (differs from musubi version)"
      fi
      return
    fi
    # Refresh existing block in place.
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] refresh musubi block in $target"
      return
    fi
    # Use a Python helper for reliable multi-line slice replacement.
    python3 - "$target" "$block_src" <<'PY'
import sys, pathlib, re
target_path = pathlib.Path(sys.argv[1])
block_path  = pathlib.Path(sys.argv[2])
text  = target_path.read_text()
block = block_path.read_text().rstrip() + "\n"
# Anchor markers to their own line — the header template references the
# markers inline in prose, so a naive str.find() would match the prose and
# corrupt the file (replacing the prose mention, leaving the real block stale).
ms = re.search(r"^<!-- musubi:start -->[ \t]*$", text, re.M)
me = re.search(r"^<!-- musubi:end -->[ \t]*$", text, re.M)
if not ms or not me or me.start() < ms.start():
    raise SystemExit(f"musubi markers not found cleanly in {target_path}")
new = text[:ms.start()] + block.rstrip() + text[me.end():]
# Ensure exactly one trailing newline
if not new.endswith("\n"):
    new += "\n"
target_path.write_text(new)
PY
    echo "  ~ refreshed musubi block in $desc"
    return
  fi

  # No marker — append.
  note_drift "musubi block not injected in $desc (no markers found)"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] append musubi block to $target"
    return
  fi
  {
    printf '\n\n---\n\n'
    cat "$block_src"
  } >> "$target"
  echo "  + appended musubi block to $desc (existing content preserved above)"
}

ensure_gitignore_entry() {
  local file="$TARGET/.gitignore"
  local entry="$1"
  local comment="$2"
  if [ ! -f "$file" ]; then
    note_drift "missing .gitignore (entry $entry not present)"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  [dry-run] create $file with $entry"
    else
      printf '# %s\n%s\n' "$comment" "$entry" > "$file"
      echo "  + created .gitignore with $entry"
    fi
    return
  fi
  if grep -qxF "$entry" "$file"; then
    echo "  = .gitignore already contains $entry"
    return
  fi
  note_drift ".gitignore missing entry $entry"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] append $entry to $file"
  else
    printf '\n# %s\n%s\n' "$comment" "$entry" >> "$file"
    echo "  + added $entry to .gitignore"
  fi
}

# ---------------------------------------------------------------------------
# 1. Directories
# ---------------------------------------------------------------------------

echo "→ Directories"
ensure_dir "$TARGET/docs/agents/comms"
ensure_dir "$TARGET/docs/agents/archive"
# Per-cycle artefact directories — Oya writes here when enabled. Empty when
# Oya is off; cheap to pre-create unconditionally so Oya never has to mkdir
# on her first write.
ensure_dir "$TARGET/docs/agents/asymmetry"
ensure_dir "$TARGET/docs/agents/shadow-review"
ensure_dir "$TARGET/docs/agents/operator-critique"
ensure_dir "$TARGET/docs/operator"
ensure_dir "$TARGET/scripts"
ensure_dir "$TARGET/.claude/commands"
echo ""

# ---------------------------------------------------------------------------
# 2. Managed docs (refresh on every run)
# ---------------------------------------------------------------------------

echo "→ Managed docs (refresh)"
refresh_managed "$MUSUBI_ROOT/docs/agents/AGENT_COLLAB_RUNBOOK.md" \
                "$TARGET/docs/agents/AGENT_COLLAB_RUNBOOK.md" \
                "docs/agents/AGENT_COLLAB_RUNBOOK.md"
# Runbook reference (runbook-1 split) — on-demand detail; NOT @-imported, but
# still musubi-managed so it stays current alongside the core runbook.
refresh_managed "$MUSUBI_ROOT/docs/agents/AGENT_COLLAB_RUNBOOK_REFERENCE.md" \
                "$TARGET/docs/agents/AGENT_COLLAB_RUNBOOK_REFERENCE.md" \
                "docs/agents/AGENT_COLLAB_RUNBOOK_REFERENCE.md"
refresh_managed "$MUSUBI_ROOT/docs/agents/PAIR_OPERATING_MODEL.md" \
                "$TARGET/docs/agents/PAIR_OPERATING_MODEL.md" \
                "docs/agents/PAIR_OPERATING_MODEL.md"
refresh_managed "$MUSUBI_ROOT/docs/operator/DEV_STRATEGY.md" \
                "$TARGET/docs/operator/DEV_STRATEGY.md" \
                "docs/operator/DEV_STRATEGY.md"
refresh_managed "$MUSUBI_ROOT/templates/IaA.md" \
                "$TARGET/docs/agents/IaA.md" \
                "docs/agents/IaA.md"
echo ""

# ---------------------------------------------------------------------------
# 3. Project-owned templates (create if absent)
# ---------------------------------------------------------------------------

echo "→ Project-owned templates (create if absent)"
copy_if_absent "$MUSUBI_ROOT/templates/agent-todo.md"          "$TARGET/docs/agents/agent-todo.md"      "docs/agents/agent-todo.md"
copy_if_absent "$MUSUBI_ROOT/templates/agent-handoff.md"       "$TARGET/docs/agents/agent-handoff.md"   "docs/agents/agent-handoff.md"
copy_if_absent "$MUSUBI_ROOT/templates/current-state.md"       "$TARGET/docs/agents/current-state.md"   "docs/agents/current-state.md"
copy_if_absent "$MUSUBI_ROOT/templates/rules-ledger.yml.template" "$TARGET/docs/agents/rules-ledger.yml"   "docs/agents/rules-ledger.yml"
echo ""

# ---------------------------------------------------------------------------
# 4. Scripts (create if absent, executable)
# ---------------------------------------------------------------------------

echo "→ Scripts (create if absent)"
copy_if_absent "$MUSUBI_ROOT/scripts/guard-staged-scope.sh" "$TARGET/scripts/guard-staged-scope.sh" "scripts/guard-staged-scope.sh"
copy_if_absent "$MUSUBI_ROOT/scripts/ci-baseline.sh"        "$TARGET/scripts/ci-baseline.sh"        "scripts/ci-baseline.sh"
# classify-slice.sh — the runbook's Lane-choice section tells agents to run
# this at slice acceptance, so it must exist in the target project (protocol-1).
copy_if_absent "$MUSUBI_ROOT/scripts/classify-slice.sh"     "$TARGET/scripts/classify-slice.sh"     "scripts/classify-slice.sh"
if [ "$DRY_RUN" -eq 0 ]; then
  [ -f "$TARGET/scripts/guard-staged-scope.sh" ] && chmod +x "$TARGET/scripts/guard-staged-scope.sh"
  [ -f "$TARGET/scripts/ci-baseline.sh" ]        && chmod +x "$TARGET/scripts/ci-baseline.sh"
  [ -f "$TARGET/scripts/classify-slice.sh" ]     && chmod +x "$TARGET/scripts/classify-slice.sh"
fi
echo ""

# ---------------------------------------------------------------------------
# 5. Slash command for Claude Code
# ---------------------------------------------------------------------------

echo "→ Slash command"
copy_if_absent "$MUSUBI_ROOT/templates/claude-commands/open-sesame.md" \
               "$TARGET/.claude/commands/open-sesame.md" \
               ".claude/commands/open-sesame.md"
echo ""

# ---------------------------------------------------------------------------
# 6. CLAUDE.md and AGENTS.md (block injection)
# ---------------------------------------------------------------------------

echo "→ Project-rules blocks"
inject_block "$TARGET/CLAUDE.md" \
             "$MUSUBI_ROOT/templates/musubi-block-claude.md" \
             "$MUSUBI_ROOT/templates/CLAUDE.md.template" \
             "CLAUDE.md"
inject_block "$TARGET/AGENTS.md" \
             "$MUSUBI_ROOT/templates/musubi-block-agents.md" \
             "$MUSUBI_ROOT/templates/AGENTS.md.template" \
             "AGENTS.md"
echo ""

# ---------------------------------------------------------------------------
# 7. .gitignore
# ---------------------------------------------------------------------------

echo "→ .gitignore"
ensure_gitignore_entry "docs/agents/comms/" "musubi: active comms (ephemeral; archived to docs/agents/archive/)"
echo ""

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------

if [ "$CHECK" -eq 1 ]; then
  echo "─────────────────────────────────────────────"
  if [ "$DRIFT" -eq 0 ]; then
    echo "musubi: --check — install is current (0 drift items)."
    exit 0
  fi
  echo "musubi: --check — $DRIFT drift item(s) found (listed above)."
  echo "Run ./bootstrap.sh $TARGET (or --update) to bring the install current."
  exit 1
fi

echo "musubi: bootstrap complete."
echo ""
echo "Next steps:"
echo "  1. Update musubi.toml in the musubi repo with project.path = $TARGET"
echo "  2. cd $MUSUBI_ROOT && ./launch_musubi.sh"
echo ""
echo "On every fresh agent session, the agents will read CLAUDE.md / AGENTS.md"
echo "(auto-loaded by their harness) which @-imports the runbook + operating"
echo "model + dev strategy. The orchestrator's brief and the /open-sesame slash"
echo "command both walk the full startup checklist."
