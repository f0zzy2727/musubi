"""Tests for the operator-channel renderer (scripts/channel-view.py).

Covers the pure markdown-to-display transforms: header detection, rule lines,
inline-marker stripping, and word-wrap behaviour. The follow loop (file
tailing, re-open on truncation) is a side effect exercised by manual runs.
"""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "channel_view",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "channel-view.py"),
)
channel_view = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(channel_view)

strip_inline = channel_view.strip_inline
render_line = channel_view.render_line


# --- strip_inline -----------------------------------------------------------

def test_strips_bold_keeps_text():
    assert strip_inline("the **anti-snapback** guard") == "the anti-snapback guard"


def test_strips_italic_keeps_text():
    assert strip_inline("a *real* limit") == "a real limit"


def test_strips_code_backticks():
    assert strip_inline("see `operator-input.md` now") == "see operator-input.md now"


def test_strips_leading_heading_and_quote():
    assert strip_inline("## Section") == "Section"
    assert strip_inline("> quoted line") == "quoted line"


def test_double_star_not_confused_by_single():
    # A lone * mid-sentence (e.g. multiplication) must survive.
    assert strip_inline("3 * 4 = 12") == "3 * 4 = 12"


# --- render_line ------------------------------------------------------------

def test_header_line_rendered_without_asterisks():
    out = render_line("**08:46 UTC — Oya:**")
    assert "**" not in out
    assert "08:46 UTC — Oya:" in out


def test_rule_line_becomes_horizontal_rule():
    out = render_line("---")
    assert "-" not in out  # the markdown dashes are gone
    assert "─" in out      # replaced by a box-drawing rule


def test_blank_line_stays_blank():
    assert render_line("") == ""
    assert render_line("   ") == ""


def test_body_line_strips_markers(monkeypatch):
    monkeypatch.setattr(channel_view, "term_width", lambda: 200)
    out = render_line("The skill checks code **shape**, not **behavior**.")
    assert "**" not in out
    assert "shape" in out and "behavior" in out


def test_long_line_word_wraps_without_breaking_words(monkeypatch):
    monkeypatch.setattr(channel_view, "term_width", lambda: 20)
    out = render_line("operator-channel survives the relay scroll completely")
    # Every wrapped row fits the width; no word is split across rows.
    for row in out.split("\n"):
        assert len(row) <= 20
    assert "operator-channel" in out  # hyphenated token kept intact
