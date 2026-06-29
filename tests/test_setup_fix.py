"""Tests for scripts/setup-fix.sh — the cross-app setup repair engine.

Contract:
  - report mode (default) writes nothing; flags gaps
  - --fix scaffolds a real north-star, creates a durable I&A home, repairs a
    binary comms file, and lays a shared cross-app intent skeleton
  - every overwrite is backed up; the run is idempotent
  - -c scopes to a single config (siblings untouched)
  - it never mutates tomls (that is the agent routine's job)
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "scripts" / "setup-fix.sh"
TEMPLATES = REPO_ROOT / "templates"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


def build_root(tmp_path):
    """A throwaway musubi root with the script + templates staged."""
    root = tmp_path / "musubi"
    (root / "scripts").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    shutil.copy(SRC, root / "scripts" / "setup-fix.sh")
    for t in ("VISION.md", "ARCHITECTURE.md"):
        shutil.copy(TEMPLATES / t, root / "templates" / t)
    return root


def add_app(root, name, *, thin=False, binary_comms=False):
    """Create a project dir + matching toml under the root. Returns project path."""
    proj = root.parent / name
    (proj / "docs" / "agents" / "comms").mkdir(parents=True)
    if thin:
        (proj / "docs" / "agents" / "IaA.md").write_text(
            "<!-- musubi-managed: iaa -->\n# IaA\n")
        ctx = '["docs/agents/IaA.md"]'
    else:
        (proj / "docs" / "PRODUCT-VISION.md").write_text("# Vision\nreal\n")
        (proj / "docs" / "ARCHITECTURE.md").write_text("# Arch\nreal\n")
        ctx = '["docs/PRODUCT-VISION.md","docs/ARCHITECTURE.md"]'
    comms = proj / "docs" / "agents" / "comms" / "active.txt"
    if binary_comms:
        comms.write_bytes(bytes([0, 1, 2, 0, 255]))
    else:
        comms.write_text("@OPUS: hi\n")
    toml = (f'[project]\npath = "{proj}"\n[comms]\n'
            f'file = "docs/agents/comms/active.txt"\n[agents.oyakata]\n'
            f'enabled = true\ncontext_docs = {ctx}\n')
    fname = "musubi.toml" if name == "default" else f"musubi-{name}.toml"
    (root / fname).write_text(toml)
    return proj


def run(root, *args):
    return subprocess.run(
        ["bash", str(root / "scripts" / "setup-fix.sh"), *args],
        capture_output=True, text=True,
    )


def test_report_flags_gaps_and_writes_nothing(tmp_path):
    root = build_root(tmp_path)
    proj = add_app(root, "thin", thin=True, binary_comms=True)
    r = run(root)
    assert r.returncode == 0, r.stderr
    assert "no real north-star" in r.stdout
    assert "BINARY/corrupt" in r.stdout
    assert "no durable I&A home" in r.stdout
    # nothing written
    assert not (proj / "docs" / "PRODUCT-VISION.md").exists()
    assert not (proj / "docs" / "i-and-a").exists()
    assert not (root / "shared-intent" / "CROSS-APP-RULES.md").exists()


def test_fix_creates_scaffolds_and_repairs(tmp_path):
    root = build_root(tmp_path)
    proj = add_app(root, "thin", thin=True, binary_comms=True)
    r = run(root, "--fix", "-y")
    assert r.returncode == 0, r.stderr
    # north-star scaffolded (DRAFT banner)
    vis = proj / "docs" / "PRODUCT-VISION.md"
    assert vis.exists() and "DRAFT" in vis.read_text().splitlines()[0]
    assert (proj / "docs" / "ARCHITECTURE.md").exists()
    # durable I&A home
    assert (proj / "docs" / "i-and-a" / "README.md").exists()
    # shared doc skeleton
    assert (root / "shared-intent" / "CROSS-APP-RULES.md").exists()
    # binary comms repaired: backed up + recreated empty text
    comms = proj / "docs" / "agents" / "comms" / "active.txt"
    assert comms.read_text() == ""
    assert list(comms.parent.glob("active.txt.corrupt.bak"))


def test_fix_is_idempotent(tmp_path):
    root = build_root(tmp_path)
    add_app(root, "thin", thin=True, binary_comms=True)
    run(root, "--fix", "-y")
    r2 = run(root, "--fix", "-y")
    assert r2.returncode == 0
    assert "FIXED" not in r2.stdout  # nothing left to do
    assert "GAP" not in r2.stdout


def test_healthy_app_reports_ok(tmp_path):
    root = build_root(tmp_path)
    add_app(root, "default", thin=False)
    r = run(root)
    assert "has a real north-star" in r.stdout
    assert "no real north-star" not in r.stdout


def test_c_scopes_to_one_app(tmp_path):
    root = build_root(tmp_path)
    keep = add_app(root, "default", thin=False)        # healthy, not targeted
    target = add_app(root, "thin", thin=True)          # targeted
    run(root, "--fix", "-y", "-c", "musubi-thin.toml")
    # targeted app got its I&A home
    assert (target / "docs" / "i-and-a").exists()
    # untargeted app was not touched
    assert not (keep / "docs" / "i-and-a").exists()


def test_never_mutates_toml(tmp_path):
    root = build_root(tmp_path)
    add_app(root, "thin", thin=True, binary_comms=True)
    before = (root / "musubi-thin.toml").read_text()
    run(root, "--fix", "-y")
    assert (root / "musubi-thin.toml").read_text() == before
