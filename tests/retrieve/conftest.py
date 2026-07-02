"""Hermetic seeding for the retrieval tests (spec §10).

Seeds a real local ``LanceVectorStore`` with a few EU rows (text + FakeEmbedding
vectors + document_id) and writes a structure index json into a
``LocalFsBackend`` — the same shapes the ingest pipeline persists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trustrag.domain.partition import PartitionPath
from trustrag.evidence.structure import StructureIndex, StructureNode
from trustrag.extract.types import StructureType
from trustrag.storage.backend import LocalFsBackend
from trustrag.storage.lance_store import LanceVectorStore
from trustrag.storage.paths import Layer, layer_prefix
from trustrag.testing.fakes import FakeEmbedding

PARTITION = PartitionPath.of(("org", "acme"))

# Three EUs of one document: a Termination heading, a salary paragraph, and a
# confidentiality paragraph. Distinct tokens keep the vector/lexical signals clean.
_CORPUS: tuple[tuple[str, str], ...] = (
    ("doc1::0", "Termination of employment by the employer"),
    ("doc1::1", "Salary and monthly compensation details"),
    ("doc1::2", "Confidentiality and non disclosure obligations"),
)


@pytest.fixture
def embedder() -> FakeEmbedding:
    return FakeEmbedding()


@pytest.fixture
def seeded_store(tmp_path: Path, embedder: FakeEmbedding) -> LanceVectorStore:
    """A leaf store upserted with the corpus, ingest-pipeline row shape."""
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(
        [
            {
                "eu_id": eu_id,
                "vector": embedder.embed(text),
                "text": text,
                "document_id": "doc1",
                "language": "en",
                "page": -1,
            }
            for eu_id, text in _CORPUS
        ]
    )
    return store


@pytest.fixture
def empty_store(tmp_path: Path) -> LanceVectorStore:
    """A leaf with no table yet — search/scan both return []."""
    return LanceVectorStore(str(tmp_path / "leaf-empty"))


@pytest.fixture
def backend_with_structure(tmp_path: Path) -> LocalFsBackend:
    """A backend holding doc1's structure index: a 'Termination' heading node
    anchoring doc1::0 and a 'Confidentiality' heading anchoring doc1::2."""
    backend = LocalFsBackend(tmp_path / "store")
    index = StructureIndex(
        document_id="doc1",
        structure_type=StructureType.heading_tree,
        nodes=(
            StructureNode(
                node_id="doc1::0",
                parent_id=None,
                label="Termination",
                kind="heading",
                eu_ref="doc1::0",
            ),
            StructureNode(
                node_id="doc1::2",
                parent_id=None,
                label="Confidentiality",
                kind="heading",
                eu_ref="doc1::2",
            ),
        ),
    )
    key = f"{layer_prefix(Layer.knowledge, PARTITION)}/structure/doc1.json"
    backend.put_json(key, index.model_dump(mode="json"))
    return backend


@pytest.fixture
def empty_backend(tmp_path: Path) -> LocalFsBackend:
    """A backend with no structure index at all."""
    return LocalFsBackend(tmp_path / "store-empty")
