"""Tests for scripts/write-oya-settings.py (robust-1).

The helper replaced a shell heredoc that interpolated $TARGET / $MUSUBI_ROOT
straight into JSON. These tests pin the two things that mattered:
  - the allowlist content is preserved (same entries, paths substituted), and
  - paths containing quotes / backslashes / `$` produce VALID JSON (the exact
    case the heredoc corrupted).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

HELPER_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "write-oya-settings.py"

_spec = importlib.util.spec_from_file_location("write_oya_settings", HELPER_PATH)
write_oya_settings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(write_oya_settings)


class TestBuildSettings:
    def test_shape_and_entry_count(self):
        data = write_oya_settings.build_settings("/proj", "/musubi")
        assert set(data) == {"permissions"}
        allow = data["permissions"]["allow"]
        assert isinstance(allow, list)
        assert len(allow) == 27  # 20 Read/Edit/Write + 7 Bash

    def test_paths_substituted(self):
        allow = write_oya_settings.build_settings("/proj", "/musubi")["permissions"]["allow"]
        assert "Read(/proj/**)" in allow
        assert "Read(/musubi/**)" in allow
        assert "Edit(/proj/docs/agents/oyakata-log.md)" in allow
        # Static Bash entries are unaffected by paths.
        assert "Bash(pwd)" in allow

    def test_trailing_slashes_stripped(self):
        allow = write_oya_settings.build_settings("/proj/", "/musubi/")["permissions"]["allow"]
        assert "Read(/proj/**)" in allow
        assert "Read(/musubi/**)" in allow

    @pytest.mark.parametrize("nasty", [
        '/tmp/we"ird/path',          # double quote
        r"/tmp/back\slash",          # backslash
        "/tmp/dollar$VAR/path",      # `$` — the heredoc-expansion case
        '/tmp/all"\\$/mix',          # all three
    ])
    def test_special_chars_produce_valid_json(self, nasty):
        """The whole point of robust-1: these paths must round-trip as valid
        JSON rather than corrupting the document (as the heredoc did)."""
        data = write_oya_settings.build_settings(nasty, "/musubi")
        rendered = json.dumps(data)
        reparsed = json.loads(rendered)
        assert reparsed == data
        # The literal path survives intact inside the permission string.
        assert any(nasty.rstrip("/") in entry for entry in reparsed["permissions"]["allow"])


class TestMain:
    def test_writes_valid_file(self, tmp_path):
        out = tmp_path / ".claude" / "settings.local.json"
        out.parent.mkdir(parents=True)
        rc = write_oya_settings.main(["prog", "/proj", "/musubi", str(out)])
        assert rc == 0
        data = json.loads(out.read_text())
        assert "Read(/proj/**)" in data["permissions"]["allow"]

    def test_wrong_arg_count_returns_2(self):
        assert write_oya_settings.main(["prog", "only-one"]) == 2

    def test_nasty_path_file_is_valid_json(self, tmp_path):
        out = tmp_path / "settings.local.json"
        rc = write_oya_settings.main(["prog", '/p"a\\th$X', "/musubi", str(out)])
        assert rc == 0
        # Must parse — the heredoc would have produced a broken file here.
        json.loads(out.read_text())
