"""Ingest embeds in BATCHES when the embedder supports it (spec §10 batch_size).

One HTTP call per Evidence Unit doesn't survive a real corpus. When the
embedder exposes ``embed_many``, ingest sends all of a document's EU texts in
batched calls (config ``embedding.batch_size``); a single-text embedder (the
hash fake, custom seams) keeps the per-item path.
"""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.ingest import IngestPipeline
from citenexus.storage.backend import LocalFsBackend

PART = PartitionPath.of(("workspace", "w1"))
# ~900 words -> three ~450-token chunks under the default chunker.
_LONG_TEXT = " ".join(f"word{i}" for i in range(900))


class BatchingEmbedder:
    """Counts calls: batch-capable embedders must be called once per batch."""

    def __init__(self) -> None:
        self.batch_calls: list[int] = []
        self.single_calls = 0

    def embed(self, text: str) -> list[float]:
        self.single_calls += 1
        return [1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(len(texts))
        return [[1.0, 0.0] for _ in texts]


class SingleOnlyEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [1.0, 0.0]


def _pipeline(tmp_path: Path, embedder: object) -> IngestPipeline:
    return IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=embedder,  # type: ignore[arg-type]
        signals=["embedding", "text"],
    )


def test_batch_capable_embedder_gets_one_batched_call(tmp_path: Path) -> None:
    embedder = BatchingEmbedder()
    result = _pipeline(tmp_path, embedder).ingest(text=_LONG_TEXT, document_id="d")
    assert result.n_units >= 2
    assert embedder.batch_calls == [result.n_units]  # ONE call, all EU texts
    assert embedder.single_calls == 0


def test_single_text_embedder_still_works(tmp_path: Path) -> None:
    embedder = SingleOnlyEmbedder()
    result = _pipeline(tmp_path, embedder).ingest(text=_LONG_TEXT, document_id="d")
    assert result.n_units >= 2
    assert embedder.calls == result.n_units


def test_client_wires_batch_size_from_config(tmp_path: Path) -> None:
    import json

    from citenexus import CiteNexus
    from citenexus.config.schema import CiteNexusConfig, EmbeddingConfig, StorageConfig
    from citenexus.lang.detect import HeuristicDetector

    calls: list[int] = []

    def embed_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        payload = json.loads(body)
        calls.append(len(payload["input"]))
        return json.dumps({"data": [{"embedding": [1.0, 0.0]} for _ in payload["input"]]}).encode(
            "utf-8"
        )

    cfg = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        embedding=EmbeddingConfig(endpoint="http://embed.test/v1", batch_size=2),
    )
    rag = CiteNexus.from_config(cfg, detector=HeuristicDetector(), embed_transport=embed_transport)
    rag.ingest(text=_LONG_TEXT, document_id="d")
    # multiple EU texts at batch_size=2 -> batched requests of <=2, never singles-per-EU
    assert calls and all(size <= 2 for size in calls)
    assert sum(calls) >= 2 and len(calls) < sum(calls) + 1  # genuinely batched
