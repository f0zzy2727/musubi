"""Tests for parsing functions in orchestrator.py.

These functions are pure (no tmux dependency, no filesystem) so they can be
tested directly. Other orchestrator behaviour — session lifecycle, file I/O,
relay dispatch — needs tmux and is exercised by manual integration runs.
"""
import pytest

from orchestrator import (
    CAPSULE_FRESHNESS_WINDOW_SECONDS,
    ConfigError,
    capsule_is_stale,
    capsule_path,
    detect_sender,
    detect_writer_from_buffer,
    extract_last_message,
    extract_messages,
    is_idle_result,
    is_state_affecting,
    message_type,
    over_pattern,
    parse_result_field,
    read_new_content,
    validate_cli_available,
    validate_config,
)


def make_cfg(over_signal="<OVER>"):
    """Build a config dict in the shape orchestrator functions expect."""
    return {
        "comms": {"over_signal": over_signal},
        "agents": {
            "opus": {"handle": "@OPUS"},
            "coda": {"handle": "@CODA"},
        },
    }


class TestOverPattern:
    """over_pattern produces a regex accepting variants of the OVER sentinel."""

    @pytest.mark.parametrize(
        "text",
        [
            "<OVER>",
            "</OVER>",
            "<over>",
            "<Over>",
            "< OVER >",
            "<OVER/>",
            "<OVER />",
            "< / OVER >",
            "<over />",
        ],
    )
    def test_accepts_variant(self, text):
        assert over_pattern("<OVER>").search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "OVER",
            "<OVERFLOW>",
            "<OVE R>",
            "this message ends without the sentinel",
            "<>OVER<>",
        ],
    )
    def test_rejects_non_match(self, text):
        assert over_pattern("<OVER>").search(text) is None

    def test_custom_sentinel(self):
        pat = over_pattern("<DONE>")
        assert pat.search("<done>") is not None
        assert pat.search("<OVER>") is None


class TestDetectSender:
    """detect_sender picks the earliest bracketed handle in the block."""

    def test_opus_sender(self):
        block = (
            "[@OPUS] [2026-05-14] [10:00 UTC]\n"
            "Type: Update\n"
            "@CODA your turn\n"
            "<OVER>"
        )
        assert detect_sender(block, make_cfg()) == "OPUS"

    def test_coda_sender(self):
        block = (
            "[@CODA] [2026-05-14] [10:00 UTC]\n"
            "Type: Update\n"
            "@OPUS your turn\n"
            "<OVER>"
        )
        assert detect_sender(block, make_cfg()) == "CODA"

    def test_bare_handle_in_body_does_not_flip_sender(self):
        """A bare @CODA in the body must not flip the sender from OPUS.

        The sender wraps their own handle in brackets in the header. The body
        addresses the peer with a bare @HANDLE. A naive matcher that accepts
        either form would misidentify the sender.
        """
        block = (
            "[@OPUS] [2026-05-14] [10:00 UTC]\n"
            "Type: Review Request\n"
            "@CODA, I reviewed your patch — the issue [@CODA] flagged earlier still holds.\n"
            "<OVER>"
        )
        # [@OPUS] is at index 0; [@CODA] appears later. Earliest wins.
        assert detect_sender(block, make_cfg()) == "OPUS"

    def test_no_handle_returns_none(self):
        assert detect_sender("Just some text\n<OVER>", make_cfg()) is None

    def test_empty_or_none_block_returns_none(self):
        assert detect_sender("", make_cfg()) is None
        assert detect_sender(None, make_cfg()) is None


class TestExtractLastMessage:
    """extract_last_message returns the most recent valid block in the buffer."""

    SEP = "---------------------------------------------------"

    def test_single_block(self):
        content = (
            f"{self.SEP}\n"
            "[@OPUS] [2026-05-14] [10:00 UTC]\n"
            "Action: did the thing\n"
            "<OVER>\n"
        )
        result = extract_last_message(content, make_cfg())
        assert result is not None
        assert "@OPUS" in result
        assert "<OVER>" in result

    def test_picks_last_of_multiple(self):
        content = (
            f"{self.SEP}\n"
            "[@OPUS] first message\n<OVER>\n"
            f"{self.SEP}\n"
            "[@CODA] second message\n<OVER>\n"
        )
        result = extract_last_message(content, make_cfg())
        assert result is not None
        assert "second message" in result
        assert "first message" not in result

    def test_returns_none_when_no_over(self):
        content = "[@OPUS] half-written message with no sentinel"
        assert extract_last_message(content, make_cfg()) is None

    def test_returns_none_when_no_handle(self):
        content = f"{self.SEP}\nSome random text\n<OVER>\n"
        assert extract_last_message(content, make_cfg()) is None

    def test_falls_back_to_whole_buffer_without_separator(self):
        """If the buffer has no separator but does have a handle + <OVER>,
        extract_last_message returns the trimmed buffer."""
        content = "[@CODA] no separator here\nstill a real message\n<OVER>\n"
        result = extract_last_message(content, make_cfg())
        assert result is not None
        assert "@CODA" in result


