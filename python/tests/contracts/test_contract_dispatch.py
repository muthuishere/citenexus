"""Ingest and retrieval pick the batch path *by contract*, not by `getattr`.

ADR-0014: "a capability discovered by `getattr` is a capability no port can see,
no type checker can verify, and no provider knows to offer." These tests pin the
replacement: `isinstance(embedder, EmbeddingProvider)`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.contracts import EmbeddingProvider
from citenexus.domain.partition import PartitionPath
from citenexus.ingest import IngestPipeline
from citenexus.storage.backend import LocalFsBackend

PART = PartitionPath.of(("workspace", "w1"))
# ~900 words -> three ~450-token chunks under the default chunker.
_LONG_TEXT = " ".join(f"word{i}" for i in range(900))


class ContractEmbedder:
    """A provider written against the published contract only."""

    def __init__(self, dim: int = 2) -> None:
        self.batches: list[int] = []
        self.dim = dim

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        return [[1.0, float(len(t) % 7)] for t in texts]


class LegacyEmbedder:
    """The deprecated single-text shape — still supported."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [1.0, float(len(text) % 7)]


def _pipeline(tmp_path: Path, embedder: object | None) -> IngestPipeline:
    return IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=embedder,  # type: ignore[arg-type]
        signals=["embedding", "text"],
    )


def test_the_contract_embedder_satisfies_the_protocol() -> None:
    assert isinstance(ContractEmbedder(), EmbeddingProvider)
    assert not isinstance(LegacyEmbedder(), EmbeddingProvider)


def test_contract_embedder_gets_one_batched_call(tmp_path: Path) -> None:
    embedder = ContractEmbedder()
    result = _pipeline(tmp_path, embedder).ingest(text=_LONG_TEXT, document_id="d")
    assert result.n_units >= 2
    assert embedder.batches == [result.n_units]


def test_contract_embedder_is_never_asked_for_a_single_text(tmp_path: Path) -> None:
    embedder = ContractEmbedder()
    assert not hasattr(embedder, "embed")
    _pipeline(tmp_path, embedder).ingest(text=_LONG_TEXT, document_id="d")


def test_legacy_embedder_keeps_the_per_text_path(tmp_path: Path) -> None:
    embedder = LegacyEmbedder()
    result = _pipeline(tmp_path, embedder).ingest(text=_LONG_TEXT, document_id="d")
    assert embedder.calls == result.n_units


def test_no_embedder_writes_the_placeholder_without_a_fake_provider(tmp_path: Path) -> None:
    result = _pipeline(tmp_path, None).ingest(text="short text", document_id="d")
    assert result.status == "ingested"
    assert result.n_units >= 1


def test_query_embedding_goes_through_the_same_dispatch(tmp_path: Path) -> None:
    """A batch-only provider must work for retrieval too — no `embed` needed."""
    embedder = ContractEmbedder()
    rag = CiteNexus(tmp_path, embedder=embedder)
    rag.ingest(text="The employee shall not disclose confidential information.", document_id="nda")
    before = len(embedder.batches)
    hits = rag.retrieve("disclose confidential")
    assert hits
    # The query itself was embedded as a batch of one.
    assert embedder.batches[before:] == [1]


def test_legacy_embedder_still_drives_the_client(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=LegacyEmbedder())
    rag.ingest(text="The employee shall not disclose confidential information.", document_id="nda")
    assert rag.retrieve("disclose confidential")


# --- R2: failure is raised, never encoded ----------------------------------


class ExplodingEmbedder:
    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("model refused")


class ExplodingGenerator:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        raise RuntimeError("model refused")


def test_a_raising_embedder_fails_ingest_loudly(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="model refused"):
        _pipeline(tmp_path, ExplodingEmbedder()).ingest(text="anything", document_id="d")


def test_a_raising_generator_fails_ask_loudly(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, generator=ExplodingGenerator())
    rag.ingest(text="The employee shall not disclose confidential information.", document_id="nda")
    with pytest.raises(RuntimeError, match="model refused"):
        rag.ask("Can the employee disclose confidential information?")
