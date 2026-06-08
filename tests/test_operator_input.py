"""Tests for the operator-input relay (oyakata-11, the input half of the
operator console).

Covers the pure parse layer (splitting a freshly-appended span of
operator-input.md into per-submit messages) and the config gating + path
resolution in oyakata.py. The tmux split, the console read-loop, and the
send-keys relay into Oya's pane are side effects exercised by manual /
integration runs, not here.
"""
from oyakata import (
    parse_operator_input,
    operator_input_enabled,
    resolve_operator_input_path,
)


# --- parse_operator_input ---------------------------------------------------

def test_parses_single_entry():
    span = "\n**09:11 UTC — Operator:**\nset the SMH stop please\n"
    assert parse_operator_input(span) == ["set the SMH stop please"]


def test_parses_multiple_entries_in_order():
    span = (
        "\n**09:11 UTC — Operator:**\nfirst message\n"
        "\n**09:12 UTC — Operator:**\nsecond message\n"
    )
    assert parse_operator_input(span) == ["first message", "second message"]


def test_multiline_message_body_preserved():
    span = "\n**09:11 UTC — Operator:**\nline one\nline two\n"
    assert parse_operator_input(span) == ["line one\nline two"]


def test_preamble_before_first_header_ignored():
    # A read span that includes the file header (e.g. first read after seeding)
    # must not relay the preamble as a message — only real entries.
    span = (
        "# Operator Input\n\n> blurb\n\n---\n"
        "\n**09:11 UTC — Operator:**\nreal message\n"
    )
    assert parse_operator_input(span) == ["real message"]


def test_empty_and_headerless_return_empty():
    assert parse_operator_input("") == []
    assert parse_operator_input("just some text, no header\n") == []
    # A header with an empty body is dropped, not relayed as a blank message.
    assert parse_operator_input("\n**09:11 UTC — Operator:**\n\n") == []


def test_em_dash_header_exact_form():
    # The header uses an em dash (—), matching what operator-console.sh writes.
    # A hyphen-minus must NOT match (would split mid-message).
    span = "\n**09:11 UTC - Operator:**\nnot a real header\n"
    assert parse_operator_input(span) == []


# --- config gating + path resolution ---------------------------------------

def _cfg(oya=None, project_path="/tmp/proj"):
    agents = {"opus": {}, "coda": {}}
    if oya is not None:
        agents["oyakata"] = oya
    return {"project": {"path": project_path}, "agents": agents}


def test_enabled_defaults_on_when_oya_on():
    assert operator_input_enabled(_cfg(oya={"enabled": True})) is True


def test_disabled_when_oya_off():
    assert operator_input_enabled(_cfg(oya={"enabled": False})) is False
    assert operator_input_enabled(_cfg(oya=None)) is False


def test_explicit_opt_out():
    cfg = _cfg(oya={"enabled": True, "operator_input": False})
    assert operator_input_enabled(cfg) is False


def test_path_resolves_relative_to_project():
    cfg = _cfg(oya={"enabled": True}, project_path="/home/me/proj")
    assert resolve_operator_input_path(cfg) == "/home/me/proj/docs/agents/operator-input.md"


def test_path_absolute_passthrough():
    cfg = _cfg(oya={"enabled": True, "operator_input_path": "/abs/input.md"})
    assert resolve_operator_input_path(cfg) == "/abs/input.md"


def test_path_custom_relative():
    cfg = _cfg(oya={"enabled": True, "operator_input_path": "ops/in.md"},
               project_path="/p")
    assert resolve_operator_input_path(cfg) == "/p/ops/in.md"
