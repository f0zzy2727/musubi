"""Tests for the A1 discipline auto-fire wiring in oyakata.py — extract file
targets from a slice claim, run the discipline scope sensor, relay triggered
disciplines to Oya."""
import os

import oyakata


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- extract_file_targets -------------------------------------------------

def test_extract_first_file_target():
    msg = "Type: Update\nFirst file target: src/auth/session.ts\nResult: claimed"
    assert oyakata.extract_file_targets(msg) == ["src/auth/session.ts"]


def test_extract_multiple_owned_files():
    msg = (
        "First file target: src/a.ts\n"
        "Second owned file confirmed: src/b.tsx\n"
    )
    assert oyakata.extract_file_targets(msg) == ["src/a.ts", "src/b.tsx"]


def test_extract_files_line_with_trailing_prose():
    msg = "Files: src/x.py and also touches docs/readme."
    out = oyakata.extract_file_targets(msg)
    assert "src/x.py" in out


def test_extract_none_when_no_targets():
    msg = "Type: Update\nResult: completed\nNothing to declare here."
    assert oyakata.extract_file_targets(msg) == []


# --- run_discipline_sensor (shells out to the real classifier) ------------

def test_sensor_fires_on_auth_file():
    res = oyakata.run_discipline_sensor(["src/auth/session.ts"], REPO)
    assert res is not None
    disciplines = [t["discipline"] for t in res["triggers"]]
    assert "threat-model-auth-changes" in disciplines


def test_sensor_none_on_empty_files():
    assert oyakata.run_discipline_sensor([], REPO) is None


def test_sensor_none_when_script_missing(tmp_path):
    # orchestrator_dir without the script -> graceful None.
    assert oyakata.run_discipline_sensor(["src/auth/x.ts"], str(tmp_path)) is None


# --- flag_disciplines_to_oyakata (relay path, send_message mocked) --------

def _patch_send(monkeypatch):
    sent = []
    import orchestrator
    monkeypatch.setattr(orchestrator, "send_message",
                        lambda pane, msg, cfg: sent.append(msg))
    monkeypatch.setattr(orchestrator, "_log", lambda *a, **k: None)
    return sent


def test_flag_relays_when_disciplines_fire(monkeypatch):
    sent = _patch_send(monkeypatch)
    msg = "Result: claimed\nFirst file target: src/auth/session.ts"
    oyakata.flag_disciplines_to_oyakata(msg, p_oyakata=object(), cfg={}, orchestrator_dir=REPO)
    assert len(sent) == 1
    assert "threat-model-auth-changes" in sent[0]
    assert "scope sensor fired" in sent[0]


def test_flag_noop_when_no_oya(monkeypatch):
    sent = _patch_send(monkeypatch)
    msg = "Result: claimed\nFirst file target: src/auth/session.ts"
    oyakata.flag_disciplines_to_oyakata(msg, p_oyakata=None, cfg={}, orchestrator_dir=REPO)
    assert sent == []


def test_flag_noop_when_no_disciplines(monkeypatch):
    sent = _patch_send(monkeypatch)
    # A plain markdown doc touches no strategic surface -> no triggers.
    msg = "Result: claimed\nFirst file target: docs/notes.md"
    oyakata.flag_disciplines_to_oyakata(msg, p_oyakata=object(), cfg={}, orchestrator_dir=REPO)
    assert sent == []
