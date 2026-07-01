"""Recursive, structure-aware text chunker (spec §7 chunking).

Research-backed defaults (Anthropic contextual-retrieval + 2025/26 chunking
benchmarks): ~400-512 token chunks with ~15% overlap, split on natural
boundaries (paragraph -> line -> sentence -> word) so a chunk never straddles a
semantic break when it can avoid it. Token count is approximated by whitespace
words (no tokenizer dependency); the point is bounded, overlapping, boundary-
respecting chunks — not exact token parity with any one model.
"""

from __future__ import annotations

from trustrag.evidence.chunker import chunk_text


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_text("A short clause.", max_tokens=50, overlap=5)
    assert chunks == ["A short clause."]


def test_empty_or_whitespace_yields_nothing() -> None:
    assert chunk_text("", max_tokens=50, overlap=5) == []
    assert chunk_text("   \n  ", max_tokens=50, overlap=5) == []


def test_long_text_splits_into_bounded_chunks() -> None:
    words = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_text(words, max_tokens=100, overlap=10)
    assert len(chunks) > 1
    # every chunk is within the size bound (word-approximated tokens)
    for chunk in chunks:
        assert len(chunk.split()) <= 100


def test_chunks_overlap_for_continuity() -> None:
    words = " ".join(f"w{i}" for i in range(300))
    chunks = chunk_text(words, max_tokens=100, overlap=20)
    # consecutive chunks share trailing/leading words (overlap window)
    first_tail = set(chunks[0].split()[-20:])
    second_head = set(chunks[1].split()[:20])
    assert first_tail & second_head


def test_prefers_paragraph_boundaries() -> None:
    para_a = " ".join(f"a{i}" for i in range(60))
    para_b = " ".join(f"b{i}" for i in range(60))
    text = f"{para_a}\n\n{para_b}"
    # a max that fits one paragraph but not both -> split on the blank line
    chunks = chunk_text(text, max_tokens=70, overlap=0)
    assert any(c.strip().startswith("a0") for c in chunks)
    assert any(c.strip().startswith("b0") for c in chunks)
    # the boundary chunk should not mix the tail of A with the head of B
    assert not any("a59" in c and "b0" in c for c in chunks)


def test_reconstructs_all_content() -> None:
    words = [f"w{i}" for i in range(250)]
    chunks = chunk_text(" ".join(words), max_tokens=60, overlap=0)
    seen = " ".join(chunks).split()
    # with zero overlap every original word appears exactly once, in order
    assert seen == words


def test_overlap_clamped_below_size() -> None:
    # overlap >= max_tokens would loop forever; it must be clamped.
    words = " ".join(f"w{i}" for i in range(200))
    chunks = chunk_text(words, max_tokens=50, overlap=999)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.split()) <= 50
