"""Loader for the committed cross-language conformance fixtures.

Mirrors ``golang/internal/conform`` and ``js/src/conform/fixtures.ts``: the
fixture is read from disk as opaque JSON, never regenerated. If a port helper
exists, Python gets one too — otherwise every Python test re-derives the path
and the "read it as data" discipline erodes one copy-paste at a time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFORMANCE_DIR = Path(__file__).resolve().parents[3] / "conformance"


def load_case(name: str) -> Any:
    """Parse ``conformance/cases/<name>`` (e.g. ``"tokenize.json"``)."""
    return json.loads((CONFORMANCE_DIR / "cases" / name).read_text(encoding="utf-8"))


def load_data(name: str) -> Any:
    """Parse a top-level ``conformance/<name>`` (e.g. ``"stopwords.json"``)."""
    return json.loads((CONFORMANCE_DIR / name).read_text(encoding="utf-8"))
