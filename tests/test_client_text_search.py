"""The text-search seam is injectable independently of the vector store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trustrag import TrustRAG
from trustrag.testing import FakeEmbedding, FakeLLM


class CustomTextSearch:
    """Stands in for Elasticsearch/Tantivy/etc. — any TextSearch backend."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [
            {
                "eu_id": "custom::0",
                "text": "Termination requires thirty days notice.",
                "document_id": "custom",
                "language": "en",
                "page": -1,
                "checksum": "abc",
                "raw_uri": "raw/abc",
                "_text_score": 9.9,
            }
        ]


def test_injected_text_search_serves_the_lexical_signal(tmp_path: Path) -> None:
    custom = CustomTextSearch()
    rag = TrustRAG(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        signals=["text"],  # lexical only — the injected backend is the signal
        text_search=custom,
    )
    hits = rag.retrieve("What does termination require?")
    assert custom.queries  # the injected backend was consulted
    assert hits[0].eu_id == "custom::0"  # its rows surface (RRF-fused score)
    assert hits[0].text == "Termination requires thirty days notice."
