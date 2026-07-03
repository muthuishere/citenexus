"""Lifecycle hooks — observe every stage, mutate nothing (toolnexus-style).

``Hooks`` gives operators callbacks at the moments that matter: ingest done,
candidates retrieved, answer produced, refusal issued, stream chunk released.
They are OBSERVE-ONLY by design: a hook cannot alter the verified path (same
philosophy as retriever plugins never bypassing RRF + grounding), and a hook
that raises is swallowed — user code must never break the pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.hooks import Hooks
from citenexus.testing import FakeEmbedding, FakeLLM

_NDA = "The employee shall not disclose confidential information."


def _rag(tmp_path: Path, hooks: Hooks) -> CiteNexus:
    return CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM(), hooks=hooks)


def test_hooks_fire_across_the_lifecycle(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    hooks = Hooks(
        on_ingest=lambda result: seen.setdefault("ingest", result),
        on_retrieve=lambda query, candidates: seen.setdefault("retrieve", (query, candidates)),
        on_answer=lambda result: seen.setdefault("answer", result),
    )
    rag = _rag(tmp_path, hooks)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ask("Can the employee disclose confidential information?")

    assert seen["ingest"].document_id == "nda"
    query, candidates = seen["retrieve"]
    assert "disclose" in query
    assert candidates and candidates[0].document_id == "nda"
    assert seen["answer"].sources[0].document == "nda"


def test_on_refuse_fires_instead_of_on_answer(tmp_path: Path) -> None:
    events: list[str] = []
    hooks = Hooks(
        on_answer=lambda result: events.append("answer"),
        on_refuse=lambda result: events.append("refuse"),
    )
    rag = _rag(tmp_path, hooks)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ask("What is the capital of France?")
    assert events == ["refuse"]


def test_stream_chunks_fire_on_chunk(tmp_path: Path) -> None:
    chunks: list[str] = []
    hooks = Hooks(on_chunk=lambda chunk: chunks.append(chunk))
    rag = _rag(tmp_path, hooks)
    rag.ingest(text=_NDA, document_id="nda")
    out = rag.stream("Can the employee disclose confidential information?")
    assert list(out) == chunks
    assert chunks  # something streamed


def test_a_raising_hook_never_breaks_the_pipeline(tmp_path: Path) -> None:
    def boom(*args: Any) -> None:
        raise RuntimeError("user hook bug")

    hooks = Hooks(on_ingest=boom, on_retrieve=boom, on_answer=boom, on_refuse=boom)
    rag = _rag(tmp_path, hooks)
    rag.ingest(text=_NDA, document_id="nda")
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.answer  # pipeline unaffected by the broken hooks
