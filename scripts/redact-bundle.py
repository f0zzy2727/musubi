#!/usr/bin/env python3
"""redact-bundle.py — mask obvious secrets in a staged debug bundle (priv-1).

Walks a directory and redacts common credential patterns in text files in
place, then prints a one-line summary. Best-effort and pattern-based — NOT a
guarantee that every secret is gone. It complements, not replaces, the bundle's
file-level safety sweep (which deletes .env/.pem/key/credentials files) and the
opt-in gate on transcripts. Run it before zipping when transcripts are included,
since transcripts are the most likely place a pasted key or token survives.

Usage:
  redact-bundle.py <dir>
"""
from __future__ import annotations

import os
import re
import sys

# (label, compiled pattern, replacement). Order matters: the broad key=value
# rule runs last so the specific token shapes redact to a clean marker first.
PATTERNS = [
    ("private key block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED PRIVATE KEY]"),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    ("openai key", re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED]"),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    ("aws access key id", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
    ("google api key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[REDACTED]"),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    ("bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer [REDACTED]"),
    # Generic `key = value` / `key: "value"` for sensitive key names. The key
    # may be a compound identifier (ACCESS_TOKEN, SECRET_KEY, AUTH_TOKEN) so the
    # core sensitive word is matched as a substring of an identifier — but bare
    # "key" is excluded (it would catch innocents like `monkey=`); only
    # api_key/access_key shapes qualify.
    ("key=value secret",
     re.compile(
         r"(?i)([A-Za-z0-9_\-]*(?:secret|token|password|passwd|api[_-]?key|access[_-]?key)[A-Za-z0-9_\-]*)"
         r"(\s*[:=]\s*)([\"']?)[^\s\"']{6,}([\"']?)"
     ),
     r"\1\2\3[REDACTED]\4"),
]

# Extensions we treat as text (everything in a musubi bundle that could carry a
# pasted secret). Binary blobs are skipped.
TEXT_EXT = {".txt", ".md", ".json", ".jsonl", ".yml", ".yaml", ".log", ".csv", ".toml", ".cfg", ".ini", ""}
MAX_BYTES = 50 * 1024 * 1024  # skip pathologically large files


def _is_text(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def redact_text(text: str) -> tuple[str, int]:
    """Return (redacted_text, count). Pure — unit-testable without disk."""
    total = 0
    for _label, rx, repl in PATTERNS:
        text, n = rx.subn(repl, text)
        total += n
    return text, total


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: redact-bundle.py <dir>", file=sys.stderr)
        return 2
    root = argv[1]
    files_touched = 0
    redactions = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            if not _is_text(p):
                continue
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
                # surrogateescape (not "replace") so any non-UTF-8 bytes in an
                # untouched region round-trip back to their original bytes on
                # write — a file we only partially redact is never corrupted.
                with open(p, "r", encoding="utf-8", errors="surrogateescape") as f:
                    original = f.read()
            except OSError:
                continue
            new, n = redact_text(original)
            if n:
                try:
                    with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
                        f.write(new)
                    files_touched += 1
                    redactions += n
                except OSError:
                    pass
    print(f"redact-bundle: {redactions} redaction(s) across {files_touched} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
