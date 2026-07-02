"""The client emits telemetry into an injected sink (spec §6c).

Observability is one event stream: ``ask()`` emits a ``generate`` StageEvent
carrying the answering model's real token usage and the answer/refuse outcome,
attributed to the partition. This is what the cost view and quality counters read
— for legal/medical, provenance + measurable groundedness are the point.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.telemetry import InMemorySink, Outcome, Stage
from citenexus.telemetry.events import TokenUsage
from citenexus.testing import FakeEmbedding


class UsageLLM:
    """A fake generator that echoes the passage and reports token usage."""

    def __init__(self) -> None:
        self.last_usage: TokenUsage | None = None

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        self.last_usage = TokenUsage(input=42, output=8)
        return passage


def _rag(tmp_path: Path, sink: InMemorySink) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=UsageLLM(),
        sink=sink,
    )


def test_ask_emits_generate_event_with_tokens(tmp_path: Path) -> None:
    sink = InMemorySink()
    rag = _rag(tmp_path, sink)
    rag.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered

    generate_events = [e for e in sink.events if e.stage is Stage.generate]
    assert len(generate_events) == 1
    event = generate_events[0]
    assert event.outcome is Outcome.ok
    assert event.tokens is not None
    assert event.tokens.input == 42
    assert event.tokens.output == 8
    assert event.partition == rag.partition


def test_ask_emits_refused_outcome(tmp_path: Path) -> None:
    sink = InMemorySink()
    rag = _rag(tmp_path, sink)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    result = rag.ask("What is the capital of France?")
    assert result.evidence.decision is Decision.refused

    generate_events = [e for e in sink.events if e.stage is Stage.generate]
    assert len(generate_events) == 1
    assert generate_events[0].outcome is Outcome.refused


def test_ask_emits_fusion_event_with_candidate_count(tmp_path: Path) -> None:
    sink = InMemorySink()
    rag = _rag(tmp_path, sink)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    rag.ask("What does termination require?")

    fusion_events = [e for e in sink.events if e.stage is Stage.fusion]
    assert len(fusion_events) == 1
    assert fusion_events[0].units is not None
    assert fusion_events[0].units.candidates >= 1


def test_ingest_emits_extract_and_embedding_events(tmp_path: Path) -> None:
    sink = InMemorySink()
    rag = _rag(tmp_path, sink)
    rag.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )

    extract_events = [e for e in sink.events if e.stage is Stage.extract]
    embedding_events = [e for e in sink.events if e.stage is Stage.embedding]
    assert len(extract_events) == 1
    assert len(embedding_events) == 1
    for event in (*extract_events, *embedding_events):
        assert event.document_id == "nda"
        assert event.duration_ms > 0
        assert event.outcome is Outcome.ok
        assert event.partition == rag.partition


def test_unchanged_reingest_emits_no_ingest_events(tmp_path: Path) -> None:
    sink = InMemorySink()
    rag = _rag(tmp_path, sink)
    rag.ingest(text="hello world", document_id="d")
    before = len(sink.events)
    rag.ingest(text="hello world", document_id="d")  # idempotent skip
    assert len(sink.events) == before


def test_no_sink_is_a_silent_noop(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=UsageLLM())
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    # Must not raise when no sink is configured.
    result = rag.ask("What does termination require?")
    assert result.evidence.decision is Decision.answered
