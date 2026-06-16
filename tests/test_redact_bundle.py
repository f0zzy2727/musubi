"""Tests for scripts/redact-bundle.py (priv-1).

Pins the redaction patterns and the in-place file pass. Best-effort by design,
so the tests assert that the high-signal credential shapes are masked and that
ordinary prose is left intact.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

HELPER_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "redact-bundle.py"

_spec = importlib.util.spec_from_file_location("redact_bundle", HELPER_PATH)
redact_bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redact_bundle)


class TestRedactText:
    @pytest.mark.parametrize("secret", [
        "sk-ant-0123456789ABCDEFGHIJabcdef",       # anthropic
        "sk-0123456789ABCDEFGHIJabcdef",            # openai
        "ghp_0123456789ABCDEFGHIJ0123456789abcd",   # github
        "AKIA0123456789ABCDEF",                      # aws access key id
        "AIzaSyA0123456789abcdefABCDEF0123456789x",  # google
        "xoxb-0123456789-abcdefABCDEF",              # slack
    ])
    def test_token_shapes_are_masked(self, secret):
        out, n = redact_bundle.redact_text(f"key found: {secret} <-")
        assert n >= 1
        assert secret not in out
        assert "[REDACTED]" in out

    def test_bearer_token_masked(self):
        out, n = redact_bundle.redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6")
        assert n >= 1
        assert "Bearer [REDACTED]" in out

    def test_private_key_block_masked(self):
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA...lots...of...base64\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out, n = redact_bundle.redact_text(f"here it is:\n{block}\ndone")
        assert n >= 1
        assert "PRIVATE KEY-----" not in out
        assert "[REDACTED PRIVATE KEY]" in out

    @pytest.mark.parametrize("line", [
        'api_key = "abcd1234secretvalue"',
        "password: hunter2hunter2",
        "ACCESS_TOKEN=ZYXW9876543210abcd",
    ])
    def test_key_value_secrets_masked(self, line):
        out, n = redact_bundle.redact_text(line)
        assert n >= 1
        assert "[REDACTED]" in out

    @pytest.mark.parametrize("clean", [
        "This is an ordinary comms line about a slice review.",
        "git status shows three modified files",
        "The token of appreciation was metaphorical.",  # 'token' word, no key=value
    ])
    def test_ordinary_prose_untouched(self, clean):
        out, n = redact_bundle.redact_text(clean)
        assert out == clean
        assert n == 0


class TestMain:
    def test_redacts_files_in_place(self, tmp_path):
        f = tmp_path / "chats" / "claude" / "t.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text('{"text":"my key is sk-ant-0123456789ABCDEFGHIJxyz here"}\n')
        rc = redact_bundle.main(["prog", str(tmp_path)])
        assert rc == 0
        after = f.read_text()
        assert "sk-ant-" not in after
        assert "[REDACTED]" in after

    def test_skips_binary_extensions(self, tmp_path):
        f = tmp_path / "blob.png"
        raw = "sk-ant-0123456789ABCDEFGHIJxyz"
        f.write_text(raw)  # .png not in TEXT_EXT → left alone
        redact_bundle.main(["prog", str(tmp_path)])
        assert f.read_text() == raw

    def test_wrong_args_return_2(self):
        assert redact_bundle.main(["prog"]) == 2
