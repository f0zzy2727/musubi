"""Tests for the operator-input console (scripts/operator-console.py).

Covers the paste-burst coalescing and the file-format contract with the
orchestrator's relay parser. The console replaced operator-console.sh because
bash 3.2's readline relayed only the first line of a multi-line/long paste,
repeated (field report 2026-06-09); these tests pin the fixed behaviour:

  - a paste burst (all lines ready at once) coalesces into ONE message
  - a deliberately-paced line stays its own message
  - bracketed-paste markers are stripped
  - what the console writes parses back to the right number of relay messages
"""
import importlib.util
import os
import sys
import time
import threading

_SPEC = importlib.util.spec_from_file_location(
    "operator_console",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "operator-console.py"),
)
operator_console = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(operator_console)

from oyakata import parse_operator_input  # noqa: E402


def _read_submit_with_stdin(text, *, paced_after=None):
    """Drive Reader.next_message() once against `text` fed through a real pipe
    (so select()/os.read behave as on a tty). If `paced_after` is set, that many
    leading lines are written immediately and the remainder after a pause longer
    than DRAIN_TIMEOUT — simulating a human typing a fresh line after a paste."""
    r, w = os.pipe()
    lines = text.splitlines(keepends=True)

    def feed():
        try:
            if paced_after is None:
                os.write(w, text.encode())
            else:
                os.write(w, "".join(lines[:paced_after]).encode())
                time.sleep(operator_console.DRAIN_TIMEOUT * 3)
                os.write(w, "".join(lines[paced_after:]).encode())
        finally:
            # Close the write end so the reader sees EOF — without this the
            # empty-input case blocks forever waiting for a terminator.
            os.close(w)

    t = threading.Thread(target=feed)
    t.start()
    try:
        return operator_console.Reader(r).next_message()
    finally:
        t.join()
        os.close(r)


# --- paste coalescing -------------------------------------------------------

def test_multiline_paste_coalesces_to_one_message():
    paste = "first line\nsecond line\nthird line\n"
    body = _read_submit_with_stdin(paste)
    assert body == "first line\nsecond line\nthird line"


def test_single_line_is_itself():
    assert _read_submit_with_stdin("just one line\n") == "just one line"


def test_long_single_line_survives_intact():
    long_line = "x" * 500
    assert _read_submit_with_stdin(long_line + "\n") == long_line


def test_paced_line_after_burst_is_not_swallowed():
    # First two lines arrive as a burst; the third comes after a human-sized
    # pause, so it must NOT be coalesced into this submit.
    body = _read_submit_with_stdin(
        "burst one\nburst two\nlater typed\n", paced_after=2
    )
    assert body == "burst one\nburst two"


def test_eof_returns_none():
    assert _read_submit_with_stdin("") is None


# --- bracketed-paste defence ------------------------------------------------

def test_strips_bracketed_paste_markers():
    # Some terminals leave bracketed-paste on; the \e[200~ / \e[201~ wrappers
    # must never reach Oya's message.
    paste = "\033[200~hello there\033[201~\n"
    assert _read_submit_with_stdin(paste) == "hello there"


# --- file-format contract with the orchestrator relay -----------------------

def test_written_entries_parse_to_one_message_per_submit(tmp_path):
    f = str(tmp_path / "operator-input.md")
    operator_console._append(f, "11:00 UTC", "line a\nline b\nline c")  # one paste
    operator_console._append(f, "11:01 UTC", "a typed line")            # one type
    msgs = parse_operator_input(open(f, encoding="utf-8").read())
    assert len(msgs) == 2
    assert msgs[0] == "line a\nline b\nline c"
    assert msgs[1] == "a typed line"
