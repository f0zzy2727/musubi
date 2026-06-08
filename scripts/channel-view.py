#!/usr/bin/env python3
"""channel-view.py — a live, human-readable view of the operator channel.

Replaces a raw `tail -F` in the OYA -> OPERATOR pane. `tail` shows the channel
file's markdown verbatim — literal `**` around every header, `---` separators,
and hard mid-word wraps at the pane edge — which reads as raw, not as prose
(field note 2026-06-08: "not really human language"). This renderer fixes the
*presentation* without touching what Oya writes:

  - `**HH:MM UTC — Oya:**` style headers      -> bold, coloured, no asterisks
  - `---` / `***` / `___` separator lines      -> a dim horizontal rule
  - inline `**bold**` / `*italic*` / `` `code` `` -> the text, markers stripped
  - leading `#` headings / `>` blockquotes      -> marker stripped
  - long lines                                  -> word-wrapped to pane width
                                                   (never mid-word)

It follows the file like `tail -F`: prints the existing tail, then streams new
entries as Oya appends them, and re-opens if the file is truncated or recreated.
Pure-stdlib; no markdown library required. attach-oya.sh falls back to `tail`
when python3 is unavailable, so this is a progressive enhancement, not a
dependency.

Usage:  channel-view.py <channel.md path> [--tail N]
"""
import os
import re
import sys
import time
import signal
import shutil
import textwrap

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
RESET = "\033[0m"

# A header line is a whole line that is just `**...**` — the channel's
# `**HH:MM UTC — Oya:**` / `**... — Operator:**` entry markers.
_HEADER_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
# A horizontal-rule line: three or more of the same -, * or _ alone.
_RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def term_width():
    """Pane width, clamped to a sane floor. In a tmux pane this reports the
    pane's columns; falls back to 80 when there's no tty."""
    return max(24, shutil.get_terminal_size((80, 24)).columns)


def strip_inline(text):
    """Remove inline markdown markers, keeping the visible text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)          # **bold**
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)  # *italic*
    text = re.sub(r"`(.+?)`", r"\1", text)                # `code`
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)         # # heading
    text = re.sub(r"^\s{0,3}>\s?", "", text)              # > blockquote
    return text


def render_line(line):
    """Turn one raw markdown line into a display string (may be multi-line
    after wrapping). Returns '' for blank lines so paragraph spacing survives."""
    width = term_width()
    if _RULE_RE.match(line):
        return DIM + ("─" * width) + RESET
    m = _HEADER_RE.match(line)
    if m:
        # Whole-line header: bold + cyan, asterisks gone.
        return BOLD + CYAN + m.group(1).strip() + RESET
    if not line.strip():
        return ""
    text = strip_inline(line.rstrip("\n"))
    if not text.strip():
        return ""
    # Word-wrap to the pane; never break inside a word or on hyphens (so
    # "1:00" and "operator-channel" stay intact).
    return textwrap.fill(
        text, width=width,
        break_long_words=False, break_on_hyphens=False,
    )


def emit(line):
    sys.stdout.write(render_line(line) + "\n")
    sys.stdout.flush()


# Set by the SIGWINCH handler when the terminal/pane is resized. The follow
# loop notices it, clears the pane, and re-renders the visible tail at the new
# width — without this, lines pre-wrapped at the old width stay wrapped wrong
# after a resize (the exact mid-word breakage the renderer exists to avoid).
_resized = False


def _on_resize(signum, frame):
    global _resized
    _resized = True


def _render_tail(path, tail_lines):
    """Clear the pane and re-render the last `tail_lines` of the file at the
    CURRENT width. Returns the file's EOF offset so following resumes from
    there. Used for the initial draw and on every resize."""
    sys.stdout.write("\033[2J\033[H")  # clear screen + home cursor
    offset = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = f.read().splitlines()
            offset = f.tell()
        for line in existing[-tail_lines:]:
            emit(line)
    except FileNotFoundError:
        pass
    return offset


def follow(path, tail_lines):
    """tail -F behaviour: print the last `tail_lines` rendered lines of the
    file, then stream new appends, re-opening on truncation/recreation and
    re-rendering on resize."""
    global _resized
    try:
        signal.signal(signal.SIGWINCH, _on_resize)
    except (ValueError, AttributeError, OSError):
        pass  # no SIGWINCH (non-main thread / unsupported platform) — degrade

    offset = _render_tail(path, tail_lines)
    try:
        last_ino = os.stat(path).st_ino
    except FileNotFoundError:
        last_ino = None

    buf = ""
    while True:
        # A resize re-renders the whole visible tail at the new width, then
        # resumes following from EOF (so we don't re-emit what we just drew).
        if _resized:
            _resized = False
            offset = _render_tail(path, tail_lines)
            buf = ""

        try:
            st = os.stat(path)
        except FileNotFoundError:
            time.sleep(0.4)
            continue
        # Recreated (new inode) or truncated (shrank): re-follow from the top.
        if last_ino is not None and st.st_ino != last_ino:
            offset = 0
            buf = ""
        elif st.st_size < offset:
            offset = 0
            buf = ""
        last_ino = st.st_ino

        if st.st_size > offset:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
            buf += chunk
            # Render only complete lines; keep any partial trailing line in buf
            # so a mid-write append doesn't render half a line.
            *complete, buf = buf.split("\n")
            for line in complete:
                emit(line)
        time.sleep(0.4)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = argv[0]
    tail_lines = 100
    if "--tail" in argv:
        try:
            tail_lines = int(argv[argv.index("--tail") + 1])
        except (ValueError, IndexError):
            tail_lines = 100
    try:
        follow(path, tail_lines)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
