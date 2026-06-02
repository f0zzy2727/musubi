#!/usr/bin/env bash
# doctor.sh — musubi preflight diagnostic ("musubi --doctor").
#
# Checks that the host environment can run a musubi session WITHOUT launching
# anything. Every probe prints a single PASS / FAIL / WARN line with an
# actionable fix on failure. The script never spawns tmux panes, never starts
# an agent CLI, never touches the comms file — it only reads.
#
# Exit status:
#   0  no FAIL lines (WARN lines are tolerated; they soft-fail at runtime)
#   1  one or more FAIL lines
#
# What it checks:
#   - tmux present (and version)
#   - the two agent CLIs on PATH (cli names read from musubi.toml:
#     [agents.opus].cli and [agents.coda].cli; default 'claude' / 'codex')
#   - a clipboard tool present (pbcopy/wl-copy/xclip/xsel/clip.exe) — WARN only
#   - python3 >= 3.11
#   - project.path from musubi.toml exists and is enterable
#   - musubi.toml present and parseable (WARN if only the .example exists)
#   - when the Oya layer is enabled: that the project has vision/architecture/
#     roadmap docs for Oya to anchor on (WARN only — she degrades gracefully)
#
# Style mirrors scripts/cwd-preflight.sh and scripts/guard-staged-scope.sh:
# set -euo pipefail, plain echo reporting, no external config beyond
# musubi.toml.

set -euo pipefail

# Resolve the musubi repo root from this script's own location so the doctor
# can be run from anywhere (CI, a subdirectory, a wrapper).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
TOML="$REPO_ROOT/musubi.toml"
TOML_EXAMPLE="$REPO_ROOT/musubi.toml.example"

# Tally of FAIL lines. Non-zero exit iff this ends up > 0.
fail_count=0

pass() { echo "PASS  $1"; }
warn() { echo "WARN  $1"; }
fail() {
  echo "FAIL  $1"
  fail_count=$((fail_count + 1))
}

