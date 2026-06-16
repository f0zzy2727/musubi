"""Tests for oyakata-2 slice 2 — auto_wire_pretooluse_hook.

Covers the idempotent merge into `<project_path>/.claude/settings.local.json`:

  - Disabled in config → no-op (no file touched).
  - No existing file → creates `.claude/` dir + file with the hook entry.
  - Existing file with unrelated keys → preserves them, appends entry.
  - Existing musubi entry with same path → unchanged (no I/O).
  - Existing musubi entry with different path → updates path in place.
  - Malformed JSON in existing file → warns + skips (never overwrites).
  - Missing project_path → warns + skips (never raises).
  - Missing hook script on disk → warns + skips.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

import oyakata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(enabled: bool, no_secrets: bool = False) -> dict:
    """Minimal cfg shape the auto-wirer reads. `no_secrets` adds the sec-1
    `[security].repo_has_no_secrets` opt-in block."""
    cfg = {
        "agents": {
            "oyakata": {
                "permissions": {"enabled": enabled},
            },
        },
    }
    if no_secrets:
        cfg["security"] = {"repo_has_no_secrets": True}
    return cfg


def _make_fake_orchestrator(tmp_path) -> pathlib.Path:
    """Build a fake musubi clone at tmp_path/musubi with the expected hook
    script in scripts/. Returns the dir to pass as orchestrator_dir."""
    musubi = tmp_path / "musubi"
    (musubi / "scripts").mkdir(parents=True)
    (musubi / "scripts" / "oya-pretooluse.py").write_text("#!/usr/bin/env python3\n")
    return musubi


def _make_project(tmp_path) -> pathlib.Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def _settings_path(project: pathlib.Path) -> pathlib.Path:
    return project / ".claude" / "settings.local.json"


# ---------------------------------------------------------------------------
# Disabled / skipped paths
# ---------------------------------------------------------------------------

class TestSkippedPaths:
    def test_permissions_disabled_in_config_no_op(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(False), str(project), str(musubi))
        # No .claude/ dir should have been created.
        assert not (project / ".claude").exists()

    def test_missing_project_path_no_op(self, tmp_path):
        musubi = _make_fake_orchestrator(tmp_path)
        bogus = tmp_path / "does-not-exist"
        # Should not raise.
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(bogus), str(musubi))

    def test_missing_hook_script_no_op(self, tmp_path):
        project = _make_project(tmp_path)
        # Don't create the hook script — orchestrator_dir exists but no script.
        empty_musubi = tmp_path / "empty-musubi"
        empty_musubi.mkdir()
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(empty_musubi))
        # No .claude/ should be created when the hook script doesn't exist.
        assert not (project / ".claude").exists()


# ---------------------------------------------------------------------------
# Creation paths
# ---------------------------------------------------------------------------

class TestCreation:
    def test_creates_claude_dir_and_settings_file(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        settings_path = _settings_path(project)
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data
        pre = data["hooks"]["PreToolUse"]
        assert len(pre) == 1
        assert pre[0]["matcher"] == oyakata.PRETOOLUSE_HOOK_MATCHER
        assert pre[0]["hooks"][0]["timeout"] == oyakata.PRETOOLUSE_HOOK_TIMEOUT
        assert pre[0]["hooks"][0]["command"].endswith("scripts/oya-pretooluse.py")
        # Path is absolute (Claude Code requirement).
        assert os.path.isabs(pre[0]["hooks"][0]["command"])

    def test_creates_only_under_claude_dir(self, tmp_path):
        # Auto-wiring must never write outside <project>/.claude/.
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        before = set(p.name for p in project.iterdir())
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        after = set(p.name for p in project.iterdir())
        assert after - before == {".claude"}


# ---------------------------------------------------------------------------
# sec-1 Slice 2 — [security].repo_has_no_secrets disclose-tier opt-in
# ---------------------------------------------------------------------------

class TestDiscloseOptIn:
    def _command(self, project) -> str:
        data = json.loads(_settings_path(project).read_text())
        return data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    @pytest.mark.parametrize("cfg, expected", [
        ({}, False),
        ({"security": {}}, False),
        ({"security": {"repo_has_no_secrets": False}}, False),
        ({"security": {"repo_has_no_secrets": True}}, True),
        ({"security": "not-a-dict"}, False),
    ])
    def test_repo_has_no_secrets_helper(self, cfg, expected):
        assert oyakata.repo_has_no_secrets(cfg) is expected

    def test_default_command_is_bare_path(self, tmp_path):
        """No [security] block → command is the bare hook path, byte-identical
        to the pre-sec-1 entry (no env wrapper)."""
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        cmd = self._command(project)
        assert "MUSUBI_REPO_HAS_NO_SECRETS" not in cmd
        assert "/usr/bin/env" not in cmd
        assert cmd.endswith("scripts/oya-pretooluse.py")

    def test_opt_in_wraps_command_with_env(self, tmp_path):
        """repo_has_no_secrets=true → command is wrapped in /usr/bin/env so the
        hook runs with MUSUBI_REPO_HAS_NO_SECRETS=1, and stays an absolute path
        for the auto-wirer's checks."""
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True, no_secrets=True), str(project), str(musubi))
        cmd = self._command(project)
        assert cmd.startswith("/usr/bin/env MUSUBI_REPO_HAS_NO_SECRETS=1 ")
        # The hook path is double-quoted so a checkout location with a space
        # can't split the wrapped command into the wrong args.
        assert cmd.endswith('scripts/oya-pretooluse.py"')
        assert '"' in cmd
        assert os.path.isabs(cmd)

    def test_opt_in_path_with_space_is_quoted(self, tmp_path):
        """A musubi checkout location containing a space must stay a single
        quoted argument in the wrapped command, not split into two."""
        musubi = tmp_path / "My Projects" / "musubi"
        (musubi / "scripts").mkdir(parents=True)
        (musubi / "scripts" / "oya-pretooluse.py").write_text("#!/usr/bin/env python3\n")
        project = _make_project(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True, no_secrets=True), str(project), str(musubi))
        cmd = self._command(project)
        # The whole path (with its space) sits inside one pair of quotes.
        assert '"' in cmd
        quoted = cmd.split('"', 1)[1].rsplit('"', 1)[0]
        assert quoted.endswith("scripts/oya-pretooluse.py")
        assert "My Projects" in quoted

    def test_flipping_flag_rewrites_single_entry(self, tmp_path):
        """Turning the opt-in on after an off launch updates the existing entry
        in place (verdict 'updated') — not a second duplicate hook."""
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        assert "MUSUBI_REPO_HAS_NO_SECRETS" not in self._command(project)
        oyakata.auto_wire_pretooluse_hook(_cfg(True, no_secrets=True), str(project), str(musubi))
        # Exactly one entry, now wrapped.
        data = json.loads(_settings_path(project).read_text())
        pre = data["hooks"]["PreToolUse"]
        assert len(pre) == 1
        assert self._command(project).startswith("/usr/bin/env MUSUBI_REPO_HAS_NO_SECRETS=1 ")
        # And flipping back off restores the bare path, still one entry.
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        data = json.loads(_settings_path(project).read_text())
        assert len(data["hooks"]["PreToolUse"]) == 1
        assert "MUSUBI_REPO_HAS_NO_SECRETS" not in self._command(project)


