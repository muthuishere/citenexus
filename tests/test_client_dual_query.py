"""EN dual-query RRF through the public client — cross-lingual abstention fix.

A French question over English evidence used to abstain twice over: the vector/
lexical retrievers missed (no shared tokens), and even on a hit the relevance
gate compared French tokens to English text. With an injected reformulator the
client retrieves with BOTH queries (RRF-fused) and lets the EN reformulation
count for relevance — while the citation and the faithfulness gate stay exactly
as strict as before.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM

_EN_DOC = "Customers can request a full refund within fourteen days of purchase."


class FakeReformulator:
    """fr -> en lookup standing in for the small model; counts calls."""

    def __init__(self) -> None:
        self.calls = 0
        self._table = {
            "Quel est le délai pour demander un remboursement?": (
                "What is the deadline to request a refund?"
            ),
        }

    def reformulate(self, query: str) -> str | None:
        self.calls += 1
        return self._table.get(query)


def _rag(tmp_path: Path, reformulator: FakeReformulator | None) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        reformulator=reformulator,
    )


def test_french_query_abstains_without_reformulator(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="refund-policy")
    result = rag.ask("Quel est le délai pour demander un remboursement?")
    assert result.evidence.decision is Decision.refused  # the baseline failure


def test_french_query_answers_with_dual_query(tmp_path: Path) -> None:
    rag = _rag(tmp_path, FakeReformulator())
    rag.ingest(text=_EN_DOC, document_id="refund-policy")
    result = rag.ask("Quel est le délai pour demander un remboursement?")
    assert result.evidence.decision is Decision.answered
    # the citation is the VERBATIM English evidence — never the reformulation
    assert result.sources[0].passage == _EN_DOC
    assert result.sources[0].document == "refund-policy"


def test_retrieve_uses_dual_query_too(tmp_path: Path) -> None:
    rag = _rag(tmp_path, FakeReformulator())
    rag.ingest(text=_EN_DOC, document_id="refund-policy")
    hits = rag.retrieve("Quel est le délai pour demander un remboursement?")
    assert any(h.document_id == "refund-policy" for h in hits)


def test_english_query_unaffected(tmp_path: Path) -> None:
    rag = _rag(tmp_path, FakeReformulator())
    rag.ingest(text=_EN_DOC, document_id="refund-policy")
    result = rag.ask("What is the deadline to request a refund?")
    assert result.evidence.decision is Decision.answered
