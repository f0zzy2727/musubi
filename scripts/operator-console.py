#!/usr/bin/env python3
"""operator-console.py — the operator's INPUT surface for talking to Oya.

Replaces operator-console.sh. That version used `read -r -e` (the bash readline
line-editor), which on macOS runs against **bash 3.2** — a readline with no
bracketed-paste support. Pasting a long or multi-line block into the (narrow)
console pane mis-tokenised the clipboard: only the first line landed in
operator-input.md, re-emitted, so Oya saw the first line repeated and the
channel pane echoed it back (field report 2026-06-09). The fix is to stop using
readline at all and read the pane in plain cooked mode, where the tty driver
delivers a paste as ordinary text — then coalesce a paste *burst* into one
message so a multi-line paste reaches Oya as a single thought, not N relays.

Behaviour:
  - The operator types to Oya HERE, not in Oya's own pane — the orchestrator
    `send-keys`-relays pair traffic INTO Oya's pane and overwrites mid-typed
    input there. This pane has exactly one writer, so nothing collides.
  - On submit, the message is appended to operator-input.md with a timestamp
    header. The orchestrator watches that file and relays each new entry into
    Oya's pane (see oyakata.relay_operator_input_to_oyakata).
  - A clipboard paste of several lines arrives as a fast burst; we drain the
    burst (DRAIN_TIMEOUT) and join it into ONE entry. A line typed by hand,
    with a human pause after Enter, stays its own entry.

Pure-stdlib. attach-oya.sh falls back to operator-console.sh when python3 is
unavailable, so this is a progressive enhancement, not a dependency.

Usage (normally launched by attach-oya.sh, not by hand):
  operator-console.py <operator-input.md path>
"""
import os
import re
import sys
import time
import select
import datetime

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
RESET = "\033[0m"

BAR = "─" * 44

# After the first line of a submit arrives, we wait this long for more lines.
# A paste delivers all its lines within a few milliseconds, so they fall inside
# the window and coalesce into one message; a human typing the next line takes
# far longer than this, so deliberate lines stay separate. Tuned for "paste = one
# message" without merging hand-typed turns.
DRAIN_TIMEOUT = 0.2

# Some terminals leave bracketed-paste mode on from the previous shell, wrapping
# a paste in these markers. We never enable it ourselves, but strip the markers
# defensively so they can't leak into Oya's message.
_BRACKET_PASTE_RE = re.compile(r"\033\[20[01]~")


def _stamp():
    """UTC HH:MM, matching the form Oya uses in the channel so the input log and
    her channel read as one conversation."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")


def _print_header():
    sys.stdout.write(BAR + "\n")
    sys.stdout.write(" TALK TO OYA  ·  type here, read her replies above\n")
    sys.stdout.write(" Your keystrokes land here only — never overwritten by relay traffic.\n")
    sys.stdout.write(BAR + "\n\n")
    sys.stdout.flush()


class Reader:
    """Reads operator submits from a fd using raw os.read + select.

    Deliberately NOT sys.stdin.readline(): a buffered text reader reads ahead
    into its own buffer, so select() on the fd can't see lines already pulled
    out of the kernel — coalescing would then depend on read timing and break
    intermittently. Reading raw bytes ourselves keeps select() authoritative:
    nothing leaves the kernel buffer except via an os.read we control.

    A submit is "every complete line available when the pane goes quiet". A
    paste burst (many newlines arriving together) drains into one multi-line
    message; a single typed line drains alone. Text after the last newline
    (a paste without a trailing newline, or a half-typed line) is held in
    `buf` until the operator presses Enter."""

    def __init__(self, fd):
        self.fd = fd
        self.buf = ""

    def _read(self, timeout):
        """One read. Returns decoded text, '' on a quiet timeout, or None at
        EOF. timeout=None blocks until input arrives."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return ""
        data = os.read(self.fd, 65536)
        if data == b"":
            return None
        return _BRACKET_PASTE_RE.sub("", data.decode("utf-8", "replace"))

    def next_message(self):
        """Block for the next submit. Returns the message body (one line, or a
        coalesced multi-line paste), or None at EOF."""
        while True:
            if "\n" not in self.buf:
                chunk = self._read(timeout=None)  # block for input
                if chunk is None:  # EOF
                    if self.buf.strip():
                        body, self.buf = self.buf, ""
                        return body
                    return None
                self.buf += chunk
            # Drain the rest of a burst: keep reading while input is waiting
            # within DRAIN_TIMEOUT. A paste's lines all fall inside this window;
            # a human's next line takes far longer, so it stays a separate submit.
            while True:
                chunk = self._read(timeout=DRAIN_TIMEOUT)
                if not chunk:  # '' (quiet) or None (EOF) — burst is over
                    break
                self.buf += chunk
            if "\n" in self.buf:
                # Submit every complete line; keep any trailing partial for next.
                body, _, self.buf = self.buf.rpartition("\n")
                return body
            # Got input but no newline yet (unterminated paste / mid-type) —
            # loop back and block for the Enter that completes it.


def _append(input_file, stamp, body):
    """Append one entry. The header is the exact delimiter the orchestrator
    splits on — keep it `**HH:MM UTC — Operator:**`, on its own line."""
    with open(input_file, "a", encoding="utf-8") as f:
        f.write("\n**%s — Operator:**\n" % stamp)
        f.write(body + "\n")


def run(input_file):
    os.makedirs(os.path.dirname(os.path.abspath(input_file)), exist_ok=True)
    _print_header()
    reader = Reader(sys.stdin.fileno())
    while True:
        sys.stdout.write("\n" + BOLD + CYAN + "YOU → " + RESET)
        sys.stdout.flush()
        body = reader.next_message()
        if body is None:
            # EOF: re-prompt rather than exit, so a stray Ctrl-D doesn't kill the
            # operator's only input surface. A tiny sleep avoids a busy-spin if
            # stdin is permanently closed (pane detached).
            sys.stdout.write("\n")
            time.sleep(0.2)
            continue
        if not body.strip():
            # Blank submit — would relay an empty message to Oya. Skip.
            continue
        stamp = _stamp()
        _append(input_file, stamp, body)
        n = body.count("\n") + 1
        suffix = (" (%d lines)" % n) if n > 1 else ""
        sys.stdout.write(
            DIM + "   ↳ sent to Oya (%s)%s — watch the channel pane for her reply\n\n" % (stamp, suffix) + RESET
        )
        sys.stdout.flush()


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        run(argv[0])
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
