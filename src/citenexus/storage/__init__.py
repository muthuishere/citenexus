"""S3-native storage: partition→prefix, the backend seam, pluggable stores.

CiteNexus supports pluggable vector databases behind two protocols —
``VectorStore`` (dense) and ``TextSearch`` (lexical) — with each backend
contributing a (vector, text) pair:

- **Lance** (recommended, zero infra, S3-native): ``LanceVectorStore`` +
  ``LanceTextSearch`` (BM25-lite over ``scan()``).
- **Postgres** (bring your own DB): ``PostgresVectorStore`` +
  ``PostgresTextSearch`` (pgvector dense + native ``tsvector`` text).
- **Yours**: implement the protocols and inject.
"""

from citenexus.storage.backend import LocalFsBackend, S3Backend, StorageBackend
from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.storage.lance_store import (
    LanceTextSearch,
    LanceVectorStore,
    LeafVectorStore,
    StorageOptions,
)
from citenexus.storage.manifest import (
    EtagManifest,
    ProcessingManifest,
    load_manifest,
    save_manifest,
)
from citenexus.storage.paths import Layer, layer_prefix, leaf_vector_uri, partition_segment
from citenexus.storage.postgres_store import (
    PostgresTextSearch,
    PostgresVectorStore,
    table_name_for,
)
from citenexus.storage.protocols import TextSearch, VectorStore

__all__ = [
    "Bm25TextSearch",
    "EtagManifest",
    "LanceTextSearch",
    "LanceVectorStore",
    "Layer",
    "LeafVectorStore",
    "LocalFsBackend",
    "PostgresTextSearch",
    "PostgresVectorStore",
    "ProcessingManifest",
    "S3Backend",
    "StorageBackend",
    "StorageOptions",
    "TextSearch",
    "VectorStore",
    "layer_prefix",
    "leaf_vector_uri",
    "load_manifest",
    "partition_segment",
    "save_manifest",
    "table_name_for",
]
