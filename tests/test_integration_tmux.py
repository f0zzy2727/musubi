"""B1 — real-tmux integration test.

Every other test mocks tmux (MagicMock panes). This one exercises the actual
send-keys + capture-pane path against a live tmux server, closing the "no
real-tmux integration test" trust gap. Skips cleanly when tmux is absent so
CI without tmux still passes; CI installs tmux so it runs there.
"""
import shutil
import time

import pytest

libtmux = pytest.importorskip("libtmux")

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)

from orchestrator import send_message, capture_pane, relay_instruction, strip_ansi


_SESSION = "musubi-itest"


@pytest.fixture
def two_panes():
    """A live tmux session with two shell panes. Torn down after the test."""
    server = libtmux.Server()
    # Clean any leftover session from a prior aborted run.
    for s in list(server.sessions):
        if s.name == _SESSION:
            s.kill()
    session = server.new_session(session_name=_SESSION, attach=False)
    window = session.active_window
    pane0 = window.active_pane
    pane1 = window.split(attach=False)
    time.sleep(0.5)  # let both shells settle
    try:
        yield pane0, pane1
    finally:
        session.kill()


def _wait_for(pane, token, timeout=5.0):
    """Poll the pane's captured text for `token` up to `timeout` seconds."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = strip_ansi(capture_pane(pane, 80))
        if token in last:
            return True
        time.sleep(0.25)
    return False


def test_send_message_reaches_real_pane(two_panes):
    pane0, _ = two_panes
    token = "MUSUBIPROBE_SEND_7F3A"
    send_message(pane0, f"echo {token}")
    assert _wait_for(pane0, token), "probe token never appeared in the pane"


def test_relay_routes_to_other_pane_only(two_panes):
    pane0, pane1 = two_panes  # pane0 = OPUS/claude, pane1 = CODA/codex
    token = "MUSUBIPROBE_RELAY_9B2C"
    cfg = {
        "comms": {"file": "/tmp/musubi_itest_comms.txt", "over_signal": "<OVER>"},
        "agents": {
            "opus": {"handle": "@OPUS"},
            "coda": {"handle": "@CODA"},
        },
    }
    message = f"Type: Update\nResult: completed\nNote: {token}"
    # OPUS sends -> pair pattern relays to CODA (pane1) only.
    relay_instruction(message, "OPUS", p_claude=pane0, p_codex=pane1, cfg=cfg)
    assert _wait_for(pane1, token), "CODA pane did not receive the relayed message"
