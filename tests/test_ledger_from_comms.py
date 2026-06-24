"""Tests for scripts/ledger-from-comms.py — mechanical rules-ledger fire
counting (protocol-1 Tier 1 item 3).

Covers: citation-pattern message-counting, per-cycle attribution, cycle-slug
derivation, the both-format (flow + expanded) write-back preserving every
non-fires byte, idempotency / --check, and malformed-comms tolerance.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


# Hyphenated script name — import via importlib (same pattern as the
# classify-slice-disciplines test).
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ledger-from-comms.py"
_spec = importlib.util.spec_from_file_location("ledger_from_comms", _SCRIPT)
lfc = importlib.util.module_from_spec(_spec)
sys.modules["ledger_from_comms"] = lfc
_spec.loader.exec_module(lfc)


# --- fixtures -------------------------------------------------------------

# A ledger with BOTH fires formats: flow-style (rule-a) and expanded (rule-b),
# plus surrounding comments + a sibling `catches:` key that must survive.
LEDGER_MIXED = """\
schema_version: 1
project: test
last_updated_at: 2026-05-20T11:43:00Z
last_updated_cycle: old-cycle-2026-05-20

rules:

  # comment above rule a — must be preserved
  - id: rule-a
    type: discipline
    citation_pattern: "STOP rule 18"
    fires: { total: 0, by_cycle: {} }
    catches: { total: 0, by_class: {}, examples: [] }
    notes: "keep me"

  - id: rule-b
    type: guard
    citation_pattern: "GO baton"
    fires:
      total: 0
      by_cycle: {}
    catches: { total: 0, by_class: {}, examples: [] }
    notes: ""

  - id: rule-c
    type: discipline
    citation_pattern: "never appears anywhere"
    fires: { total: 0, by_cycle: {} }
    catches: { total: 0, by_class: {}, examples: [] }
"""


def _msg(handle, body):
    sep = "-" * 51
    return f"{sep}\n[{handle}] [2026-05-15] [11:44 UTC]\n{body}\n<OVER>\n"


@pytest.fixture
def ledger_file(tmp_path):
    p = tmp_path / "rules-ledger.yml"
    p.write_text(LEDGER_MIXED)
    return p


# --- load_rules -----------------------------------------------------------

def test_load_rules_extracts_id_and_pattern(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    assert {r.id for r in rules} == {"rule-a", "rule-b", "rule-c"}
    by_id = {r.id: r.citation_pattern for r in rules}
    assert by_id["rule-a"] == "STOP rule 18"


# --- cycle slug derivation ------------------------------------------------

def test_cycle_slug_from_archive_name():
    assert lfc.cycle_slug_for("x/comms-2026-05-15-token-cleanup-001.txt") == \
        "2026-05-15-token-cleanup-001"


def test_cycle_slug_override_wins():
    assert lfc.cycle_slug_for("comms-foo.txt", override="my-cycle") == "my-cycle"


def test_cycle_slug_non_conforming_uses_stem():
    assert lfc.cycle_slug_for("active.txt") == "active"


# --- fire counting --------------------------------------------------------

def test_counts_fires_per_message_not_per_occurrence(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    # One message mentions "STOP rule 18" twice -> counts as ONE fire.
    text = _msg("@OPUS", "per STOP rule 18, and again STOP rule 18 baseline")
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    lfc.count_fires(rules, text, "cycle-x", acc)
    assert acc["rule-a"].total == 1
    assert acc["rule-a"].by_cycle == {"cycle-x": 1}


def test_two_messages_two_fires(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    text = _msg("@OPUS", "STOP rule 18 here") + _msg("@CODA", "and STOP rule 18 there")
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    lfc.count_fires(rules, text, "cycle-x", acc)
    assert acc["rule-a"].total == 2


def test_silent_rule_stays_zero(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    text = _msg("@OPUS", "GO baton handed over")
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    lfc.count_fires(rules, text, "cycle-x", acc)
    assert acc["rule-c"].total == 0
    assert acc["rule-b"].total == 1  # GO baton matched


def test_citation_match_is_case_insensitive(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    text = _msg("@OPUS", "invoking go BATON now")
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    lfc.count_fires(rules, text, "c", acc)
    assert acc["rule-b"].total == 1


# --- widened matching: aliases + regex (fire-counter under-count fix) ------

# A rule whose literal citation_pattern is the dashed slug, but agents type
# paraphrases. Aliases + a regex widen the fire detection.
LEDGER_WIDENED = """\
schema_version: 1
project: test
rules:
  - id: capsule-staleness
    type: guard
    citation_pattern: "capsule-staleness"
    citation_aliases:
      - "capsule is stale"
      - "stale capsule"
    citation_regex: "capsule .{0,20}(?:stale|out of date)"
    fires: { total: 0, by_cycle: {} }
  - id: literal-only
    type: discipline
    citation_pattern: "exact-only-token"
    fires: { total: 0, by_cycle: {} }
