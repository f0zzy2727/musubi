"""Tests for oyakata-2 slice 3 — tier-2 Oya-as-decider.

Covers the new code paths in scripts/oya-pretooluse.py:

  - is_tier2_candidate() — git-status-based classifier
  - consult_oya() — request file write + verdict poll round-trip
  - main() — full pipeline routing tier-2 candidates through Oya

Each test that exercises the round-trip simulates Oya by writing the
verdict file from a background thread on a controlled timing.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest

import importlib.util

HOOK_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "oya-pretooluse.py"

_spec = importlib.util.spec_from_file_location("oya_pretooluse", HOOK_PATH)
oya_pretooluse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oya_pretooluse)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_git_repo(repo_dir: pathlib.Path) -> None:
    """Initialise a git repo with one committed file so subsequent edits
    show up in `git status`."""
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo_dir)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "Test"],
        check=True,
    )
    (repo_dir / "tracked.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo_dir), "add", "tracked.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-q", "-m", "init"],
        check=True,
    )


def _make_modified(repo_dir: pathlib.Path, name: str = "tracked.py") -> pathlib.Path:
    """Modify a tracked file so it shows up in `git status` as modified."""
    path = repo_dir / name
    path.write_text(path.read_text() + "y = 2\n")
    return path


def _make_untracked(repo_dir: pathlib.Path, name: str = "new.py") -> pathlib.Path:
    """Create an untracked file (also shows up in `git status`)."""
    path = repo_dir / name
    path.write_text("z = 3\n")
    return path


# ---------------------------------------------------------------------------
# is_tier2_candidate
# ---------------------------------------------------------------------------

class TestIsTier2Candidate:
    def test_edit_on_modified_file_is_candidate(self, tmp_path):
        _init_git_repo(tmp_path)
        target = _make_modified(tmp_path)
        ok, reason = oya_pretooluse.is_tier2_candidate(
            "Edit",
            {"file_path": str(target), "old_string": "x", "new_string": "X"},
            project_root=str(tmp_path),
        )
        assert ok is True
        assert "git status" in reason

    def test_write_on_untracked_file_is_candidate(self, tmp_path):
        _init_git_repo(tmp_path)
        target = _make_untracked(tmp_path)
        ok, _ = oya_pretooluse.is_tier2_candidate(
            "Write",
            {"file_path": str(target), "content": "..."},
            project_root=str(tmp_path),
        )
        assert ok is True

    def test_notebookedit_on_modified_file_is_candidate(self, tmp_path):
        _init_git_repo(tmp_path)
        target = _make_modified(tmp_path)
        ok, _ = oya_pretooluse.is_tier2_candidate(
            "NotebookEdit",
            {"file_path": str(target)},
            project_root=str(tmp_path),
        )
        assert ok is True

    def test_edit_on_unchanged_file_is_not_candidate(self, tmp_path):
        _init_git_repo(tmp_path)
        # Add a second file that IS modified so `git status` isn't empty —
        # otherwise the classifier takes the "empty git status" early-exit
        # branch, which is a different (and also correct) defer reason.
        _make_modified(tmp_path, "tracked.py")
        # Also commit a second tracked-and-unchanged file.
        other = tmp_path / "unchanged.py"
        other.write_text("a = 1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "unchanged.py"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "add unchanged"], check=True)
        # Now: git status shows tracked.py modified, unchanged.py is clean.
        ok, reason = oya_pretooluse.is_tier2_candidate(
            "Edit",
            {"file_path": str(other)},
            project_root=str(tmp_path),
        )
        assert ok is False
        assert "not in `git status`" in reason

    def test_read_is_not_a_tier2_tool(self, tmp_path):
        _init_git_repo(tmp_path)
        _make_modified(tmp_path)
        ok, _ = oya_pretooluse.is_tier2_candidate(
            "Read",
            {"file_path": str(tmp_path / "tracked.py")},
            project_root=str(tmp_path),
        )
        assert ok is False

    def test_bash_is_not_a_tier2_tool(self, tmp_path):
        # Bash writes might LOGICALLY belong to tier-2, but they're explicitly
        # out-of-scope for this slice (the metachar fence + safe-command
        # head match handle them in tier-1).
        _init_git_repo(tmp_path)
        ok, _ = oya_pretooluse.is_tier2_candidate(
            "Bash",
            {"command": "echo hi > tracked.py"},
            project_root=str(tmp_path),
        )
        assert ok is False

    def test_missing_file_path_defers(self, tmp_path):
        _init_git_repo(tmp_path)
        ok, _ = oya_pretooluse.is_tier2_candidate("Edit", {}, project_root=str(tmp_path))
        assert ok is False

    def test_non_git_directory_defers(self, tmp_path):
        # No git init — `git status` will fail, in_motion set is empty.
        ok, reason = oya_pretooluse.is_tier2_candidate(
            "Edit",
            {"file_path": str(tmp_path / "x.py")},
            project_root=str(tmp_path),
        )
        assert ok is False
        assert "git status" in reason


# ---------------------------------------------------------------------------
# consult_oya — round-trip with simulated Oya
# ---------------------------------------------------------------------------

class TestConsultOya:
    def _patch_short_timeout(self, monkeypatch, seconds=2.0):
        """Compress the verdict timeout so tests run fast. Polling stays
        at its native interval."""
        monkeypatch.setattr(oya_pretooluse, "TIER2_VERDICT_TIMEOUT_S", seconds)
        monkeypatch.setattr(oya_pretooluse, "TIER2_VERDICT_POLL_INTERVAL_S", 0.05)

    def _simulate_oya(self, pending_dir: pathlib.Path, delay: float, verdict: dict):
        """Background thread that waits `delay` seconds, then writes the
        verdict file for whatever request is currently pending in the
        directory. Returns the thread (caller joins it)."""
        def worker():
            time.sleep(delay)
            # Find the latest request file written into pending_dir.
            tries = 0
            while tries < 100:
                if pending_dir.is_dir():
                    requests = [p for p in pending_dir.iterdir() if p.name.endswith(".request.json")]
                    if requests:
                        rid = requests[0].name[:-len(".request.json")]
                        (pending_dir / f"{rid}.verdict.json").write_text(json.dumps(verdict))
                        return
                time.sleep(0.02)
                tries += 1
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t

    def test_allow_verdict_returns_allow(self, tmp_path, monkeypatch):
        self._patch_short_timeout(monkeypatch, 3.0)
        pending_dir = pathlib.Path(oya_pretooluse._pending_dir(str(tmp_path)))
        oya = self._simulate_oya(
            pending_dir,
            delay=0.1,
            verdict={"verdict": "allow", "reason": "in scope"},
        )
        decision, reason = oya_pretooluse.consult_oya(
            "Edit",
            {"file_path": str(tmp_path / "foo.py")},
            project_root=str(tmp_path),
        )
        oya.join(timeout=3)
        assert decision == "allow"
        assert "in scope" in reason

    def test_defer_verdict_returns_defer(self, tmp_path, monkeypatch):
        self._patch_short_timeout(monkeypatch, 3.0)
        pending_dir = pathlib.Path(oya_pretooluse._pending_dir(str(tmp_path)))
        self._simulate_oya(
            pending_dir,
            delay=0.1,
            verdict={"verdict": "defer", "reason": "out of slice"},
        )
        decision, reason = oya_pretooluse.consult_oya(
            "Edit",
            {"file_path": str(tmp_path / "foo.py")},
            project_root=str(tmp_path),
        )
        assert decision == "defer"
        assert "out of slice" in reason

    def test_timeout_returns_defer(self, tmp_path, monkeypatch):
        # No Oya simulator — verdict file never appears.
        self._patch_short_timeout(monkeypatch, 0.3)
        decision, reason = oya_pretooluse.consult_oya(
            "Edit",
            {"file_path": str(tmp_path / "foo.py")},
            project_root=str(tmp_path),
        )
        assert decision == "defer"
        assert "did not respond" in reason

    def test_malformed_verdict_returns_defer(self, tmp_path, monkeypatch):
        self._patch_short_timeout(monkeypatch, 3.0)
        pending_dir = pathlib.Path(oya_pretooluse._pending_dir(str(tmp_path)))

        def worker():
            time.sleep(0.1)
            tries = 0
            while tries < 100:
                if pending_dir.is_dir():
                    requests = [p for p in pending_dir.iterdir() if p.name.endswith(".request.json")]
                    if requests:
                        rid = requests[0].name[:-len(".request.json")]
                        # Write malformed JSON.
                        (pending_dir / f"{rid}.verdict.json").write_text("{ not json")
                        return
                time.sleep(0.02)
                tries += 1
        threading.Thread(target=worker, daemon=True).start()
        decision, _ = oya_pretooluse.consult_oya(
            "Edit",
            {"file_path": str(tmp_path / "foo.py")},
            project_root=str(tmp_path),
        )
        assert decision == "defer"

    def test_cleanup_removes_both_files(self, tmp_path, monkeypatch):
        self._patch_short_timeout(monkeypatch, 3.0)
        pending_dir = pathlib.Path(oya_pretooluse._pending_dir(str(tmp_path)))
        self._simulate_oya(
            pending_dir,
            delay=0.1,
            verdict={"verdict": "allow", "reason": "ok"},
        )
        oya_pretooluse.consult_oya(
            "Edit",
            {"file_path": str(tmp_path / "foo.py")},
            project_root=str(tmp_path),
        )
        # After consume, neither file should remain.
        leftovers = [p.name for p in pending_dir.iterdir()] if pending_dir.exists() else []
        assert not any(n.endswith(".request.json") for n in leftovers)
        assert not any(n.endswith(".verdict.json") for n in leftovers)


# ---------------------------------------------------------------------------
# Full pipeline subprocess test — main() with tier-2 routing
# ---------------------------------------------------------------------------

class TestMainTier2Routing:
    """Subprocess the actual hook script with a tier-2 candidate, simulate
    Oya from a background thread, verify the script emits the right JSON."""

    def test_tier2_allow_returns_allow_json(self, tmp_path):
        _init_git_repo(tmp_path)
        target = _make_modified(tmp_path)
        pending_dir = tmp_path / "docs" / "agents" / "oyakata-pending"

        def simulate_oya():
            tries = 0
            while tries < 200:
                if pending_dir.is_dir():
                    requests = [p for p in pending_dir.iterdir() if p.name.endswith(".request.json")]
                    if requests:
                        rid = requests[0].name[:-len(".request.json")]
                        (pending_dir / f"{rid}.verdict.json").write_text(
                            json.dumps({"verdict": "allow", "reason": "test ok"})
                        )
                        return
                time.sleep(0.05)
                tries += 1

        t = threading.Thread(target=simulate_oya, daemon=True)
        t.start()

        env = os.environ.copy()
        env["OYAKATA_DECISIONS_LOG"] = str(tmp_path / "log.md")
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps({
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "x = 1",
                    "new_string": "x = 2",
                },
            }),
            capture_output=True,
            text=True,
            cwd=str(tmp_path),  # Critical: hook reads cwd to find git root + pending dir.
            env=env,
            timeout=30,
        )
        t.join(timeout=5)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert result.stdout, f"no stdout; stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "tier-2" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_tier2_timeout_returns_defer(self, tmp_path, monkeypatch):
        # No simulated Oya. With a real TIER2_VERDICT_TIMEOUT_S=20 this would
        # be slow; we need a way to compress it. Easiest path: write a small
        # wrapper that sets the timeout. Or run the hook in-process via
        # main() under monkeypatch.
        _init_git_repo(tmp_path)
        target = _make_modified(tmp_path)

        monkeypatch.setattr(oya_pretooluse, "TIER2_VERDICT_TIMEOUT_S", 0.3)
        monkeypatch.setattr(oya_pretooluse, "TIER2_VERDICT_POLL_INTERVAL_S", 0.05)
        monkeypatch.setenv("OYAKATA_DECISIONS_LOG", str(tmp_path / "log.md"))

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            # Wire stdin to a payload, capture stdout.
            import io
            payload = json.dumps({
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target), "old_string": "x", "new_string": "X"},
            })
            monkeypatch.setattr("sys.stdin", io.StringIO(payload))
            buf = io.StringIO()
            monkeypatch.setattr("sys.stdout", buf)
            rc = oya_pretooluse.main()
            output = buf.getvalue()
        finally:
            os.chdir(old_cwd)

        assert rc == 0
        # Timeout -> defer -> empty stdout (no allow JSON).
        assert output == ""

    def test_tier1_path_unaffected_by_tier2_code(self, tmp_path):
        # Smoke-test: a tier-1 unconditional tool should still allow without
        # touching tier-2 plumbing.
        env = os.environ.copy()
        env["OYAKATA_DECISIONS_LOG"] = str(tmp_path / "log.md")
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}),
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "tier-1" in out["hookSpecificOutput"]["permissionDecisionReason"]
