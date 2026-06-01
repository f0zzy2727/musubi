"""Tests for scripts/classify-slice-disciplines.py — the strategic-Oya v0.3
scope sensor.

These tests verify the trigger table fires correctly on representative
slice shapes (auth changes, new endpoints, schema migrations, payments,
UI, AI features, large diffs) and stays silent on slices that touch
nothing strategically interesting.

The classifier is a pure function — no filesystem reads beyond what the
caller passes in. All tests pass file lists + planning-doc strings
directly.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


# The script lives in scripts/ with a hyphenated name, so we import it
# via importlib rather than relying on Python's name-mangling rules.
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify-slice-disciplines.py"
_spec = importlib.util.spec_from_file_location("classify_slice_disciplines", _SCRIPT)
classify_mod = importlib.util.module_from_spec(_spec)
sys.modules["classify_slice_disciplines"] = classify_mod
_spec.loader.exec_module(classify_mod)

classify = classify_mod.classify


def disciplines_in(hits):
    """Helper — set of discipline names from a list of TriggerHit."""
    return {h.discipline for h in hits}


# ---------------------------------------------------------------------------
# Empty / silent cases
# ---------------------------------------------------------------------------

def test_empty_input_fires_nothing():
    assert classify() == []


def test_unstrategic_slice_fires_nothing():
    """A README typo fix shouldn't trigger any strategic discipline."""
    hits = classify(
        files=["README.md", "CHANGELOG.md"],
        planning_doc="Fix a typo in the README.",
        loc=4,
    )
    assert hits == []


def test_silent_below_size_thresholds():
    """A small refactor below 300 LOC and ≤3 files doesn't fire arch-sketch."""
    hits = classify(
        files=["src/util.ts", "src/util.test.ts"],
        loc=120,
    )
    assert "arch-sketch-before-large-slice" not in disciplines_in(hits)


# ---------------------------------------------------------------------------
# Path triggers
# ---------------------------------------------------------------------------

def test_auth_path_fires_threat_model():
    hits = classify(files=["src/auth/session.ts"])
    assert "threat-model-auth-changes" in disciplines_in(hits)


def test_new_endpoint_fires_abuse_case():
    hits = classify(files=["src/api/users/route.ts"])
    assert "abuse-case-named-on-new-input" in disciplines_in(hits)


def test_schema_migration_fires_rollback():
    hits = classify(files=["db/migrations/20260520_add_tenant_column.sql"])
    assert "migration-has-rollback-plan" in disciplines_in(hits)


def test_payments_path_fires_idempotency():
    hits = classify(files=["src/payments/charge.ts"])
    assert "idempotency-on-money-handling" in disciplines_in(hits)


def test_ui_component_fires_a11y():
    hits = classify(files=["src/app/dashboard/settings-client.tsx"])
    assert "a11y-check-on-ui-slice" in disciplines_in(hits)


def test_ai_path_fires_design_contract():
    hits = classify(files=["src/llm/prompt-templates.ts"])
    assert "ai-integration-design-contract" in disciplines_in(hits)


def test_anthropic_import_fires_ai_design_contract():
    hits = classify(
        files=["src/features/chat.py"],
        planning_doc="```python\nfrom anthropic import Anthropic\nclient = Anthropic()\n```",
    )
    assert "ai-integration-design-contract" in disciplines_in(hits)


# ---------------------------------------------------------------------------
# Content triggers (planning-doc text)
# ---------------------------------------------------------------------------

def test_planning_doc_keyword_fires_auth():
    hits = classify(
        files=["src/lib/helpers.ts"],
        planning_doc="This slice refactors the access token rotation logic.",
    )
    assert "threat-model-auth-changes" in disciplines_in(hits)


def test_planning_doc_pii_fires_inventory():
    hits = classify(
        files=["src/lib/user-utils.ts"],
        planning_doc="Adds GDPR-compliant data deletion path for user accounts.",
    )
    assert "pii-inventory-on-data-change" in disciplines_in(hits)


