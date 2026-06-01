# shellcheck shell=bash
# cwd-preflight.sh — sourceable helpers for launcher cwd defence.
#
# Background (orch-6, surfaced 2026-05-23):
# Node-based agent CLIs (Claude Code, Codex) crash with `EPERM: process.cwd
# failed ... uv_cwd` when the shell's working-directory handle has been
# invalidated between sessions. The prompt label keeps displaying the old
# project directory, but the underlying handle is dead — usually because
# iCloud Drive sync (on by default for ~/Desktop, ~/Documents, ~/Downloads)
# moved files underneath us, or a parent directory was renamed, or the
# folder was briefly unmounted.
#
# This file provides two helpers; both launchers source it.
#
#   preflight_cwd       — verifies the current shell's pwd is readable.
#                         Aborts with operator-readable recovery text if not.
#
#   warn_icloud_path P  — emits a one-shot warning if P is under an
#                         iCloud-synced macOS folder. Non-fatal.
#
# Keep this file POSIX-ish: launch_musubi.sh is zsh, launch_musubi_tmux.sh
# is bash. No bash-only constructs.

preflight_cwd() {
    if ! pwd >/dev/null 2>&1; then
        cat >&2 <<'EOM'

ERROR: Current working directory is stale (cannot read pwd).

The shell's working-directory handle is invalid — usually caused by
iCloud sync moving files underneath the session, a folder rename, or
a brief unmount. Node-based agent CLIs crash with EPERM uv_cwd in
this state.

To recover:
  1. Close this terminal window entirely.
  2. Open a new terminal.
  3. cd ~ first, then cd to your project root.
  4. Re-run this launcher.

EOM
        return 1
    fi
    return 0
}

warn_icloud_path() {
    # Single argument: an absolute path to check.
    # Warns (does not abort) if the path is under a macOS iCloud-synced
    # folder. iCloud sync can invalidate the cwd handle between sessions.
    target="$1"
    case "$target" in
        "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*)
            cat >&2 <<EOM

WARNING: project path is under a macOS iCloud-synced folder:
  $target

iCloud Drive sync can invalidate the shell's working-directory handle
between sessions and cause Claude Code / Codex to crash with EPERM
uv_cwd on restart. If you hit that crash, close the terminal, open a
new one, cd ~, then cd back to the project and retry.

Recommended fix: move the project to ~/Dev/ (or any non-synced
location) to avoid the failure mode entirely.

EOM
            ;;
    esac
}
