"""Tests for the comms-file lock (one orchestrator per comms file).

Guards the structural fix for two orchestrators corrupting one comms file:
each truncates the other's active.txt at boot, replaying the whole cycle. The
lock makes a second orchestrator on the same file refuse to boot; a stale lock
(dead owner) is taken over so a crash never wedges future launches.
"""
import json
import os

import pytest

from orchestrator import (
    _pid_alive,
    comms_lock_path,
    read_comms_lock,
    acquire_comms_lock,
    release_comms_lock,
)


@pytest.fixture
def comms(tmp_path):
    f = tmp_path / "docs" / "agents" / "comms" / "active.txt"
    f.parent.mkdir(parents=True)
    f.write_text("")
    return str(f)


# --- _pid_alive -------------------------------------------------------------

def test_own_pid_is_alive():
    assert _pid_alive(os.getpid()) is True


def test_absurd_pid_is_dead():
    # A PID this high effectively never exists on a normal system.
    assert _pid_alive(2_000_000_000) is False


def test_garbage_pid_is_dead():
    assert _pid_alive(None) is False
    assert _pid_alive("nope") is False
    assert _pid_alive(0) is False


# --- acquire / refuse / takeover --------------------------------------------

def test_acquire_when_unheld_succeeds(comms):
    ok, lock_path = acquire_comms_lock(comms, "alpha")
    assert ok is True
    assert os.path.exists(lock_path)
    held = read_comms_lock(lock_path)
    assert held["pid"] == os.getpid()
    assert held["session"] == "alpha"
    release_comms_lock(lock_path)


def test_live_peer_is_refused(comms):
    # A lock owned by a DIFFERENT, live PID (the parent of this process is a
    # safe always-alive other pid) must refuse.
    lock_path = comms_lock_path(comms)
    other_live_pid = os.getppid()
    assert other_live_pid != os.getpid()
    with open(lock_path, "w") as f:
        json.dump({"pid": other_live_pid, "session": "billion",
                   "comms": comms, "started": "2026-06-09 10:00:00"}, f)
    ok, info = acquire_comms_lock(comms, "billion-2")
    assert ok is False
    assert info["pid"] == other_live_pid
    assert info["session"] == "billion"


def test_stale_lock_is_taken_over(comms):
    # A lock owned by a dead PID is stale — acquire takes it over.
    lock_path = comms_lock_path(comms)
    with open(lock_path, "w") as f:
        json.dump({"pid": 2_000_000_000, "session": "ghost",
                   "comms": comms, "started": "2026-06-09 09:00:00"}, f)
    ok, returned = acquire_comms_lock(comms, "fresh")
    assert ok is True
    assert read_comms_lock(returned)["pid"] == os.getpid()
    release_comms_lock(returned)


def test_own_reacquire_succeeds(comms):
    ok1, lp = acquire_comms_lock(comms, "alpha")
    ok2, lp2 = acquire_comms_lock(comms, "alpha")  # same process re-acquires
    assert ok1 and ok2
    assert lp == lp2
    release_comms_lock(lp)


def test_release_only_removes_own_lock(comms):
    lock_path = comms_lock_path(comms)
    # A lock owned by someone else must NOT be removed by our release.
    with open(lock_path, "w") as f:
        json.dump({"pid": os.getppid(), "session": "other", "comms": comms,
                   "started": "x"}, f)
    release_comms_lock(lock_path)
    assert os.path.exists(lock_path), "release must not delete another process's lock"


def test_malformed_lock_is_overwritten(comms):
    lock_path = comms_lock_path(comms)
    lock_path_obj = lock_path
    with open(lock_path_obj, "w") as f:
        f.write("{ not json")
    ok, lp = acquire_comms_lock(comms, "alpha")
    assert ok is True  # unreadable holder treated as no holder
    assert read_comms_lock(lp)["pid"] == os.getpid()
    release_comms_lock(lp)
