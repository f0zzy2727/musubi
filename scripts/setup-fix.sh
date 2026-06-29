#!/usr/bin/env bash
# setup-fix.sh — find and (optionally) repair the structural setup problems that
# make musubi agents re-derive the same mistakes across apps:
#
#   - apps whose Oya boots with no real north-star (only the managed IaA.md)
#   - missing PRODUCT-VISION / ARCHITECTURE docs
#   - no durable I&A home (lessons written to IaA.md get clobbered)
#   - no shared cross-app intent doc (a rule learned once doesn't reach siblings)
#   - binary/corrupt comms files
#
# It does ONLY the deterministic, safe parts: scaffolding doc templates,
# creating dirs, recreating a broken comms file, and laying down a shared-intent
# skeleton. It never writes the *content* of a vision/architecture (that needs
# judgement — the /musubi-setup-fix command drives an agent to do that and to
# rewire each toml's context_docs after you approve the drafts).
#
# Read-only by default. `--fix` applies changes; every overwrite is backed up.
#
# Usage (from your musubi folder):
#   bash scripts/setup-fix.sh                 # report gaps across all apps
#   bash scripts/setup-fix.sh --fix           # apply mechanical fixes (asks per step)
#   bash scripts/setup-fix.sh --fix -y        # apply without per-step prompts
#   bash scripts/setup-fix.sh -c musubi-x.toml --fix   # one app only

set -u

APPLY=0; ASSUME_YES=0; ONLY_TOMLS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fix) APPLY=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -c) shift; ONLY_TOMLS="$ONLY_TOMLS $1" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MUSUBI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATES="$MUSUBI_ROOT/templates"
SHARED_DIR="$MUSUBI_ROOT/shared-intent"
SHARED_DOC="$SHARED_DIR/CROSS-APP-RULES.md"

c_grn=$(printf '\033[32m'); c_yel=$(printf '\033[33m'); c_rst=$(printf '\033[0m')
gap(){ printf '%s  GAP%s  %s\n' "$c_yel" "$c_rst" "$1"; }
ok(){  printf '%s  OK %s  %s\n' "$c_grn" "$c_rst" "$1"; }
did(){ printf '%s FIXED%s %s\n' "$c_grn" "$c_rst" "$1"; }
info(){ printf '       %s\n' "$1"; }

# ask QUESTION — returns 0 for yes. Auto-yes with -y; auto-no when not applying.
ask(){
  [ "$APPLY" -eq 1 ] || return 1
  [ "$ASSUME_YES" -eq 1 ] && return 0
  printf '       apply? [y/N] '; read -r a </dev/tty 2>/dev/null || return 1
  case "$a" in y|Y|yes) return 0 ;; *) return 1 ;; esac
}

backup(){ [ -e "$1" ] && cp -p "$1" "$1.bak.$(date +%Y%m%d-%H%M%S)" 2>/dev/null; }

