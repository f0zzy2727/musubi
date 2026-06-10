#!/usr/bin/env bash
# collect-debug-bundle.sh — gather musubi session artifacts into one zip
# for remote analysis (logs, comms, capsule docs, Oya logs, pane scrollback,
# agent chat transcripts, doctor output).
#
# Multi-app aware: by default it discovers EVERY musubi*.toml in the musubi
# checkout root (same glob as scripts/pick-config.sh, .example excluded) and
# collects each configured project into its own apps/<toml-stem>/ folder
# inside one zip.
#
# Usage (from the musubi checkout root, or anywhere):
#   bash scripts/collect-debug-bundle.sh                  # all musubi*.toml
#   bash scripts/collect-debug-bundle.sh -c musubi-app2.toml -c musubi-app3.toml
#   bash scripts/collect-debug-bundle.sh -d 30 -o /tmp
#
#   -c  collect only this toml (repeatable). Default: every musubi*.toml
#       in the checkout root except musubi.toml.example
#   -d  how many days of chat transcripts to include (default: 14)
#   -o  where to write the zip (default: ~/Desktop, falls back to ~)
#
# What it collects PER APP (per toml):
#   - the toml itself + project git info
#   - project docs/agents/* musubi artifacts: active comms (path from
#     [comms].file), comms + capsule archives, current-state / agent-todo /
#     agent-handoff, oyakata-log.md ([agents.oyakata].log_path),
#     operator-channel.md, operator-input.md, oyakata-decisions.md,
#     operator-actions.md, rules-ledger.yml, asymmetry / shadow-review /
#     operator-critique corpora, runbook
#   - north-star docs (vision/architecture/roadmap/ADRs + context_docs) —
#     to verify what Oya COULD have loaded at boot
#   - live tmux pane scrollback for that toml's session — the orchestrator
#     log only exists as pane stdout, so this is the only place boot lines
#     survive
#   - Claude Code transcripts for that project (~/.claude/projects/<slug>/)
#     — Oya's boot Read calls are the hard evidence of what she actually read
# Plus ONCE globally:
#   - musubi checkout git info + doctor.sh output (doctor reads musubi.toml only)
#   - Codex CLI sessions + logs (recent only; ~/.codex is not per-project)
#
# PRIVACY: the zip contains chat transcripts, which may quote your source
# code and comms. Review before sending. It never includes your projects'
# source trees, credentials files, or .env files.
#
# bash 3.2 compatible (macOS default).

set -u

DAYS=14
OUTDIR=""
TOMLS=""

while getopts "c:d:o:h" opt; do
  case "$opt" in
    c) TOMLS="$TOMLS
$OPTARG" ;;
    d) DAYS="$OPTARG" ;;
    o) OUTDIR="$OPTARG" ;;
    h)
      sed -n '2,45p' "$0"
      exit 0
      ;;
    *) echo "usage: $0 [-c musubi.toml]... [-d days] [-o outdir]" >&2; exit 2 ;;
  esac
done

# --- locate musubi checkout ---------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MUSUBI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default discovery: every musubi*.toml in the checkout root, minus the
# shipped template — the same candidate set pick-config.sh offers at launch.
if [ -z "$TOMLS" ]; then
  for f in "$MUSUBI_DIR"/musubi*.toml; do
    [ -f "$f" ] || continue
    case "$f" in *.example) continue ;; esac
    TOMLS="$TOMLS
$f"
  done
fi

# Validate the list before doing any work (newline-separated; paths may
# contain spaces, so never word-split with a bare `for`).
n_tomls=0
while IFS= read -r t; do
  [ -z "$t" ] && continue
  if [ ! -f "$t" ]; then
    echo "ERROR: toml not found: $t" >&2
    exit 1
  fi
  n_tomls=$((n_tomls + 1))
done <<EOF_TOMLS
$TOMLS
EOF_TOMLS
if [ "$n_tomls" -eq 0 ]; then
  echo "ERROR: no musubi*.toml found in $MUSUBI_DIR — pass one with -c" >&2
  exit 1
