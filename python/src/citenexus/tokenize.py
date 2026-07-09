"""The pinned SPEC-PORTS-v1 §4 tokenizer: lowercase, ``[a-z0-9]+`` splitting,
no stemming. A frozen contract — every port (Go, TS, Rust-bound) matches this
exactly, and every gate/retrieval algorithm here tokenizes through this one
function so they can never drift from each other.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())
