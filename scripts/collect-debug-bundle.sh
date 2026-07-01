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
#   bash collect-debug-bundle.sh -m ~/Desktop/musubi      # script copied elsewhere
#
#   -c  collect only this toml (repeatable). Default: every musubi*.toml
#       in the checkout root except musubi.toml.example
#   -m  path to the musubi checkout. Default: auto-detected (next to this
#       script, current dir, ~/Desktop/musubi, ~/musubi, ~/Dev/musubi*)
#   -d  how many days of chat transcripts to include (default: 14)
#   -T  INCLUDE agent chat transcripts (Claude + Codex). OFF by default
#       (privacy): transcripts can quote source, comms, and pasted secrets.
#       When set, the bundle runs a best-effort secret-redaction pass before
#       zipping. Without -T the bundle carries no transcripts at all.
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
#   - Fly.io logs (best-effort): if `flyctl` is installed/authed and a
#     fly.toml is found under the project (up to 3 levels deep, e.g.
#     backend/fly.toml or <subproject>/backend/fly.toml), runs
#     `flyctl logs -a <app> --no-tail` and captures the output, plus
#     `flyctl releases`/`flyctl status` (deploy timeline + machine health —
#     tiny, and survives past the log-retention window). Fly's own log
#     retention is short (minutes-to-hours) — logs only help if run soon
#     after the incident; releases/status help regardless.
#   - recent CI run timeline via `gh run list` (list only, not full logs)
# Plus ONCE globally:
#   - musubi checkout git info + doctor.sh output (doctor reads musubi.toml only)
#   - transient local build/upload logs (best-effort, /tmp/build-*.log,
#     /tmp/upload-*.log — small text, whichever app built most recently)
#   - Codex CLI sessions + logs (recent only; ~/.codex is not per-project)
#
# PRIVACY: by default this bundle contains NO chat transcripts. It collects
# comms, capsule/agent docs, config tomls, and tmux scrollback — review before
# sending. Pass -T to include Claude + Codex transcripts (which can quote your
# source, comms, and pasted secrets); when you do, a best-effort secret-
# redaction pass runs before zipping. It never includes your projects' source
# trees, credentials files, or .env files (a file-level safety sweep enforces
# this regardless). The MANIFEST lists which sensitive classes are present.
#
# bash 3.2 compatible (macOS default).

set -u

DAYS=14
OUTDIR=""
TOMLS=""
MUSUBI_DIR_OPT=""
INCLUDE_TRANSCRIPTS=0
MAXKB=51200   # per-file size cap (KB); files larger are skipped. Override with -S.

# Binary / media / archive / model extensions never worth shipping for TEXT
# analysis. These (esp. audio in TTS projects) are what blow a bundle to GB.
SKIP_EXT_RE='\.(wav|mp3|m4a|aac|flac|ogg|opus|aif|aiff|wma|mp4|mov|avi|mkv|webm|m4v|png|jpg|jpeg|gif|bmp|tif|tiff|webp|ico|psd|heic|pdf|zip|gz|tgz|bz2|xz|7z|rar|tar|jar|war|woff|woff2|ttf|otf|eot|so|dylib|dll|bin|wasm|node|exe|class|pyc|pyo|sqlite|sqlite3|db|dat|model|onnx|pt|pth|ckpt|safetensors|npy|npz|parquet|mlmodel)$'

while getopts "c:d:m:o:S:Th" opt; do
  case "$opt" in
    c) TOMLS="$TOMLS
$OPTARG" ;;
    d) DAYS="$OPTARG" ;;
    m) MUSUBI_DIR_OPT="$OPTARG" ;;
    o) OUTDIR="$OPTARG" ;;
    S) MAXKB="$OPTARG" ;;
    T) INCLUDE_TRANSCRIPTS=1 ;;
    h)
      sed -n '2,49p' "$0"
      exit 0
      ;;
    *) echo "usage: $0 [-c musubi.toml]... [-m musubi-dir] [-d days] [-T] [-S maxKB] [-o outdir]" >&2; exit 2 ;;
  esac
done

case "$MAXKB" in *[!0-9]*|'') echo "ERROR: -S takes a number (KB)" >&2; exit 2 ;; esac

# --- locate musubi checkout ---------------------------------------------------
# The script may have been copied out of the checkout and run from anywhere
# (e.g. from $HOME), so script-relative location is only the first guess.
# A directory counts as the checkout when it has a musubi*.toml (non-example)
# or orchestrator.py.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

