"""Tests for scripts/classify-slice.sh — the protocol-1 mechanical lane
classifier. Invoked via subprocess with explicit --files/--loc so the tests
are hermetic (no dependence on the repo's actual staged state)."""
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify-slice.sh"


def classify(files, loc):
    out = subprocess.run(
        ["bash", str(_SCRIPT), "--loc", str(loc), "--format", "json",
         "--files", *files],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


@pytest.mark.parametrize("files,loc,expected", [
    (["README.md"], 5, "tiny"),
    (["a.md", "b.txt"], 18, "tiny"),
    (["package.json"], 3, "tiny"),
    (["poetry.lock"], 2, "tiny"),
    (["requirements.txt"], 4, "tiny"),
    (["docs/guide.md"], 120, "lightweight"),          # docs but >20 LOC
    (["a.md", "b.md", "c.md"], 10, "lightweight"),     # docs but >2 files
    (["src/util.ts"], 12, "lightweight"),              # single small code change
    (["src/a.ts", "src/b.ts"], 40, "heavy"),           # multi-file code
    (["src/big.ts"], 350, "heavy"),                    # >300 LOC
    (["src/App.tsx"], 5, "heavy"),                      # UI
    (["db/migrations/001.sql"], 5, "heavy"),            # schema
    ([".github/workflows/ci.yml"], 3, "heavy"),         # CI
    (["docs/agents/current-state.md"], 4, "heavy"),     # state file (also .md!)
    (["docs/agents/agent-handoff.md"], 4, "heavy"),     # state file
])
def test_lane(files, loc, expected):
    result = classify(files, loc)
    assert result["lane"] == expected, f"{files} @ {loc} LOC -> {result}"


def test_state_file_beats_doc_classification():
    # current-state.md is *.md but must classify heavy, not tiny — the state
    # check has to run before the doc check.
    assert classify(["docs/agents/current-state.md"], 2)["lane"] == "heavy"


def test_text_format_emits_lane_line():
    out = subprocess.run(
        ["bash", str(_SCRIPT), "--loc", "5", "--files", "README.md"],
        capture_output=True, text=True, check=True,
    )
    assert "Lane: tiny" in out.stdout


def test_reasons_present():
    result = classify(["src/App.tsx"], 5)
    assert any("UI" in r for r in result["reasons"])


# --- blast_radius: a SEPARATE axis from the lane (forced-debate gating) -------

@pytest.mark.parametrize("files,loc,expected", [
    (["db/migrations/001.sql"], 5, "high"),        # schema — destructive surface
    (["src/App.tsx"], 5, "high"),                  # UI
    ([".github/workflows/ci.yml"], 3, "high"),     # CI
    (["docs/agents/current-state.md"], 4, "high"), # state file
    (["src/big.ts"], 350, "high"),                 # >300 LOC
    (["README.md"], 5, "low"),                     # docs
    (["src/util.ts"], 12, "low"),                  # small code
])
def test_blast_radius(files, loc, expected):
    assert classify(files, loc)["blast_radius"] == expected, files


def test_blast_radius_orthogonal_to_lane():
    # A multi-file code change is heavy LANE but LOW blast radius — the two axes
    # must not collapse into one (debate ceremony shouldn't fire on plain code).
    result = classify(["src/a.ts", "src/b.ts"], 40)
    assert result["lane"] == "heavy"
    assert result["blast_radius"] == "low"


def test_text_format_emits_blast_radius_line():
    out = subprocess.run(
        ["bash", str(_SCRIPT), "--loc", "5", "--files", "db/migrations/001.sql"],
        capture_output=True, text=True, check=True,
    )
    assert "Blast radius: high" in out.stdout
