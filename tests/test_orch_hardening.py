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


# --- docs-2: capsule-aware trim + boot auto-rotate --------------------------
from orchestrator import trim_capsule, auto_rotate_managed_docs
import pathlib


def _write_bloated_capsule(tmp_path, n_entries=18, entry_chars=3000):
    """A capsule shaped like the field one: header + invariant + HEAD pointer +
    many freeform **bold** log entries + a couple `## ` structured sections."""
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    parts = [
        "# Current State\n",
        "> Capsule-before-comms invariant note.\n",
        "**Last verified HEAD:** abc1234 (the current commit pointer)\n",
    ]
    for i in range(n_entries):
        parts.append(f"**Old log entry {i} (2026-06-13):** " + "x" * entry_chars + "\n")
    parts.append("**Active cycle:** stage-7 build\n")
    parts.append("\n## Active slices\n\n| Agent | Slice |\n|---|---|\n| Opus | S1 |\n")
    parts.append("\n## Locked decisions this session\n\n| Decision |\n|---|\n| keep X |\n")
    cap = agents / "current-state.md"
    cap.write_text("".join(parts))
    return cap


def test_trim_capsule_keeps_skeleton_drops_log_bulk(tmp_path):
    cap = _write_bloated_capsule(tmp_path)
    orig = cap.read_text()
    result = trim_capsule(cap, keep_recent_entries=2)
    assert result is not None
    archive, new_size = result
    # Full original archived losslessly.
    assert pathlib.Path(archive).read_text() == orig
    new = cap.read_text()
    # Shrunk hard.
    assert new_size < len(orig) // 5
    # Orientation skeleton PRESERVED (not blanked — the anti-amnesia guarantee).
    assert "**Last verified HEAD:** abc1234" in new
    assert "**Active cycle:** stage-7 build" in new
    assert "## Active slices" in new
    assert "## Locked decisions this session" in new
    assert "| Opus | S1 |" in new
    # Most-recent entries kept; the old bulk dropped.
    assert "Old log entry 17" in new
    assert "Old log entry 16" in new
    assert "Old log entry 0" not in new
    assert "Old log entry 5" not in new


def test_trim_capsule_none_when_no_freeform_bulk(tmp_path):
    # A clean capsule (no freeform log entries to drop) -> nothing to trim.
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True)
    cap = agents / "current-state.md"
    cap.write_text("# Current State\n**Last verified HEAD:** abc\n\n## Active slices\n\n| a |\n")
    assert trim_capsule(cap) is None


def test_auto_rotate_trims_capsule_and_rotates_handoff(tmp_path):
    cap = _write_bloated_capsule(tmp_path)
    _write_handoff(tmp_path, n_sections=5, section_chars=30_000)
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    rotated = auto_rotate_managed_docs(cfg)
    labels = {r[0] for r in rotated}
    assert "capsule" in labels and "agent-handoff" in labels
    # Capsule trimmed (skeleton survives), handoff rotated — both now small.
    assert "**Last verified HEAD:** abc1234" in cap.read_text()
    assert (tmp_path / "docs/agents/current-state.md").stat().st_size < MANAGED_DOC_WARN_CHARS
    assert (tmp_path / "docs/agents/agent-handoff.md").stat().st_size < MANAGED_DOC_REFUSE_CHARS


def test_auto_rotate_respects_off_switch(tmp_path):
    _write_bloated_capsule(tmp_path)
    cfg = {"comms": {"auto_rotate_managed_docs": False}, "project": {"path": str(tmp_path)}}
    assert auto_rotate_managed_docs(cfg) == []


def test_auto_rotate_skips_small_docs(tmp_path):
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True)
    (agents / "current-state.md").write_text("# Current State\n**Last verified HEAD:** abc\n")
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    assert auto_rotate_managed_docs(cfg) == []


def test_auto_rotate_leaves_claude_md_alone(tmp_path):
    # CLAUDE.md is reference, not a cycle log — never auto-rotated even when huge.
    (tmp_path / "CLAUDE.md").write_text("x" * (MANAGED_DOC_WARN_CHARS + 5000))
    cfg = {"comms": {}, "project": {"path": str(tmp_path)}}
    assert auto_rotate_managed_docs(cfg) == []
    assert (tmp_path / "CLAUDE.md").stat().st_size > MANAGED_DOC_WARN_CHARS  # untouched


# --- burn-1: Oya append-log tail-rotation ----------------------------------
from orchestrator import (
    rotate_append_log,
    OYA_LOG_ROTATE_CHARS,
    OYA_LOG_KEEP_CHARS,
)


def _write_oya_log(tmp_path, name, n_entries, entry_chars, header, entry_fmt):
    """Append-only Oya log: a small document header + many dated entries."""
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    parts = [header]
    for i in range(n_entries):
        parts.append(entry_fmt(i) + "x" * entry_chars + "\n")
    p = agents / name
    p.write_text("".join(parts))
    return p


