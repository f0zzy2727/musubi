"""Pytest conftest — ensures the project root is importable so tests/ can
`from orchestrator import ...` without packaging shenanigans."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
