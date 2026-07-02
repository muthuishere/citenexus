"""The signal-gated, idempotent ingest pipeline (spec §8)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from trustrag.domain.partition import PartitionPath
from trustrag.ingest import IngestPipeline
from trustrag.storage.backend import LocalFsBackend
from trustrag.storage.lance_store import LanceVectorStore
from trustrag.storage.paths import Layer, layer_prefix, leaf_vector_uri
from trustrag.testing import FakeEmbedding
from trustrag.worker.queue import DurableQueue

PART = PartitionPath.of(("workspace", "w1"))


def _pipeline(
    tmp_path: Path,
    signals: Iterable[str] = ("embedding", "text"),
    queue: DurableQueue | None = None,
) -> IngestPipeline:
    return IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=list(signals),
        queue=queue,
    )


def _store(tmp_path: Path) -> LanceVectorStore:
    return LanceVectorStore(leaf_vector_uri(str(tmp_path), PART))


def test_raw_text_ingest_yields_units_with_language(tmp_path: Path) -> None:
    p = _pipeline(tmp_path)
    r = p.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )
    assert r.status == "ingested"
    assert r.n_units >= 1
    hits = _store(tmp_path).search(FakeEmbedding().embed("disclose confidential"), limit=3)
    assert hits and hits[0]["language"]


def test_unknown_source_falls_back_to_plain(tmp_path: Path) -> None:
    p = _pipeline(tmp_path)
    r = p.ingest(b"just some opaque bytes", document_id="blob")
    assert r.status == "ingested"
    assert r.n_units >= 1


def test_idempotent_reingest_is_unchanged(tmp_path: Path) -> None:
    p = _pipeline(tmp_path)
    p.ingest(text="hello world", document_id="d")
    r2 = p.ingest(text="hello world", document_id="d")
    assert r2.status == "unchanged"


def test_embedding_signal_upserts_into_leaf(tmp_path: Path) -> None:
    p = _pipeline(tmp_path, signals=("embedding", "text"))
    p.ingest(text="termination requires thirty days written notice", document_id="t")
    assert _store(tmp_path).search(FakeEmbedding().embed("termination notice"), limit=3)


def test_structure_signal_persists_index(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    p = IngestPipeline(
        backend=backend,
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["structure"],
    )
    p.ingest(text="some content", document_id="d")
    key = f"{layer_prefix(Layer.knowledge, PART)}/structure/d.json"
    assert backend.exists(key)


def test_no_structure_signal_skips_index(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    p = IngestPipeline(
        backend=backend,
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["embedding", "text"],
    )
    p.ingest(text="some content", document_id="d")
    key = f"{layer_prefix(Layer.knowledge, PART)}/structure/d.json"
    assert not backend.exists(key)


def test_slow_path_signal_enqueues(tmp_path: Path) -> None:
    p = _pipeline(tmp_path, signals=("embedding", "graph"), queue=DurableQueue(":memory:"))
    r = p.ingest(text="entities and relations live here", document_id="g")
    assert r.enqueued_slow_path


def test_no_enqueue_without_slow_path_signal(tmp_path: Path) -> None:
    p = _pipeline(tmp_path, signals=("embedding", "text"), queue=DurableQueue(":memory:"))
    r = p.ingest(text="x y z", document_id="g")
    assert not r.enqueued_slow_path


def test_result_reports_units_for_a_markdown_file(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# Title\n\nBody paragraph here.\n")
    r = _pipeline(tmp_path).ingest(str(md))
    assert r.document_id == "doc"
    assert r.n_units >= 2
    assert len(r.eu_ids) == r.n_units


def test_chunking_is_the_default_and_yields_child_eu_ids(tmp_path: Path) -> None:
    r = _pipeline(tmp_path).ingest(text="A short clause about disclosure.", document_id="nda")
    # small block = exactly one child, but under the chunked id scheme
    assert r.eu_ids == ("nda::0::0",)


def test_chunking_disabled_reproduces_legacy_block_ids(tmp_path: Path) -> None:
    p = IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["embedding", "text"],
        chunking_enabled=False,
    )
    r = p.ingest(text="A short clause about disclosure.", document_id="nda")
    # the backward-compat escape hatch: one block -> one EU, {doc}::{order}
    assert r.eu_ids == ("nda::0",)


def test_oversized_block_chunks_into_verbatim_children(tmp_path: Path) -> None:
    big = " ".join(f"word{i}" for i in range(600))  # > 450 tokens, one block
    r = _pipeline(tmp_path).ingest(text=big, document_id="big")
    assert r.n_units > 1
    assert all(eu_id.startswith("big::0::") for eu_id in r.eu_ids)
    # no contextualizer configured -> indexed text IS the verbatim chunk
    rows = {str(row["eu_id"]): str(row["text"]) for row in _store(tmp_path).scan()}
    assert set(rows) == set(r.eu_ids)
    words = set(big.split())
    for text in rows.values():
        assert set(text.split()) <= words  # verbatim: no model words, ever


def test_contextualizer_enriches_index_only(tmp_path: Path) -> None:
    class FakeContextualizer:
        def contextualize(self, *, chunk: str, document: str) -> str:
            return f"CONTEXT: situates the chunk.\n{chunk}"

    p = IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["embedding", "text"],
        contextualizer=FakeContextualizer(),
    )
    p.ingest(text="The employee shall not disclose secrets.", document_id="nda")
    rows = list(_store(tmp_path).scan())
    assert rows and all(str(row["text"]).startswith("CONTEXT:") for row in rows)
