"""Tests for the Phase 1 orchestrator hardening (orch-1 / orch-2 / orch-3).

- orch-1: resolve_archive_dir defensive fallback when the convention would
  land at the filesystem root (/archive).
- orch-2: check_managed_doc_sizes warn/refuse thresholds.
- orch-3: recognised_handles, unrecognised_handles_in, git head helpers.
"""
import os

import pytest

from comms import resolve_archive_dir
import orchestrator as orch
from orchestrator import (
    ConfigError,
    check_managed_doc_sizes,
    rotate_managed_doc,
    reset_capsule,
    recognised_handles,
    unrecognised_handles_in,
    _git_head_sha,
    _git_head_summary,
    MANAGED_DOC_WARN_CHARS,
    MANAGED_DOC_REFUSE_CHARS,
)


def _write_handoff(tmp_path, n_sections, section_chars):
    """Create a handoff with a preamble + n dated cycle sections (newest first)."""
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    body = ["# Agent Handoff Log\n", "\n", "## [Cycle name] — [YYYY-MM-DD]\n", "template preamble\n"]
    for i in range(n_sections):
        day = 28 - i  # newest (28) first
        body.append(f"\n## Cycle {i} — Opus — 2026-05-{day:02d}\n")
        body.append("x" * section_chars + "\n")
    p = agents / "agent-handoff.md"
    p.write_text("".join(body))
    return p


def _cfg(comms_file, project_path, archive_dir=None):
    comms = {"file": comms_file}
    if archive_dir is not None:
        comms["archive_dir"] = archive_dir
    return {"comms": comms, "project": {"path": project_path}}


# --- orch-1: resolve_archive_dir ------------------------------------------

def test_archive_dir_legacy_tmp_path_falls_back_to_project_local():
    # /tmp/agent_comms.txt -> convention would give /archive (read-only root).
    cfg = _cfg("/tmp/agent_comms.txt", "/home/me/proj")
    assert resolve_archive_dir(cfg) == "/home/me/proj/docs/agents/archive"


def test_archive_dir_normal_convention_unchanged():
    cfg = _cfg("/home/me/proj/docs/agents/comms/active.txt", "/home/me/proj")
    assert resolve_archive_dir(cfg) == "/home/me/proj/docs/agents/archive"


def test_archive_dir_explicit_relative_is_project_joined():
    cfg = _cfg("/tmp/agent_comms.txt", "/home/me/proj", archive_dir="my/arch")
    assert resolve_archive_dir(cfg) == "/home/me/proj/my/arch"


def test_archive_dir_explicit_absolute_is_verbatim():
    cfg = _cfg("/tmp/agent_comms.txt", "/home/me/proj", archive_dir="/var/arch")
    assert resolve_archive_dir(cfg) == "/var/arch"


# --- orch-2: managed-doc size guard ---------------------------------------

def test_size_guard_silent_when_all_small(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * 100)
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    # Must not raise; small docs produce no offenders.
    check_managed_doc_sizes(cfg)


