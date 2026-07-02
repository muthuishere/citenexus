"""The client scales down to what you give it (spec §15: depth never required).

- No models at all -> ingest + retrieve() work (lexical BM25 over stored text).
- embedder= adds vector search; generator= adds ask()/stream()/evaluate().
- Asking without a generator fails with a CLEAR error naming the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trustrag import TrustRAG
from trustrag.answer.result import Decision
from trustrag.testing import FakeEmbedding, FakeLLM

_NDA = "The employee shall not disclose confidential information."


def test_zero_model_client_ingests_and_searches(tmp_path: Path) -> None:
    rag = TrustRAG(tmp_path)  # no embedder, no generator
    result = rag.ingest(text=_NDA, document_id="nda")
    assert result.status == "ingested"

    hits = rag.retrieve("disclose confidential")
    assert hits
    assert hits[0].document_id == "nda"
    assert hits[0].text is not None and "confidential" in hits[0].text


def test_zero_model_ask_raises_clear_error(tmp_path: Path) -> None:
    rag = TrustRAG(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    with pytest.raises(ValueError, match="generator"):
        rag.ask("Can the employee disclose?")
    with pytest.raises(ValueError, match="generator"):
        rag.stream("Can the employee disclose?")
    with pytest.raises(ValueError, match="generator"):
        rag.evaluate(tmp_path / "golden.csv")


def test_embedder_only_client_gets_vector_search(tmp_path: Path) -> None:
    rag = TrustRAG(tmp_path, embedder=FakeEmbedding())
    rag.ingest(text=_NDA, document_id="nda")
    hits = rag.retrieve("Can the employee disclose confidential information?")
    assert any(h.document_id == "nda" for h in hits)
    with pytest.raises(ValueError, match="generator"):
        rag.ask("Can the employee disclose?")


def test_full_client_unchanged(tmp_path: Path) -> None:
    rag = TrustRAG(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM())
    rag.ingest(text=_NDA, document_id="nda")
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].document == "nda"


def test_from_config_without_llm_is_retrieve_only(tmp_path: Path) -> None:
    import json

    from trustrag.config.schema import EmbeddingConfig, StorageConfig, TrustRAGConfig
    from trustrag.lang.detect import HeuristicDetector

    def embed_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        payload = json.loads(body)
        data = [{"embedding": [1.0, 0.0]} for _ in payload["input"]]
        return json.dumps({"data": data}).encode("utf-8")

    cfg = TrustRAGConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        embedding=EmbeddingConfig(endpoint="http://embed.test/v1"),
        # no llm endpoint at all — search-only deployment
    )
    rag = TrustRAG.from_config(cfg, detector=HeuristicDetector(), embed_transport=embed_transport)
    rag.ingest(text=_NDA, document_id="nda")
    assert rag.retrieve("disclose confidential")
    with pytest.raises(ValueError, match="generator"):
        rag.ask("anything")


def test_from_config_without_any_models_is_lexical_only(tmp_path: Path) -> None:
    from trustrag.config.schema import StorageConfig, TrustRAGConfig
    from trustrag.lang.detect import HeuristicDetector

    cfg = TrustRAGConfig(storage=StorageConfig(bucket=str(tmp_path)))
    rag = TrustRAG.from_config(cfg, detector=HeuristicDetector())
    rag.ingest(text=_NDA, document_id="nda")
    hits = rag.retrieve("disclose confidential")
    assert hits and hits[0].document_id == "nda"
