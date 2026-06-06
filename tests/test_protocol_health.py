"""Tests for the orch-7 / orch-8 protocol-health surfaces.

- orch-7: runbook version parsing/comparison, version-drift check against
  the shipped runbook, and protocol-detachment detection over a real
  throwaway git repo (commit dates + mtimes both backdated — freshness is
  max(last commit, mtime) per protocol file).
- orch-8: the pure status-segment formatters in comms.py and the banner
  emitters. The watcher-side episode tracking is closures over tmux state,
  exercised by manual integration runs, not here.
"""
import os
import subprocess
import time

import pytest

from comms import (
    compose_status_right,
    format_relay_refusal_status,
    parse_runbook_version,
    runbook_version_tuple,
)
from orchestrator import (
    check_protocol_detachment,
    check_runbook_version_drift,
    emit_protocol_health_banner,
    emit_refusal_banner,
)


# --- parse_runbook_version / runbook_version_tuple ---------------------------

def test_parses_plain_version_header():
    assert parse_runbook_version("# Runbook\n**Version:** 1.10\n") == "1.10"


def test_parses_forked_version_header():
    text = "**Version:** 1.7 (forked from musubi 2026-05-10 by IaA cycle x)\n"
    assert parse_runbook_version(text) == "1.7"


def test_no_header_returns_none():
    assert parse_runbook_version("# Runbook\nno version here\n") is None
    assert parse_runbook_version("") is None
    assert parse_runbook_version(None) is None


def test_version_tuple_numeric_comparison():
    # The reason the tuple exists: '1.9' < '1.10' must hold numerically.
    assert runbook_version_tuple("1.9") < runbook_version_tuple("1.10")
    assert runbook_version_tuple("2.0") > runbook_version_tuple("1.10")
    assert runbook_version_tuple(None) is None
    assert runbook_version_tuple("one.two") is None


# --- format_relay_refusal_status / compose_status_right ----------------------

def test_refusal_status_empty_clears():
    assert format_relay_refusal_status({}) == ""


def test_refusal_status_names_guard_and_count():
    s = format_relay_refusal_status({"capsule-stale": 3})
    assert "capsule-stale" in s and "×3" in s and s.startswith("⛔")


def test_refusal_status_multiple_guards_sorted():
    s = format_relay_refusal_status({"idle-streak": 1, "capsule-stale": 2})
    assert s.index("capsule-stale") < s.index("idle-streak")


def test_compose_status_right_joins_non_empty():
    assert compose_status_right("a", "", "b") == "a | b"
    assert compose_status_right("", "") == ""
    assert compose_status_right("only") == "only"


# --- check_runbook_version_drift ---------------------------------------------

def _cfg(project_path):
    return {
        "project": {"path": str(project_path)},
        "comms": {"file": os.path.join(str(project_path),
                                       "docs/agents/comms/active.txt")},
    }


def _write_project_runbook(project_path, version_line):
    rb = project_path / "docs" / "agents"
    rb.mkdir(parents=True, exist_ok=True)
    (rb / "AGENT_COLLAB_RUNBOOK.md").write_text(
        f"# Agent Collaboration Runbook\n**Version:** {version_line}\n")


def test_drift_warns_when_project_runbook_older(tmp_path):
    _write_project_runbook(tmp_path, "1.7 (forked from musubi 2026-05-10)")
    note = check_runbook_version_drift(_cfg(tmp_path))
    assert note is not None
    assert "v1.7" in note and "bootstrap" in note


def test_drift_silent_when_versions_match(tmp_path):
    # Read the shipped version so the test tracks future runbook bumps.
    shipped = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "docs", "agents",
        "AGENT_COLLAB_RUNBOOK.md")
    with open(shipped, encoding="utf-8") as f:
        shipped_v = parse_runbook_version(f.read())
    _write_project_runbook(tmp_path, shipped_v)
    assert check_runbook_version_drift(_cfg(tmp_path)) is None