has_tomls() {
  for f in "$1"/musubi*.toml; do
    [ -f "$f" ] || continue
    case "$f" in *.example) continue ;; esac
    return 0
  done
  return 1
}

MUSUBI_DIR=""
if [ -n "$MUSUBI_DIR_OPT" ]; then
  if [ ! -d "$MUSUBI_DIR_OPT" ]; then
    echo "ERROR: -m directory not found: $MUSUBI_DIR_OPT" >&2
    exit 1
  fi
  MUSUBI_DIR="$(cd "$MUSUBI_DIR_OPT" && pwd)"
else
  CANDIDATES="$SCRIPT_DIR/..
$PWD
$HOME/Desktop/musubi
$HOME/musubi
$HOME/Dev/musubi"
  # also any ~/Dev/musubi* checkout (musubi.repo etc.)
  for d in "$HOME"/Dev/musubi*; do
    [ -d "$d" ] && CANDIDATES="$CANDIDATES
$d"
  done
  while IFS= read -r d; do
    [ -d "$d" ] || continue
    if has_tomls "$d" || [ -f "$d/orchestrator.py" ]; then
      MUSUBI_DIR="$(cd "$d" && pwd)"
      break
    fi
  done <<EOF_CAND
$CANDIDATES
EOF_CAND
fi

if [ -z "$MUSUBI_DIR" ]; then
  echo "ERROR: could not find a musubi checkout (looked next to this script," >&2
  echo "in the current directory, ~/Desktop/musubi, ~/musubi, ~/Dev/musubi*)." >&2
  echo "Point me at it:  bash $0 -m /path/to/musubi" >&2
  exit 1
fi

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

