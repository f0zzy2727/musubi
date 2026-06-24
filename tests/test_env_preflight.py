"""Tests for scripts/env-preflight.sh (keys-1).

The launcher sources this to load a project's `.env` into the orchestrator (and
thus every spawned pane) and to warn, operator-readably, when a configured coder
CLI has no API key in the environment. Codex reporting "no keys / sandboxed" is
almost always this: keys never exported in the launching shell (field report
2026-06-20). These tests pin:

  - a `.env` is loaded, with quotes stripped and comments/junk lines skipped
  - an explicit export in the environment WINS over the .env (never clobbered)
  - the missing-key warning fires only when codex is configured AND no key set
  - sourcing works under both bash and (when present) zsh — both launchers
"""
import os
import shutil
import subprocess
import textwrap

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "env-preflight.sh")


def _run(snippet, shell="bash", env=None):
    """Source env-preflight.sh in `shell` and run `snippet`, returning the
    CompletedProcess. `snippet` sees the helper functions already sourced."""
    full = ". '%s'\n%s" % (os.path.abspath(_SCRIPT), textwrap.dedent(snippet))
    run_env = dict(os.environ)
    # Strip any key the host happens to export so tests are hermetic.
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        run_env.pop(k, None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [shell, "-c", full], capture_output=True, text=True, env=run_env
    )


def _write_env(tmp_path, body):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text(textwrap.dedent(body))
    return str(proj)


def test_loads_env_and_strips_quotes(tmp_path):
    proj = _write_env(tmp_path, """\
        # a comment
        OPENAI_API_KEY="sk-fromfile"
        export SUPABASE_URL='https://x.supabase.co'
        BARE=plain
        not_an_assignment
        bad-key=skip_me
    """)
    res = _run(f"""
        load_project_env '{proj}' '{tmp_path}' || true
        echo "OPENAI=$OPENAI_API_KEY"
        echo "SUPA=$SUPABASE_URL"
        echo "BARE=$BARE"
        echo "BAD=${{bad:-unset}}"
    """)
    assert res.returncode == 0, res.stderr
    assert "OPENAI=sk-fromfile" in res.stdout
    assert "SUPA=https://x.supabase.co" in res.stdout  # both quote styles stripped
    assert "BARE=plain" in res.stdout
    assert "BAD=unset" in res.stdout  # malformed key skipped, not exported


def test_explicit_export_wins_over_env_file(tmp_path):
    proj = _write_env(tmp_path, 'OPENAI_API_KEY="sk-fromfile"\n')
    res = _run(
        f"""
        load_project_env '{proj}' '{tmp_path}' || true
        echo "OPENAI=$OPENAI_API_KEY"
        """,
        env={"OPENAI_API_KEY": "sk-PREEXISTING"},
    )
    assert "OPENAI=sk-PREEXISTING" in res.stdout  # file never clobbers the env


def test_missing_env_file_is_noop(tmp_path):
    res = _run(f"load_project_env '{tmp_path}/nope' '{tmp_path}/also-nope'; echo rc=$?")
    # No file found -> returns nonzero, but must not error or print a load line.
    assert "Loading environment" not in res.stdout
    assert res.returncode == 0


def _toml(tmp_path, *clis):
    body = "[project]\npath = \"/tmp/x\"\n"
    for i, c in enumerate(clis):
        body += f"[agents.a{i}]\ncli = \"{c}\"\n"
    p = tmp_path / "musubi.toml"
    p.write_text(body)
    return str(p)


def test_warns_when_codex_configured_and_no_key(tmp_path):
    cfg = _toml(tmp_path, "claude", "codex")
    res = _run(f"warn_missing_keys '{cfg}'")
    assert "no API key is set" in res.stderr
    assert "OPENAI_API_KEY" in res.stderr


def test_no_warning_when_key_present(tmp_path):
    cfg = _toml(tmp_path, "claude", "codex")
    res = _run(f"warn_missing_keys '{cfg}'", env={"OPENAI_API_KEY": "sk-x"})
    assert res.stderr.strip() == ""


def test_no_warning_when_codex_absent(tmp_path):
    cfg = _toml(tmp_path, "claude", "claude")
    res = _run(f"warn_missing_keys '{cfg}'")
    assert res.stderr.strip() == ""


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_sources_under_zsh(tmp_path):
    # launch_musubi.sh runs under zsh — the helper must behave there too.
    proj = _write_env(tmp_path, 'SUPABASE_URL="https://z.example"\n')
    res = _run(
        f"load_project_env '{proj}' '{tmp_path}' || true\necho SUPA=$SUPABASE_URL",
        shell="zsh",
    )
    assert "SUPA=https://z.example" in res.stdout, res.stderr