class TestExtractMessages:
    """extract_messages drains EVERY complete block in write order.

    Regression suite for the 2026-06-06 field-diagnosed relay drops: the
    last-block-only predecessor silently discarded every earlier message
    whenever 2+ posts landed in one watcher read window, and the
    advance-to-EOF offset jumped over still-composing partial tails."""

    SEP = "---------------------------------------------------"

    def test_returns_all_blocks_in_write_order(self):
        content = (
            f"{self.SEP}\n"
            "[@OPUS] first message\n<OVER>\n"
            f"{self.SEP}\n"
            "[@CODA] second message\n<OVER>\n"
            f"{self.SEP}\n"
            "[@OPUS] third message\n<OVER>\n"
        )
        blocks, consumed = extract_messages(content, make_cfg())
        assert len(blocks) == 3
        assert "first message" in blocks[0]
        assert "second message" in blocks[1]
        assert "third message" in blocks[2]

    def test_burst_without_separators_still_splits_on_over(self):
        """Message boundaries are the over-signal, not the cosmetic separator —
        agents that skip the dash line must not get their messages merged."""
        content = (
            "[@OPUS] reply A\n<OVER>\n"
            "[@CODA] reply B\n<OVER>\n"
        )
        blocks, _ = extract_messages(content, make_cfg())
        assert len(blocks) == 2
        assert "reply A" in blocks[0] and "reply B" not in blocks[0]
        assert "reply B" in blocks[1] and "reply A" not in blocks[1]

    def test_consumed_stops_at_last_complete_block(self):
        """A still-composing partial tail is NOT consumed — the watcher must
        re-read it next tick rather than jump the offset past it."""
        complete = "[@OPUS] done part\n<OVER>\n"
        partial = "[@CODA] half-written, no sentinel yet"
        content = complete + partial
        blocks, consumed = extract_messages(content, make_cfg())
        assert len(blocks) == 1
        tail = content[consumed:]
        assert "half-written" in tail
        assert "<OVER>" not in tail

    def test_junk_over_span_dropped_but_consumed(self):
        """An over-closed span with no recognised handle is noise: excluded
        from the block list but still counted as consumed so the watcher
        doesn't spin on it forever."""
        junk = "stray paste with no handle\n<OVER>\n"
        real = "[@CODA] real message\n<OVER>\n"
        content = junk + real
        blocks, consumed = extract_messages(content, make_cfg())
        assert len(blocks) == 1
        assert "real message" in blocks[0]
        assert consumed >= content.rindex("<OVER>")

    def test_empty_and_no_over_content(self):
        assert extract_messages("", make_cfg()) == ([], 0)
        blocks, consumed = extract_messages(
            "[@OPUS] composing, not finished", make_cfg())
        assert blocks == [] and consumed == 0

    def test_oya_block_recognised(self):
        cfg = make_cfg()
        cfg["agents"]["oyakata"] = {"handle": "@OYA"}
        content = "[@OYA] Note for the pair\n<OVER>\n"
        blocks, _ = extract_messages(content, cfg)
        assert len(blocks) == 1 and "@OYA" in blocks[0]

    def test_last_message_parity(self):
        """extract_last_message must agree with extract_messages[-1]."""
        content = (
            f"{self.SEP}\n[@OPUS] one\n<OVER>\n"
            f"{self.SEP}\n[@CODA] two\n<OVER>\n"
        )
        blocks, _ = extract_messages(content, make_cfg())
        assert extract_last_message(content, make_cfg()) == blocks[-1]

    def test_verbatim_duplicate_blocks_both_returned(self):
        """Two identical posts are two messages — dedup is the watcher's
        recently-relayed memory's job (and refusals must not poison it),
        not the parser's."""
        msg = "[@OPUS] same text\n<OVER>\n"
        blocks, _ = extract_messages(msg + msg, make_cfg())
        assert len(blocks) == 2
        assert blocks[0] == blocks[1]


class TestDetectWriterFromBuffer:
    """detect_writer_from_buffer picks the LATEST bracketed handle.

    Distinct from detect_sender: used during stall detection when an agent has
    written part of a message but not yet appended <OVER>. The most recent
    bracketed handle is the writer who is currently composing.
    """

    def test_picks_latest_handle(self):
        buf = (
            "[@OPUS] earlier message\n<OVER>\n"
            "---\n"
            "[@CODA] writing now..."
        )
        assert detect_writer_from_buffer(buf, make_cfg()) == "CODA"

    def test_single_writer(self):
        assert detect_writer_from_buffer("[@OPUS] composing\n", make_cfg()) == "OPUS"

    def test_no_handle_returns_none(self):
        assert detect_writer_from_buffer("just text", make_cfg()) is None


