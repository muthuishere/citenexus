"""Recursive, structure-aware text chunking (spec §7).

The 2025/26 chunking consensus (and Anthropic's contextual-retrieval baseline):
recursive splitting on natural boundaries at ~400-512 tokens with ~15% overlap
beats both naive fixed-size and (on cost/benefit) semantic chunking. This module
is that recursive splitter — pure, deterministic, dependency-free.

Approach: try to keep whole paragraphs together; when a unit exceeds the size
bound, recurse to the next finer boundary (paragraph -> line -> sentence ->
word), accumulating pieces into size-bounded chunks with a trailing-word overlap
window so adjacent chunks share context.

Token counting is approximated by whitespace words — no tokenizer dependency.
The goal is bounded, overlapping, boundary-respecting chunks, not exact token
parity with any specific model's tokenizer.
"""

from __future__ import annotations

import re

_PARAGRAPH = re.compile(r"\n\s*\n")
_LINE = re.compile(r"\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\s+")

DEFAULT_MAX_TOKENS = 450
DEFAULT_OVERLAP = 60


def _tokens(text: str) -> int:
    return len(text.split())


def _split_units(text: str) -> list[str]:
    """Split ``text`` on the coarsest boundary that yields more than one piece."""
    for pattern in (_PARAGRAPH, _LINE, _SENTENCE):
        pieces = [p.strip() for p in pattern.split(text) if p.strip()]
        if len(pieces) > 1:
            return pieces
    # finest boundary: individual words
    return [w for w in _WORD.split(text) if w]


def chunk_text(
    text: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split ``text`` into bounded, overlapping, boundary-respecting chunks."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    text = text.strip()
    if not text:
        return []
    if _tokens(text) <= max_tokens:
        return [text]
    # Overlap must be strictly below the size or the window can't advance.
    overlap = max(0, min(overlap, max_tokens - 1))

    # 1) Recursively break into pieces that each fit the bound, on the coarsest
    #    boundary possible — so a piece never straddles a paragraph/sentence it
    #    didn't have to. 2) Greedily pack contiguous pieces into size-bounded
    #    chunks. Only a single oversized run of words is windowed.
    pieces = _fit_pieces(text, max_tokens)
    return _pack(pieces, max_tokens, overlap)


def _fit_pieces(text: str, max_tokens: int) -> list[str]:
    """Recursively split ``text`` until every piece fits ``max_tokens``."""
    if _tokens(text) <= max_tokens:
        return [text]
    units = _split_units(text)
    if len(units) == 1:
        # a single oversized word-run: hard-split into max_tokens windows
        words = units[0].split()
        return [" ".join(words[i : i + max_tokens]) for i in range(0, len(words), max_tokens)]
    out: list[str] = []
    for unit in units:
        out.extend(_fit_pieces(unit, max_tokens))
    return out


def _pack(pieces: list[str], max_tokens: int, overlap: int) -> list[str]:
    """Greedily pack pieces into chunks; carry an overlap tail between chunks."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for piece in pieces:
        n = _tokens(piece)
        if current and size + n > max_tokens:
            chunks.append("\n".join(current))
            tail = _overlap_tail(current, overlap)
            current = tail[:]
            size = sum(_tokens(p) for p in current)
        current.append(piece)
        size += n
    if current:
        chunks.append("\n".join(current))
    return chunks


def _overlap_tail(pieces: list[str], overlap: int) -> list[str]:
    """The trailing pieces whose combined size is within ``overlap`` tokens."""
    if overlap <= 0:
        return []
    tail: list[str] = []
    size = 0
    for piece in reversed(pieces):
        n = _tokens(piece)
        if size + n > overlap:
            break
        tail.insert(0, piece)
        size += n
    return tail
