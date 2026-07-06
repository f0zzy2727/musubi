"""Tests for scripts/oya-boot-context.py — the Oya boot-context generator.

Contract (north-star-2 + re-anchor gate, field incident 2026-07-06):
  - emits a git ground-truth snapshot of the project (HEAD, branch, dirty,
    worktrees, branches carrying commits HEAD lacks)
  - inlines the BODIES of [agents.oyakata].context_docs (absolute or
    project-relative), falling back to the recognised discovery set
  - configured-but-missing docs produce an explicit MISSING line
  - oversized docs are truncated with a MUST-READ marker, never dropped
  - managed-template docs are called out, not injected as vision
  - a non-git project degrades to an explicit note, exit code still 0
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "oya-boot-context.py"


def run_gen(toml: Path, project: Path):
    out = subprocess.run(
        ["python3", str(SCRIPT), str(toml), str(project)],
        capture_output=True, text=True, timeout=60,
    )
    return out


def git(project: Path, *args):
    subprocess.run(
        ["git", "-C", str(project), *args],
        check=True, capture_output=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin",
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "HOME": str(project)},
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)
    git(proj, "init", "-b", "main")
    (proj / "README.md").write_text("# app\n")
    git(proj, "add", "-A")
    git(proj, "commit", "-m", "initial commit")
    return proj


def write_toml(tmp_path: Path, project: Path, context_docs: str | None) -> Path:
    toml = tmp_path / "musubi.toml"
    body = f'[project]\npath = "{project}"\n\n[agents.oyakata]\nenabled = true\n'
    if context_docs is not None:
        body += f"context_docs = {context_docs}\n"
    toml.write_text(body)
    return toml


def test_ground_truth_snapshot(tmp_path, project):
    (project / "docs" / "PRODUCT-VISION.md").write_text("Soul Gallery is logged-in only.\n")
    git(project, "add", "-A")
    git(project, "commit", "-m", "add vision")
    toml = write_toml(tmp_path, project, '["docs/PRODUCT-VISION.md"]')
    out = run_gen(toml, project)
    assert out.returncode == 0
    assert "Repo ground truth" in out.stdout
    assert "add vision" in out.stdout          # HEAD subject
    assert "branch: main" in out.stdout
    assert "working tree: clean" in out.stdout


def test_dirty_tree_and_divergent_branch_flagged(tmp_path, project):
    git(project, "branch", "feature")
    git(project, "checkout", "feature")
    (project / "extra.txt").write_text("x\n")
    git(project, "add", "-A")
    git(project, "commit", "-m", "feature-only work")
    git(project, "checkout", "main")
    (project / "junk.txt").write_text("dirty\n")
    toml = write_toml(tmp_path, project, None)
    out = run_gen(toml, project)
    assert "DIVERGENCE" in out.stdout
    assert "feature" in out.stdout
    assert "RE-ANCHOR" in out.stdout
    assert "DIRTY" in out.stdout


def test_context_docs_content_inlined(tmp_path, project):
    vision = project / "docs" / "PRODUCT-VISION.md"
    vision.write_text("The gallery is the app's MATCHING surface — logged-in by definition.\n")
    shared = tmp_path / "shared" / "CROSS-APP-RULES.md"
    shared.parent.mkdir()
    shared.write_text("Never auto-publish to any store.\n")
    toml = write_toml(tmp_path, project,
                      f'["docs/PRODUCT-VISION.md", "{shared}"]')
    out = run_gen(toml, project)
    assert "MATCHING surface" in out.stdout            # relative doc body inlined
    assert "Never auto-publish" in out.stdout          # absolute doc body inlined
    assert f"BEGIN {vision}" in out.stdout


def test_missing_configured_doc_reported(tmp_path, project):
    toml = write_toml(tmp_path, project, '["docs/DOES-NOT-EXIST.md"]')
    out = run_gen(toml, project)
    assert "MISSING" in out.stdout
    assert "DOES-NOT-EXIST.md" in out.stdout


def test_oversized_doc_truncated_with_must_read(tmp_path, project):
    big = project / "docs" / "PRODUCT-VISION.md"
    big.write_text("\n".join(f"line {i}" for i in range(3000)))
    toml = write_toml(tmp_path, project, '["docs/PRODUCT-VISION.md"]')
    out = run_gen(toml, project)
    assert "TRUNCATED" in out.stdout
    assert "MUST read the remainder" in out.stdout
    assert "line 2999" not in out.stdout


def test_managed_template_not_injected_as_vision(tmp_path, project):
    doc = project / "docs" / "PRODUCT-VISION.md"
    doc.write_text("<!-- musubi-managed: template -->\nplaceholder body\n")
    toml = write_toml(tmp_path, project, '["docs/PRODUCT-VISION.md"]')
    out = run_gen(toml, project)
    assert "TEMPLATE" in out.stdout
    assert "placeholder body" not in out.stdout


def test_discovery_fallback_without_context_docs(tmp_path, project):
    (project / "docs" / "ARCHITECTURE.md").write_text("Single Fly backend, Expo client.\n")
    toml = write_toml(tmp_path, project, None)
    out = run_gen(toml, project)
    assert "Single Fly backend" in out.stdout
    # a missing discovery candidate is normal — must NOT produce MISSING noise
    assert "MISSING" not in out.stdout


def test_no_docs_at_all_names_the_gap(tmp_path, project):
    toml = write_toml(tmp_path, project, None)
    out = run_gen(toml, project)
    assert "NO north-star docs found" in out.stdout


def test_non_git_project_degrades_explicitly(tmp_path):
    proj = tmp_path / "plain"
    proj.mkdir()
    toml = write_toml(tmp_path, proj, None)
    out = run_gen(toml, proj)
    assert out.returncode == 0
    assert "NOT A GIT REPOSITORY" in out.stdout