def test_size_guard_warns_but_allows_mid_size(tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("x" * (MANAGED_DOC_WARN_CHARS + 10))
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    check_managed_doc_sizes(cfg)  # no raise
    assert "WARNING" in capsys.readouterr().out


def test_size_guard_refuses_oversized(tmp_path):
    big = tmp_path / "docs" / "agents"
    big.mkdir(parents=True)
    (big / "agent-handoff.md").write_text("x" * (MANAGED_DOC_REFUSE_CHARS + 1))
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    with pytest.raises(ConfigError) as exc:
        check_managed_doc_sizes(cfg)
    assert "agent-handoff" in str(exc.value)


def test_size_guard_skips_missing_files(tmp_path):
    # No managed docs present at all — must not raise.
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    check_managed_doc_sizes(cfg)


def test_size_guard_non_interactive_still_raises(tmp_path):
    # Default path (no tty) preserves the hard-fail behaviour for CI/tests.
    p = _write_handoff(tmp_path, n_sections=4, section_chars=30_000)
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    with pytest.raises(ConfigError):
        check_managed_doc_sizes(cfg, interactive=False)
    # File untouched (no rotation without consent).
    assert p.stat().st_size > MANAGED_DOC_REFUSE_CHARS


# --- orch-2: rotate_managed_doc + interactive prompt ----------------------

def test_rotate_trims_to_recent_and_archives(tmp_path):
    p = _write_handoff(tmp_path, n_sections=5, section_chars=30_000)
    orig = p.read_text()
    archive = rotate_managed_doc(p, keep_recent=2)
    assert archive is not None
    # Archive holds the full original, losslessly.
    assert __import__("pathlib").Path(archive).read_text() == orig
    new = p.read_text()
    # Preamble kept; 2 newest sections kept; older ones gone.
    assert "# Agent Handoff Log" in new
    assert "Cycle 0 — Opus — 2026-05-28" in new
    assert "Cycle 1 — Opus — 2026-05-27" in new
    assert "Cycle 4 —" not in new
    assert p.stat().st_size < MANAGED_DOC_REFUSE_CHARS


def test_rotate_returns_none_when_too_few_sections(tmp_path):
    p = _write_handoff(tmp_path, n_sections=1, section_chars=10)
    assert rotate_managed_doc(p, keep_recent=2) is None


def test_size_guard_rotates_on_yes(tmp_path, monkeypatch):
    _write_handoff(tmp_path, n_sections=5, section_chars=30_000)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    # Must NOT raise — it rotates and continues.
    check_managed_doc_sizes(cfg, interactive=True)
    handoff = tmp_path / "docs/agents/agent-handoff.md"
    assert handoff.stat().st_size < MANAGED_DOC_REFUSE_CHARS
    archives = list((tmp_path / "docs/agents/archive").glob("agent-handoff-archive-*.md"))
    assert archives, "expected an archive file from rotation"


def test_reset_capsule_archives_and_shrinks(tmp_path):
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True)
    cap = agents / "current-state.md"
    cap.write_text("# Current State\n" + "x" * 200_000)  # bloated, no cycle sections
    archive = reset_capsule(cap)
    import pathlib
    assert pathlib.Path(archive).read_text().endswith("x" * 100)  # full content archived
    fresh = cap.read_text()
    assert len(fresh) < 5_000                # reset to a small snapshot
    assert "## Active slices" in fresh       # real capsule shape
    assert "## Locked decisions this session" in fresh


def test_size_guard_resets_bloated_capsule_on_yes(tmp_path, monkeypatch):
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True)
    # A capsule with only a couple dated sections but huge bulk — section-rotation
    # would NOT get it under the ceiling; reset must.
    (agents / "current-state.md").write_text(
        "# Current State\n" + "preamble " * 30_000
        + "\n## 2026-05-01 note\nx\n## 2026-05-02 note\ny\n")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    check_managed_doc_sizes(cfg, interactive=True)  # must NOT raise
    assert (agents / "current-state.md").stat().st_size < MANAGED_DOC_REFUSE_CHARS
    assert list((agents / "archive").glob("current-state-archive-*.md"))


def test_size_guard_raises_on_no(tmp_path, monkeypatch):
    _write_handoff(tmp_path, n_sections=4, section_chars=30_000)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    with pytest.raises(ConfigError):
        check_managed_doc_sizes(cfg, interactive=True)


# --- orch-3: handle recognition -------------------------------------------

def test_recognised_handles_excludes_handleless_observer():
    cfg = {"agents": {
        "opus": {"handle": "@OPUS"},
        "coda": {"handle": "@CODA"},
        "oyakata": {"log_path": "x"},  # observer — no handle
    }}
    assert set(recognised_handles(cfg)) == {"@OPUS", "@CODA"}


def test_unrecognised_handles_flags_new_agent():
    text = "blah [@OPUS] said hi and [@OYA] observed and [@CODA] replied"
    assert unrecognised_handles_in(text, ["@OPUS", "@CODA"]) == ["@OYA"]


def test_unrecognised_handles_case_insensitive_and_deduped():
    text = "[@oya] ... [@OYA] ... [@Oya]"
    assert unrecognised_handles_in(text, ["@OPUS"]) == ["@oya"]


def test_unrecognised_handles_none_when_all_known():
    text = "[@OPUS] and [@CODA] only"
    assert unrecognised_handles_in(text, ["@OPUS", "@CODA"]) == []


# --- orch-3: git head helpers (run against this repo) ---------------------

def test_git_head_helpers_on_repo():
    repo = os.path.dirname(os.path.abspath(orch.__file__))
    sha = _git_head_sha(repo)
    summary = _git_head_summary(repo)
    assert sha and len(sha) >= 4
    assert summary and summary.startswith(sha)


def test_git_head_helpers_non_repo_return_none(tmp_path):
    assert _git_head_sha(str(tmp_path)) is None
    assert _git_head_summary(str(tmp_path)) is None
