"""Streaming wraps verified answers."""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.domain.trust import TrustMode
from citenexus.testing import FakeEmbedding, FakeLLM


def test_strict_stream_yields_verified_sentence_chunks(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM())
    rag.ingest(text="Termination requires notice. Disclosure is forbidden.", document_id="p")

    chunks = rag.stream("What does termination require?", mode=TrustMode.strict)
    assert chunks == ("Termination requires notice.", "Disclosure is forbidden.")


def test_normal_stream_yields_word_chunks(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM())
    rag.ingest(text="Termination requires notice", document_id="p")

    chunks = rag.stream("What does termination require?", mode=TrustMode.normal)
    assert chunks == ("Termination ", "requires ", "notice")
