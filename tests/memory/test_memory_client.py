"""Conversation memory enriches retrieval context without becoming evidence."""

from __future__ import annotations

from pathlib import Path

from trustrag import TrustRAG
from trustrag.answer.result import Decision
from trustrag.config.signals import Signal
from trustrag.testing import FakeEmbedding, FakeLLM


def _rag(tmp_path: Path) -> TrustRAG:
    return TrustRAG(
        tmp_path,
        signals=[Signal.embedding, Signal.text],
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
    )


def test_memory_context_helps_follow_up_retrieve_same_topic(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(
        text="The termination clause requires thirty days notice.",
        document_id="contract",
    )

    first = rag.ask("What does the termination clause require?", conversation_id="c1")
    assert first.evidence.decision is Decision.answered

    follow_up = rag.ask("What about it?", conversation_id="c1")
    assert follow_up.evidence.decision is Decision.answered
    assert follow_up.sources[0].document == "contract"
    recalled = rag.recall("c1", "termination")
    assert recalled
    assert "termination" in f"{recalled[0].question} {recalled[0].answer}".lower()
