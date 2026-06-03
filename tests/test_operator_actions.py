"""Tests for the operator-action surface.

Covers the pure parse/format layer in comms.py (the operator-actions capsule)
and the config gating + path resolution in oyakata.py. The tmux status-bar
write and the desktop notification are side effects exercised by manual
integration runs, not here.
"""
import pytest

from comms import parse_operator_actions, format_actions_status
from oyakata import operator_actions_enabled, resolve_operator_actions_path


# --- parse_operator_actions -------------------------------------------------

def test_parses_pending_unchecked_items():
    text = """\
# Operator Actions

## Pending

- [ ] **Set SMH trailing stop @ $113.95 in T212** — _asked 2026-06-03 09:11 UTC · Cycle 4_
      Full position 0.9361 sh. Reply "stop is set" when done.

- [ ] **Approve the prod deploy** — _asked 09:20 UTC_

## Resolved

- [x] **Set VST stop @ $148** — _resolved 09:05_
"""
    pending = parse_operator_actions(text)
    assert len(pending) == 2
    assert pending[0]["summary"] == "Set SMH trailing stop @ $113.95 in T212"
    assert pending[1]["summary"] == "Approve the prod deploy"


def test_resolved_items_excluded():
    text = "- [x] **done thing** — _resolved_\n- [ ] **open thing**\n"
    pending = parse_operator_actions(text)
    assert [a["summary"] for a in pending] == ["open thing"]


def test_empty_or_no_pending_returns_empty():
    assert parse_operator_actions("") == []
    assert parse_operator_actions("# Operator Actions\n\n## Pending\n\n## Resolved\n") == []
    # HTML-comment example rows (as in the template) are not checkbox lines.
    assert parse_operator_actions("<!-- - [ ] example -->\n") == []


def test_continuation_detail_is_not_a_separate_action():
    text = """\
- [ ] **Do the thing** — _asked now_
      this is detail, deeply indented, not its own checkbox
      - [ ] this nested checkbox is detail, not a top-level action
"""
    pending = parse_operator_actions(text)
    assert len(pending) == 1
    assert pending[0]["summary"] == "Do the thing"


def test_key_is_stable_across_bold_and_whitespace():
    a = parse_operator_actions("- [ ] **Set   the  stop**\n")[0]
    b = parse_operator_actions("- [ ] Set the stop\n")[0]
    assert a["key"] == b["key"]


def test_summary_strips_trailing_metadata():
    # em-dash, en-dash, and double-hyphen separators all trim the metadata tail.
    for sep in (" — ", " – ", " -- ", " - "):
        text = f"- [ ] **Approve deploy**{sep}_asked 09:20_\n"
        assert parse_operator_actions(text)[0]["summary"] == "Approve deploy"


def test_asterisk_bullets_supported():
    assert parse_operator_actions("* [ ] **starred item**\n")[0]["summary"] == "starred item"


# --- format_actions_status --------------------------------------------------

def test_status_empty_when_no_pending():
    assert format_actions_status([]) == ""


def test_status_single_action():
    pending = parse_operator_actions("- [ ] **Set the stop @ $113.95**\n")
    assert format_actions_status(pending) == "⚑ AWAITING YOU: Set the stop @ $113.95"


def test_status_multiple_actions_shows_count_and_first():
    pending = parse_operator_actions(
        "- [ ] **First thing**\n- [ ] **Second thing**\n- [ ] **Third thing**\n"
    )
    status = format_actions_status(pending)
    assert status == "⚑ 3 AWAITING YOU: First thing (+2 more)"


# --- config gating + path resolution ---------------------------------------

def _cfg(oya=None, project_path="/tmp/proj"):
    agents = {"opus": {}, "coda": {}}
    if oya is not None:
        agents["oyakata"] = oya
    return {"project": {"path": project_path}, "agents": agents}


def test_enabled_defaults_on_when_oya_on():
    assert operator_actions_enabled(_cfg(oya={"enabled": True})) is True


def test_disabled_when_oya_off():
    assert operator_actions_enabled(_cfg(oya={"enabled": False})) is False
    assert operator_actions_enabled(_cfg(oya=None)) is False


def test_explicit_opt_out():
    cfg = _cfg(oya={"enabled": True, "operator_actions": False})
    assert operator_actions_enabled(cfg) is False


def test_path_resolves_relative_to_project():
    cfg = _cfg(oya={"enabled": True}, project_path="/home/me/proj")
    assert resolve_operator_actions_path(cfg) == "/home/me/proj/docs/agents/operator-actions.md"


def test_path_absolute_passthrough():
    cfg = _cfg(oya={"enabled": True, "operator_actions_path": "/abs/actions.md"})
    assert resolve_operator_actions_path(cfg) == "/abs/actions.md"


def test_path_custom_relative():
    cfg = _cfg(oya={"enabled": True, "operator_actions_path": "ops/todo.md"},
               project_path="/p")
    assert resolve_operator_actions_path(cfg) == "/p/ops/todo.md"
