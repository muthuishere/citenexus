"""S3-native storage: partition→prefix, the backend seam, per-leaf vector stores."""

from trustrag.storage.backend import LocalFsBackend, S3Backend, StorageBackend
from trustrag.storage.lance_store import LeafVectorStore, StorageOptions
from trustrag.storage.manifest import (
    EtagManifest,
    ProcessingManifest,
    load_manifest,
    save_manifest,
)
from trustrag.storage.paths import Layer, layer_prefix, leaf_vector_uri, partition_segment

__all__ = [
    "EtagManifest",
    "Layer",
    "LeafVectorStore",
    "LocalFsBackend",
    "ProcessingManifest",
    "S3Backend",
    "StorageBackend",
    "StorageOptions",
    "layer_prefix",
    "leaf_vector_uri",
    "load_manifest",
    "partition_segment",
    "save_manifest",
]
