"""Integration tests for the relay pipeline.

Exercises the orchestrator's end-to-end flow without a real tmux:
  file content → parser → guards → relay decision → pane send_keys

Uses MagicMock panes that record send_keys calls so we can assert the
relay went to the right pane(s) with the right content. Pure functions
(parsing, guards) are already covered by test_parsing.py — this file
covers the integration glue that wires them together, which the
independent assessment flagged as untested.
"""

import os
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from comms import (
    capsule_is_stale,
    detect_sender,
    extract_last_message,
    is_idle_result,
    is_state_affecting,
    message_type,
    over_pattern,
    parse_result_field,
)
from collections import deque

from orchestrator import (
    relay_instruction,
    send_message,
    RECENTLY_RELAYED_WINDOW,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path):
    """Standard cfg with a temp project + comms file."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    comms_dir = project_dir / "docs" / "agents" / "comms"
    comms_dir.mkdir(parents=True)
    capsule_dir = project_dir / "docs" / "agents"
    capsule_path = capsule_dir / "current-state.md"
    capsule_path.write_text("# Capsule\n")
    return {
        "project": {"path": str(project_dir)},
        "agents": {
            "opus": {"name": "Opus", "handle": "@OPUS", "cli": "claude"},
            "coda": {"name": "Coda", "handle": "@CODA", "cli": "codex"},
        },
        "comms": {
            "file": str(comms_dir / "active.txt"),
            "over_signal": "<OVER>",
            "capsule": "docs/agents/current-state.md",
            "send_pause_seconds": 0.0,  # tests don't need real pauses
        },
        "tmux": {"session_name": "musubi-test"},
    }


@pytest.fixture
def panes():
    """Mock Opus + Coda panes. Each pane records its send_keys calls."""
    p_opus = MagicMock(name="opus_pane", pane_id="%0")
    p_coda = MagicMock(name="coda_pane", pane_id="%1")
    return p_opus, p_coda


def _message(sender_handle, body="Action: ship\nResult: completed\n", over="<OVER>"):
    """Build a syntactically valid comms message block."""
    return (
        "---------------------------------------------------\n"
        f"[{sender_handle}] [2026-05-19] [10:00 UTC]\n"
        "To: @PEER\n"
        "Type: Update\n"
        "\n"
        f"{body}"
        f"\n{over}\n"
    )


# ---------------------------------------------------------------------------
# Recently-relayed dedup window (re-read / shrink protection)
# ---------------------------------------------------------------------------

class TestRecentlyRelayedWindow:
    """The dedup window must be deep enough to cover a whole-cycle re-read.

    When something external truncates+rewrites active.txt mid-cycle, the
    watcher re-reads from offset 0 and re-drains every block; only blocks still
    inside this window are recognised as already-relayed and skipped. A
    too-small window (the original 8) re-relayed every older message — flooding
    Oya with the entire cycle on each shrink (field bug 2026-06-09). This guards
    the size from silently regressing back down.
    """

    def test_window_covers_a_realistic_cycle(self):
        # A busy cycle is hundreds of messages; 8 (the buggy value) is nowhere
        # near enough. Require a substantial floor.
        assert RECENTLY_RELAYED_WINDOW >= 500

    def test_full_reread_of_a_long_span_dedups_every_block(self):
        # Model the watcher's dedup: relay N(>old window) unique blocks, then a
        # shrink-triggered re-read of the SAME blocks must skip all of them.
        recently = deque(maxlen=RECENTLY_RELAYED_WINDOW)
        blocks = [_message("@OPUS", body=f"Action: step {i}\n") for i in range(300)]
        for b in blocks:
            assert b not in recently  # first pass — all new
            recently.append(b)
        # Re-read (offset reset to 0): every block already seen → none re-relays.
        re_relayed = [b for b in blocks if b not in recently]
        assert re_relayed == [], "a full re-read must not re-relay already-seen blocks"


# ---------------------------------------------------------------------------
# Relay decision matrix — who receives a message from whom?
# ---------------------------------------------------------------------------

class TestRelayDecisionMatrix:
    """relay_instruction routes messages by sender:
       OPUS → CODA only
       CODA → OPUS only
       OYAKATA → BOTH
    """

    def test_opus_message_relays_to_coda_only(self, cfg, panes):
        p_opus, p_coda = panes
        msg = _message("@OPUS")

        relay_instruction(msg, "OPUS", p_opus, p_coda, cfg)

        assert p_coda.send_keys.called, "Coda should receive Opus's message"
        assert not p_opus.send_keys.called, "Opus must NOT receive their own message back"

    def test_coda_message_relays_to_opus_only(self, cfg, panes):
        p_opus, p_coda = panes
        msg = _message("@CODA")

        relay_instruction(msg, "CODA", p_opus, p_coda, cfg)

        assert p_opus.send_keys.called, "Opus should receive Coda's message"
        assert not p_coda.send_keys.called, "Coda must NOT receive their own message back"

    def test_oyakata_message_relays_to_both(self, cfg, panes):
        p_opus, p_coda = panes
        msg = _message("@OYA")

        relay_instruction(msg, "OYAKATA", p_opus, p_coda, cfg)

        assert p_opus.send_keys.called, "Opus should receive Oya's message"
        assert p_coda.send_keys.called, "Coda should receive Oya's message"

    def test_unknown_sender_does_not_relay(self, cfg, panes):
        p_opus, p_coda = panes
        msg = _message("@OPUS")

        relay_instruction(msg, "UNKNOWN", p_opus, p_coda, cfg)

        assert not p_opus.send_keys.called
        assert not p_coda.send_keys.called

    def test_relay_includes_message_body(self, cfg, panes):
        p_opus, p_coda = panes
        msg = _message("@OPUS", body="Action: ship slice 5\nResult: completed\n")

        relay_instruction(msg, "OPUS", p_opus, p_coda, cfg)

        # send_message does send_keys(content, enter=False) then send_keys('', enter=True).
        # The first call contains the relayed content; verify the body shows up.
        first_call_args = p_coda.send_keys.call_args_list[0]
        relayed_text = first_call_args[0][0]
        assert "Action: ship slice 5" in relayed_text
        assert "Result: completed" in relayed_text
        assert "@OPUS" in relayed_text


# ---------------------------------------------------------------------------
# End-to-end: file → parse → relay
# ---------------------------------------------------------------------------

class TestFileToRelay:
    """The path a real comms event takes: write to file → parse → detect
    sender → relay. Skips the actual watcher loop (which is an infinite
    poll) but covers every other stage."""

    def test_full_round_trip_opus_to_coda(self, cfg, panes, tmp_path):
        p_opus, p_coda = panes
        comms_file = cfg["comms"]["file"]
        msg = _message("@OPUS", body="Action: implementing\nResult: started\n")

        # Simulate the agent writing to the comms file
        with open(comms_file, "w") as f:
            f.write(msg)

        # Watcher would now read new content
        with open(comms_file) as f:
            content = f.read()

        # Parse + detect + relay
        block = extract_last_message(content, cfg)
        assert block is not None, "should parse the message"
        sender = detect_sender(block, cfg)
        assert sender == "OPUS"

        relay_instruction(block, sender, p_opus, p_coda, cfg)
        assert p_coda.send_keys.called

    def test_bracket_variant_message_is_handled(self, cfg, panes, tmp_path):
        """Independent-review finding: [[@OPUS]] variant should be parsed,
        not silently dropped."""
        p_opus, p_coda = panes
        comms_file = cfg["comms"]["file"]
        # Double-bracket variant in the header
        msg = (
            "---------------------------------------------------\n"
            "[[@CODA]] [2026-05-19] [10:00 UTC]\n"
            "Type: Update\n"
            "\n"
            "Action: testing\nResult: completed\n"
            "\n<OVER>\n"
        )
        with open(comms_file, "w") as f:
            f.write(msg)
        with open(comms_file) as f:
            content = f.read()

        block = extract_last_message(content, cfg)
        assert block is not None, "[[@CODA]] should still parse (substring match)"
        sender = detect_sender(block, cfg)
        assert sender == "CODA", f"detect_sender should accept [[@CODA]], got {sender!r}"

        relay_instruction(block, sender, p_opus, p_coda, cfg)
        assert p_opus.send_keys.called

    def test_unparseable_content_returns_none(self, cfg):
        """No handle in content → extract returns None (caller's retry loop
        handles the skip)."""
        content = "some random text without handle or sentinel"
        assert extract_last_message(content, cfg) is None

    def test_missing_over_returns_none(self, cfg):
        """Handle present but no <OVER> → not a complete message."""
        content = "[@OPUS] hello but no over sentinel"
        assert extract_last_message(content, cfg) is None


# ---------------------------------------------------------------------------
# Guard logic — ack-of-ack streak detection
# ---------------------------------------------------------------------------

class TestAckOfAckGuard:
    """3 consecutive idle results should be detectable by the watcher.
    The actual streak counter lives in watch_and_relay; we test the
    underlying classification used to increment it."""

    def test_idle_results_classify_idle(self):
        assert is_idle_result("not started")
        assert is_idle_result("nothing claimed")
        assert is_idle_result("idle")
        assert is_idle_result("holding")
        assert is_idle_result("no slice")
        assert is_idle_result("awaiting review")
        assert is_idle_result("claimed")  # bare claimed = idle for streak

    def test_active_results_do_not_classify_idle(self):
        assert not is_idle_result("started")
        assert not is_idle_result("completed")
        assert not is_idle_result("spawned")
        assert not is_idle_result("confirmed_running")

    def test_three_idle_messages_in_sequence(self, cfg):
        """Build a chain of three idle messages and verify each parses as
        idle. The watcher's streak counter combines these into the guard
        decision."""
        idle_results = []
        for handle in ("@OPUS", "@CODA", "@OPUS"):
            msg = _message(handle, body="Action: waiting\nResult: holding\n")
            block = extract_last_message(msg, cfg)
            assert block is not None
            result = parse_result_field(block)
            idle_results.append(is_idle_result(result))
        assert all(idle_results), "three consecutive idle results should all classify idle"


# ---------------------------------------------------------------------------
# Guard logic — capsule-staleness
# ---------------------------------------------------------------------------

class TestCapsuleStalenessGuard:
    """State-affecting messages (Review Request / Decision / Blocker) require
    the capsule to have been touched within 120s of the message."""

    def test_fresh_capsule_passes(self, cfg):
        """Capsule just modified (test fixture writes it on setup) → not stale."""
        assert not capsule_is_stale(cfg), "freshly-created capsule should not be stale"

    def test_state_affecting_types_classify_correctly(self):
        assert is_state_affecting("Review Request")
        assert is_state_affecting("Decision")
        assert is_state_affecting("Blocker")
        assert not is_state_affecting("Update")
        assert not is_state_affecting("Note")
        assert not is_state_affecting("Recommendation")

    def test_message_type_extraction(self, cfg):
        msg = (
            "[@OPUS] [2026-05-19] [10:00 UTC]\n"
            "Type: Review Request\n"
            "Subject: slice 5 ready\n"
            "\n"
            "Action: reviewed\nResult: changes_requested\n"
            "<OVER>"
        )
        assert message_type(msg) == "Review Request"
        assert is_state_affecting(message_type(msg))

    def test_stale_capsule_detected(self, cfg, tmp_path):
        """Backdate the capsule mtime to > 120s ago → should classify stale."""
        from comms import capsule_path
        cpath = capsule_path(cfg)
        old_time = time.time() - 200  # 200s ago, > 120s window
        os.utime(cpath, (old_time, old_time))
        assert capsule_is_stale(cfg), "200s-old capsule should classify stale"


# ---------------------------------------------------------------------------
# send_message — the tmux-side dispatch
# ---------------------------------------------------------------------------

class TestSendMessage:
    """send_message does two-step send: content with enter=False, then
    empty with enter=True. Verifies the pattern that fixes Claude's
    long-paste behaviour."""

    def test_two_step_send_pattern(self, cfg, panes):
        p_opus, _ = panes
        send_message(p_opus, "hello world", cfg)

        assert p_opus.send_keys.call_count == 2
        # First call: content, no enter
        first = p_opus.send_keys.call_args_list[0]
        assert first[0][0] == "hello world"
        assert first[1].get("enter") is False
        # Second call: empty string with enter=True
        second = p_opus.send_keys.call_args_list[1]
        assert second[0][0] == ""
        assert second[1].get("enter") is True

    def test_send_message_accepts_no_cfg(self, panes):
        """cfg is optional — utility callers can omit it."""
        p_opus, _ = panes
        send_message(p_opus, "ping")  # should not raise
        assert p_opus.send_keys.called


# ---------------------------------------------------------------------------
# Codex review findings — regression tests
# ---------------------------------------------------------------------------

class TestOyaMessageParsing:
    """P1.1 (Codex 2026-05-19): extract_last_message previously hardcoded
    @OPUS / @CODA handle checks and dropped @OYA-only messages silently.
    Fixed to iterate all configured handles."""

    def test_oya_only_message_with_no_pair_handles_parses(self, cfg):
        """A minimal Oya message addressed to @LEAD (no @OPUS/@CODA in body)
        must parse — previously returned None."""
        # Add Oya to cfg
        cfg["agents"]["oyakata"] = {"name": "Oya", "handle": "@OYA", "enabled": True}
        msg = (
            "[@OYA] [2026-05-19] [10:00 UTC]\n"
            "To: @LEAD\n"
            "Type: Note\n"
            "\n"
            "Heads-up only. No action required.\n"
            "\n<OVER>"
        )
        block = extract_last_message(msg, cfg)
        assert block is not None, "P1.1 regression: @OYA-only message dropped"
        assert detect_sender(block, cfg) == "OYAKATA"

    def test_oya_unconfigured_still_rejects_oya_message(self, cfg):
        """When Oya is NOT configured, @OYA-only messages should still be
        rejected (Oya isn't a participant in this session)."""
        msg = "[@OYA] hello <OVER>"
        # cfg has no oyakata entry
        assert extract_last_message(msg, cfg) is None


class TestStateTransitionGuard:
    """P2.2 (Codex 2026-05-19): capsule-staleness guard was hardcoded to
    Review Request / Decision / Blocker types. Updates reporting state
    transitions (Result=started/blocked/completed) bypassed the guard.
    Fixed: is_state_affecting now also fires on six-state-vocab Results."""

    def test_update_with_started_is_state_affecting(self):
        msg = (
            "[@OPUS] [date]\n"
            "Type: Update\n"
            "\n"
            "Action: implementing slice 5\n"
            "Result: started\n"
            "\n<OVER>"
        )
        assert is_state_affecting("Update", msg) is True

    def test_update_with_completed_is_state_affecting(self):
        msg = "Result: completed\n<OVER>"
        assert is_state_affecting("Update", msg) is True

    def test_update_with_blocked_and_reason_is_state_affecting(self):
        """Tolerant of qualifying text after the state word."""
        msg = "Result: blocked — waiting on @LEAD review\n<OVER>"
        assert is_state_affecting("Update", msg) is True

    def test_update_with_holding_is_not_state_affecting(self):
        """Idle Results don't trigger the guard."""
        msg = "Result: holding\n<OVER>"
        assert is_state_affecting("Update", msg) is False

    def test_review_request_still_state_affecting_with_no_block(self):
        """Backward compat: Type-only call signature still works."""
        assert is_state_affecting("Review Request") is True
        assert is_state_affecting("Review Request", None) is True

    def test_update_with_no_result_is_not_state_affecting(self):
        msg = "Type: Update\n\nAction: thinking out loud\n<OVER>"
        assert is_state_affecting("Update", msg) is False


class TestOyaSpawnEnvironmentPropagation:
    """P1.2 (Codex 2026-05-19): orchestrator must pass MUSUBI_ROOT to
    attach-oya.sh so the script can find its prompt file regardless of
    where the user cloned the repo. attach-oya.sh defaults to
    ~/Dev/musubi.repo; orchestrator.py lives wherever the user cloned."""

    def test_spawn_oya_passes_musubi_root_in_env(self, cfg, tmp_path):
        """Verify spawn_oya_if_enabled includes MUSUBI_ROOT in the env it
        passes to subprocess.Popen."""
        from unittest.mock import patch, MagicMock
        from oyakata import spawn_oya_if_enabled
        import os
        import oyakata as oyakata_module

        # Enable Oya in cfg
        cfg["agents"]["oyakata"] = {"name": "Oya", "handle": "@OYA", "enabled": True}

        # Build a fake session with no existing Oya pane (so spawn proceeds)
        session = MagicMock()
        session.active_window.panes = []  # no panes yet → no idempotency hit
        session.name = "test-session"

        # Find the actual orchestrator dir (where the spawn script lives)
        import orchestrator
        expected_root = os.path.dirname(os.path.abspath(orchestrator.__file__))

        # Patch Popen so we can inspect the env without actually running anything
        with patch.object(oyakata_module, "subprocess") as mock_subprocess:
            mock_subprocess.Popen = MagicMock()
            # Also patch the post-spawn wait loop so we don't sit for 30s
            with patch.object(oyakata_module, "discover_oyakata_pane",
                              side_effect=[None, MagicMock()]):
                spawn_oya_if_enabled(cfg, "musubi.toml", session)

        assert mock_subprocess.Popen.called, "Popen should have been called"
        _args, kwargs = mock_subprocess.Popen.call_args
        env = kwargs.get("env", {})
        assert env.get("MUSUBI_ROOT") == expected_root, (
            f"MUSUBI_ROOT not propagated; got {env.get('MUSUBI_ROOT')!r}, "
            f"expected {expected_root!r}"
        )
        assert env.get("OYA_QUIET_BANNER") == "1"
        assert env.get("MUSUBI_SESSION") == "test-session"


# ---------------------------------------------------------------------------
# Watcher resume offset (orphan-tail field bug, okami bed 2026-06-11)
# ---------------------------------------------------------------------------

class TestResumeOffset:
    """A watcher that (re)starts on a live comms file must resume just past
    the last over-signal, not at raw EOF. Raw EOF lands mid-message whenever
    an agent is mid-append at boot: the head is never read and the tail is
    later quarantined as an `_unparseable_` sidecar — four orphaned tails on
    the okami bed in one morning of --attach relaunches (2026-06-11)."""

    def test_missing_file_is_zero(self, cfg):
        from comms import resume_offset
        assert resume_offset(cfg["comms"]["file"] + ".nope", cfg) == 0

    def test_no_over_signal_falls_back_to_eof(self, cfg):
        """Preamble-only file (no over yet): EOF, same as old behaviour —
        nothing in-flight to protect, and re-reading an unparseable preamble
        would churn the quarantine path."""
        from comms import resume_offset
        path = cfg["comms"]["file"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("# comms preamble, no messages yet\n")
        assert resume_offset(path, cfg) == os.path.getsize(path)

    def test_complete_file_resumes_at_eof(self, cfg):
        """All messages closed: last over end == EOF region (trailing
        newline after it may remain unread — it must be <= EOF and past
        the final over token)."""
        from comms import resume_offset
        path = cfg["comms"]["file"]
        content = _message("@OPUS") + _message("@CODA")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        off = resume_offset(path, cfg)
        consumed = content.encode("utf-8")[:off].decode("utf-8")
        assert consumed.rstrip().endswith("<OVER>")
        assert content[len(consumed):].strip() == ""

    def test_mid_compose_tail_is_preserved(self, cfg):
        """The regression case: agent mid-append at boot. Resume offset must
        sit at the end of the LAST COMPLETE message so the partial head is
        re-read together with its tail when the over-signal lands."""
        from comms import resume_offset, read_new_content, extract_messages
        path = cfg["comms"]["file"]
        complete = _message("@OPUS")
        partial_head = (
            "---------------------------------------------------\n"
            "[@CODA] [2026-06-11] [09:54 UTC]\n"
            "To: @OPUS\n"
            "Type: Update\n"
            "\n"
            "Action: SPEC planni"  # mid-word, exactly like the field artefact
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(complete + partial_head)
        off = resume_offset(path, cfg)
        # Old behaviour: off == EOF → partial head skipped, tail orphaned.
        assert off < os.path.getsize(path), "must not resume at raw EOF"
        # The whole partial head is still ahead of the offset (plus the
        # newline that trailed the previous over-signal).
        assert read_new_content(path, off) == "\n" + partial_head
        # When the tail + over-signal arrive, the message parses whole.
        with open(path, "a", encoding="utf-8") as f:
            f.write("ng note lands in SPEC.md\n<OVER>\n")
        blocks, _ = extract_messages(read_new_content(path, off), cfg)
        assert len(blocks) == 1
        assert "SPEC planning note lands in SPEC.md" in blocks[0]

    def test_multibyte_content_offset_is_byte_accurate(self, cfg):
        """Em-dashes etc. before the last over-signal must not skew the byte
        offset (the watcher seeks in bytes)."""
        from comms import resume_offset, read_new_content
        path = cfg["comms"]["file"]
        complete = _message("@OPUS", body="Result: pass — approved — clean\n")
        partial = "[@CODA] [2026-06-11] [10:07 UTC]\nEverything from"
        with open(path, "w", encoding="utf-8") as f:
            f.write(complete + partial)
        off = resume_offset(path, cfg)
        assert read_new_content(path, off) == "\n" + partial


# ---------------------------------------------------------------------------
# Operator handle carry-through ([operator].handle, field report 2026-06-12)
# ---------------------------------------------------------------------------

class TestOperatorHandle:
    """Sessions were defaulting to @LEAD even when the bed names its operator.
    [operator].handle in musubi.toml must carry through everything the
    orchestrator and Oya emit about the operator at runtime."""

    def test_default_is_lead(self, cfg):
        from comms import operator_handle
        assert operator_handle(cfg) == "@LEAD"

    def test_configured_handle_wins(self, cfg):
        from comms import operator_handle
        cfg["operator"] = {"handle": "@MICHI", "name": "Michi"}
        assert operator_handle(cfg) == "@MICHI"

    def test_missing_at_prefix_is_tolerated(self, cfg):
        from comms import operator_handle
        cfg["operator"] = {"handle": "MICHI"}
        assert operator_handle(cfg) == "@MICHI"

    def test_blank_handle_falls_back(self, cfg):
        from comms import operator_handle
        cfg["operator"] = {"handle": "   "}
        assert operator_handle(cfg) == "@LEAD"

    def test_operator_input_relay_uses_configured_handle(self, cfg, panes):
        """The console-message relay instruction Oya receives must name the
        configured operator, not the @LEAD role default."""
        from oyakata import relay_operator_input_to_oyakata
        cfg["operator"] = {"handle": "@MICHI"}
        cfg["comms"]["send_pause_seconds"] = 0.0
        p_oya, _ = panes
        relay_operator_input_to_oyakata("status?", p_oya, cfg)
        sent = " ".join(
            str(c.args[0]) for c in p_oya.send_keys.call_args_list if c.args
        )
        assert "@MICHI" in sent
        assert "@LEAD" not in sent

    def test_spawn_env_carries_operator_handle(self, cfg):
        """spawn_oya_if_enabled must export MUSUBI_OPERATOR_HANDLE so
        attach-oya.sh can substitute the prompt's @LEAD references."""
        from unittest.mock import patch, MagicMock
        import oyakata as oyakata_module
        from oyakata import spawn_oya_if_enabled

        cfg["agents"]["oyakata"] = {"name": "Oya", "handle": "@OYA", "enabled": True}
        cfg["operator"] = {"handle": "@MICHI"}
        session = MagicMock()
        session.active_window.panes = []
        session.name = "test-session"

        with patch.object(oyakata_module, "subprocess") as mock_subprocess:
            mock_subprocess.Popen = MagicMock()
            with patch.object(oyakata_module, "discover_oyakata_pane",
                              side_effect=[None, MagicMock()]):
                spawn_oya_if_enabled(cfg, "musubi.toml", session)

        assert mock_subprocess.Popen.called
        _args, kwargs = mock_subprocess.Popen.call_args
        assert kwargs.get("env", {}).get("MUSUBI_OPERATOR_HANDLE") == "@MICHI"