def good_cfg():
    """Minimum-valid musubi.toml structure, as a dict."""
    return {
        "project": {"path": "/tmp/proj"},
        "agents": {
            "opus": {"name": "Opus", "handle": "@OPUS", "cli": "claude"},
            "coda": {"name": "Coda", "handle": "@CODA", "cli": "codex"},
        },
        "comms": {"file": "docs/agents/comms/active.txt", "over_signal": "<OVER>"},
        "tmux": {"session_name": "musubi"},
    }


class TestValidateConfig:
    """validate_config raises ConfigError with a dotted path on the first
    missing key, wrong type, or empty string."""

    def test_good_config_passes(self):
        validate_config(good_cfg())  # no raise

    def test_optional_keys_allowed(self):
        cfg = good_cfg()
        cfg["comms"]["runbook"] = "docs/agents/AGENT_COLLAB_RUNBOOK.md"
        cfg["comms"]["stall_seconds"] = 60
        validate_config(cfg)  # extras are fine

    @pytest.mark.parametrize("section", ["project", "agents", "comms", "tmux"])
    def test_missing_top_level_section(self, section):
        cfg = good_cfg()
        del cfg[section]
        with pytest.raises(ConfigError, match=section):
            validate_config(cfg)

    def test_missing_agent_handle(self):
        cfg = good_cfg()
        del cfg["agents"]["coda"]["handle"]
        with pytest.raises(ConfigError, match=r"agents\.coda\.handle"):
            validate_config(cfg)

    def test_missing_project_path(self):
        cfg = good_cfg()
        del cfg["project"]["path"]
        with pytest.raises(ConfigError, match=r"project\.path"):
            validate_config(cfg)

    def test_empty_string_rejected(self):
        cfg = good_cfg()
        cfg["project"]["path"] = ""
        with pytest.raises(ConfigError, match="empty"):
            validate_config(cfg)

    def test_whitespace_only_rejected(self):
        cfg = good_cfg()
        cfg["tmux"]["session_name"] = "   "
        with pytest.raises(ConfigError, match="empty"):
            validate_config(cfg)

    def test_wrong_type_rejected(self):
        cfg = good_cfg()
        cfg["tmux"]["session_name"] = 42
        with pytest.raises(ConfigError, match=r"tmux\.session_name"):
            validate_config(cfg)

    def test_non_dict_top_level(self):
        with pytest.raises(ConfigError, match="top-level"):
            validate_config("not a dict")

    def test_agents_not_a_table(self):
        cfg = good_cfg()
        cfg["agents"] = ["opus", "coda"]
        with pytest.raises(ConfigError, match="agents"):
            validate_config(cfg)


class TestValidateCliAvailable:
    """validate_cli_available is a thin shutil.which wrapper that raises
    ConfigError when the CLI isn't on PATH."""

    def test_command_on_path(self):
        validate_cli_available("python3")  # exists wherever this test runs

    def test_missing_command_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            validate_cli_available("definitely-not-a-real-command-xyz123")


class TestParseResultField:
    """parse_result_field pulls the Result line value out of a message block."""

    def test_extracts_simple_result(self):
        msg = "[@OPUS] [2026-05-14] [10:00 UTC]\nType: Update\nResult:\ncompleted\n<OVER>"
        # Result field can be on its own line followed by content; test the
        # single-line form which is the common shape.
        msg2 = "[@OPUS] [2026-05-14] [10:00 UTC]\nResult: completed\n<OVER>"
        assert parse_result_field(msg2) == "completed"

    def test_extracts_multiword(self):
        msg = "Result: NOT STARTED — awaiting tasking from @LEAD"
        assert parse_result_field(msg) == "NOT STARTED — awaiting tasking from @LEAD"

    def test_missing_field_returns_none(self):
        assert parse_result_field("Type: Update\nNo result here\n<OVER>") is None

    def test_empty_or_none_returns_none(self):
        assert parse_result_field("") is None
        assert parse_result_field(None) is None


class TestIsIdleResult:
    """is_idle_result classifies Result values for ack-of-ack streak detection."""

    @pytest.mark.parametrize(
        "result",
        [
            "NOT STARTED",
            "not started",
            "NOT STARTED — awaiting tasking",
            "idle",
            "Holding for @LEAD",
            "no slice claimed",
            "awaiting cycle kickoff",
            "claimed",  # bare claimed with no transition
            "Claimed",
            None,  # missing field treated as idle
            "",
        ],
    )
    def test_classified_as_idle(self, result):
        assert is_idle_result(result) is True

    @pytest.mark.parametrize(
        "result",
        [
            "started",
            "completed",
            "spawned (pid 4711)",
            "blocked — waiting on schema decision",
            "confirmed_running",
            "pass — 5/5 tests green",
            "fail — type error on src/foo.ts:42",
        ],
    )
    def test_classified_as_active(self, result):
        assert is_idle_result(result) is False


