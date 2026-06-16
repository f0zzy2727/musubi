"""Reproducible benchmark artifact (pkg-1).

The external audit noted the benchmark claims were prose-only. comms-metrics.py
already emits JSON; this test makes one artifact *reproducible from committed
data*: it re-runs the metrics over the committed fixture comms thread and
asserts the output matches the committed artifact byte-for-value. If anyone
changes the metric definitions OR the fixture, the artifact must be
regenerated — which is exactly the reproducibility guarantee the audit asked
for.

Regenerate the artifact after an intentional change:
  python3 scripts/comms-metrics.py tests/fixtures/comms-sample/docs/agents \
      --json docs/positioning/benchmarks/artifacts/sample-metrics.json
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "comms_metrics", ROOT / "scripts" / "comms-metrics.py"
)
comms_metrics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(comms_metrics)

FIXTURE = ROOT / "tests" / "fixtures" / "comms-sample" / "docs" / "agents"
ARTIFACT = ROOT / "docs" / "positioning" / "benchmarks" / "artifacts" / "sample-metrics.json"


def _recompute() -> dict:
    return comms_metrics.analyze(comms_metrics.find_files(str(FIXTURE)))


def test_artifact_matches_recomputed_metrics():
    """The committed artifact is exactly what the tool produces on the fixture.
    Drift here means the artifact is stale — regenerate it (see module docstring)."""
    committed = json.loads(ARTIFACT.read_text())["comms-sample"]
    assert _recompute() == committed


def test_fixture_demonstrates_a_genuine_contested_exchange():
    """Guards the narrative the fixture is meant to show: a substantive catch,
    a formal dissent, and both contested slices resolved over multiple rounds
    (not rubber-stamped)."""
    m = json.loads(ARTIFACT.read_text())["comms-sample"]
    assert m["review_results"] == 4
    assert m["substantive_review_rate"] == 0.25
    assert m["formal_dissent_rate"] == 0.25
    assert m["zero_finding_approve_rate"] == 0.5
    assert m["contested_slices"] == 2
    assert m["multi_round_contested_rate"] == 1.0
    assert m["single_exchange_contested_rate"] == 0.0
