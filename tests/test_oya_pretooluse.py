"""Tests for oyakata-2 slice 1 — PreToolUse hook tier-1 allowlist.

Covers:
  - classify() — the pure decision function
  - classify_bash() — the read-only-pattern + metachar combination
  - log_decision() — best-effort audit trail
  - main() — the full stdin→decision→stdout pipeline, run as a subprocess
    against the actual hook script so we exercise the same path Claude Code
    will at runtime.

The OYAKATA_DECISIONS_LOG env var is set to a tmpdir-relative path in every
test so the live `docs/agents/oyakata-decisions.md` is never touched.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

# Hook script lives in scripts/. Importing it as a module needs an explicit
# sys.path tweak because it has a hyphen in its filename and pytest's default
# discovery doesn't reach scripts/. We pull it in via importlib so the unit
# tests can call the pure functions directly without subprocessing.
import importlib.util

HOOK_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "oya-pretooluse.py"

_spec = importlib.util.spec_from_file_location("oya_pretooluse", HOOK_PATH)
oya_pretooluse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oya_pretooluse)


# ---------------------------------------------------------------------------
# classify_bash — pure logic, no I/O
# ---------------------------------------------------------------------------

class TestClassifyBash:
    @pytest.mark.parametrize("cmd", [
        # METADATA-ONLY: reveal status/refs/names/stats, never file content.
        "git status",
        "git status -s",
        "git status --short --branch",
        "git log --oneline",
        "git log --oneline -10",
        "git log --oneline -n 20",
        "git branch",
        "git branch -l",
        "git branch --list",
        "git branch -a",
        "git rev-parse HEAD",
        "git ls-files",
        "git ls-tree HEAD",
        "pwd",
        "whoami",
        "date",
        "date -u",
        "ls",
        "ls -la /tmp",
        "wc -l file.txt",
        "file ./binary",
        "stat README.md",
        "which python3",
        "command -v node",
        "type cd",
    ])
    def test_safe_commands_auto_approve(self, cmd):
        ok, reason = oya_pretooluse.classify_bash(cmd)
        assert ok is True, f"expected allow for {cmd!r}, got defer: {reason}"

    @pytest.mark.parametrize("cmd", [
        # sec-1 (2026-06-16): "non-mutating" is NOT "safe to disclose". These
        # reads leak file content / config / credentials and must DEFER by
        # default. The auditor's exact attack cases are included.
        "git show HEAD",
        "git show HEAD:.env",          # prints a tracked secret file's contents
        "git diff",
        "git diff HEAD~1",
        "git log",                     # general log; `git log -p` shows patches
        "git log -p",
        "git blame README.md",         # prints file content lines
        "git config --get user.email",
        "git config --get http.extraheader",   # credential-bearing header
        "git config --list",           # dumps all config incl. creds
        "git remote",
        "git remote -v",               # remote URLs may embed user:token@host
    ])
    def test_disclosure_commands_defer_by_default(self, cmd):
        """Content/config-disclosing reads defer unless the operator opts in."""
        ok, reason = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"disclosure command {cmd!r} must defer by default, was auto-approved ({reason})"

    @pytest.mark.parametrize("cmd", [
        "git show HEAD",
        "git diff",
        "git log",
        "git config --list",
        "git remote -v",
    ])
    def test_disclosure_commands_allow_when_opted_in(self, cmd, monkeypatch):
        """[security].repo_has_no_secrets (env MUSUBI_REPO_HAS_NO_SECRETS) lets an
        operator who knows the repo is clean re-enable the disclose tier."""
        monkeypatch.setenv("MUSUBI_REPO_HAS_NO_SECRETS", "1")
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is True, f"opt-in should auto-approve {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        # Bare `$` env expansion → defer, even with the disclose opt-in on.
        # The opt-in only relaxes the git disclose tier, never expansion/cat.
        "echo $TOKEN",
        "echo ${AWS_SECRET_ACCESS_KEY}",
        "ls $HOME/.ssh",
        "git show $REF",
        "cat .env",
        "printenv",
    ])
    def test_expansion_and_content_readers_defer_even_with_opt_in(self, cmd, monkeypatch):
        monkeypatch.setenv("MUSUBI_REPO_HAS_NO_SECRETS", "1")
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"{cmd!r} must defer regardless of opt-in"

    @pytest.mark.parametrize("cmd", [
        # `echo` was removed from the allowlist entirely.
        "echo hello",
        "echo $TOKEN",
    ])
    def test_echo_defers(self, cmd):
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"echo is no longer auto-approved; {cmd!r} must defer"

    @pytest.mark.parametrize("cmd", [
        # Disclose arbitrary file CONTENTS — must NOT auto-approve. Normal file
        # reads route through the path-scoped Read tool, not raw Bash `cat`.
        "cat README.md",
        "cat /Users/x/.ssh/id_rsa",
        "cat .env",
        "head -n 20 file.txt",
        "head ~/.aws/credentials",
        "tail -50 log.txt",
        "tail secrets.txt",
        # Dump the environment, including any exported API keys.
        "printenv",
        "printenv PATH",
        "env",
    ])
    def test_secret_readers_defer(self, cmd):
        """Regression: file-content and env readers were once tier-1 allowed.
        Auto-approving them is silent secret disclosure (cat ~/.ssh/id_rsa,
        printenv → API keys). They must defer to a permission prompt."""
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"secret-reader {cmd!r} must defer, was auto-approved"

    @pytest.mark.parametrize("cmd", [
        # Newline-injection bypass: an allow-listed FIRST line must not smuggle
        # an arbitrary SECOND line past the start-anchored allowlist.
        "git status\nrm -rf /tmp/x",
        "ls -la\nrm -rf /tmp/x",
        "git status\r\nrm -rf /tmp/x",
        "pwd\nshutdown now",
        "echo hi\nmv important.db /tmp/",
    ])
    def test_newline_injection_defers(self, cmd):
        """Regression: allowlist patterns anchor at string start (re.match), so
        without a newline fence a multi-line command auto-approved its payload."""
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"newline-injection {cmd!r} must defer, was auto-approved"

    @pytest.mark.parametrize("cmd", [
        # Shell metacharacters → defer.
        "git status | tee out.txt",
        "git log > log.txt",
        "git status; rm -rf /",
        "git log && echo done",
        "git log || echo failed",
        "git log $(whoami)",
        "git log `whoami`",
        "ls > out.txt",
        "ls < input",
        "cat file | grep foo",
        # Conservative: '&' anywhere (even quoted) defers. This is
        # over-strict but the failure mode is "operator answers a prompt".
        "git log --grep='foo&bar'",
        # Background.
        "ls &",
    ])
    def test_metachars_defer(self, cmd):
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"expected defer for {cmd!r}, got allow"

    @pytest.mark.parametrize("cmd", [
        # Not in the read-only allowlist.
        "rm -rf /tmp/foo",
        "git push",
        "git commit -m 'wip'",
        "git checkout main",
        "git merge feature",
        "git rebase main",
        "git reset --hard",
        "git branch -d feature",
        "git branch -D feature",
        "git branch --delete feature",
        "curl https://example.com",
        "wget https://example.com",
        "npm install",
        "pip install requests",
        "make build",
        "docker run --rm alpine",
        "sudo apt update",
        "mv a b",
        "cp a b",
        "touch new.txt",
    ])
    def test_state_changing_commands_defer(self, cmd):
        ok, _ = oya_pretooluse.classify_bash(cmd)
        assert ok is False, f"expected defer for {cmd!r}, got allow"

    def test_empty_command_defers(self):
        ok, _ = oya_pretooluse.classify_bash("")
        assert ok is False


# ---------------------------------------------------------------------------
# classify — top-level dispatch
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "NotebookRead"])
    def test_unconditional_tools_auto_approve(self, tool):
        ok, reason = oya_pretooluse.classify(tool, {})
        assert ok is True
        assert tool in reason

    def test_bash_with_safe_command_auto_approves(self):
        ok, _ = oya_pretooluse.classify("Bash", {"command": "git status"})
        assert ok is True

    def test_bash_with_unsafe_command_defers(self):
        ok, _ = oya_pretooluse.classify("Bash", {"command": "git push"})
        assert ok is False

    def test_bash_with_missing_command_defers(self):
        ok, _ = oya_pretooluse.classify("Bash", {})
        assert ok is False

    def test_bash_with_non_string_command_defers(self):
        # Defensive: tool_input shape may drift across CC versions.
        ok, _ = oya_pretooluse.classify("Bash", {"command": ["git", "status"]})
        assert ok is False

    @pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "WebFetch", "Task", "UnknownTool"])
    def test_unlisted_tools_defer(self, tool):
        ok, _ = oya_pretooluse.classify(tool, {"file_path": "/tmp/x"})
        assert ok is False


# ---------------------------------------------------------------------------
# log_decision — best-effort audit trail
# ---------------------------------------------------------------------------

class TestLogDecision:
    def test_creates_log_with_header_on_first_write(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oyakata-decisions.md"
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", str(log_file))
        oya_pretooluse.log_decision("ALLOW", "Read", "test", "/tmp/x")
        content = log_file.read_text()
        assert "oyakata-decisions — auto-approve audit trail" in content
        assert "ALLOW Read" in content
        assert "/tmp/x" in content

    def test_appends_to_existing_log(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oyakata-decisions.md"
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", str(log_file))
        oya_pretooluse.log_decision("ALLOW", "Read", "first", "/tmp/a")
        oya_pretooluse.log_decision("DEFER", "Bash", "second", "rm -rf")
        content = log_file.read_text()
        assert content.count("---") == 1  # header separator only, no repeats
        assert "first" in content
        assert "second" in content
        assert "DEFER" in content

    def test_truncates_long_summary(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oyakata-decisions.md"
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", str(log_file))
        long_input = "x" * 1000
        oya_pretooluse.log_decision("ALLOW", "Bash", "test", long_input)
        content = log_file.read_text()
        # Each line should be skim-readable. The summary is capped at 160.
        relevant_lines = [ln for ln in content.splitlines() if "ALLOW Bash" in ln]
        assert relevant_lines
        # Total line shouldn't blow past a few hundred chars given the cap.
        assert all(len(ln) < 400 for ln in relevant_lines)

    def test_collapses_newlines_in_summary(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oyakata-decisions.md"
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", str(log_file))
        oya_pretooluse.log_decision("ALLOW", "Bash", "test", "line1\nline2\nline3")
        content = log_file.read_text()
        # Each decision must occupy exactly one line so the log stays skim-friendly.
        # The smoke check: no decision spans multiple lines in the audit body.
        body = content.split("---", 1)[1]
        for line in body.strip().splitlines():
            if line and "::" in line:
                # Has the ts+decision+tool+reason+summary on one line.
                assert "\n" not in line

    def test_failure_to_write_does_not_raise(self, monkeypatch):
        # Point the log at a path that can't be created. The hook MUST never
        # crash the tool flow on log-write failure.
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", "/this/path/cannot/exist/xyz/log.md")
        # Should swallow the OSError silently.
        oya_pretooluse.log_decision("ALLOW", "Read", "test", "x")


# ---------------------------------------------------------------------------
# End-to-end: subprocess the actual script with realistic stdin
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Subprocess the hook script as Claude Code would. Verifies the full
    stdin→classify→stdout pipeline, JSON shapes, and exit codes."""

    def _run(self, tool_name, tool_input, log_path):
        env = os.environ.copy()
        env["OYAKATA_DECISIONS_LOG"] = str(log_path)
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
            capture_output=True,
            text=True,
            env=env,
        )
        return result

    def test_read_returns_allow_json(self, tmp_path):
        r = self._run("Read", {"file_path": "/tmp/x"}, tmp_path / "log.md")
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "oyakata-2" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_bash_safe_command_returns_allow_json(self, tmp_path):
        r = self._run("Bash", {"command": "git status"}, tmp_path / "log.md")
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_bash_unsafe_command_emits_no_output(self, tmp_path):
        r = self._run("Bash", {"command": "git push"}, tmp_path / "log.md")
        assert r.returncode == 0
        assert r.stdout == ""

    @pytest.mark.parametrize("cmd", [
        "git show HEAD:.env",   # sec-1 headline: must not auto-approve a tracked secret
        "echo $TOKEN",          # env-expansion disclosure
        "git config --list",
        "git remote -v",
    ])
    def test_bash_disclosure_command_emits_no_output(self, cmd, tmp_path):
        """End-to-end: the auditor's disclosure cases produce no allow JSON, so
        Claude Code falls through to its normal permission prompt."""
        r = self._run("Bash", {"command": cmd}, tmp_path / "log.md")
        assert r.returncode == 0
        assert r.stdout == "", f"{cmd!r} should not emit an allow decision"

    def test_write_emits_no_output(self, tmp_path):
        r = self._run(
            "Write",
            {"file_path": "/tmp/x", "content": "y"},
            tmp_path / "log.md",
        )
        assert r.returncode == 0
        assert r.stdout == ""

    def test_malformed_stdin_does_not_crash(self, tmp_path):
        # CC sends well-formed JSON, but defence in depth: if we ever get
        # garbage, exit cleanly with no decision.
        env = os.environ.copy()
        env["OYAKATA_DECISIONS_LOG"] = str(tmp_path / "log.md")
        r = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="this is not json {{{",
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0
        assert r.stdout == ""