fi

# --- minimal toml reader (same tolerance level as doctor.sh) -------------------
# toml_value SECTION KEY FILE → bare value of `key = "value"` inside [section]
toml_value() {
  awk -v section="[$1]" -v key="$2" '
    $0 == section { in_s = 1; next }
    /^\[/ { in_s = 0 }
    in_s && $1 == key {
      line = $0
      sub(/^[^=]*=[ \t]*/, "", line)
      sub(/[ \t]*(#.*)?$/, "", line)
      gsub(/^"|"$/, "", line)
      print line
      exit
    }
  ' "$3" 2>/dev/null
}

# --- staging dir ----------------------------------------------------------------
STAMP="$(date +%Y-%m-%d_%H%M%S)"
HOST="$(hostname -s 2>/dev/null || echo host)"
STAGE="$(mktemp -d /tmp/musubi-bundle.XXXXXX)"
B="$STAGE/musubi-debug-$HOST-$STAMP"
mkdir -p "$B"
MANIFEST="$B/MANIFEST.txt"

note() { echo "$1" | tee -a "$MANIFEST"; }
miss() { echo "MISSING: $1" >> "$MANIFEST"; }

# copy_one SRC DESTSUBDIR — copy file/dir if present, record either way
copy_one() {
  src="$1"; sub="$2"
  if [ -e "$src" ]; then
    mkdir -p "$B/$sub"
    cp -R "$src" "$B/$sub/" 2>/dev/null && echo "OK: $src -> $sub/" >> "$MANIFEST" || miss "$src (copy failed)"
  else
    miss "$src"
  fi
}

echo "musubi debug bundle — $STAMP" > "$MANIFEST"
echo "host: $HOST  user: $(whoami)" >> "$MANIFEST"
echo "musubi checkout: $MUSUBI_DIR" >> "$MANIFEST"
echo "tomls collected: $n_tomls" >> "$MANIFEST"
echo "transcript window: last $DAYS days" >> "$MANIFEST"
echo "---" >> "$MANIFEST"

# --- global section 1: musubi checkout + doctor ---------------------------------
note "[global] musubi checkout + doctor"
mkdir -p "$B/musubi"
(
  cd "$MUSUBI_DIR" || exit 0
  {
    echo "HEAD: $(git rev-parse HEAD 2>/dev/null)"
    echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    git log --oneline -5 2>/dev/null
    echo "status:"
    git status --short 2>/dev/null
  } > "$B/musubi/git-info.txt"
)
if [ -x "$MUSUBI_DIR/scripts/doctor.sh" ] || [ -f "$MUSUBI_DIR/scripts/doctor.sh" ]; then
  ( cd "$MUSUBI_DIR" && bash scripts/doctor.sh > "$B/musubi/doctor-output.txt" 2>&1 )
  echo "OK: doctor.sh output captured (NOTE: doctor reads musubi.toml only, not the other tomls)" >> "$MANIFEST"
else
  miss "scripts/doctor.sh"
fi

# --- per-app collection ----------------------------------------------------------
collect_app() {
  TOML="$1"
  stem="$(basename "$TOML" .toml)"
  APP="apps/$stem"
  mkdir -p "$B/$APP"

  PROJ="$(toml_value project path "$TOML")"
  SESSION="$(toml_value tmux session_name "$TOML")"
  [ -z "$SESSION" ] && SESSION="musubi"
  COMMS_REL="$(toml_value comms file "$TOML")"
  [ -z "$COMMS_REL" ] && COMMS_REL="docs/agents/comms/active.txt"
  OYA_LOG_REL="$(toml_value agents.oyakata log_path "$TOML")"
  [ -z "$OYA_LOG_REL" ] && OYA_LOG_REL="docs/agents/oyakata-log.md"
  OI_REL="$(toml_value agents.oyakata operator_input_path "$TOML")"
  [ -z "$OI_REL" ] && OI_REL="docs/agents/operator-input.md"

  note "[$stem] project: ${PROJ:-<unset>}  session: $SESSION"
  cp "$TOML" "$B/$APP/$(basename "$TOML")" 2>/dev/null

  if [ -z "$PROJ" ] || [ ! -d "$PROJ" ]; then
    miss "[$stem] [project].path missing or not a directory: '$PROJ' — skipping app"
    return
  fi

  (
    cd "$PROJ" || exit 0
    {
      echo "HEAD: $(git rev-parse HEAD 2>/dev/null)"
      echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
      echo "recent:"
      git log --oneline -10 2>/dev/null
    } > "$B/$APP/project-git-info.txt"
  )

  # musubi artifacts in the project
  copy_one "$PROJ/$COMMS_REL"                          "$APP/agents/comms"
  copy_one "$PROJ/$(dirname "$COMMS_REL")/archive"     "$APP/agents/comms"
  copy_one "$PROJ/docs/agents/archive"                 "$APP/agents"
  copy_one "$PROJ/docs/agents/current-state.md"        "$APP/agents"
  copy_one "$PROJ/docs/agents/agent-todo.md"           "$APP/agents"
  copy_one "$PROJ/docs/agents/agent-handoff.md"        "$APP/agents"
  copy_one "$PROJ/$OYA_LOG_REL"                        "$APP/agents"
  copy_one "$PROJ/docs/agents/operator-channel.md"     "$APP/agents"
  copy_one "$PROJ/$OI_REL"                             "$APP/agents"
  copy_one "$PROJ/docs/agents/oyakata-decisions.md"    "$APP/agents"
  copy_one "$PROJ/docs/agents/operator-actions.md"     "$APP/agents"
  copy_one "$PROJ/docs/agents/rules-ledger.yml"        "$APP/agents"
  copy_one "$PROJ/docs/agents/asymmetry"               "$APP/agents"
  copy_one "$PROJ/docs/agents/shadow-review"           "$APP/agents"
  copy_one "$PROJ/docs/agents/operator-critique"       "$APP/agents"
  copy_one "$PROJ/docs/agents/AGENT_COLLAB_RUNBOOK.md" "$APP/agents"

  # north-star docs (what Oya could have loaded)
  for rel in docs/PRODUCT-VISION.md docs/VISION.md docs/PRD.md PRD.md \
             docs/ARCHITECTURE.md docs/ROADMAP.md docs/BACKLOG.md README.md; do
    copy_one "$PROJ/$rel" "$APP/north-star"
  done
  copy_one "$PROJ/docs/adr"          "$APP/north-star"
  copy_one "$PROJ/docs/architecture" "$APP/north-star"
  ctx_raw="$(awk '/^\[agents.oyakata\]/{f=1;next} /^\[/{f=0} f && /context_docs/' "$TOML" 2>/dev/null)"
  if [ -n "$ctx_raw" ]; then
    echo "[$stem] context_docs line: $ctx_raw" >> "$MANIFEST"
    echo "$ctx_raw" | grep -oE '"[^"]*"' | tr -d '"' | while read -r p; do
      [ -n "$p" ] && copy_one "$PROJ/$p" "$APP/north-star/context_docs"
    done
  fi

  # tmux pane scrollback for THIS app's session (orchestrator log lives only here)
  if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null; then
    mkdir -p "$B/$APP/tmux"
    tmux list-panes -s -t "$SESSION" \
      -F '#{pane_id} #{pane_title} #{pane_current_path}' > "$B/$APP/tmux/pane-list.txt" 2>/dev/null
    tmux list-panes -s -t "$SESSION" -F '#{pane_id}' 2>/dev/null | while read -r pid; do
      safe="$(echo "$pid" | tr -d '%')"
      tmux capture-pane -p -t "$pid" -S -50000 > "$B/$APP/tmux/pane-$safe-scrollback.txt" 2>/dev/null
    done
    echo "OK: [$stem] captured scrollback for session $SESSION" >> "$MANIFEST"
  else
    miss "[$stem] tmux session '$SESSION' (not running — orchestrator boot log unavailable)"
  fi

  # Claude Code transcripts for THIS project path.
  # Claude Code stores them under ~/.claude/projects/<slug>/ where slug =
  # project path with every non-alphanumeric char replaced by '-'. Oya runs
  # as a Claude Code session cwd'd to the project, so her boot turns (which
  # files she actually Read) are in here.
  SLUG="$(echo "$PROJ" | sed 's|[^A-Za-z0-9]|-|g')"
  CC_DIR="$HOME/.claude/projects/$SLUG"
  if [ -d "$CC_DIR" ]; then
    mkdir -p "$B/$APP/chats/claude"
    found_cc=0
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      cp "$f" "$B/$APP/chats/claude/" 2>/dev/null && found_cc=$((found_cc + 1))
    done <<EOF_LIST
$(find "$CC_DIR" -maxdepth 1 -name '*.jsonl' -mtime "-$DAYS" 2>/dev/null)
EOF_LIST
    echo "OK: [$stem] $found_cc Claude transcript(s) from $CC_DIR" >> "$MANIFEST"
    [ "$found_cc" -eq 0 ] && miss "[$stem] Claude transcripts newer than $DAYS days in $CC_DIR"
  else
    miss "[$stem] $CC_DIR (no Claude Code transcripts for this project path)"
  fi
}

while IFS= read -r t; do
  [ -z "$t" ] && continue
  collect_app "$t"
done <<EOF_TOMLS
$TOMLS
EOF_TOMLS

# --- global section 2: Codex CLI sessions + logs (not per-project) ---------------
note "[global] Codex CLI sessions + logs (last $DAYS days)"
if [ -d "$HOME/.codex" ]; then
  mkdir -p "$B/chats/codex"
  found_cx=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel_dir="$(dirname "${f#"$HOME"/.codex/}")"
    mkdir -p "$B/chats/codex/$rel_dir"
    cp "$f" "$B/chats/codex/$rel_dir/" 2>/dev/null && found_cx=$((found_cx + 1))
  done <<EOF_LIST
$(find "$HOME/.codex/sessions" "$HOME/.codex/log" -type f -mtime "-$DAYS" 2>/dev/null)
EOF_LIST
  echo "OK: $found_cx Codex file(s)" >> "$MANIFEST"
  [ "$found_cx" -eq 0 ] && miss "Codex files newer than $DAYS days under ~/.codex"
else
  miss "~/.codex (Codex CLI artifacts)"
fi

# --- safety sweep: never ship obvious secrets -------------------------------------
find "$B" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name 'id_rsa*' \
  -o -name 'credentials*' -o -name '*.key' \) -type f -delete 2>/dev/null
echo "---" >> "$MANIFEST"
echo "safety sweep: removed any .env/.pem/key/credentials files from bundle" >> "$MANIFEST"

# --- zip ---------------------------------------------------------------------------
[ -z "$OUTDIR" ] && { [ -d "$HOME/Desktop" ] && OUTDIR="$HOME/Desktop" || OUTDIR="$HOME"; }
ZIP="$OUTDIR/musubi-debug-$HOST-$STAMP.zip"
( cd "$STAGE" && zip -qr "$ZIP" "$(basename "$B")" )
rc=$?
rm -rf "$STAGE"

if [ $rc -ne 0 ] || [ ! -f "$ZIP" ]; then
  echo "ERROR: zip failed (rc=$rc)" >&2
  exit 1
fi

SIZE="$(du -h "$ZIP" | cut -f1)"
echo ""
echo "Bundle ready: $ZIP ($SIZE)"
echo ""
echo "REVIEW BEFORE SENDING: the chats/ folders contain agent transcripts,"
echo "which can quote your source code and comms. Unzip and skim if unsure."
