"""Tests for scripts/cost-report.py — honest Claude-side token accounting."""
import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cost-report.py"
_spec = importlib.util.spec_from_file_location("cost_report", _SCRIPT)
cr = importlib.util.module_from_spec(_spec)
sys.modules["cost_report"] = cr
_spec.loader.exec_module(cr)


def _line(ts, cwd, inp, out, cc=0, crd=0):
    return json.dumps({
        "type": "assistant", "timestamp": ts, "cwd": cwd,
        "message": {"usage": {
            "input_tokens": inp, "output_tokens": out,
            "cache_creation_input_tokens": cc, "cache_read_input_tokens": crd,
        }},
    })


def _make_projects(tmp_path):
    d = tmp_path / "projects" / "proj-a"
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text(
        _line("2026-05-29T10:00:00Z", "/Users/me/Dev/musubi", 100, 50, cc=200, crd=300) + "\n"
        + _line("2026-05-30T11:00:00Z", "/Users/me/Dev/musubi", 10, 5) + "\n"
        + "not json\n"
        + json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"  # no usage
    )
    d2 = tmp_path / "projects" / "proj-b"
    d2.mkdir(parents=True)
    (d2 / "s2.jsonl").write_text(_line("2026-05-29T09:00:00Z", "/Users/me/Dev/other", 1000, 1) + "\n")
    return tmp_path / "projects"


def test_tally_sums_all_token_fields(tmp_path):
    pd = _make_projects(tmp_path)
    t = cr.tally(str(pd))
    assert t["messages"] == 3
    assert t["input_tokens"] == 1110
    assert t["output_tokens"] == 56
    assert t["cache_creation_input_tokens"] == 200
    assert t["cache_read_input_tokens"] == 300


def test_since_filter(tmp_path):
    pd = _make_projects(tmp_path)
    t = cr.tally(str(pd), since="2026-05-30")
    assert t["messages"] == 1  # only the 05-30 line
    assert t["input_tokens"] == 10


def test_project_filter(tmp_path):
    pd = _make_projects(tmp_path)
    t = cr.tally(str(pd), project="musubi")
    assert t["messages"] == 2  # both musubi-cwd lines, not the 'other' one
    assert t["input_tokens"] == 110


def test_skips_malformed_and_usageless_lines(tmp_path):
    pd = _make_projects(tmp_path)
    # 4 lines in s1 but only 2 carry usage; the "not json" and user line are skipped.
    t = cr.tally(str(pd), project="musubi")
    assert t["messages"] == 2


def test_main_missing_dir_returns_2(tmp_path, capsys):
    rc = cr.main(["--claude-dir", str(tmp_path / "nope")])
    assert rc == 2


def test_main_json_format(tmp_path, capsys):
    pd = _make_projects(tmp_path)
    rc = cr.main(["--claude-dir", str(pd), "--format", "json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["messages"] == 3


def test_text_report_states_codex_caveat(tmp_path, capsys):
    pd = _make_projects(tmp_path)
    cr.main(["--claude-dir", str(pd)])
    out = capsys.readouterr().out
    assert "Claude side only" in out
    assert "Codex" in out  # the honest limitation is stated
