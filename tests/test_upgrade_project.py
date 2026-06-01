"""Tests for scripts/upgrade_project.py — Slice 6 / upgrade path.

Critical safety properties to verify:
  - Counter values are NEVER modified on existing rules
  - Idempotent (re-run after apply is a no-op)
  - Empty ledger gets all framework rules
  - Partial ledger gets only the missing rules
  - Auto-backups happen before any write
  - Audit-mode never writes anything
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml


# Load the upgrade script via importlib (hyphenated path-like behaviour).
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "upgrade_project.py"
_spec = importlib.util.spec_from_file_location("upgrade_project", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
sys.modules["upgrade_project"] = _module
_spec.loader.exec_module(_module)


@pytest.fixture
def fake_project(tmp_path):
    """Build a minimal target project layout under tmp_path."""
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    return tmp_path


def write_ledger(project_path, rules_yaml):
    """Write a rules-ledger.yml at the canonical location."""
    ledger_path = project_path / "docs" / "agents" / "rules-ledger.yml"
    full_yaml = f"""schema_version: 1
project: test-project
runbook_version: "1.7"
generated_at: 2026-05-20T00:00:00Z
last_updated_at: 2026-05-20T00:00:00Z
last_updated_cycle: initial-bootstrap

rules:
{rules_yaml}

  # ─── Project-specific STOP rules ───────────────────────────────────────

# ─── Reviewer calibration (Brier scoring, opt-in per Review Result) ──────
reviewer_calibration: []

# ─── Cycle-close summaries (Oya appends one per cycle close) ─────────────
cycle_summary: []
"""
    ledger_path.write_text(full_yaml)
    return ledger_path


def write_musubi_toml(project_path, content):
    (project_path / "musubi.toml").write_text(content)


# ---------------------------------------------------------------------------
# audit_ledger
# ---------------------------------------------------------------------------

class TestAuditLedger:
    def test_missing_ledger_reports_all_template_rules_as_missing(self, fake_project):
        # No ledger file at all
        result = _module.audit_ledger(str(fake_project))
        assert result["target_ledger"] is None
        assert len(result["missing"]) > 0
        assert "threat-model-auth-changes" in [r["id"] for r in result["missing"]]

    def test_empty_ledger_reports_all_template_rules_as_missing(self, fake_project):
        write_ledger(fake_project, "  []")
        result = _module.audit_ledger(str(fake_project))
        # Missing = all template rules
        assert len(result["missing"]) == len(result["template_rules"])

    def test_fully_populated_ledger_reports_no_missing(self, fake_project):
        # Copy the entire framework template as the target's ledger
        template_path = _module.TEMPLATE_LEDGER
        target_path = fake_project / "docs" / "agents" / "rules-ledger.yml"
        # Replace placeholders so it parses
        text = template_path.read_text()
        text = (text.replace("<PROJECT-SLUG>", "test-project")
                    .replace("<SET-AT-BOOTSTRAP>", "2026-05-20T00:00:00Z"))
        target_path.write_text(text)

        result = _module.audit_ledger(str(fake_project))
        assert result["missing"] == []

    def test_partial_ledger_reports_only_missing(self, fake_project):
        # Ledger has ONLY the threat-model-auth-changes rule
        write_ledger(fake_project, """
  - id: threat-model-auth-changes
    type: strategic-discipline
    scope: framework
    runbook_section: "docs/operator/strategic-disciplines.md"
    citation_pattern: "threat-model-auth-changes"
    provenance:
      added_in_runbook_version: "1.8"
      added_on: 2026-05-20
      added_reason: |
        seeded
    fires: { total: 5, by_cycle: {} }
    catches: { total: 2, by_class: {}, examples: [] }
    bypasses: { total: 0, examples: [] }
    skipped: { total: 1, examples: [] }
    silent_misses: { total: 0, examples: [] }
    notes: ""
