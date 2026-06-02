"""Tests for scripts/doctor.sh — the Oya north-star docs preflight check.

doctor.sh is otherwise environment-dependent (tmux, agent CLIs, python),
so these tests assert ONLY on the Oya-specific lines and never on the
exit code (a CI runner without tmux will legitimately FAIL other probes).

The check's contract:
  - silent when the Oya layer is disabled (or absent)
  - WARN, never FAIL, when Oya is enabled but no north-star docs exist
    (she degrades gracefully by asking on turn one)
  - PASS when a recognised vision/architecture/roadmap doc is present
  - context_docs takes precedence over auto-discovery; a listed-but-missing
    path WARNs
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_SRC = REPO_ROOT / "scripts" / "doctor.sh"


def run_doctor(tmp_path: Path, toml_body: str) -> str:
    """Build a throwaway musubi repo + project, run doctor.sh, return stdout."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts").mkdir(parents=True)
    shutil.copy(DOCTOR_SRC, fake_repo / "scripts" / "doctor.sh")

    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)

    toml = toml_body.replace("__PROJ__", str(proj))
    (fake_repo / "musubi.toml").write_text(toml)

    result = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "doctor.sh")],
        capture_output=True,
        text=True,
    )
    return result.stdout, proj


def oya_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if "Oya" in ln]


@pytest.fixture(autouse=True)
def _require_bash():
    if shutil.which("bash") is None:
        pytest.skip("bash not available")


def test_disabled_is_silent(tmp_path):
    toml = '[project]\npath = "__PROJ__"\n[agents.oyakata]\nenabled = false\n'
    stdout, _ = run_doctor(tmp_path, toml)
    assert oya_lines(stdout) == []


def test_absent_block_is_silent(tmp_path):
    toml = '[project]\npath = "__PROJ__"\n'
    stdout, _ = run_doctor(tmp_path, toml)
    assert oya_lines(stdout) == []


def test_enabled_no_docs_warns_not_fails(tmp_path):
    toml = '[project]\npath = "__PROJ__"\n[agents.oyakata]\nenabled = true\n'
    stdout, _ = run_doctor(tmp_path, toml)
    lines = oya_lines(stdout)
    assert any("WARN" in ln and "no vision" in ln for ln in lines)
    assert not any("FAIL" in ln for ln in lines)


def test_enabled_with_vision_doc_passes(tmp_path):
    toml = '[project]\npath = "__PROJ__"\n[agents.oyakata]\nenabled = true\n'
    stdout, proj = run_doctor(tmp_path, toml)
    # Re-run after planting a doc (run_doctor made the dirs; write then re-run).
    (proj / "docs" / "VISION.md").write_text("# vision\n")
    result = subprocess.run(
        ["bash", str(tmp_path / "repo" / "scripts" / "doctor.sh")],
        capture_output=True, text=True,
    )
    assert any("PASS" in ln and "north-star docs found" in ln
               for ln in oya_lines(result.stdout))


def test_adr_directory_counts_as_north_star(tmp_path):
    toml = '[project]\npath = "__PROJ__"\n[agents.oyakata]\nenabled = true\n'
    stdout, proj = run_doctor(tmp_path, toml)
    adr = proj / "docs" / "adr"
    adr.mkdir()
    (adr / "0001-use-x.md").write_text("# adr\n")
    result = subprocess.run(
        ["bash", str(tmp_path / "repo" / "scripts" / "doctor.sh")],
        capture_output=True, text=True,
    )
    assert any("PASS" in ln for ln in oya_lines(result.stdout))


def test_context_docs_present_passes(tmp_path):
    toml = ('[project]\npath = "__PROJ__"\n[agents.oyakata]\n'
            'enabled = true\ncontext_docs = ["docs/brief.md"]\n')
    stdout, proj = run_doctor(tmp_path, toml)
    (proj / "docs" / "brief.md").write_text("# brief\n")
    result = subprocess.run(
        ["bash", str(tmp_path / "repo" / "scripts" / "doctor.sh")],
        capture_output=True, text=True,
    )
    assert any("PASS" in ln and "context_docs all present" in ln
               for ln in oya_lines(result.stdout))


def test_context_docs_missing_warns(tmp_path):
    toml = ('[project]\npath = "__PROJ__"\n[agents.oyakata]\n'
            'enabled = true\ncontext_docs = ["docs/missing.md"]\n')
    stdout, _ = run_doctor(tmp_path, toml)
    lines = oya_lines(stdout)
    assert any("WARN" in ln and "context_docs listed but missing" in ln
               for ln in lines)
    assert not any("FAIL" in ln for ln in lines)