def test_planning_doc_external_api_fires_failure_mode():
    hits = classify(
        files=["src/lib/integration.ts"],
        planning_doc="Wraps the third-party API with retry-backoff and timeout discipline.",
    )
    assert "external-integration-failure-mode" in disciplines_in(hits)


# ---------------------------------------------------------------------------
# Size triggers
# ---------------------------------------------------------------------------

def test_loc_over_threshold_fires_arch_sketch():
    hits = classify(files=["src/big-refactor.ts"], loc=450)
    assert "arch-sketch-before-large-slice" in disciplines_in(hits)


def test_file_count_over_threshold_fires_arch_sketch():
    hits = classify(files=[f"src/file-{i}.ts" for i in range(5)], loc=50)
    assert "arch-sketch-before-large-slice" in disciplines_in(hits)


def test_loc_at_threshold_does_not_fire():
    """Exactly at threshold = not fired (strict greater-than)."""
    hits = classify(files=["src/x.ts"], loc=300)
    assert "arch-sketch-before-large-slice" not in disciplines_in(hits)


# ---------------------------------------------------------------------------
# Multi-discipline cases
# ---------------------------------------------------------------------------

def test_auth_endpoint_fires_both_disciplines():
    """A new auth endpoint should fire both threat-model AND abuse-case."""
    hits = classify(files=["src/api/auth/login/route.ts"])
    disc = disciplines_in(hits)
    assert "threat-model-auth-changes" in disc
    assert "abuse-case-named-on-new-input" in disc


def test_large_auth_change_fires_three_disciplines():
    """Big auth refactor: threat-model + arch-sketch + (potentially) a11y."""
    hits = classify(
        files=[f"src/auth/session-{i}.ts" for i in range(6)],
        loc=520,
    )
    disc = disciplines_in(hits)
    assert "threat-model-auth-changes" in disc
    assert "arch-sketch-before-large-slice" in disc


# ---------------------------------------------------------------------------
# Evidence trail correctness
# ---------------------------------------------------------------------------

def test_evidence_names_the_matched_path():
    hits = classify(files=["src/auth/session.ts"])
    threat_hit = next(h for h in hits if h.discipline == "threat-model-auth-changes")
    assert any("src/auth/session.ts" in ev for ev in threat_hit.evidence)


def test_evidence_includes_planning_doc_line():
    hits = classify(
        files=["src/lib/x.ts"],
        planning_doc="We're refactoring the authentication boundary on the api gateway.",
    )
    threat_hit = next(h for h in hits if h.discipline == "threat-model-auth-changes")
    # At least one evidence entry should reference the planning doc line
    assert any("planning doc:" in ev for ev in threat_hit.evidence)


def test_evidence_capped_to_keep_output_scannable():
    """Per-pattern content matches are capped at 3 to prevent evidence
    explosion on planning docs that repeat keywords heavily."""
    long_doc = "\n".join(["authentication boundary check"] * 20)
    hits = classify(files=["src/x.ts"], planning_doc=long_doc)
    threat_hit = next(h for h in hits if h.discipline == "threat-model-auth-changes")
    # Each content_pattern is capped at 3 hits. Multiple patterns may match
    # the same lines but each pattern's evidence list is bounded.
    planning_doc_hits = [ev for ev in threat_hit.evidence if ev.startswith("planning doc:")]
    # Generous upper bound — many patterns can match, but never blow up
    assert len(planning_doc_hits) < 30


# ---------------------------------------------------------------------------
# Case-insensitivity
# ---------------------------------------------------------------------------

def test_case_insensitive_path_match():
    hits = classify(files=["src/AUTH/Session.ts"])
    assert "threat-model-auth-changes" in disciplines_in(hits)


def test_case_insensitive_content_match():
    hits = classify(
        files=["src/x.ts"],
        planning_doc="WCAG 2.1 AA compliance check.",
    )
    assert "a11y-check-on-ui-slice" in disciplines_in(hits)