""")
        result = _module.audit_ledger(str(fake_project))
        missing_ids = [r["id"] for r in result["missing"]]
        assert "threat-model-auth-changes" not in missing_ids
        # All other framework rules should be missing
        assert len(missing_ids) >= 9


# ---------------------------------------------------------------------------
# audit_musubi_toml
# ---------------------------------------------------------------------------

class TestAuditTomlBlock:
    def test_no_toml_file(self, fake_project):
        result = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert result["exists"] is False

    def test_toml_with_no_requires_block(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

[agents.opus]
name = "Opus"
handle = "@OPUS"
cli = "claude"

[agents.coda]
name = "Coda"
handle = "@CODA"
cli = "codex"

[comms]
file = "comms.txt"
over_signal = "<OVER>"

[tmux]
session_name = "musubi"
""")
        result = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert result["exists"] is True
        assert result["active"] is False
        assert result["commented_present"] is False

    def test_toml_with_active_block(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

[requires.skills]
core = ["cso"]

[agents.opus]
name = "Opus"
handle = "@OPUS"
cli = "claude"

[agents.coda]
name = "Coda"
handle = "@CODA"
cli = "codex"

[comms]
file = "comms.txt"
over_signal = "<OVER>"

[tmux]
session_name = "musubi"
""")
        result = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert result["active"] is True

    def test_toml_with_commented_block(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

[agents.opus]
name = "Opus"
handle = "@OPUS"
cli = "claude"

[agents.coda]
name = "Coda"
handle = "@CODA"
cli = "codex"

[comms]
file = "comms.txt"
over_signal = "<OVER>"

[tmux]
session_name = "musubi"

# [requires.skills]
# core = ["cso"]
""")
        result = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert result["active"] is False
        assert result["commented_present"] is True


# ---------------------------------------------------------------------------
# apply_ledger_merge (the critical safety property)
# ---------------------------------------------------------------------------

class TestApplyLedgerMerge:
    def test_apply_appends_missing_rules(self, fake_project):
        write_ledger(fake_project, """
  - id: threat-model-auth-changes
    type: strategic-discipline
    scope: framework
    runbook_section: "docs/operator/strategic-disciplines.md"
    citation_pattern: "threat-model-auth-changes"
    provenance:
      added_in_runbook_version: "1.8"
      added_on: 2026-05-20
      added_reason: |
        seeded
    fires: { total: 7, by_cycle: {cycle-a: 7} }
    catches: { total: 3, by_class: {test-design: 3}, examples: [] }
    bypasses: { total: 0, examples: [] }
    skipped: { total: 2, examples: [] }
    silent_misses: { total: 0, examples: [] }
    notes: "live counter data preserved"
""")
        ledger_path = fake_project / "docs" / "agents" / "rules-ledger.yml"
        before = ledger_path.read_text()

        audit = _module.audit_ledger(str(fake_project))
        result = _module.apply_ledger_merge(audit, ledger_path)

        after = ledger_path.read_text()
        assert result is not None
        assert result["backup"].exists()
        assert len(result["added_ids"]) >= 9  # 10 strategic - 1 already present

        # CRITICAL: the original rule's counter section must survive verbatim
        assert "total: 7" in after, "fire count was modified"
        assert "cycle-a: 7" in after, "by_cycle entry was lost"
        assert "live counter data preserved" in after, "notes were lost"
        # Original rule still present (not duplicated by id)
        assert after.count("- id: threat-model-auth-changes") == 1

    def test_apply_idempotent_after_full_population(self, fake_project):
        # Apply once
        write_ledger(fake_project, "  []")
        audit = _module.audit_ledger(str(fake_project))
        ledger_path = fake_project / "docs" / "agents" / "rules-ledger.yml"
        _module.apply_ledger_merge(audit, ledger_path)

        # Second audit should find nothing missing
        audit2 = _module.audit_ledger(str(fake_project))
        assert audit2["missing"] == []

    def test_backup_file_created(self, fake_project):
        write_ledger(fake_project, "  []")
        audit = _module.audit_ledger(str(fake_project))
        ledger_path = fake_project / "docs" / "agents" / "rules-ledger.yml"
        result = _module.apply_ledger_merge(audit, ledger_path)
        assert result["backup"].exists()
        assert "backup" in result["backup"].name


# ---------------------------------------------------------------------------
# apply_toml_append
# ---------------------------------------------------------------------------

class TestApplyTomlAppend:
    def test_appends_commented_block(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

[tmux]
session_name = "musubi"
""")
        toml_audit = _module.audit_musubi_toml(fake_project / "musubi.toml")
        result = _module.apply_toml_append(toml_audit)
        assert result is not None
        text = (fake_project / "musubi.toml").read_text()
        assert "# [requires.skills]" in text

    def test_no_op_when_block_already_active(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

[requires.skills]
core = ["cso"]
""")
        toml_audit = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert _module.apply_toml_append(toml_audit) is None

    def test_no_op_when_block_already_commented(self, fake_project):
        write_musubi_toml(fake_project, """[project]
path = "/tmp"

# [requires.skills]
# core = ["cso"]
""")
        toml_audit = _module.audit_musubi_toml(fake_project / "musubi.toml")
        assert _module.apply_toml_append(toml_audit) is None
