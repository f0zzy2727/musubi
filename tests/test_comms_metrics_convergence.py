"""Tests for the convergence-quality metric in scripts/comms-metrics.py.

Covers classify_review_result (the deterministic premature-consensus proxy) and
the rates it feeds. The metric keys on real Review Result structure: a clean
zero-finding approve is rubber-stamp-shaped; a positive `found` bullet is a
genuine catch; verdict phrases (changes_requested / not confident) are formal
dissent. Bare `reject` / `blocking` must NOT count — they are code vocabulary
in app comms (Promise.reject, non-blocking) and over-match badly.
"""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "comms_metrics",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "comms-metrics.py"),
)
cm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cm)

classify = cm.classify_review_result


# --- classify_review_result -------------------------------------------------

def test_clean_zero_finding_approve():
    body = ("Subject: looks good\nGO: yes\nAction: read the diff.\n"
            "Findings I went looking for:\n"
            "- off-by-one in cursor: not-found — bounds inclusive\n"
            "- null guard: not-found — checked\n")
    assert classify(body) == "clean"


def test_substantive_positive_finding():
    body = ("Findings I went looking for:\n"
            "- persist scope alignment: found-RISK — marker lands under wrong scope\n"
            "- null guard: not-found — fine\n")
    assert classify(body) == "substantive"


def test_found_bullet_is_substantive():
    body = "- missing null-guard on user_id: found — widget.ts:97 dereferences\n"
    assert classify(body) == "substantive"


def test_formal_dissent_changes_requested():
    body = "Subject: OTP fix — NOT confident / changes requested\n- all: not-found\n"
    assert classify(body) == "dissent"


def test_not_confident_is_dissent():
    body = "Subject: bug-path not verified, not confident\nAction: ...\n"
    assert classify(body) == "dissent"


def test_code_reject_does_not_count_as_dissent():
    # Promise.reject / rejectWithValue in discussed code must not flip a clean
    # approve into a dissent. This is the over-match bug the regex was tightened for.
    body = ("Action: the saga calls Promise.reject and rejectWithValue on error.\n"
            "Findings I went looking for:\n- error path: not-found — handled\n")
    assert classify(body) == "clean"


def test_non_blocking_does_not_count():
    body = "Action: this is a non-blocking nit.\n- naming: not-found — fine\n"
    assert classify(body) == "clean"


def test_not_found_defect_is_not_substantive():
    # 'not-found-defect' means the reviewer looked for a defect and found none.
    body = "- marker lifecycle: not-found-defect — set/cleared at correct points\n"
    assert classify(body) == "clean"


# --- end-to-end rates over a synthetic corpus -------------------------------

def test_rates_over_synthetic_corpus(tmp_path):
    corpus = (
        "[@OPUS] [2026-06-01] [10:00 UTC]\n"
        "Type: Review Result\nSubject: clean\n"
        "- a: not-found — ok\n\n"
        "[@CODA] [2026-06-01] [10:05 UTC]\n"
        "Type: Review Result\nSubject: caught one\n"
        "- b: found — real defect at x.ts:9\n\n"
        "[@OPUS] [2026-06-01] [10:10 UTC]\n"
        "Type: Review Result\nSubject: changes requested\n"
        "- c: not-found — ok\n\n"
        "[@CODA] [2026-06-01] [10:15 UTC]\n"
        "Type: Review Request\nSubject: please review\n"
        "Action: requesting review.\n"
    )
    d = tmp_path / "docs" / "agents" / "comms"
    d.mkdir(parents=True)
    (d / "active.txt").write_text(corpus)
    m = cm.analyze(cm.find_files(str(tmp_path / "docs" / "agents")))
    # 3 review RESULTS (the Request is excluded), one of each class.
    assert m["review_results"] == 3
    assert m["zero_finding_approve_rate"] == round(1 / 3, 3)
    assert m["substantive_review_rate"] == round(1 / 3, 3)
    assert m["formal_dissent_rate"] == round(1 / 3, 3)
    # No Slice: tags in this corpus -> exchange-level metric degrades to None.
    assert m["single_exchange_contested_rate"] is None
    assert m["contested_slices"] == 0


# --- exchange-level convergence (Slice grouping; the spike's target metric) ---

