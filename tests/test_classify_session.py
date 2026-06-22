"""Tests for orch-5 / Slice 5.5 — smart existing-session classification.

Verifies the three-state classifier (live / orphan / ambiguous) returns
the right answer for representative session shapes. Pane objects are
mocked since libtmux's real Pane requires an actual tmux server.
"""
import os
from unittest.mock import MagicMock

import pytest

from orchestrator import (
    KNOWN_SHELLS,
    classify_existing_session,
    describe_session_panes,
    pane_in_shell,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def make_pane(pane_id, current_command, current_path="/tmp/project"):
    """Build a mock libtmux Pane for the classifier.

    The classifier reads:
      - pane.pane_current_command (string)
      - pane.cmd("display-message", "-p", "#{pane_current_path}").stdout (list)
      - pane.pane_id (for describe_session_panes)
    """
    pane = MagicMock()
    pane.pane_id = pane_id
    pane.pane_current_command = current_command

    cmd_result = MagicMock()
    cmd_result.stdout = [current_path]
    pane.cmd.return_value = cmd_result

    return pane


def make_session(panes):
    """Build a mock session with the given pane list."""
    session = MagicMock()
    session.active_window.panes = panes
    return session


# Default to a project path NOT inside the musubi repo, so the Oya-pane
# filter doesn't accidentally claim a regular pair pane is Oya.
# Tests that need an Oya pane set current_path to the musubi repo root.
MUSUBI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/docs/operator"


# ---------------------------------------------------------------------------
# pane_in_shell unit
# ---------------------------------------------------------------------------

class TestPaneInShell:
    def test_zsh_is_shell(self):
        assert pane_in_shell(make_pane("%0", "zsh"))

    def test_bash_is_shell(self):
        assert pane_in_shell(make_pane("%0", "bash"))

    def test_uppercase_normalized(self):
        assert pane_in_shell(make_pane("%0", "ZSH"))

    def test_claude_is_not_shell(self):
        assert not pane_in_shell(make_pane("%0", "claude"))

    def test_codex_is_not_shell(self):
        assert not pane_in_shell(make_pane("%0", "codex"))

    def test_node_is_not_shell(self):
        # Codex CLI shows as 'node' since it's a node app
        assert not pane_in_shell(make_pane("%0", "node"))

    def test_version_string_is_not_shell(self):
        # Claude Code 2.x reports its version, e.g. '2.1.145'
        assert not pane_in_shell(make_pane("%0", "2.1.145"))

    def test_empty_command_is_not_shell(self):
        # Defensive: empty/None doesn't accidentally classify as shell
        pane = MagicMock()
        pane.pane_current_command = ""
        assert not pane_in_shell(pane)

    def test_missing_attribute_is_not_shell(self):
        # If libtmux raises on access, treat as 'something running'
        pane = MagicMock()
        pane.pane_current_command = None
        assert not pane_in_shell(pane)

    def test_all_known_shells_classify(self):
        for shell in KNOWN_SHELLS:
            assert pane_in_shell(make_pane("%0", shell)), f"{shell} should be a shell"


# ---------------------------------------------------------------------------
# classify_existing_session — pair-only configurations
# ---------------------------------------------------------------------------

class TestClassifyPairOnly:
    def test_both_panes_running_claude_codex_is_live(self):
        session = make_session([
            make_pane("%0", "claude"),
            make_pane("%1", "codex"),
        ])
        assert classify_existing_session(session) == "live"

    def test_real_world_claude_node_is_live(self):
        # Mirrors the user's actual live session: claude shows as '2.1.145',
        # codex shows as 'node'
        session = make_session([
            make_pane("%0", "2.1.145"),
            make_pane("%1", "node"),
        ])
        assert classify_existing_session(session) == "live"

    def test_both_panes_in_shell_is_orphan(self):
        session = make_session([
            make_pane("%0", "zsh"),
            make_pane("%1", "zsh"),
        ])
        assert classify_existing_session(session) == "orphan"

    def test_both_shells_at_repo_root_is_orphan(self):
        # Reboot / Ctrl+C'd-launch regression: dropped-to-shell panes default
        # to the musubi repo-root cwd, which the Oya-pane cwd heuristic would
        # otherwise mistake for Oya panes — flagging every pane as Oya, leaving
        # zero pair panes, and spuriously prompting the operator. All-shell is
        # an unambiguous corpse and must classify as orphan (silent recreate).
        # Repo root = where orchestrator.py lives = the classifier's
        # musubi_root_path. MUSUBI_ROOT is that + "/docs/operator".
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        session = make_session([
            make_pane("%0", "zsh", current_path=repo_root),
            make_pane("%1", "zsh", current_path=repo_root),
        ])
        assert classify_existing_session(session) == "orphan"

    def test_one_alive_one_shell_is_ambiguous(self):
        session = make_session([
            make_pane("%0", "claude"),
            make_pane("%1", "zsh"),
        ])
        assert classify_existing_session(session) == "ambiguous"

    def test_single_pane_is_ambiguous(self):
        session = make_session([make_pane("%0", "claude")])
        assert classify_existing_session(session) == "ambiguous"

    def test_zero_panes_is_ambiguous(self):
        session = make_session([])
        assert classify_existing_session(session) == "ambiguous"


# ---------------------------------------------------------------------------
# classify_existing_session — with Oya pane (3-pane configurations)
# ---------------------------------------------------------------------------

class TestClassifyWithOya:
    def test_pair_live_oya_live_is_live(self):
        session = make_session([
            make_pane("%0", "claude", current_path=MUSUBI_ROOT),  # Oya
            make_pane("%1", "claude", current_path="/Users/x/project"),  # Opus
            make_pane("%2", "codex", current_path="/Users/x/project"),   # Coda
        ])
        assert classify_existing_session(session) == "live"

    def test_pair_live_oya_dead_is_live(self):
        # Dead Oya pane in an otherwise-live session is still 'live'; Oya
        # re-spawns on attach.
        session = make_session([
            make_pane("%0", "zsh", current_path=MUSUBI_ROOT),  # Oya dead
            make_pane("%1", "claude", current_path="/Users/x/project"),
            make_pane("%2", "codex", current_path="/Users/x/project"),
        ])
        assert classify_existing_session(session) == "live"

    def test_pair_orphan_oya_alive_is_orphan(self):
        # Dead pair = orphan regardless of Oya state.
        session = make_session([
            make_pane("%0", "claude", current_path=MUSUBI_ROOT),  # Oya alive
            make_pane("%1", "zsh", current_path="/Users/x/project"),
            make_pane("%2", "zsh", current_path="/Users/x/project"),
        ])
        assert classify_existing_session(session) == "orphan"

    def test_partial_pair_with_oya_is_ambiguous(self):
        session = make_session([
            make_pane("%0", "claude", current_path=MUSUBI_ROOT),  # Oya
            make_pane("%1", "claude", current_path="/Users/x/project"),  # Opus alive
            make_pane("%2", "zsh", current_path="/Users/x/project"),     # Coda dead
        ])
        assert classify_existing_session(session) == "ambiguous"


# ---------------------------------------------------------------------------
# describe_session_panes
# ---------------------------------------------------------------------------

class TestDescribeSessionPanes:
    def test_returns_id_command_shell_marker(self):
        session = make_session([
            make_pane("%0", "claude"),
            make_pane("%1", "zsh"),
        ])
        descriptions = describe_session_panes(session)
        assert descriptions == [
            ("%0", "claude", False),
            ("%1", "zsh", True),
        ]

    def test_handles_empty_session(self):
        session = make_session([])
        assert describe_session_panes(session) == []

    def test_handles_exception_gracefully(self):
        session = MagicMock()
        # Simulate libtmux throwing on attribute access
        type(session).active_window = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("tmux gone"))
        )
        assert describe_session_panes(session) == []
