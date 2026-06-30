"""Public TrustRAG client — L5 answer / verify / evaluate."""

from __future__ import annotations

from pathlib import Path

from trustrag import TrustRAG
from trustrag.answer.flow import Generator
from trustrag.answer.result import Decision
from trustrag.testing import FakeEmbedding, FakeLLM


class HallucinatingLLM:
    def answer(
        self, question: str, passage: str, answer_language: str = "en"
    ) -> str:
        return "Paris is the capital of France"


def _rag(tmp_path: Path, generator: Generator | None = None) -> TrustRAG:
    return TrustRAG(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=generator or FakeLLM(),
    )


def test_retrieve_and_ask_cite_ingested_evidence(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )

    hits = rag.retrieve("Can the employee disclose confidential information?")
    assert hits
    assert hits[0].checksum
    assert hits[0].raw_uri

    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].document == "nda"
    assert result.claims[0].supported
    assert result.provenance[0].checksum


def test_ask_refuses_when_no_relevant_evidence(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text="Termination requires thirty days notice.", document_id="contract")

    result = rag.ask("What is the capital of France?")
    assert result.evidence.decision is Decision.refused
    assert result.claims == ()
    assert result.sources == ()


def test_ask_refuses_unsupported_generation(tmp_path: Path) -> None:
    rag = _rag(tmp_path, HallucinatingLLM())
    rag.ingest(text="Termination requires thirty days notice.", document_id="contract")

    result = rag.ask("What does termination require?")
    assert result.evidence.decision is Decision.refused
    assert result.claims == ()


def test_evaluate_csv_reports_grounded_cited_answers(
    tmp_path: Path,
) -> None:
    rag = _rag(tmp_path / "store")
    rag.ingest(text="Termination requires thirty days notice.", document_id="contract")
    golden = tmp_path / "golden.csv"
    golden.write_text(
        "question,expected\n"
        "What does termination require?,thirty days notice\n"
        "What is the capital of France?,\n",
        encoding="utf-8",
    )

    report = rag.evaluate(golden)
    assert report.total == 2
    assert report.answered == 1
    assert report.refused == 1
    assert report.groundedness_rate == 1.0
    assert report.citation_rate == 1.0