def test_exchange_level_single_vs_multi_round(tmp_path):
    corpus = (
        # slice S1: contested (a finding) but only ONE review turn -> single-exchange
        "[@OPUS] [2026-06-01] [10:00 UTC]\n"
        "Type: Review Result\nSlice: S1\n- a: found — defect at x.ts:9\n\n"
        # slice S2: contested AND two review turns -> multi-round (the goal)
        "[@OPUS] [2026-06-01] [10:05 UTC]\n"
        "Type: Review Result\nSlice: S2\n- b: found — risk at y.ts:3\n\n"
        "[@CODA] [2026-06-01] [10:10 UTC]\n"
        "Type: Review Result\nSlice: S2\n- b: not-found — addressed, re-verified\n\n"
        # slice S3: NOT contested (clean approve) -> excluded from the denominator
        "[@OPUS] [2026-06-01] [10:15 UTC]\n"
        "Type: Review Result\nSlice: S3\n- c: not-found — ok\n"
    )
    d = tmp_path / "docs" / "agents" / "comms"
    d.mkdir(parents=True)
    (d / "active.txt").write_text(corpus)
    m = cm.analyze(cm.find_files(str(tmp_path / "docs" / "agents")))
    assert m["contested_slices"] == 2          # S1, S2 (S3 clean, excluded)
    assert m["single_exchange_contested_rate"] == 0.5   # S1 of {S1,S2}
    assert m["multi_round_contested_rate"] == 0.5       # S2 of {S1,S2}


# --- consensus-1 v0 scorer: correlated_blindspot_score ----------------------

score = cm.correlated_blindspot_score


def test_all_components_high_is_high_band():
    # rubber-stamp + no dissent + converged vocab + premature consensus + misses
    r = score(zfa=0.9, dissent_rate=0.05, sei=0.02, single_exchange_rate=0.9,
              escape_n=8, review_msgs=10)
    assert r["band"] == "high"
    assert r["score"] >= 0.6
    assert set(r["components"]) == {
        "rubber_stamp", "dissent_absence", "role_convergence",
        "premature_consensus", "realized_miss",
    }


def test_healthy_pair_is_low_band():
    # lots of dissent, differentiated roles, multi-round, no escapes
    r = score(zfa=0.1, dissent_rate=0.6, sei=0.3, single_exchange_rate=0.1,
              escape_n=0, review_msgs=20)
    assert r["band"] == "low"
    assert r["score"] < 0.4
    # SEI above the reference => zero convergence risk
    assert r["components"]["role_convergence"] == 0.0


def test_missing_signals_are_omitted_not_faked():
    # no SEI (single coder) and no Slice tags -> those components absent,
    # score still computed from the rest, not invented.
    r = score(zfa=0.5, dissent_rate=0.3, sei=None, single_exchange_rate=None,
              escape_n=0, review_msgs=5)
    assert "role_convergence" not in r["components"]
    assert "premature_consensus" not in r["components"]
    assert r["components"]  # still has rubber_stamp + dissent_absence + realized_miss
    assert r["score"] is not None


def test_no_data_returns_none_score():
    r = score(zfa=None, dissent_rate=None, sei=None, single_exchange_rate=None,
              escape_n=0, review_msgs=0)
    assert r["score"] is None
    assert r["band"] is None


def test_components_clamped_to_unit_interval():
    # escape_n > review_msgs and a tiny SEI must not push a component past 1.0
    r = score(zfa=1.0, dissent_rate=0.0, sei=0.001, single_exchange_rate=1.0,
              escape_n=50, review_msgs=10)
    for v in r["components"].values():
        assert 0.0 <= v <= 1.0
    assert r["score"] <= 1.0


def test_scorer_wired_into_analyze(tmp_path):
    corpus = (
        "[@OPUS] [2026-06-01] [10:00 UTC]\n"
        "Type: Review Result\nSlice: S1\nGO: yes\n- a: not-found — ok\n"
    )
    d = tmp_path / "docs" / "agents" / "comms"
    d.mkdir(parents=True)
    (d / "active.txt").write_text(corpus)
    m = cm.analyze(cm.find_files(str(tmp_path / "docs" / "agents")))
    assert "correlated_blindspot_risk" in m
    assert "score" in m["correlated_blindspot_risk"]
