"""Streaming over already-verified `Result` objects."""

from __future__ import annotations

import re
from collections.abc import Iterator

from citenexus.answer.result import Result
from citenexus.domain.trust import TrustMode

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def stream_result(result: Result) -> Iterator[str]:
    """Yield chunks without weakening verification.

    Strict mode is sentence-gated: the full answer has already passed `ask()`,
    then sentences are released. Normal/exploratory mode yields word chunks.
    """
    if result.mode is TrustMode.strict:
        for match in _SENTENCE_RE.finditer(result.answer):
            chunk = match.group(0).strip()
            if chunk:
                yield chunk
        return

    words = result.answer.split()
    for idx, word in enumerate(words):
        suffix = "" if idx == len(words) - 1 else " "
        yield f"{word}{suffix}"