# toml_value SECTION KEY FILE
#
# Section-aware extractor for a `key = "value"` line under a `[SECTION]`
# header. Pure awk so the doctor has no hard dependency on python3 (which is
# itself one of the things we are checking for). Handles single- or
# double-quoted values and trailing `# comments`. Prints nothing if absent.
toml_value() {
  local section="$1" key="$2" file="$3"
  [ -f "$file" ] || return 0
  awk -v want_section="$section" -v want_key="$key" '
    # Strip a trailing inline comment that is not inside quotes. Good enough
    # for the simple values musubi.toml uses (paths and bare identifiers).
    function strip_comment(s,   out, i, c, inq, q) {
      out = ""; inq = 0; q = ""
      for (i = 1; i <= length(s); i++) {
        c = substr(s, i, 1)
        if (inq) {
          out = out c
          if (c == q) inq = 0
        } else if (c == "\"" || c == "\x27") {
          inq = 1; q = c; out = out c
        } else if (c == "#") {
          break
        } else {
          out = out c
        }
      }
      return out
    }
    {
      line = $0
      sub(/^[ \t]+/, "", line)
      sub(/[ \t]+$/, "", line)
    }
    /^\[/ {
      cur = line
      sub(/^\[/, "", cur)
      sub(/\][ \t]*$/, "", cur)
      next
    }
    cur == want_section {
      stripped = strip_comment(line)
      sub(/[ \t]+$/, "", stripped)
      # Match: key = value
      if (stripped ~ "^" want_key "[ \t]*=") {
        val = stripped
        sub("^" want_key "[ \t]*=[ \t]*", "", val)
        # Unquote.
        if (val ~ /^".*"$/) { sub(/^"/, "", val); sub(/"$/, "", val) }
        else if (val ~ /^\x27.*\x27$/) { sub(/^\x27/, "", val); sub(/\x27$/, "", val) }
        print val
        exit
      }
    }
  ' "$file"
}

# expand_tilde PATH — expand a leading ~ to $HOME (toml stores literal '~').
expand_tilde() {
  local in="$1" tilde="~"
  case "$in" in
    "$tilde") printf '%s\n' "$HOME" ;;
    "$tilde"/*) printf '%s\n' "$HOME/${in#"$tilde"/}" ;;
    *) printf '%s\n' "$in" ;;
  esac
}

echo "musubi --doctor"
echo "repo: $REPO_ROOT"
echo "==============================="

# ---------------------------------------------------------------------------
# musubi.toml present and parseable
# ---------------------------------------------------------------------------
toml_ok=0
if [ -f "$TOML" ]; then
  if command -v python3 >/dev/null 2>&1; then
    if python3 - "$TOML" <<'PY' >/dev/null 2>&1
import sys
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        sys.exit(0)  # cannot verify here; treat as parseable, awk reads it anyway
with open(sys.argv[1], "rb") as f:
    tomllib.load(f)
PY
    then
      pass "musubi.toml present and parseable ($TOML)"
      toml_ok=1
    else
      fail "musubi.toml present but NOT parseable ($TOML)
        fix: check for TOML syntax errors (unbalanced quotes/brackets); compare against musubi.toml.example."
    fi
  else
    # No python3 to validate with; awk still reads the keys below.
    warn "musubi.toml present but could not validate parse (python3 absent) ($TOML)"
    toml_ok=1
  fi
elif [ -f "$TOML_EXAMPLE" ]; then
  warn "only musubi.toml.example found — no musubi.toml yet
        fix: cp \"$TOML_EXAMPLE\" \"$TOML\" and edit project.path."
else
  fail "no musubi.toml and no musubi.toml.example found in $REPO_ROOT
        fix: create musubi.toml at the repo root (see docs / musubi.toml.example)."
fi

# ---------------------------------------------------------------------------
# tmux present (and version)
# ---------------------------------------------------------------------------
if command -v tmux >/dev/null 2>&1; then
  tmux_ver="$(tmux -V 2>/dev/null || echo 'unknown version')"
  pass "tmux on PATH ($tmux_ver)"
else
  fail "tmux not found on PATH
        fix: install tmux (macOS: 'brew install tmux'; Debian/Ubuntu: 'sudo apt-get install -y tmux')."
fi

# ---------------------------------------------------------------------------
# Agent CLIs on PATH (names from musubi.toml, defaulting to claude / codex)
# ---------------------------------------------------------------------------
opus_cli=""
coda_cli=""
if [ -f "$TOML" ]; then
  opus_cli="$(toml_value 'agents.opus' 'cli' "$TOML")"
  coda_cli="$(toml_value 'agents.coda' 'cli' "$TOML")"
fi
[ -n "$opus_cli" ] || opus_cli="claude"
[ -n "$coda_cli" ] || coda_cli="codex"

check_cli() {
  local role="$1" cli="$2"
  if command -v "$cli" >/dev/null 2>&1; then
    pass "$role agent CLI '$cli' on PATH"
  else
    fail "$role agent CLI '$cli' not found on PATH
        fix: install '$cli' or correct [agents.$role].cli in musubi.toml, then ensure it is on PATH."
  fi
}
check_cli "opus" "$opus_cli"
check_cli "coda" "$coda_cli"

# ---------------------------------------------------------------------------
# Clipboard tool (WARN only — auto-paste soft-fails to manual Cmd+V)
# ---------------------------------------------------------------------------
clip_found=""
for tool in pbcopy wl-copy xclip xsel clip.exe; do
  if command -v "$tool" >/dev/null 2>&1; then
    clip_found="$tool"
    break
  fi
done
if [ -n "$clip_found" ]; then
  pass "clipboard tool present ($clip_found)"
else
  warn "no clipboard tool found (pbcopy/wl-copy/xclip/xsel/clip.exe)
        impact: auto-paste of prompts is disabled; you will paste manually.
        fix (optional): macOS has pbcopy built-in; Linux: 'sudo apt-get install -y xclip' (X11) or 'wl-clipboard' (Wayland)."
fi

# ---------------------------------------------------------------------------
# python3 >= 3.11
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  py_ver="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo '')"
  if python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' >/dev/null 2>&1; then
    pass "python3 ${py_ver:-unknown} (>= 3.11)"
  else
    fail "python3 ${py_ver:-unknown} is older than 3.11
        fix: install Python 3.11+ (macOS: 'brew install python@3.12'; Debian/Ubuntu: 'sudo apt-get install -y python3.11') and put it on PATH."
  fi
else
  fail "python3 not found on PATH
        fix: install Python 3.11+ (macOS: 'brew install python@3.12'; Debian/Ubuntu: 'sudo apt-get install -y python3') and put it on PATH."
fi

# ---------------------------------------------------------------------------
# project.path exists and is enterable
# ---------------------------------------------------------------------------
if [ "$toml_ok" -eq 1 ] && [ -f "$TOML" ]; then
  proj_raw="$(toml_value 'project' 'path' "$TOML")"
  if [ -z "$proj_raw" ]; then
    fail "musubi.toml has no [project].path
        fix: add 'path = \"/absolute/path/to/your/project\"' under [project] in musubi.toml."
  else
    proj_path="$(expand_tilde "$proj_raw")"
    if [ ! -d "$proj_path" ]; then
      fail "project.path does not exist or is not a directory: $proj_path
        fix: correct [project].path in musubi.toml to point at your project's root directory."
    elif ( cd -- "$proj_path" >/dev/null 2>&1 && cd -- "$REPO_ROOT" >/dev/null 2>&1 ); then
      pass "project.path exists and is enterable ($proj_path)"
    else
      fail "project.path exists but could not be entered: $proj_path
        fix: check directory permissions, or that the path is not on a stale/unmounted volume."
    fi
  fi
else
  warn "skipping project.path check (musubi.toml not available)"
fi

# ---------------------------------------------------------------------------
# Oya north-star docs — only when the third-agent layer is enabled.
# Oya custodians the vision; without vision/architecture/roadmap docs she
# falls back to README and stops on turn one to ask. WARN (not FAIL): she
# degrades gracefully, but it is avoidable friction.
# ---------------------------------------------------------------------------
oya_enabled=""
[ -f "$TOML" ] && oya_enabled="$(toml_value 'agents.oyakata' 'enabled' "$TOML")"
if [ "$oya_enabled" = "true" ]; then
  if [ -n "${proj_path:-}" ] && [ -d "${proj_path:-}" ]; then
    # Operator-specified docs take precedence over auto-discovery.
    ctx_raw="$(toml_value 'agents.oyakata' 'context_docs' "$TOML")"
    if [ -n "$ctx_raw" ] && [ "$ctx_raw" != "[]" ]; then
      ctx_paths="$(printf '%s\n' "$ctx_raw" | grep -oE '"[^"]*"|'\''[^'\'']*'\''' | tr -d '"'\' || true)"
      missing=""; found_ctx=0
      for p in $ctx_paths; do
        found_ctx=1
        [ -e "$proj_path/$p" ] || missing="$missing $p"
      done
      if [ "$found_ctx" -eq 1 ] && [ -z "$missing" ]; then
        pass "Oya enabled: context_docs all present in project"
      elif [ -n "$missing" ]; then
        warn "Oya enabled: context_docs listed but missing in project:$missing
        fix: create the file(s) under $proj_path, or correct the paths in [agents.oyakata].context_docs."
      fi
    else
      # No explicit context_docs — check the auto-discovered recognised docs.
      # README.md is deliberately excluded: Oya treats it only as a weak fallback.
      found=""
      for rel in docs/PRODUCT-VISION.md docs/VISION.md docs/PRD.md PRD.md \
                 docs/ARCHITECTURE.md docs/ROADMAP.md docs/BACKLOG.md; do
        [ -f "$proj_path/$rel" ] && found="$found $rel"
      done
      for d in docs/adr docs/architecture; do
        if [ -d "$proj_path/$d" ] && [ -n "$(ls -A "$proj_path/$d" 2>/dev/null || true)" ]; then
          found="$found $d/"
        fi
      done
      if [ -n "$found" ]; then
        pass "Oya enabled: north-star docs found ($found )"
      else
        warn "Oya enabled but no vision/architecture/roadmap docs found in project
        impact: Oya falls back to README.md (weak) and will stop on turn one to ask for a north-star.
        fix: add the docs (cp templates/VISION.md templates/ROADMAP.md templates/ARCHITECTURE.md \"$proj_path/docs/\"),
             or point [agents.oyakata].context_docs at your existing docs. See README: \"Prerequisite: give Oya a north-star\"."
      fi
    fi
  else
    warn "Oya enabled but project.path unavailable — cannot check for north-star docs"
  fi
fi

echo "==============================="
if [ "$fail_count" -gt 0 ]; then
  echo "doctor: $fail_count FAIL — environment is NOT ready. Address the FAIL lines above."
  exit 1
fi
echo "doctor: OK — no FAIL lines. Environment is ready (review any WARN lines)."
exit 0