# fly_app_name FLY_TOML — bare value of top-level `app = "..."` (before any
# [section]); fly.toml quotes with either ' or ".
fly_app_name() {
  awk '
    /^\[/ { exit }
    /^app[ \t]*=/ {
      line = $0
      sub(/^app[ \t]*=[ \t]*/, "", line)
      sub(/[ \t]*#.*$/, "", line)
      gsub(/^["'"'"']|["'"'"']$/, "", line)
      print line
      exit
    }
  ' "$1" 2>/dev/null
}

# _copy_filtered SRCFILE DESTFILE LABEL — copy one file unless it is binary
# or over the size cap. Returns 0 if copied, 1 if skipped/failed.
_copy_filtered() {
  f="$1"; dest="$2"; label="$3"
  # fast extension reject (case-insensitive)
  lc="$(printf '%s' "$f" | tr 'A-Z' 'a-z')"
  if printf '%s' "$lc" | grep -qE "$SKIP_EXT_RE"; then
    echo "SKIP(binary-ext): $label" >> "$MANIFEST"; return 1
  fi
  # size cap
  bytes="$(wc -c < "$f" 2>/dev/null || echo 0)"
  if [ "${bytes:-0}" -gt $((MAXKB * 1024)) ]; then
    echo "SKIP(>${MAXKB}KB): $label (${bytes}B)" >> "$MANIFEST"; return 1
  fi
  # content sniff: catch extensionless binaries (grep -I = binary -> no match)
  if ! grep -Iq . "$f" 2>/dev/null; then
    echo "SKIP(binary-content): $label" >> "$MANIFEST"; return 1
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$f" "$dest" 2>/dev/null && return 0 || { miss "$label (copy failed)"; return 1; }
}

# copy_one SRC DESTSUBDIR — copy file/dir if present, record either way.
# TEXT-ONLY and size-capped: binaries/media/archives and oversize files are
# skipped (and noted in MANIFEST) so a binary-heavy project (e.g. TTS audio)
# can't balloon the bundle to gigabytes.
copy_one() {
  src="$1"; sub="$2"
  if [ ! -e "$src" ]; then miss "$src"; return; fi
  mkdir -p "$B/$sub"
  if [ -f "$src" ]; then
    _copy_filtered "$src" "$B/$sub/$(basename "$src")" "$src" \
      && echo "OK: $src -> $sub/" >> "$MANIFEST"
    return
  fi
  # directory: mirror text files only, preserving structure
  base="$(basename "$src")"; kept=0
  find "$src" -type f 2>/dev/null | while IFS= read -r f; do
    rel="${f#"$src"/}"
    _copy_filtered "$f" "$B/$sub/$base/$rel" "$f" && kept=$((kept + 1))
  done
  echo "OK(dir): $src -> $sub/$base/ (text-only, <=${MAXKB}KB/file)" >> "$MANIFEST"
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

  # Fly.io logs (best-effort). Looks for fly.toml up to 3 levels deep under
  # the project (covers repo-root, backend/fly.toml, and nested-subproject
  # layouts like <repo>/<app>/backend/fly.toml). Skips cleanly if flyctl
  # isn't installed/authed — never fails the bundle.
  if command -v flyctl >/dev/null 2>&1; then
    fly_found=0
    while IFS= read -r fly_toml; do
      [ -z "$fly_toml" ] && continue
      app_name="$(fly_app_name "$fly_toml")"
      if [ -z "$app_name" ]; then
        echo "MISSING: [$stem] $fly_toml has no top-level app = \"...\"" >> "$MANIFEST"
        continue
      fi
      mkdir -p "$B/$APP/fly"
      if flyctl logs -a "$app_name" --no-tail > "$B/$APP/fly/$app_name-logs.txt" 2>&1; then
        echo "OK: [$stem] flyctl logs -a $app_name --no-tail -> fly/$app_name-logs.txt" >> "$MANIFEST"
        fly_found=$((fly_found + 1))
      else
        echo "MISSING: [$stem] flyctl logs -a $app_name failed (not authed, app not found, or no recent logs — see fly/$app_name-logs.txt)" >> "$MANIFEST"
      fi
      # Deploy/release timeline + current machine health — tiny, and unlike
      # `logs` this survives past Fly's short log retention window, so it's
      # what tells you WHEN something shipped even after the logs are gone.
      if flyctl releases -a "$app_name" > "$B/$APP/fly/$app_name-releases.txt" 2>&1; then
        echo "OK: [$stem] flyctl releases -a $app_name -> fly/$app_name-releases.txt" >> "$MANIFEST"
      else
        echo "MISSING: [$stem] flyctl releases -a $app_name failed" >> "$MANIFEST"
      fi
      if flyctl status -a "$app_name" > "$B/$APP/fly/$app_name-status.txt" 2>&1; then
        echo "OK: [$stem] flyctl status -a $app_name -> fly/$app_name-status.txt" >> "$MANIFEST"
      else
        echo "MISSING: [$stem] flyctl status -a $app_name failed" >> "$MANIFEST"
      fi
    done <<EOF_FLY
$(find "$PROJ" -maxdepth 3 -name node_modules -prune -o -maxdepth 3 -name 'fly.toml' -print 2>/dev/null)
EOF_FLY
    [ "$fly_found" -eq 0 ] && [ ! -d "$B/$APP/fly" ] && miss "[$stem] no fly.toml found under $PROJ (3 levels deep)"
  else
    miss "[$stem] flyctl not installed — Fly logs unavailable"
  fi

  # Recent CI run timeline (list only — NOT full run logs, which can be huge).
  # Gives a pass/fail/timestamp trail even when nothing else does.
  if command -v gh >/dev/null 2>&1; then
    if (cd "$PROJ" && gh run list -L 20 > "$B/$APP/gh-run-list.txt" 2>&1); then
      echo "OK: [$stem] gh run list -L 20 -> gh-run-list.txt" >> "$MANIFEST"
    else
      echo "MISSING: [$stem] gh run list failed (no gh auth, no remote, or not a GitHub repo)" >> "$MANIFEST"
      rm -f "$B/$APP/gh-run-list.txt" 2>/dev/null
    fi
  else
    miss "[$stem] gh CLI not installed — CI run list unavailable"
  fi

  # Claude Code transcripts for THIS project path. OPT-IN (-T) — transcripts can
  # quote source, comms, and pasted secrets, so they're excluded by default.
  # Claude Code stores them under ~/.claude/projects/<slug>/ where slug =
  # project path with every non-alphanumeric char replaced by '-'. Oya runs
  # as a Claude Code session cwd'd to the project, so her boot turns (which
  # files she actually Read) are in here.
  if [ "$INCLUDE_TRANSCRIPTS" -ne 1 ]; then
    echo "EXCLUDED: [$stem] Claude transcripts (privacy default; pass -T to include)" >> "$MANIFEST"
  else
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
  fi
}

while IFS= read -r t; do
  [ -z "$t" ] && continue
  collect_app "$t"
done <<EOF_TOMLS
$TOMLS
EOF_TOMLS

# --- global section 2: transient local build/upload logs (best-effort) ---------
# Fixed-name /tmp logs (not per-project — the build scripts always write the
# same path, so this only ever has the MOST RECENT build/upload, whichever
# app that was for). Small text; skipped cleanly if absent or overwritten.
note "[global] transient build/upload logs (best-effort, /tmp)"
mkdir -p "$B/build-logs"
found_bl=0
for bl in /tmp/build-ios.log /tmp/build-android.log /tmp/upload-ios.log /tmp/upload-android.log; do
  if [ -f "$bl" ]; then
    _copy_filtered "$bl" "$B/build-logs/$(basename "$bl")" "$bl" \
      && { echo "OK: $bl -> build-logs/ (mtime: $(date -r "$bl" 2>/dev/null || stat -c %y "$bl" 2>/dev/null))" >> "$MANIFEST"; found_bl=$((found_bl + 1)); }
  else
    miss "$bl (not present — may have been overwritten by a later build, or none run)"
  fi
done
[ "$found_bl" -eq 0 ] && rmdir "$B/build-logs" 2>/dev/null

# --- global section 3: Codex CLI sessions + logs (not per-project) ---------------
# OPT-IN (-T) — same privacy rationale as the Claude transcripts above.
if [ "$INCLUDE_TRANSCRIPTS" -ne 1 ]; then
  echo "EXCLUDED: Codex CLI transcripts (privacy default; pass -T to include)" >> "$MANIFEST"
else
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
fi

# --- safety sweep: never ship obvious secrets -------------------------------------
find "$B" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name 'id_rsa*' \
  -o -name 'credentials*' -o -name '*.key' \) -type f -delete 2>/dev/null
echo "---" >> "$MANIFEST"
echo "safety sweep: removed any .env/.pem/key/credentials files from bundle" >> "$MANIFEST"

# --- redaction pass: mask pasted secrets (only meaningful with transcripts) -------
REDACTOR="$MUSUBI_DIR/scripts/redact-bundle.py"
if [ "$INCLUDE_TRANSCRIPTS" -eq 1 ]; then
  if command -v python3 >/dev/null 2>&1 && [ -f "$REDACTOR" ]; then
    redact_summary="$(python3 "$REDACTOR" "$B" 2>/dev/null)"
    echo "redaction: ${redact_summary:-ran (no summary)}" >> "$MANIFEST"
  else
    echo "redaction: SKIPPED (python3 or redact-bundle.py unavailable) — review transcripts by hand" >> "$MANIFEST"
  fi
else
  echo "redaction: n/a (no transcripts included)" >> "$MANIFEST"
fi

# --- sensitive-class manifest: declare what classes the bundle carries ------------
{
  echo "---"
  echo "SENSITIVE CLASSES IN THIS BUNDLE:"
  echo "- comms + capsule + agent docs ........ YES (always)"
  echo "- config tomls (paths/handles) ........ YES (secrets are not stored in toml)"
  echo "- tmux pane scrollback ................ when a session was live (see per-app lines above)"
  echo "- Fly.io logs/releases/status .......... when flyctl + fly.toml found (see per-app lines above; can contain request/job IDs, emails)"
  echo "- gh CI run list ....................... when gh CLI authed (list only: status/branch/timestamp, no log bodies)"
  echo "- transient build/upload logs (/tmp) .... when present (see build-logs/ lines above)"
  if [ "$INCLUDE_TRANSCRIPTS" -eq 1 ]; then
    echo "- agent chat transcripts (Claude/Codex) INCLUDED via -T — redaction pass applied"
  else
    echo "- agent chat transcripts (Claude/Codex) EXCLUDED (default; pass -T to include)"
  fi
} >> "$MANIFEST"

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
if [ "$INCLUDE_TRANSCRIPTS" -eq 1 ]; then
  echo "REVIEW BEFORE SENDING: -T included agent transcripts (chats/). A best-effort"
  echo "redaction pass ran, but it is not a guarantee — unzip and skim before sending."
else
  echo "No transcripts included (default). See MANIFEST.txt for the sensitive classes"
  echo "present; pass -T to include Claude + Codex transcripts (redacted) if needed."
fi