def test_drift_flags_stale_musubi_clone(tmp_path):
    _write_project_runbook(tmp_path, "99.0")
    note = check_runbook_version_drift(_cfg(tmp_path))
    assert note is not None and "stale" in note


def test_drift_silent_when_project_runbook_missing(tmp_path):
    assert check_runbook_version_drift(_cfg(tmp_path)) is None


# --- check_protocol_detachment ------------------------------------------------

def _git(repo, *args, env_extra=None):
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    if env_extra:
        env.update(env_extra)
    subprocess.run(["git", "-C", str(repo)] + list(args),
                   check=True, capture_output=True, env=env)


def _commit_all(repo, msg, when_unix):
    stamp = f"{when_unix} +0000"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg, "--no-verify",
         env_extra={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def _seed_repo(tmp_path, protocol_age_days, code_age_days):
    """Repo where protocol files were committed (and mtimed)
    `protocol_age_days` ago and a code file `code_age_days` ago."""
    now = int(time.time())
    proto_ts = now - protocol_age_days * 86400
    code_ts = now - code_age_days * 86400
    _git(tmp_path, "init", "-q")
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True)
    capsule = agents / "current-state.md"
    capsule.write_text("# Current State\nstale snapshot\n")
    _commit_all(tmp_path, "docs: capsule", proto_ts)
    os.utime(capsule, (proto_ts, proto_ts))
    (tmp_path / "app.py").write_text("print('hello')\n")
    _commit_all(tmp_path, "feat: code moves on", code_ts)
    return tmp_path


def test_detachment_fires_on_wide_gap(tmp_path):
    repo = _seed_repo(tmp_path, protocol_age_days=8, code_age_days=0)
    note = check_protocol_detachment(_cfg(repo))
    assert note is not None
    assert "protocol" in note.lower()
    assert "commit" in note.lower()


def test_detachment_silent_when_protocol_fresh(tmp_path):
    repo = _seed_repo(tmp_path, protocol_age_days=0, code_age_days=0)
    assert check_protocol_detachment(_cfg(repo)) is None


def test_detachment_silent_below_threshold(tmp_path):
    repo = _seed_repo(tmp_path, protocol_age_days=1, code_age_days=0)
    assert check_protocol_detachment(_cfg(repo)) is None


def test_detachment_respects_configured_threshold(tmp_path):
    repo = _seed_repo(tmp_path, protocol_age_days=8, code_age_days=0)
    cfg = _cfg(repo)
    cfg["orchestrator"] = {"detachment_threshold_days": 30}
    assert check_protocol_detachment(cfg) is None


def test_detachment_fresh_mtime_overrides_old_commit(tmp_path):
    # An uncommitted-but-current capsule must not false-positive: the
    # operator's discipline may outrun their committing.
    repo = _seed_repo(tmp_path, protocol_age_days=8, code_age_days=0)
    capsule = repo / "docs" / "agents" / "current-state.md"
    capsule.write_text("# Current State\nfreshly reconciled\n")  # mtime = now
    assert check_protocol_detachment(_cfg(repo)) is None


def test_detachment_silent_outside_git_repo(tmp_path):
    assert check_protocol_detachment(_cfg(tmp_path)) is None


# --- banners (smoke) -----------------------------------------------------------

def test_protocol_health_banner_prints_notes(capsys):
    emit_protocol_health_banner(["note one", "note two"])
    out = capsys.readouterr().out
    assert "PROTOCOL HEALTH" in out and "note one" in out and "note two" in out


def test_protocol_health_banner_silent_when_empty(capsys):
    emit_protocol_health_banner([])
    assert capsys.readouterr().out == ""


def test_refusal_banner_names_guard(capsys):
    emit_refusal_banner("capsule-stale", "details here")
    out = capsys.readouterr().out
    assert "RELAY HELD" in out and "capsule-stale" in out and "details here" in out