tomlval(){ grep -m1 -E "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null \
           | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*#.*$//; s/^"//; s/"$//'; }

# is this path a musubi-managed template (zero product knowledge)?
is_managed(){ [ -f "$1" ] && head -n1 "$1" 2>/dev/null | grep -q '<!-- musubi-managed:'; }

# discover tomls. -c values are resolved against the musubi root (so a bare
# filename works regardless of the caller's CWD), matching doctor.sh -c.
# TOMLS is newline-separated and iterated with `while read` so paths (or the
# musubi root) containing spaces are never word-split.
TOMLS=""
if [ -n "$ONLY_TOMLS" ]; then
  for c in $ONLY_TOMLS; do
    case "$c" in /*) TOMLS="$TOMLS
$c" ;; *) TOMLS="$TOMLS
$MUSUBI_ROOT/$c" ;; esac
  done
else
  for f in "$MUSUBI_ROOT"/musubi*.toml; do
    [ -f "$f" ] || continue
    case "$f" in *.example) continue ;; esac
    TOMLS="$TOMLS
$f"
  done
fi
[ -n "$TOMLS" ] || { echo "No musubi*.toml found in $MUSUBI_ROOT" >&2; exit 1; }

echo "musubi setup-fix — root: $MUSUBI_ROOT"
[ "$APPLY" -eq 1 ] && echo "MODE: FIX (changes will be written, originals backed up)" \
                   || echo "MODE: report only (run with --fix to apply)"
echo

# --- shared cross-app intent doc (one, for all apps) ---------------------------
echo "== shared cross-app intent =="
if [ -f "$SHARED_DOC" ]; then
  ok "shared intent doc exists: ${SHARED_DOC#"$MUSUBI_ROOT"/}"
else
  gap "no shared cross-app intent doc — a rule learned in one app can't reach the others"
  info "would create: ${SHARED_DOC#"$MUSUBI_ROOT"/} (skeleton; the command fills it + wires every app's context_docs)"
  if ask; then
    mkdir -p "$SHARED_DIR"
    {
      echo "# Cross-app rules (shared north-star)"
      echo
      echo "Truths that apply to EVERY app. Every app's musubi.toml should load this"
      echo "file in [agents.oyakata].context_docs. Write rules UP into this file once;"
      echo "every app reads them DOWN at boot. This is how a lesson learned in one app"
      echo "protects all of them."
      echo
      echo "## Account / resource model"
      echo "- (example) Voice IDs and clone IDs are ACCOUNT-LEVEL: they already exist"
      echo "  on the shared account. Never rebuild them per app — copy the pointer."
      echo "- Before building N of any resource per app, first ask: is this resource"
      echo "  account-level and already present? If yes, reference it; do not recreate."
      echo
      echo "## Add rules below as failures are root-caused"
      echo "- "
    } > "$SHARED_DOC"
    did "created ${SHARED_DOC#"$MUSUBI_ROOT"/}"
  fi
fi
echo

# --- per-app -------------------------------------------------------------------
while IFS= read -r toml; do
  [ -z "$toml" ] && continue
  stem="$(basename "$toml" .toml)"
  proj="$(tomlval "$toml" path)"
  echo "== $stem =="
  if [ -z "$proj" ] || [ ! -d "$proj" ]; then
    gap "project.path missing or unreadable: '${proj:-<unset>}' — skipping"
    echo; continue
  fi

  # 1) north-star: real vision/architecture, or only managed IaA.md?
  has_real=0
  for d in docs/PRODUCT-VISION.md docs/VISION.md docs/ARCHITECTURE.md docs/PRD.md; do
    [ -f "$proj/$d" ] && ! is_managed "$proj/$d" && has_real=1
  done
  if [ "$has_real" -eq 1 ]; then
    ok "has a real north-star doc (vision/architecture present)"
  else
    gap "no real north-star — Oya boots blind (only managed IaA.md / nothing)"
    for pair in "VISION.md:docs/PRODUCT-VISION.md" "ARCHITECTURE.md:docs/ARCHITECTURE.md"; do
      tmpl="$TEMPLATES/${pair%%:*}"; dest="$proj/${pair##*:}"
      if [ -f "$dest" ]; then info "exists (untouched): ${pair##*:}"; continue; fi
      info "would scaffold ${pair##*:} from template (DRAFT — the command fills it)"
      if ask; then
        mkdir -p "$(dirname "$dest")"
        { echo "<!-- DRAFT scaffold — replace with real content. Generated by setup-fix.sh. -->"; cat "$tmpl"; } > "$dest"
        did "scaffolded ${pair##*:}"
      fi
    done
  fi

  # 2) durable I&A home (off the IaA.md append-trap)
  if [ -d "$proj/docs/i-and-a" ]; then
    ok "durable I&A home present (docs/i-and-a/)"
  else
    gap "no durable I&A home — lessons in IaA.md get clobbered on rewrite"
    info "would create docs/i-and-a/ (one file per rule; never auto-rewritten)"
    if ask; then
      mkdir -p "$proj/docs/i-and-a"
      {
        echo "# Inspect & Adapt — durable rules"
        echo
        echo "One file per encoded rule. Unlike IaA.md (managed, clobbered on rewrite),"
        echo "files here persist. Cross-app rules belong in the shared CROSS-APP-RULES.md;"
        echo "app-specific rules live here and/or in rules-ledger.yml so they reload."
      } > "$proj/docs/i-and-a/README.md"
      did "created docs/i-and-a/"
    fi
  fi

  # 3) comms file health
  comms_rel="$(tomlval "$toml" file)"; [ -z "$comms_rel" ] && comms_rel="docs/agents/comms/active.txt"
  comms="$proj/$comms_rel"
  if [ ! -e "$comms" ]; then
    info "comms file absent ($comms_rel) — first session will create it"
  elif [ ! -s "$comms" ]; then
    ok "comms file present (empty/fresh)"
  elif grep -Iq . "$comms" 2>/dev/null; then
    ok "comms file is readable text"
  else
    gap "comms file is BINARY/corrupt: $comms_rel"
    info "would back it up (.corrupt.bak) and recreate empty"
    if ask; then
      backup "$comms"; mv "$comms" "$comms.corrupt.bak" 2>/dev/null; : > "$comms"
      did "recreated $comms_rel (old saved as .corrupt.bak)"
    fi
  fi

  # 4) wiring advice (toml edits are the command's job, not this script's)
  ctx="$(grep -m1 context_docs "$toml" | sed 's/^[[:space:]]*//')"
  info "current context_docs: ${ctx:-<none set>}"
  info "target: include real vision/architecture + the shared doc:"
  info "  context_docs = [\"docs/PRODUCT-VISION.md\", \"docs/ARCHITECTURE.md\", \"$SHARED_DOC\"]"
  echo
done <<EOF_TOMLS
$TOMLS
EOF_TOMLS

echo "Next: run /musubi-setup-fix in this folder to fill the scaffolds with real"
echo "content (interview + draft + your approval) and wire each toml's context_docs."