class TestMessageType:
    """message_type extracts the Type field from a message block."""

    def test_extracts_review_request(self):
        msg = "[@OPUS] [2026-05-14] [10:00 UTC]\nType: Review Request\nSubject: x\n<OVER>"
        assert message_type(msg) == "Review Request"

    def test_extracts_decision(self):
        assert message_type("Type: Decision\nbody\n<OVER>") == "Decision"

    def test_missing_returns_none(self):
        assert message_type("[@OPUS] no type line here\n<OVER>") is None


class TestIsStateAffecting:
    """is_state_affecting identifies message types that require a fresh capsule."""

    @pytest.mark.parametrize(
        "msg_type",
        ["Review Request", "Decision", "Blocker", "review request", "DECISION"],
    )
    def test_state_affecting(self, msg_type):
        assert is_state_affecting(msg_type) is True

    @pytest.mark.parametrize(
        "msg_type",
        ["Update", "Status", "Review Result", "Correction", "Note", None, ""],
    )
    def test_not_state_affecting(self, msg_type):
        assert is_state_affecting(msg_type) is False


class TestCapsuleStaleness:
    """capsule_path resolution + capsule_is_stale freshness check."""

    def _make_cfg(self, project_path, capsule_rel="docs/agents/current-state.md"):
        return {
            "project": {"path": str(project_path)},
            "comms": {
                "file": "docs/agents/comms/active.txt",
                "over_signal": "<OVER>",
                "capsule": capsule_rel,
            },
            "agents": {
                "opus": {"name": "Opus", "handle": "@OPUS", "cli": "claude"},
                "coda": {"name": "Coda", "handle": "@CODA", "cli": "codex"},
            },
            "tmux": {"session_name": "musubi"},
        }

    def test_capsule_path_relative(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        assert capsule_path(cfg) == str(tmp_path / "docs/agents/current-state.md")

    def test_capsule_path_absolute_pass_through(self, tmp_path):
        cfg = self._make_cfg(tmp_path, capsule_rel="/absolute/path/capsule.md")
        assert capsule_path(cfg) == "/absolute/path/capsule.md"

    def test_absent_capsule_is_not_stale(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        # capsule doesn't exist → don't fail-closed
        assert capsule_is_stale(cfg) is False

    def test_fresh_capsule_is_not_stale(self, tmp_path):
        cfg = self._make_cfg(tmp_path)
        cap = tmp_path / "docs/agents/current-state.md"
        cap.parent.mkdir(parents=True)
        cap.write_text("capsule content")
        # Just-written capsule is well within the freshness window
        assert capsule_is_stale(cfg) is False

    def test_old_capsule_is_stale(self, tmp_path):
        import os
        cfg = self._make_cfg(tmp_path)
        cap = tmp_path / "docs/agents/current-state.md"
        cap.parent.mkdir(parents=True)
        cap.write_text("capsule content")
        # Backdate the file beyond the freshness window
        old = (CAPSULE_FRESHNESS_WINDOW_SECONDS + 30)
        import time as _time
        os.utime(str(cap), (_time.time() - old, _time.time() - old))
        assert capsule_is_stale(cfg) is True


class TestReadNewContent:
    """read_new_content handles missing files gracefully, reads from a given
    offset, and tolerates non-UTF-8 bytes without crashing the watcher."""

    def test_missing_file_returns_empty(self, tmp_path):
        assert read_new_content(str(tmp_path / "nope.txt"), 0) == ""

    def test_reads_full_file_from_zero(self, tmp_path):
        f = tmp_path / "comms.txt"
        f.write_text("hello world\nmore text\n")
        assert read_new_content(str(f), 0) == "hello world\nmore text\n"

    def test_reads_from_offset(self, tmp_path):
        f = tmp_path / "comms.txt"
        f.write_text("hello world\nmore text\n")
        # Skip past "hello " — offset 6 lands on 'w'.
        assert read_new_content(str(f), 6) == "world\nmore text\n"

    def test_invalid_utf8_does_not_raise(self, tmp_path):
        """A stray non-UTF-8 byte (e.g. from a terminal escape) must not take
        down the watcher. errors='replace' substitutes the bad bytes."""
        f = tmp_path / "comms.txt"
        f.write_bytes(b"hello\xff\xfeworld\n")
        result = read_new_content(str(f), 0)
        assert "hello" in result
        assert "world" in result