# ---------------------------------------------------------------------------
# Merge / idempotency / update paths
# ---------------------------------------------------------------------------

class TestMergeAndIdempotency:
    def _write_existing(self, project, contents):
        claude_dir = project / ".claude"
        claude_dir.mkdir()
        path = claude_dir / "settings.local.json"
        path.write_text(json.dumps(contents, indent=2))
        return path

    def test_preserves_unrelated_top_level_keys(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        self._write_existing(project, {"permissions": {"allow": ["Read(*)"]}})
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        data = json.loads(_settings_path(project).read_text())
        assert data["permissions"]["allow"] == ["Read(*)"]
        assert "hooks" in data and "PreToolUse" in data["hooks"]

    def test_preserves_other_pretooluse_entries(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        existing_other_entry = {
            "matcher": "Write|Edit",
            "hooks": [
                {"type": "command", "command": "/usr/bin/echo", "timeout": 3}
            ],
        }
        self._write_existing(project, {
            "hooks": {"PreToolUse": [existing_other_entry]},
        })
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        data = json.loads(_settings_path(project).read_text())
        pre = data["hooks"]["PreToolUse"]
        assert len(pre) == 2
        # Existing entry preserved verbatim.
        assert existing_other_entry in pre
        # Musubi entry appended.
        assert any(
            "oya-pretooluse.py" in h.get("command", "")
            for e in pre for h in e.get("hooks", [])
        )

    def test_idempotent_same_path(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        mtime1 = _settings_path(project).stat().st_mtime_ns
        # Second call must not rewrite the file.
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        mtime2 = _settings_path(project).stat().st_mtime_ns
        assert mtime1 == mtime2, "second call rewrote the file (not idempotent)"

    def test_updates_command_path_when_musubi_moves(self, tmp_path):
        project = _make_project(tmp_path)
        # Wire from musubi-old.
        old_musubi = _make_fake_orchestrator(tmp_path / "old")
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(old_musubi))
        old_cmd = json.loads(_settings_path(project).read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert str(old_musubi) in old_cmd

        # Now re-launch from musubi-new (operator moved the checkout).
        new_musubi = _make_fake_orchestrator(tmp_path / "new")
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(new_musubi))
        new_cmd = json.loads(_settings_path(project).read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert str(new_musubi) in new_cmd
        assert str(old_musubi) not in new_cmd
        # Still only ONE musubi entry — not appended.
        pre = json.loads(_settings_path(project).read_text())["hooks"]["PreToolUse"]
        oya_entries = [
            e for e in pre
            if any("oya-pretooluse.py" in h.get("command", "") for h in e.get("hooks", []))
        ]
        assert len(oya_entries) == 1

    def test_existing_manual_wiring_is_detected_and_updated(self, tmp_path):
        # Operator manually added a hook entry with a different matcher/timeout
        # but pointing at oya-pretooluse.py. Auto-wirer should detect it as
        # "ours" (substring match on basename) and normalise to the canonical
        # shape on next launch.
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        manual_entry = {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": "/somewhere/else/scripts/oya-pretooluse.py",
                    "timeout": 99,
                }
            ],
        }
        self._write_existing(project, {
            "hooks": {"PreToolUse": [manual_entry]},
        })
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        pre = json.loads(_settings_path(project).read_text())["hooks"]["PreToolUse"]
        # Still only one entry — the manual one got updated in place.
        assert len(pre) == 1
        assert pre[0]["matcher"] == oyakata.PRETOOLUSE_HOOK_MATCHER
        assert pre[0]["hooks"][0]["timeout"] == oyakata.PRETOOLUSE_HOOK_TIMEOUT
        assert str(musubi) in pre[0]["hooks"][0]["command"]


# ---------------------------------------------------------------------------
# Malformed inputs — defensive paths
# ---------------------------------------------------------------------------

class TestMalformedInputs:
    def _stale_text(self, project, text):
        claude_dir = project / ".claude"
        claude_dir.mkdir()
        path = claude_dir / "settings.local.json"
        path.write_text(text)
        return path

    def test_malformed_json_is_not_overwritten(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        path = self._stale_text(project, "this is not { valid json")
        original = path.read_text()
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        # File preserved exactly — operator must fix or delete by hand.
        assert path.read_text() == original

    def test_non_object_top_level_json_is_not_overwritten(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        path = self._stale_text(project, json.dumps(["not", "an", "object"]))
        original = path.read_text()
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        assert path.read_text() == original

    def test_malformed_hooks_block_is_not_overwritten(self, tmp_path):
        # hooks should be a dict; here it's a string. Don't clobber.
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        path = self._stale_text(project, json.dumps({"hooks": "oops a string"}))
        original = path.read_text()
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        assert path.read_text() == original

    def test_malformed_pretooluse_array_is_not_overwritten(self, tmp_path):
        project = _make_project(tmp_path)
        musubi = _make_fake_orchestrator(tmp_path)
        path = self._stale_text(project, json.dumps({"hooks": {"PreToolUse": "should-be-list"}}))
        original = path.read_text()
        oyakata.auto_wire_pretooluse_hook(_cfg(True), str(project), str(musubi))
        assert path.read_text() == original


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

class TestPermissionsConfigHelper:
    def test_default_false_on_empty_cfg(self):
        assert oyakata.oyakata_permissions_enabled({}) is False

    def test_default_false_without_permissions_block(self):
        assert oyakata.oyakata_permissions_enabled({"agents": {"oyakata": {"enabled": True}}}) is False

    def test_true_when_explicitly_enabled(self):
        cfg = {"agents": {"oyakata": {"permissions": {"enabled": True}}}}
        assert oyakata.oyakata_permissions_enabled(cfg) is True

    def test_false_when_explicitly_disabled(self):
        cfg = {"agents": {"oyakata": {"permissions": {"enabled": False}}}}
        assert oyakata.oyakata_permissions_enabled(cfg) is False
