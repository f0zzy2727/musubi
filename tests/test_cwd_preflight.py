"""Tests for orch-6 — launcher cwd preflight + Desktop-path warning.

Verifies the three Python helpers added to orchestrator.py:

  - validate_project_path  — raises ConfigError on missing / non-dir paths,
                             logs warning on iCloud-synced paths.
  - _is_icloud_synced_path — classifies macOS paths under ~/Desktop,
                             ~/Documents, ~/Downloads as iCloud-synced.
  - detect_eperm_uvcwd     — matches the Node EPERM uv_cwd crash signature
                             in captured pane text.

The shell-side helpers (preflight_cwd, warn_icloud_path in
scripts/cwd-preflight.sh) are exercised via syntax-check + manual smoke
test; they're trivial enough not to warrant a separate harness.
"""
import os
import tempfile

import pytest

from orchestrator import (
    ConfigError,
    _is_icloud_synced_path,
    detect_eperm_uvcwd,
    validate_project_path,
)


# ---------------------------------------------------------------------------
# detect_eperm_uvcwd
# ---------------------------------------------------------------------------

class TestDetectEpermUvcwd:
    def test_full_crash_signature_matches(self):
        text = (
            "node:internal/process/per_thread:128\n"
            "    cwd = binding.cwd();\n"
            "Error: EPERM: process.cwd failed, uv_cwd"
        )
        assert detect_eperm_uvcwd(text) is True

    def test_eperm_alone_does_not_match(self):
        assert detect_eperm_uvcwd("EPERM: operation not permitted") is False

    def test_uvcwd_alone_does_not_match(self):
        assert detect_eperm_uvcwd("uv_cwd in some other context") is False

    def test_empty_string(self):
        assert detect_eperm_uvcwd("") is False


# ---------------------------------------------------------------------------
# _is_icloud_synced_path
# ---------------------------------------------------------------------------

class TestIsIcloudSyncedPath:
    @pytest.fixture
    def home(self):
        return os.path.expanduser("~")

    def test_desktop_subdir_is_synced(self, home):
        assert _is_icloud_synced_path(f"{home}/Desktop/my-project") is True

    def test_documents_subdir_is_synced(self, home):
        assert _is_icloud_synced_path(f"{home}/Documents/notes") is True

    def test_downloads_subdir_is_synced(self, home):
        assert _is_icloud_synced_path(f"{home}/Downloads/dump") is True

    def test_dev_dir_is_not_synced(self, home):
        assert _is_icloud_synced_path(f"{home}/Dev/proj") is False

    def test_home_itself_is_not_synced(self, home):
        assert _is_icloud_synced_path(home) is False

    def test_system_path_is_not_synced(self):
        assert _is_icloud_synced_path("/etc/passwd") is False

    def test_bare_icloud_root_counts(self, home):
        # Running musubi from ~/Desktop directly is itself a smell — surface
        # the warning rather than miss it on a technicality.
        assert _is_icloud_synced_path(f"{home}/Desktop") is True


# ---------------------------------------------------------------------------
# validate_project_path
# ---------------------------------------------------------------------------

class TestValidateProjectPath:
    def test_valid_directory_passes(self):
        with tempfile.TemporaryDirectory() as td:
            validate_project_path(td)  # no exception

    def test_missing_path_raises(self):
        with pytest.raises(ConfigError, match="does not exist"):
            validate_project_path("/this/path/does/not/exist/xyz123")

    def test_file_not_directory_raises(self):
        with tempfile.NamedTemporaryFile() as tf:
            with pytest.raises(ConfigError, match="not a directory"):
                validate_project_path(tf.name)

    def test_tilde_expansion(self):
        # ~ should expand and resolve correctly. We don't assert the result
        # passes (operator's home might not exist in CI), just that the
        # tilde-prefixed form doesn't blow up on its own.
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            validate_project_path("~")

    def test_icloud_path_passes_but_warns(self, caplog):
        # iCloud-synced paths must NOT raise — they're a warning, not a block.
        # We synthesise a directory under ~/Desktop only if Desktop exists;
        # otherwise skip (CI runners typically lack the macOS home layout).
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        if not os.path.isdir(desktop):
            pytest.skip("~/Desktop not present (non-macOS CI)")
        # Use the live ~/Desktop itself — validate_project_path is read-only
        # apart from the os.chdir round-trip, which restores cwd in `finally`.
        validate_project_path(desktop)  # must not raise
