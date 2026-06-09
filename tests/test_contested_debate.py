"""Tests for the contested-debate spike config gate (forced-debate mechanism #1).

contested_debate is opt-in and defaults OFF — unlike operator_input/actions which
default on — because it gives Oya barrier-holding authority (blind position before
either coder reads the other), a stronger power than the rest of v0.3-strategic.
"""
from oyakata import contested_debate_enabled


def _cfg(oya=None, project_path="/tmp/proj"):
    agents = {"opus": {}, "coda": {}}
    if oya is not None:
        agents["oyakata"] = oya
    return {"project": {"path": project_path}, "agents": agents}


def test_defaults_off_even_when_oya_on():
    # The key difference from the other surfaces: a spike must be opted into.
    assert contested_debate_enabled(_cfg(oya={"enabled": True})) is False


def test_off_when_oya_off():
    assert contested_debate_enabled(_cfg(oya={"enabled": False, "contested_debate": True})) is False
    assert contested_debate_enabled(_cfg(oya=None)) is False


def test_explicit_opt_in():
    assert contested_debate_enabled(_cfg(oya={"enabled": True, "contested_debate": True})) is True
