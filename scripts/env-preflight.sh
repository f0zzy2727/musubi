# shellcheck shell=bash
# env-preflight.sh — sourceable helpers for launcher environment/key defence.
#
# Background (keys-1, surfaced 2026-06-20):
# A coder CLI (notably Codex) reports "no API key" / "sandboxed" when the
# launcher was started from a shell that never exported the project's keys.
# musubi itself applies NO sandbox and does NO key handling — the panes simply
# inherit the launcher's environment, and an empty environment in means an
# empty environment out. A non-technical operator has no way to see this: the
# CLI just fails opaquely downstream, and the supervisor may even invent a
# false "restricted launcher mode" explanation (oya-1confab).
#
# This file provides two helpers; both launchers source it.
#
#   load_project_env P O   — source a `.env` file (export every assignment) so
#                            the orchestrator and every spawned pane inherit the
#                            keys. Looks first in project dir P, then in the
#                            orchestrator dir O. A var already set in the live
#                            environment WINS (a `.env` never clobbers an
#                            explicit export). No-op when no `.env` exists.
#
#   warn_missing_keys C     — read the configured coder CLIs from config C and,
#                            if a CLI is known to need an API key and none is
#                            present in the environment, emit an
#                            operator-readable warning with the exact fix. Never
#                            aborts — keys may live in a CLI's own config file.
#
# Keep this file POSIX-ish: launch_musubi.sh is zsh, launch_musubi_tmux.sh is
# bash. No bash-only constructs.

# Source one .env file, exporting each KEY=VALUE. Lines that are blank, comments
# (#...), or lack an '=' are skipped. A `key` already present in the live
# environment is left untouched, so an explicit `export FOO=...` before launch
# always beats the file. Returns 0 if a file was loaded, 1 if none found.
_load_one_env() {
    envfile="$1"
    [ -f "$envfile" ] || return 1
    echo "Loading environment from $envfile"
    while IFS= read -r line || [ -n "$line" ]; do
        # Strip a leading `export ` and surrounding whitespace.
        line="${line#"${line%%[![:space:]]*}"}"   # ltrim
        case "$line" in
            ''|'#'*) continue ;;                    # blank / comment
            export\ *) line="${line#export }" ;;
        esac
        case "$line" in
            *=*) ;;                                  # must be an assignment
            *) continue ;;
        esac
        key="${line%%=*}"
        val="${line#*=}"
        # Trim whitespace around the key; reject non-identifier keys.
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            ''|*[!A-Za-z0-9_]*) continue ;;
        esac
        # Don't override a var already set in the environment.
        if eval "[ -n \"\${$key+x}\" ]"; then
            continue
        fi
        # Strip matching surrounding quotes from the value, if any.
        case "$val" in
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        export "$key=$val"
    done < "$envfile"
    return 0
}

load_project_env() {
    # Args: project_path orchestrator_dir
    project_path="$1"
    orchestrator_dir="$2"
    # Expand a leading ~ in the project path. We MATCH a literal "~/" prefix in
    # the config string and expand it ourselves via $HOME — we are not relying on
    # shell tilde expansion, so SC2088 is a false positive here.
    # shellcheck disable=SC2088
    case "$project_path" in
        "~") project_path="$HOME" ;;
        "~/"*) project_path="$HOME/${project_path#"~/"}" ;;
    esac
    loaded=1
    if [ -n "$project_path" ]; then
        _load_one_env "$project_path/.env" && loaded=0
    fi
    # Orchestrator-dir .env is a secondary location (e.g. shared dev keys).
    _load_one_env "$orchestrator_dir/.env" && loaded=0
    return $loaded
}

warn_missing_keys() {
    # Arg: path to the musubi config (toml). Reads the coder CLIs and warns if
    # one that needs an API key has none in the environment.
    config="$1"
    [ -f "$config" ] || return 0
    # Pull the `cli = "..."` values under [agents.*]. Cheap awk, no toml parser.
    clis=$(awk -F'"' '/^[[:space:]]*cli[[:space:]]*=/{print $2}' "$config" 2>/dev/null)
    case "$clis" in
        *codex*)
            # Codex CLI authenticates with OPENAI_API_KEY (or an OpenRouter key
            # when so configured). If neither is present, say so plainly.
            if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
                cat >&2 <<'EOM'

WARNING: Codex is a configured coder but no API key is set in this shell.
  Codex needs OPENAI_API_KEY (or OPENROUTER_API_KEY) in its environment. If it
  isn't set, Codex's pane will report it has "no keys" / is "sandboxed" — this
  is NOT a musubi restriction, just a missing environment variable.

  Fix (either one):
    * Put the key in a `.env` file in your project root, e.g.
        OPENAI_API_KEY=sk-...
      then re-run this launcher (it loads .env automatically), OR
    * export OPENAI_API_KEY=sk-...   before launching.

  (A key already exported in this shell always wins over the .env file.)

EOM
            fi
            ;;
    esac
    return 0
}
