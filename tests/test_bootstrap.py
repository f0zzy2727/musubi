"""B2 — bootstrap.sh coverage (dry-run / install / --check / idempotency).

Implemented as pytest-subprocess rather than bats so it runs in the existing
pytest CI with no new tooling dependency, while still exercising the real
shell script end-to-end against a temp project.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_BOOTSTRAP = _REPO / "bootstrap.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


def run(*args, cwd=None):
    return subprocess.run(
        ["bash", str(_BOOTSTRAP), *args],
        capture_output=True, text=True, cwd=cwd,
    )


def test_dry_run_writes_nothing(tmp_path):
    r = run("--dry-run", str(tmp_path))
    assert r.returncode == 0
    # No managed files created.
    assert not (tmp_path / "docs/agents/AGENT_COLLAB_RUNBOOK.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert "[dry-run]" in r.stdout


def test_check_reports_drift_on_empty_dir(tmp_path):
    r = run("--check", str(tmp_path))
    assert r.returncode == 1
    assert "drift" in r.stdout


def test_install_creates_expected_layout(tmp_path):
    r = run(str(tmp_path))
    assert r.returncode == 0, r.stderr
    expect = [
        "docs/agents/AGENT_COLLAB_RUNBOOK.md",
        "docs/agents/PAIR_OPERATING_MODEL.md",
        "CLAUDE.md",
        "AGENTS.md",
        ".gitignore",
        "scripts/classify-slice.sh",   # runbook depends on it (protocol-1)
        ".claude/commands/musubi-setup-fix.md",   # setup-repair routine
    ]
    for rel in expect:
        assert (tmp_path / rel).exists(), f"missing {rel}"


def test_check_clean_after_install(tmp_path):
    assert run(str(tmp_path)).returncode == 0
    r = run("--check", str(tmp_path))
    assert r.returncode == 0, r.stdout
    assert "install is current" in r.stdout


def test_idempotent_reinstall_stays_clean(tmp_path):
    run(str(tmp_path))
    # Second install must not corrupt; --check stays clean.
    r2 = run(str(tmp_path))
    assert r2.returncode == 0
    assert run("--check", str(tmp_path)).returncode == 0


def test_injected_block_markers_on_own_lines(tmp_path):
    run(str(tmp_path))
    claude = (tmp_path / "CLAUDE.md").read_text()
    # Exactly one real start-marker line and one end-marker line (anchored).
    start_lines = [ln for ln in claude.splitlines() if ln.strip() == "<!-- musubi:start -->"]
    end_lines = [ln for ln in claude.splitlines() if ln.strip() == "<!-- musubi:end -->"]
    assert len(start_lines) == 1
    assert len(end_lines) == 1


def test_reinstall_does_not_duplicate_block(tmp_path):
    run(str(tmp_path))
    run(str(tmp_path))  # refresh path
    claude = (tmp_path / "CLAUDE.md").read_text()
    start_lines = [ln for ln in claude.splitlines() if ln.strip() == "<!-- musubi:start -->"]
    assert len(start_lines) == 1, "refresh duplicated the musubi block"