"""


@pytest.fixture
def widened_ledger(tmp_path):
    p = tmp_path / "rules-ledger.yml"
    p.write_text(LEDGER_WIDENED)
    return p


def test_load_rules_reads_aliases_and_regex(widened_ledger):
    rules = {r.id: r for r in lfc.load_rules(str(widened_ledger))}
    r = rules["capsule-staleness"]
    assert r.citation_aliases == ["capsule is stale", "stale capsule"]
    assert r.citation_regex == "capsule .{0,20}(?:stale|out of date)"
    # A rule without the new fields defaults cleanly (backward compatible).
    assert rules["literal-only"].citation_aliases == []
    assert rules["literal-only"].citation_regex == ""


def test_alias_paraphrase_counts_as_fire(widened_ledger):
    rules = lfc.load_rules(str(widened_ledger))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    # Agent never types the dashed slug — uses an alias.
    text = _msg("@OYA", "the capsule is stale, regenerate before GO")
    lfc.count_fires(rules, text, "c", acc)
    assert acc["capsule-staleness"].total == 1


def test_regex_paraphrase_counts_as_fire(widened_ledger):
    rules = lfc.load_rules(str(widened_ledger))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    # Matches the regex, not the literal or aliases.
    text = _msg("@OYA", "that capsule looks out of date to me")
    lfc.count_fires(rules, text, "c", acc)
    assert acc["capsule-staleness"].total == 1


def test_one_fire_per_block_even_with_multiple_alias_hits(widened_ledger):
    rules = lfc.load_rules(str(widened_ledger))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    text = _msg("@OYA", "capsule is stale AND stale capsule AND capsule-staleness")
    lfc.count_fires(rules, text, "c", acc)
    assert acc["capsule-staleness"].total == 1  # per-message, not per-pattern


def test_literal_only_rule_unaffected_by_widening(widened_ledger):
    rules = lfc.load_rules(str(widened_ledger))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    text = _msg("@OPUS", "no token here") + _msg("@CODA", "exact-only-token present")
    lfc.count_fires(rules, text, "c", acc)
    assert acc["literal-only"].total == 1


def test_invalid_regex_is_dropped_not_fatal(tmp_path, capsys):
    led = tmp_path / "rules-ledger.yml"
    led.write_text(
        "schema_version: 1\nrules:\n"
        '  - id: bad-regex\n    citation_pattern: "anchor"\n'
        '    citation_regex: "("\n    fires: { total: 0, by_cycle: {} }\n'
    )
    rules = lfc.load_rules(str(led))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    # The bad regex is ignored; the literal still fires.
    lfc.count_fires(rules, _msg("@OPUS", "anchor holds"), "c", acc)
    assert acc["bad-regex"].total == 1
    assert "ignoring invalid citation_regex" in capsys.readouterr().err


# --- write-back: both formats + byte preservation -------------------------

def test_apply_updates_both_flow_and_expanded(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    acc["rule-a"].total = 3
    acc["rule-a"].by_cycle = {"cyc1": 3}
    acc["rule-b"].total = 5
    acc["rule-b"].by_cycle = {"cyc1": 2, "cyc2": 3}

    new_text, changed = lfc.apply_fires(ledger_file.read_text(), acc)
    assert changed == 2  # rule-c unchanged (0 -> 0)

    import yaml
    d = yaml.safe_load(new_text)
    by_id = {r["id"]: r for r in d["rules"]}
    assert by_id["rule-a"]["fires"] == {"total": 3, "by_cycle": {"cyc1": 3}}
    assert by_id["rule-b"]["fires"]["total"] == 5
    assert by_id["rule-b"]["fires"]["by_cycle"] == {"cyc1": 2, "cyc2": 3}
    # sibling keys + comments survive
    assert by_id["rule-a"]["notes"] == "keep me"
    assert by_id["rule-a"]["catches"]["total"] == 0
    assert "# comment above rule a — must be preserved" in new_text


def test_apply_only_touches_fires_lines(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    acc["rule-a"].total = 9
    acc["rule-a"].by_cycle = {"c": 9}
    original = ledger_file.read_text()
    new_text, _ = lfc.apply_fires(original, acc)
    # Expanded fires collapse to one line, so line numbers shift; assert
    # instead that every non-fires line from the original survives verbatim.
    # (catches blocks here are flow-style, so the only bare total:/by_cycle:
    # lines belong to expanded fires mappings.)
    new_lines = set(new_text.splitlines())
    for o in original.splitlines():
        s = o.strip()
        if s.startswith(("fires:", "total:", "by_cycle:")):
            continue
        assert o in new_lines, f"non-fires line lost: {o!r}"


def test_apply_is_idempotent(ledger_file):
    rules = lfc.load_rules(str(ledger_file))
    acc = {r.id: lfc.RuleFire(r.id, r.citation_pattern) for r in rules}
    acc["rule-a"].total = 4
    acc["rule-a"].by_cycle = {"c": 4}
    once, _ = lfc.apply_fires(ledger_file.read_text(), acc)
    twice, changed2 = lfc.apply_fires(once, acc)
    assert once == twice
    assert changed2 == 0


def test_split_rule_blocks_roundtrips(ledger_file):
    text = ledger_file.read_text()
    blocks = lfc._split_rule_blocks(text)
    assert "".join(b for _, b in blocks) == text
    ids = [rid for rid, _ in blocks if rid]
    assert ids == ["rule-a", "rule-b", "rule-c"]


# --- reconstruct over files + malformed tolerance -------------------------

def test_reconstruct_skips_unreadable_file(ledger_file, tmp_path, capsys):
    rules = lfc.load_rules(str(ledger_file))
    good = tmp_path / "comms-good-cycle.txt"
    good.write_text(_msg("@OPUS", "STOP rule 18 cited"))
    missing = tmp_path / "comms-does-not-exist.txt"
    acc = lfc.reconstruct(rules, [str(good), str(missing)])
    assert acc["rule-a"].total == 1
    assert "skipped unreadable" in capsys.readouterr().err


def test_reconstruct_attributes_by_filename_cycle(ledger_file, tmp_path):
    rules = lfc.load_rules(str(ledger_file))
    f = tmp_path / "comms-2026-05-15-demo.txt"
    f.write_text(_msg("@OPUS", "STOP rule 18"))
    acc = lfc.reconstruct(rules, [str(f)])
    assert acc["rule-a"].by_cycle == {"2026-05-15-demo": 1}


# --- CLI end-to-end -------------------------------------------------------

def test_main_check_detects_stale_then_apply(ledger_file, tmp_path, capsys):
    comms = tmp_path / "comms-cyc.txt"
    comms.write_text(_msg("@OPUS", "STOP rule 18") + _msg("@CODA", "GO baton"))
    # Stale: ledger has zeros, comms has fires -> --check exits 1.
    rc = lfc.main(["--ledger", str(ledger_file), "--comms", str(comms), "--check"])
    assert rc == 1
    # Apply, then --check is clean.
    rc = lfc.main(["--ledger", str(ledger_file), "--comms", str(comms), "--apply"])
    assert rc == 0
    rc = lfc.main(["--ledger", str(ledger_file), "--comms", str(comms), "--check"])
    assert rc == 0


def test_apply_metadata_sets_lines():
    text = "last_updated_at: OLD\nlast_updated_cycle: old\nrules:\n"
    out = lfc.apply_metadata(text, "2026-05-29T17:00:00Z", "gate-test-parity-2026-05-29")
    assert "last_updated_at: 2026-05-29T17:00:00Z" in out
    assert "last_updated_cycle: gate-test-parity-2026-05-29" in out


def test_apply_metadata_ignores_commented_lines():
    text = "last_updated_cycle: real\n# last_updated_cycle: commented\nrules:\n"
    out = lfc.apply_metadata(text, "T", "newcycle")
    assert "last_updated_cycle: newcycle" in out
    assert "# last_updated_cycle: commented" in out  # untouched


def test_main_apply_stamps_cycle_metadata(ledger_file, tmp_path):
    comms = tmp_path / "comms-cyc.txt"
    comms.write_text(_msg("@OPUS", "STOP rule 18 cited"))
    rc = lfc.main(["--ledger", str(ledger_file), "--comms", str(comms),
                   "--cycle", "gate-test-parity-2026-05-29", "--apply"])
    assert rc == 0
    text = ledger_file.read_text()
    assert "last_updated_cycle: gate-test-parity-2026-05-29" in text
    assert "last_updated_at: 2026-05-20T11:43:00Z" not in text  # was bumped


def test_main_apply_idempotent_with_cycle(ledger_file, tmp_path):
    comms = tmp_path / "comms-cyc.txt"
    comms.write_text(_msg("@OPUS", "STOP rule 18"))
    lfc.main(["--ledger", str(ledger_file), "--comms", str(comms),
              "--cycle", "c1", "--apply"])
    before = ledger_file.read_text()
    # Second identical run: fires unchanged + cycle already current -> no write.
    lfc.main(["--ledger", str(ledger_file), "--comms", str(comms),
              "--cycle", "c1", "--apply"])
    assert ledger_file.read_text() == before


def test_merge_fires_combines_history():
    acc = {"r": lfc.RuleFire("r", "pat")}
    acc["r"].by_cycle = {"c2": 3}
    acc["r"].total = 3
    merged = lfc.merge_fires(acc, {"r": {"c1": 5}})
    assert merged["r"].by_cycle == {"c1": 5, "c2": 3}
    assert merged["r"].total == 8


def test_merge_fires_current_scan_wins_per_cycle():
    acc = {"r": lfc.RuleFire("r", "pat")}
    acc["r"].by_cycle = {"c1": 9}
    merged = lfc.merge_fires(acc, {"r": {"c1": 5, "c2": 2}})
    assert merged["r"].by_cycle == {"c1": 9, "c2": 2}  # c1 updated, c2 preserved


def test_cycle_close_preserves_prior_cycles(ledger_file, tmp_path):
    # The regression that motivated the merge model: a second cycle-close run
    # over a different cycle must NOT wipe the first cycle's fires.
    c1 = tmp_path / "comms-c1.txt"
    c1.write_text(_msg("@OPUS", "STOP rule 18"))
    lfc.main(["--ledger", str(ledger_file), "--comms", str(c1), "--cycle", "c1", "--apply"])
    c2 = tmp_path / "comms-c2.txt"
    c2.write_text(_msg("@OPUS", "STOP rule 18 again") + _msg("@CODA", "GO baton"))
    lfc.main(["--ledger", str(ledger_file), "--comms", str(c2), "--cycle", "c2", "--apply"])

    import yaml
    d = yaml.safe_load(ledger_file.read_text())
    by_id = {r["id"]: r for r in d["rules"]}
    assert by_id["rule-a"]["fires"]["by_cycle"] == {"c1": 1, "c2": 1}  # both kept
    assert by_id["rule-a"]["fires"]["total"] == 2
    assert by_id["rule-b"]["fires"]["by_cycle"] == {"c2": 1}


def test_main_json_format(ledger_file, tmp_path, capsys):
    comms = tmp_path / "comms-cyc.txt"
    comms.write_text(_msg("@OPUS", "STOP rule 18"))
    rc = lfc.main(["--ledger", str(ledger_file), "--comms", str(comms),
                   "--format", "json"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["fires"]["rule-a"]["total"] == 1
    assert out["summary"]["rules_with_fires"] == 1
