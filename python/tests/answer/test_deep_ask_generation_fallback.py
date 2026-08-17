"""Deep-ask cites the source's words, not the context model's blurb.

The strict path was fixed for this in 0697c41; the agentic loop was not. Under
contextual retrieval (spec §7) an EU is INDEXED as ``blurb + "\\n" + chunk`` while
``passage`` keeps the verbatim chunk. ``tools.search_evidence`` handed the loop
only the enriched string, so ``strategy="deep"`` generated from it, verified it
against itself, and emitted it as ``SourceRef.passage`` — attributing a sentence
the source never wrote, and letting the guard's own output be admissible evidence
for itself.

The loop's NAVIGATION view keeps the enrichment (it is what makes contextual
retrieval rank well, and the decision model is navigating, not quoting); anything
that becomes a citation, a ``Claim``, a ``ProvenanceEntry`` or gate input must be
the verbatim ``passage``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.answer.agentic import AgenticAnswerFlow, LoopBudget
from citenexus.answer.decision import LoopDecision
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM
from citenexus.testing.fakes import FakeToolLLM

BLURB = "This chunk lists the items available in the Earrings section of the collection."
CHUNK = "Items in this section: Aella Gold Hoop Earrings, Nyla Silver Drop Earrings."


class _FakeContextualizer:
    """Prepends a situating sentence, exactly as ``evidence.contextualize`` does."""

    def contextualize(self, *, chunk: str, document: str) -> str:
        return f"{BLURB}\n{chunk}"


def _rag(tmp_path: Path, *, contextualizer: _FakeContextualizer | None) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        # An extractive generator: it answers with whatever passage it is handed,
        # so a blurb reaching generation shows up verbatim in the answer.
        generator=FakeLLM(),
        contextualizer=contextualizer,
        agentic_decider=FakeToolLLM([LoopDecision(sufficient=True)]),
        agentic_budget=LoopBudget(max_hops=2),
        top_k=5,
    )


def test_deep_never_quotes_the_context_models_blurb_as_the_source(tmp_path: Path) -> None:
    rag = _rag(tmp_path, contextualizer=_FakeContextualizer())
    rag.ingest(text=CHUNK, document_id="indieandharper")

    # The index really is enriched: what we embed carries the blurb, what we may
    # cite does not.
    rows = list(rag._store.scan())
    assert rows[0]["text"].startswith(BLURB)
    assert rows[0]["passage"] == CHUNK

    result = rag.ask("Do you have earrings?", strategy="deep")

    assert result.evidence.decision is Decision.answered
    # Byte-equal to the source chunk, with none of the context model's sentence.
    assert result.sources[0].passage == CHUNK
    assert BLURB not in result.sources[0].passage
    assert BLURB not in result.answer
    # The gate ran on the verbatim chunk too: no claim may carry the blurb.
    assert all(BLURB not in claim.claim for claim in result.claims)
    assert all(BLURB not in entry.claim for entry in result.provenance)


def test_strict_and_deep_cite_the_same_verbatim_chunk(tmp_path: Path) -> None:
    """The guarantee must not depend on which strategy the caller picked."""
    rag = _rag(tmp_path, contextualizer=_FakeContextualizer())
    rag.ingest(text=CHUNK, document_id="indieandharper")

    strict = rag.ask("Do you have earrings?", strategy="strict")
    deep = rag.ask("Do you have earrings?", strategy="deep")

    assert strict.sources[0].passage == CHUNK
    assert deep.sources[0].passage == CHUNK


def _flow(rows: list[dict[str, Any]], *, seen: list[list[str]] | None = None) -> AgenticAnswerFlow:
    def search_evidence(query: str, k: int = 5) -> list[dict[str, Any]]:
        return rows

    class _Decider:
        def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision:
            if seen is not None:
                seen.append(list(evidence))
            return LoopDecision(sufficient=True)

    return AgenticAnswerFlow(
        generator=FakeLLM(),
        decider=_Decider(),
        tools=[{"name": "search_evidence", "handler": search_evidence}],
        budget=LoopBudget(max_hops=1),
    )


def test_deep_falls_back_to_indexed_text_on_un_migrated_rows() -> None:
    """A tool/index with no ``passage`` still answers — un-migrated, not broken."""
    flow = _flow(
        [
            {
                "eu_id": "a",
                "text": CHUNK,  # legacy row: no `passage` key at all
                "document_id": "shop",
                "language": "en",
                "checksum": "sum-a",
                "signal": "vector",
                "score": 1.0,
            }
        ]
    )

    result = flow.ask("Do you have earrings?")

    assert result.evidence.decision is Decision.answered
    assert result.sources[0].passage == CHUNK


def test_the_navigation_view_keeps_the_enrichment() -> None:
    """The decision model still sees the indexed text — ranking/relevance is its job."""
    seen: list[list[str]] = []
    flow = _flow(
        [
            {
                "eu_id": "a",
                "text": f"{BLURB}\n{CHUNK}",
                "passage": CHUNK,
                "document_id": "shop",
                "language": "en",
                "checksum": "sum-a",
                "signal": "vector",
                "score": 1.0,
            }
        ],
        seen=seen,
    )

    result = flow.ask("Do you have earrings?")

    assert seen == [[f"{BLURB}\n{CHUNK}"]]
    assert result.sources[0].passage == CHUNK