def test_rotate_append_log_dated_sections_keeps_header_and_tail(tmp_path):
    # oyakata-log shape: `## YYYY-MM-DD ...` entry headers.
    p = _write_oya_log(
        tmp_path, "oyakata-log.md", n_entries=200, entry_chars=2000,
        header="# Oyakata Log\n\nAppend-only.\n\n---\n",
        entry_fmt=lambda i: f"\n## 2026-06-{(i % 28) + 1:02d} 0{i % 10}:00 UTC — entry {i}\n")
    orig = p.read_text()
    assert p.stat().st_size > OYA_LOG_ROTATE_CHARS
    archive = rotate_append_log(p, keep_chars=OYA_LOG_KEEP_CHARS)
    assert archive is not None
    # Lossless: archive holds the full original.
    assert pathlib.Path(archive).read_text() == orig
    new = p.read_text()
    assert p.stat().st_size <= OYA_LOG_KEEP_CHARS + 4000  # header cap headroom
    assert new.startswith("# Oyakata Log")           # header preserved
    assert "append-log rotation" in new              # rotation pointer present
    assert new.rstrip().endswith("x" * 100)          # most-recent tail kept


def test_rotate_append_log_iso_lines(tmp_path):
    # oyakata-decisions shape: bare `YYYY-MM-DDTHH:MM ...` lines, no `## ` headers.
    p = _write_oya_log(
        tmp_path, "oyakata-decisions.md", n_entries=2000, entry_chars=80,
        header="# oyakata-decisions — auto-approve audit trail\n\nFormat: ...\n",
        entry_fmt=lambda i: f"2026-06-30T0{i % 10}:15 ALLOW Read :: ")
    assert rotate_append_log(p, keep_chars=OYA_LOG_KEEP_CHARS) is not None
    assert p.stat().st_size <= OYA_LOG_KEEP_CHARS + 4000
    assert p.read_text().startswith("# oyakata-decisions")


def test_rotate_append_log_buried_first_header_line_snaps(tmp_path):
    # operator-channel shape: a tiny header, then a huge header-less mirror body,
    # then a single `## ` header far in. "Everything before first entry" would
    # keep the whole body — the bounded-header + line-snap path must not.
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    p = agents / "operator-channel.md"
    body = "".join(f"mirrored message line {i}\n" for i in range(20000))
    p.write_text("# Operator Channel\n\n> intro blurb\n\n" + body + "## 2026-06-30 late header\nend\n")
    assert p.stat().st_size > OYA_LOG_ROTATE_CHARS
    archive = rotate_append_log(p, keep_chars=OYA_LOG_KEEP_CHARS)
    assert archive is not None
    assert p.stat().st_size <= OYA_LOG_KEEP_CHARS + 4000   # actually trimmed
    assert p.read_text().startswith("# Operator Channel")  # header preserved


def test_rotate_append_log_small_file_noop(tmp_path):
    agents = tmp_path / "docs" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    p = agents / "oyakata-log.md"
    p.write_text("# Oyakata Log\n\n## 2026-06-30 01:00 UTC — only entry\nshort\n")
    assert rotate_append_log(p) is None  # under keep_chars — nothing to do


def test_auto_rotate_trims_oya_logs_idempotent(tmp_path):
    # Full boot path: all three Oya logs over threshold get tail-rotated once.
    big = "y" * (OYA_LOG_ROTATE_CHARS + 50_000)
    _write_oya_log(tmp_path, "oyakata-log.md", 1, len(big),
                   header="# Oyakata Log\n\n---\n",
                   entry_fmt=lambda i: "\n## 2026-06-30 01:00 UTC — e\n")
    _write_oya_log(tmp_path, "oyakata-decisions.md", 1, len(big),
                   header="# oyakata-decisions\n\n",
                   entry_fmt=lambda i: "2026-06-30T01:00 ALLOW Read :: ")
    cfg = {"comms": {}, "project": {"path": str(tmp_path)},
           "agents": {"oyakata": {}}}
    labels = {r[0] for r in auto_rotate_managed_docs(cfg)}
    assert "oyakata-log" in labels and "oyakata-decisions" in labels
    # Idempotent: a second boot rotates nothing (already small).
    assert auto_rotate_managed_docs(cfg) == []


def test_auto_rotate_oya_logs_respects_disable_flag(tmp_path):
    _write_oya_log(tmp_path, "oyakata-log.md", 1,
                   OYA_LOG_ROTATE_CHARS + 50_000,
                   header="# Oyakata Log\n\n---\n",
                   entry_fmt=lambda i: "\n## 2026-06-30 01:00 UTC — e\n")
    cfg = {"comms": {"auto_rotate_managed_docs": False},
           "project": {"path": str(tmp_path)}, "agents": {"oyakata": {}}}
    assert auto_rotate_managed_docs(cfg) == []  # gated off → untouched
